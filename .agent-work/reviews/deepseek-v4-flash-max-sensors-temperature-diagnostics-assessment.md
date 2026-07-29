# DeepSeek V4 Flash Max — Sensors / Temperature Diagnostics Assessment (Corrected)

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   clean (1 untracked file — this assessment document)
Recent commits (git log -4 --oneline):
  e7ee372 fix: detect kernel taint precisely     (Iteration 25, committed)
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

**Status:** The working tree is clean with respect to all tracked files. The only untracked path is `.agent-work/reviews/deepseek-v4-flash-max-sensors-temperature-diagnostics-assessment.md` — this document. No production code changes are present. The preceding Iteration 25 (kernel taint fix) was committed at `e7ee372` before this assessment began.

---

## 2. Current Data-Flow Inventory

### 2.1 Collector command

| Property | Value |
|---|---|
| Method | `SysCheckEngine.collect_resources()` |
| Command | `["sensors"]` |
| Timeout | `TIMEOUT_MEDIUM` (30s) |
| Optional | No (not marked as optional dependency) |
| Execution | Via `_parallel()` — returns raw `str`, **not** `CmdResult` |
| Source line | `syscheck.py:1929` (task dict entry), executed at line 1931 |

### 2.2 Command result representation

`_parallel()` returns `Dict[str, str]`. The sensors output is a plain string `r["sensors"]`, not a `CmdResult`. This means:
- No `execution_status` metadata (ok/not_found/timeout/permission_denied)
- No `return_code` available
- No way to distinguish "sensors command not found" from "sensors returned empty output"
- If `sensors` is unavailable (not installed), the subprocess call fails silently at `run_cmd` level and `_parallel` returns an error string `"(błąd rc=...)"`

### 2.3 Parsing / filtering helpers

**`_filter_invalid_temperatures(text: str) -> str`** (lines 455–481)

```python
def _filter_invalid_temperatures(text: str) -> str:
    """
    Filtruje temperatury poniżej INVALID_TEMPERATURE_CELSIUS (np. -273.15°C).
    Takie wartości oznaczają niepodłączony lub nieobsługiwany czujnik.
    """
    regex = r"^(\s*\w+\d*:\s+)([+-]?\d+[.,]\d+°[CF])(.*)"
```

- Splits input by newline, iterates per line
- Matches lines matching `label: value°C` or `label: value°F` where label is `\w+\d*`
- If matched value is `< INVALID_TEMPERATURE_CELSIUS` (-100.0), the line is **skipped**
- Non-matching lines are kept unchanged
- Also handles comma as decimal separator (e.g. `27,8°C`)

**Critical limitation of the regex:**
- Label pattern `\w+\d*` matches identifiers like `temp1`, `temp2`, but NOT multi-word labels:
  - `Package id 0: +52.0°C` — ❌ NOT matched (space in label)
  - `Core 0: +42.0°C` — ❌ NOT matched (space in label)
  - `Composite Temperature: +35.0°C` — ❌ NOT matched (space, uppercase)
  - `temp1: -273.3°C` — ✅ matched

This means many sensor lines bypass the filter and appear as-is.

### 2.4 Storage location

The filtered string is stored **only** in `self.report_lines` (display). No `RawDiagnostic`, no `Observation`, no `Evidence`. The data never enters the structured diagnostic pipeline.

### 2.5 Report output

| Section | Content | Source |
|---|---|---|
| Heading | `Sensory / temperatury` | `syscheck.py:1959` |
| Data | `codeblock(sensors_filtered)` | `syscheck.py:1962` |
| Invalid count note | If filtering removed any lines, shows count and threshold | `syscheck.py:1964-1969` |
| `crit=` note | If `"crit=" in sensors_raw`, shows ⚠️ warning | `syscheck.py:1971-1974` |

### 2.6 Downstream diagnostic usage

**None.** Temperature data is display-only. No diagnostic ID, rule, or recommendation consumes sensor data.

### 2.7 Existing tests

All in `class TestInvalidTemperatures` (lines 417–455 of `test_syscheck.py`):

| Test | Input | Asserts |
|---|---|---|
| `test_absolute_zero_filtered_out` | `temp1: -273.3°C`, `temp2: +27.8°C`, `Package id 0: +52.0°C` | `-273.3` removed; `+27.8` and `+52.0` preserved |
| `test_normal_temperatures_preserved` | `Package id 0: +52.0°C (high=+100.0°C)` + `Core 0: +42.0°C` | `+52.0`, `+42.0`, `coretemp` preserved |
| `test_all_invalid_sensors_filtered` | Mixed valid/invalid | Invalid removed, valid preserved |
| `test_valid_negative_temperature_preserved` | `temp1: -50.0°C` | `-50.0` preserved |

**Coverage gaps in tests:**
- No test for `sensors` command failure or missing command
- No test for NVMe temperature lines (`Composite Temperature:`)
- No test for absurd threshold metadata like `+65261.8°C`
- No test for Fahrenheit values
- No test for comma decimal separator (tested implicitly in filter but not explicitly)
- No collector-path test (no mocked `sensors` command result)

### 2.8 What the collector preserves

| Field | Preserved? | Notes |
|---|---|---|
| Sensor chip name | ✅ (pass-through) | e.g. `coretemp-isa-0000` |
| Adapter name | ✅ (pass-through) | e.g. `Adapter: ACPI interface` |
| Label | ✅ (pass-through) | e.g. `temp1:`, `Package id 0:` |
| Current temperature | ✅ (pass-through) | Only filtered if `< -100°C` |
| High threshold | ⚠️ (unparsed) | Present in raw text like `(high = +100.0°C)` but never parsed |
| Critical threshold | ⚠️ (unparsed) | `"crit="` existence check only; value never read |
| Source line | ✅ (pass-through) | Full text preserved |
| Device class | ❌ Not collected | No sensor classification (CPU/GPU/NVMe/network) |

---

## 3. Data-Quality Findings

### 3.1 What the current filtering already handles

- **Impossible values ≈ -273°C:** Removed by `_filter_invalid_temperatures()` using `INVALID_TEMPERATURE_CELSIUS = -100.0` threshold. Works for `tempN:` pattern.
- **European decimal comma:** Handled by `.replace(",", ".")` before `float()` conversion (for `tempN:` pattern).
- **ACPI disconnected probes:** Most ACPI sensors report `-273.1°C` to `-273.3°C` — caught by the -100°C threshold.

### 3.2 What the filtering does NOT handle

| Failure mode | Impact | Example |
|---|---|---|
| **Absurd thresholds in metadata** | Not detected; line passes through unchanged | `high = +65261.8°C` or `crit = +120000.0°C` — the regex doesn't match because it looks for `°C` at the value position, and these have format `high = +65261.8°C` which the regex `([+-]?\d+[.,]\d+°[CF])` would match the `+65261.8°C` part of that line. However, the filter only removes the line if the value is below -100°C, so absurd high values pass through. |
| **Non-`tempN:` labels** | Not filtered at all; lines like `Package id 0: -273.3°C` are preserved | Regex requires `\w+\d*:` label format |
| **Missing `high`/`crit`** | Not detected; no parsing | Sensor may lack threshold entirely |
| **Transient spikes** | Not detectable (single sample, no history) | SysCheck is not a daemon |
| **Laptop vs desktop** | No differentiation | No platform-classification mechanism exists in the repository |
| **Vendor-specific naming** | Not understood | `Composite Temperature`, `Sensor 1`, `Tctl`, `Tdie`, etc. |
| **NVMe temperatures** | Not parsed or structured | `nvme smart-log` output (not `nvme list`) would contain temperature data; currently only `nvme list` is collected and displayed raw |
| **Wi-Fi/network adapter temps** | Not parsed | Some adapters expose `temp1:` in sensors |
| **Duplicate labels (multi-core)** | No deduplication | 8 cores produce 8 lines; all displayed and none compared |
| **`sensors` command unavailable** | Silently returns error string | Not an optional dependency; no diagnostic about missing sensors |
| **`crit=` string existence check** | Produces ⚠️ even when no threshold is exceeded | `"crit=" in sensors_raw` checks only if any sensor *defines* a critical threshold, NOT whether it is *exceeded*. This is a false-positive risk in the display layer. |

---

## 4. Display-Layer Defect: The `crit=` Warning

### 4.1 Defect description

```python
if "crit=" in sensors_raw:
    self.report_lines.append("⚠️ Wykryto krytyczne limity temperatur w sensors.\n\n")
```

This fires on any `sensors` output that contains the string `crit=` — which is almost every sensors output on any Linux machine (most sensors have defined critical thresholds). This does **not** mean any threshold is exceeded. The warning is essentially always present and therefore meaningless.

**Classification:**
- This is a **display-layer correctness defect**, not a diagnostic activation issue.
- It is a false-positive in the report output, not in the structured diagnostic pipeline.
- It exists entirely in `collect_resources()` display code (lines 1971–1974).

### 4.2 Possible maintenance fix

**Option A: Remove the warning** — The string is `"crit="` which is a substring match against raw sensor output. Since `crit=` appears in virtually all sensor configurations, the warning conveys no information. Removing it would clean up the report without loss of signal.

**Option B: Replace with accurate parsing** — Parse the actual `crit=` value from each sensor line and compare it to the current reading. This would require per-line regex parsing (e.g., extracting `crit = +100.0°C` from lines like `Package id 0: +52.0°C (high = +100.0°C, crit = +100.0°C)`) and comparing numeric values. This is a small implementation task but requires test coverage for varied sensor output formats.

**Option C: Record for later** — Leave the misleading warning in place and fix it as part of a future temperature-parsing slice.

**Recommendation for this document:** The decision on fixing this display defect is independent of the diagnostic activation question below. The correction is small and low-risk, but this assessment does not implement it.

---

## 5. Candidate-by-Candidate Readiness Table

| # | Candidate | Readiness | Rationale |
|---|---|---|---|
| 1 | **CPU package over-temperature** | 🟡 Unsafe / too hardware-specific | `Package id 0:` value is present in raw output but not individually parsed. Threshold varies by CPU generation (95°C–105°C Tjmax). No sensor-provided `crit` value is parsed. Universal threshold would be guesswork. |
| 2 | **CPU core over-temperature** | 🔴 Unsafe / too hardware-specific | `Core N:` lines exist but are not parsed. Same threshold problem as package. Multi-core creates deduplication questions (one finding per core? one finding with max?). |
| 3 | **NVMe composite over-temperature** | 🔴 Low product value + prerequisite | NVMe temperature data would require `nvme smart-log` parsing per device. The `nvme` command is already optional (marked `optional_dependency=True`). The `nvme list` output currently collected is a device inventory (model, serial, firmware) and does not include temperature; temperature requires the `smart-log` subcommand. NVMe temperature thresholds are device-specific and not exposed by the standard CLI. |
| 4 | **Network adapter temperature** | 🔴 Low product value | Some Wi-Fi/ethernet chips expose temperature via sensors (e.g., `iwlwifi_1: temp1:`). Format varies. Product value is low — users rarely need a diagnostic for network adapter temperature. |
| 5 | **Generic sensor threshold violation** | 🟡 Ready with a small prerequisite | Most sensors provide `high=` and `crit=` values on the same line as the reading. These could be parsed from the existing raw output. Prerequisite: a helper that extracts both `current` and `high`/`crit` from sensor lines. Still faces the single-sample problem (SysCheck is not a daemon). |
| 6 | **Invalid sensor reading detection** | 🟢 Ready now | The `_filter_invalid_temperatures()` already identifies invalid readings. A diagnostic could count how many sensors were filtered and produce a Finding if count > 0. Low false-positive risk (values < -100°C are clearly hardware faults). |
| 7 | **`sensors` command unavailable / no data** | 🟢 Ready now | The command is not an optional dependency; failure is silently swallowed. A simple diagnostic could check whether `sensors` output is empty or contains an error message. Low false-positive risk, low implementation cost. |
| 8 | **Report-only classification** | 🟢 Already the current state | Temperature data is displayed in the report but never enters the pipeline. This is the status quo. |

---

## 6. Threshold Authority Analysis

### 6.1 Available threshold sources (in order of preference)

| Source | Present in data? | Example |
|---|---|---|
| 1. Sensor-provided `crit` | ⚠️ Present as raw text, not parsed | `crit = +100.0°C` in line like `Package id 0: +52.0°C (high = +100.0°C, crit = +100.0°C)` |
| 2. Sensor-provided `high` | ⚠️ Present as raw text, not parsed | `high = +100.0°C` |
| 3. Existing project constant | Only `INVALID_TEMPERATURE_CELSIUS = -100.0` exists. No high-temperature constant. | — |
| 4. Documented product threshold | None documented. No repository policy establishes "CPU above 80°C is hot" or any similar statement. | — |

### 6.2 Conclusion on thresholds

**No reliable temperature threshold exists in the repository today.** The `sensors` output contains per-sensor `high=` and `crit=` values in the raw text, but these are never parsed. Two paths exist:

1. **Parse sensor-provided thresholds** — This is the principled approach, but sensor output format varies significantly across chips and vendors. The `sensors` command output is designed for human reading, not machine parsing. Different sensors present thresholds in different formats (`high = +X°C`, `crit = +Y°C`, `HTCrit`, `TjMax`, etc.).

2. **Invent project-wide thresholds** — This violates the assessment constraint: "Do not invent universal temperature thresholds unless justified by existing collected metadata or stable platform semantics." The repository has no such policy today.

**Recommendation:** Neither path is safe for a deterministic diagnostic without prerequisite work.

---

## 7. False-Positive Analysis

| Risk | Analysis |
|---|---|
| **Single-sample risk** | HIGH. SysCheck captures a single `sensors` snapshot. A temporary load spike (compilation, gaming, video encoding) could show an elevated temperature that is not representative of steady-state operation. Without time-series data, a temperature Finding could be caused by running a build at the moment of diagnostic capture. |
| **`crit=` display defect** | HIGH for report quality. The current `"crit=" in sensors_raw` check fires on threshold *definition*, not threshold *exceedance*. This is a display-layer defect, not a diagnostic pipeline issue (see Section 4). |
| **Laptop vs desktop** | HIGH. A laptop CPU at 90°C under load can be normal; a desktop CPU at 90°C may indicate a cooling problem. SysCheck has no platform-classification mechanism to distinguish these cases. Any universal threshold would produce false positives on one class or false negatives on the other. |
| **GPU vs CPU vs other** | HIGH. Different components have radically different safe operating ranges. Without parsing sensor chip names and mapping them to component classes, a generic threshold would flag GPU temperatures as CPU problems or vice versa. |
| **`_filter_invalid_temperatures` regex gap** | MEDIUM. The regex only matches `tempN:` labels. Multi-word labels like `Package id 0:` are not filtered. If a `Package id 0: -273.3°C` line appears, it would pass through and appear in the report as a valid -273°C reading. |
| **Comma decimal locale** | LOW. Handled by `.replace(",", ".")`. But only for the `tempN:` regex path. |
| **Absurd metadata values** | LOW FP risk for current display-only mode, but would become a problem if thresholds are parsed without validation. |

---

## 8. Comparison Against Other Collector Activation Candidates

### 8.1 Reassessment rationale

The preceding Existing Data Activation Implementation Plan
(`deepseek-v4-flash-max-existing-data-activation-implementation-plan.md`)
identified firewall as the primary activation slice, driven by lowest
implementation cost. That plan predates the product decision to reject
firewall-first activation. This section re-evaluates candidates by
**product value and diagnostic authority**, not implementation ease.

### 8.2 Candidates sorted by product value

| # | Candidate | Product value | FP risk | Current status | Recommended disposition |
|---|---|---|---|---|---|
| 1 | **ZRAM/RAM pressure** | Medium — swap/memory pressure is a real user problem affecting performance and stability | Low-Medium (threshold-dependent; `free -h` and `zramctl` are structured enough for stable parsing) | Report-only (display) | **Likely next activation candidate** — higher user value than other report-only domains; output is relatively structured |
| 2 | **CPU governor/frequency** | Low — informational only; users rarely act on governor data | Low | Report-only (display) | Keep report-only |
| 3 | **Graphics logs** | Medium — GPU errors are user-visible | High (transient driver messages; many false positives) | Report-only (display) | Keep report-only |
| 4 | **Timers** | Low — informational listing | Low | Report-only (display) | Keep report-only |
| 5 | **Firewall** | Low-Medium — security awareness, but absence of a firewall is policy/configuration, not necessarily a workstation fault; `firewall_found` does not prove effective filtering; data lacks sufficient authority and provenance | Low per-check, but prescriptive remediation risks security-scanner drift | Report-only with pre-computed `firewall_found` | **Deferred** — rejected by product decision; implementation ease does not outweigh product and authority concerns |
| 6 | **Temperature/sensors** | Medium-High (thermal problems are real) | Medium-High (single-sample, cross-platform, no parseable thresholds) | Report-only with partial filtering | **Deferred** (this assessment) |

### 8.3 Why firewall is not the next candidate

The project explicitly rejected firewall as the first Existing Data
Activation implementation because:

1. Absence of a firewall is policy/configuration, not necessarily a
   workstation fault.
2. `firewall_found` does not prove effective filtering — a detected
   firewall may still be misconfigured.
3. The available firewall data lacks sufficient authority and provenance
   to drive a confident diagnostic.
4. Prescriptive remediation ("install a firewall") risks security-scanner
   drift and may not be appropriate for all deployment contexts.
5. The original selection was driven by implementation ease rather than
   product priority.

Firewall remains a possible future candidate if product requirements
explicitly mandate security-baseline diagnostics, but it is not the
recommended next slice.

### 8.4 Recommended next activation candidate

**ZRAM/RAM pressure assessment** should be the next Existing Data
Activation candidate, subject to a separate assessment confirming:

- `free -h` and `zramctl` output formats are stable enough for parsing
- Diagnostic thresholds can be derived from the data (e.g., available
  memory percentage, swap usage, compression ratio)
- The resulting Finding would have acceptable FP risk

This recommendation is based on:

- **Product value:** Memory pressure is a real and common workstation
  problem that users can act on (add swap, close applications, add RAM).
- **Data structure:** `free -h` and `zramctl` output is more structured
  than `sensors` output, reducing parsing complexity.
- **No new collectors needed:** Both commands already run in
  `collect_resources()`; activation requires only parsing and pipeline
  integration.

---

## 9. Final Decisions

### Decision A — Collector classification: Report-only / Deferred

**Temperature sensor data remains report-only.** The collector output is
displayed in the report section "Sensory / temperatury" but does not enter
the structured diagnostic pipeline. This classification is correct for the
current state of the data.

### Decision B — Display-layer defect: `crit=` warning

**The `"crit=" in sensors_raw` check is a display correctness defect.**
It detects whether any sensor *defines* a critical threshold, not whether
any threshold is *exceeded*. Since virtually all Linux sensor
configurations define `crit=` values, the warning fires on every report
and conveys no information.

**Recommended disposition:** Fix as a narrow report-correctness
maintenance slice. Two options:

- **Remove the warning entirely** (lowest risk, removes noise).
- **Replace with per-line `crit=` parsing** that compares the current
  reading to the sensor-defined critical threshold and warns only when a
  threshold is exceeded (more value, more implementation effort).

The decision to fix this defect is independent of diagnostic activation.

### Decision C — Diagnostic activation: Not ready

**Temperature data is not ready for deterministic diagnostic activation.**
The reasons are:

1. **No parseable threshold authority exists in the data.** Sensor-provided
   `high=` and `crit=` values are embedded in human-readable `sensors`
   output with format variations across chips and vendors. Universal
   thresholds would be guesswork.

2. **Single-sample FP risk.** SysCheck is not a daemon. A single `sensors`
   snapshot during a transient load spike would trigger a false-positive
   thermal Finding. Mitigating this would require either multiple samples
   (anti-pattern for a read-only CLI tool) or load-agnostic thresholds
   (unsafe).

3. **The three available low-cost slices (invalid reading detection,
   missing sensors detection, report-only) have low or zero product value
   for the user.** Detecting disconnected ACPI probes or missing
   `lm_sensors` does not answer "is my system overheating?".

4. **Higher-value activation candidates exist.** ZRAM/RAM pressure
   assessment addresses a real user problem with lower implementation
   complexity (see Section 8).

### Decision D — Recommended next step

```
1. Fix misleading temperature report warning (Section 4.2)
   ↓
2. Keep sensors as report-only/deferred (Decision A)
   ↓
3. Assess ZRAM/RAM pressure as next Existing Data Activation candidate
```

### What future evidence would justify temperature activation

1. A `sensors -j` (JSON output) parser could replace the human-readable
   format with structured machine-parseable data. The stability of `sensors -j`
   output across hardware configurations has not been verified in this
   repository and would need testing on 3+ different platforms before
   relying on it as a data source.

2. If the data pipeline is extended with a stable platform-classification
   mechanism (laptop vs desktop), threshold authority could be
   established per class. No such mechanism exists today.

3. If product requirements explicitly prioritize thermal diagnostics
   (e.g., mobile workstation focus), the trade-off may shift.

---

## 10. Unresolved Uncertainties

| Uncertainty | Impact | Resolution path |
|---|---|---|
| `sensors -j` output format stability across hardware configs | Could enable structured temperature parsing without per-chip regex | Test `sensors -j` on 3+ different hardware configurations. Not verified in this repository. |
| CPU Tjmax values per generation | Required for any CPU temperature diagnostic | Intel/AMD document these; could be compiled as a constant table if product requirements mandate |
| NVMe `nvme smart-log` temperature format | Required for NVMe temperature diagnostic | The `nvme` CLI has a `smart-log` subcommand with structured output; not currently collected or tested in this repository |
| Laptop vs desktop classification | Required to set correct severity for temperature readings | Could use `chassis-type` from DMI or `systemd-detect-virt`; no mechanism exists today |
| `free -h` and `zramctl` output format stability | Required for ZRAM/RAM activation candidate | Must be verified in a separate assessment before committing to parsing |

---

## 11. Confirmation

No production code, tests, constants, or configuration were modified. No
collectors, commands, diagnostics, or architecture were introduced. Only
this assessment document was corrected at the required path.

### Git restrictions confirmed

- ❌ No `syscheck.py` modification
- ❌ No `test_syscheck.py` modification
- ❌ No `constants.py` modification
- ❌ No diagnostic implementation
- ❌ No report warning fix implementation
- ❌ No `git add` / staging
- ❌ No `git commit`
- ❌ No `git push`
- ❌ No `git reset`
- ❌ No `git restore`
- ❌ No branch creation
- ❌ No artifact renaming
- ❌ No history rewrite
