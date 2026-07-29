# DeepSeek V4 Flash Max — ZRAM / RAM Pressure Diagnostics Assessment (Corrected)

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   clean (1 untracked file — this assessment document)
Recent commits (git log -5 --oneline):
  6804f70 fix: remove misleading temperature warning
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

Only this assessment document is untracked. No production changes are
present.

---

## 2. Current Data-Flow Inventory

### 2.1 Collector: `free -h`

| Property | Value |
|---|---|
| Method | `SysCheckEngine.collect_resources()` |
| Command | `["free", "-h"]` |
| Timeout | `TIMEOUT_SHORT` (10s) |
| Optional | No |
| Execution | Via `_parallel()` — returns raw `str`, **not** `CmdResult` |
| Source line | `syscheck.py:1916` (task dict entry) |
| Report display | `codeblock(r["free_h"])` at line 1944 |
| Parsing | **None** — raw string displayed as-is |

**Output format (example):**

```
               total        used        free      shared  buff/cache   available
Mem:            31Gi        12Gi       2.1Gi       1.2Gi        17Gi        18Gi
Swap:          8.0Gi       1.2Gi       6.8Gi
```

**Semantics of each column as produced by `free -h`:**

| Column | Meaning |
|---|---|
| `total` | Total installed physical RAM (or configured swap) |
| `used` | `total − free − buff/cache` — memory used by processes, kernel slabs, and non-reclaimable allocations. **Does not** include the page cache (that is in `buff/cache`). |
| `free` | Memory not allocated to any purpose |
| `shared` | Memory used by tmpfs (shared memory) — a subset of `used`/`buff/cache` |
| `buff/cache` | Page cache + buffer cache + reclaimable slab. The kernel can reclaim this under pressure. |
| `available` | Kernel's estimate (`MemAvailable` from `/proc/meminfo`) of memory available for starting new applications. Accounts for reclaimable cache. |

**Key distinction:** The formula `used = total − free − buff/cache` means
`used` specifically **excludes** the page cache. A high `used / total`
ratio is normal on any system with I/O activity because the kernel
deliberately uses free memory for caching. The column `buff/cache` holds
the reclaimable cache, and `available` reflects how much can be
reclaimed. **A diagnostic based solely on `used / total` would be
semantically incorrect.**

**Fields available in the raw string but never parsed:**

| Field | Available | Parsed | Format |
|---|---|---|---|
| Total RAM | ✅ in raw text | ❌ | Human-readable with suffix (e.g. `31Gi`, `7.7Gi`) |
| Used RAM | ✅ | ❌ | Human-readable |
| Free RAM | ✅ | ❌ | Human-readable |
| Shared | ✅ | ❌ | Human-readable |
| Buff/cache | ✅ | ❌ | Human-readable |
| Available RAM | ✅ | ❌ | Human-readable — **MemAvailable** is the key pressure signal |
| Total swap | ✅ | ❌ | Human-readable |
| Used swap | ✅ | ❌ | Human-readable |
| Free swap | ✅ | ❌ | Human-readable |

**No `free` (without `-h`) or `/proc/meminfo` is collected.** Only
human-readable `free -h` exists in the data pipeline.

**Localization:** `run_cmd()` (line 254) copies `os.environ` without
forcing `LANG=C`. The `free -h` output may therefore vary by system
locale — column headers and unit suffixes could differ. This has not been
verified on non-English systems in this repository.

### 2.2 Collector: `zramctl`

| Property | Value |
|---|---|
| Method | `SysCheckEngine.collect_resources()` |
| Command | `["zramctl"]` |
| Timeout | `TIMEOUT_SHORT` (10s) |
| Optional | No |
| Execution | Via `_parallel()` — raw `str` |
| Source line | `syscheck.py:1917` |
| Report display | `codeblock(r["zramctl"])` at line 1947 |
| Parsing | **None** — raw string displayed as-is |

**Output format (example):**

```
NAME       ALGORITHM DISKSIZE   DATA  COMPR  TOTAL  STREAMS MOUNTPOINT
/dev/zram0 lz4             8G   2.5G  614M   653M       12 [SWAP]
```

**Fields available in raw text but never parsed:**

| Field | Available | Parsed | Format |
|---|---|---|---|
| Device name | ✅ | ❌ | `/dev/zram0` |
| Algorithm | ✅ | ❌ | `lz4`, `zstd`, `lzo` |
| Disksize | ✅ | ❌ | Human-readable (`8G`) |
| Data (original size) | ✅ | ❌ | Human-readable (`2.5G`) |
| Compressed size | ✅ | ❌ | Human-readable (`614M`) |
| Total memory used | ✅ | ❌ | Human-readable (`653M`) |
| Streams | ✅ | ❌ | Integer |
| Mountpoint | ✅ | ❌ | `[SWAP]` or `/mount/point` |

**Failure mode:** If `zramctl` is not available, `_parallel()` returns a
Polish error string via `cmd_ok()` fallback: `"(nie znaleziono: zramctl)"`,
`"(błąd rc=...)"`, or `"(błąd równoległy: ...)"` depending on the failure
mode.

### 2.3 Collector: kernel errors (OOM evidence)

| Property | Value |
|---|---|
| Method | `SysCheckEngine.collect_kernel_hw()` |
| Command | `journalctl -b -k \| grep -iE 'error\|fail\|BUG\|lockup\|hung\|oom\|taint\|Call Trace'` |
| Source line | `syscheck.py:2125-2128` |
| Result type | `CmdResult` (via `_parallel_cmd()`) |
| Display | `kernel_errors_out = _filter_own_journal_entries(kernel_errors_result.to_fallback_text())` |
| OOM-specific parsing | **None** — OOM lines coexist with all other kernel errors in a single display block |

The regex `RE_KERNEL_ERROR = r"error|fail|BUG|lockup|hung|oom|taint|Call Trace"`
matches the contiguous substring `"oom"` case-insensitively anywhere in a
journal line. This means:

- Lines containing `"oom-killer:"` match ✅ (contains `"oom"`)
- Lines containing `"oom_reaper"` match ✅ (contains `"oom"`)
- Lines containing `"systemd-oomd"` match ✅ (contains `"oomd"` which contains `"oom"`)
- Lines containing incidental words like `"bloom"`, `"doom"`, `"room"`,
  or identifiers containing `"oom"` also match — these are noise.

Lines **not** matched by the `oom` alternative (and likely not matched
by any other alternative either):

- `"Out of memory:"` ❌ — does NOT contain the substring `"oom"`
- `"Memory cgroup out of memory:"` ❌ — does NOT contain `"oom"`
- `"oom"` is a 3-character sequence; `"memory"` contains `"memo"`, not
  `"oom"`. No form of the word `"memory"` contains the substring `"oom"`.

**No dedicated OOM collector exists.** OOM evidence is a subset of the
general kernel error display only if the line happens to match one of
the broad display-grep alternatives. Lines that describe OOM outcomes
(`Out of memory:`) but lack `oom-killer`, `oom_reaper`, or another
matched keyword are **silently excluded** from the existing filtered
output.

### 2.4 Other memory-related data

| Data source | Collected? | Where |
|---|---|---|
| `loadavg` (`/proc/loadavg`) | ✅ Display only, line 1938 | `collect_resources()` — CPU load, not memory |
| `ps aux --sort=-%mem` | ✅ Display only (top 16), line 1954-1957 | Per-process memory %, not parsed |
| `/proc/meminfo` | ❌ Not collected | — |
| `swapon --show` | ❌ Not collected | — |
| `/proc/pressure/memory` (PSI) | ❌ Not collected | — |
| `free` (machine-readable) | ❌ Not collected | Only `free -h` exists |
| `vmstat` | ❌ Not collected | — |
| `/proc/sys/vm/swappiness` | ❌ Not collected | — |

### 2.5 Storage location

All RAM, swap, and ZRAM data is stored **only** in `self.report_lines`
(display). No `RawDiagnostic`, `Observation`, or `Evidence` is created for
any memory, swap, or ZRAM data. Kernel OOM evidence is also
display-only — it passes through `_filter_own_journal_entries()` but never
enters the structured diagnostic pipeline.

### 2.6 Structured diagnostic usage

**None.** The diagnostic pipeline has:

| Component | RAM/swap/ZRAM usage | OOM usage |
|---|---|---|
| `RawDiagnostic` | 0 of 12 instances | 0 of 12 |
| `Observation` | 0 of 12 categories | 0 of 12 |
| `Evidence` | 0 of 12 branches | 0 of 12 |
| Diagnostic rules | 0 of 11 rules | 0 of 11 |
| `FindingKind` | 0 of 9 values | 0 of 9 |

### 2.7 Existing tests

**No tests exist for memory, swap, ZRAM, or OOM data flow.** The only
incidental references are:

- `TestSensorsCollectorPath` (lines 5915-5920 of `test_syscheck.py`)
  provides empty strings for `free_h`, `zramctl`, `loadavg` as mock noise
  — these are not memory tests.
- Line 5774 mentions `"swapper"` as a process name in segfault tests —
  not a memory test.

---

## 3. Current Architecture Compatibility Table

Before proposing any contract, every new category, enum value, severity,
confidence, and evidence type must be checked against existing source
definitions.

### 3.1 `FindingKind` enum (lines 129-139)

| Existing value | Can be reused? |
|---|---|
| `FAILED_UNIT` | ❌ Unrelated |
| `STORAGE_USAGE` | ❌ Storage-specific |
| `SCRUB_STATUS` | ❌ Btrfs-specific |
| `DEVICE_ERROR` | ❌ Btrfs-specific |
| `SEGFAULT` | ❌ Stability-specific |
| `KERNEL_COUNT` | ❌ Package-specific |
| `KERNEL_TAINT` | Closest semantic match — kernel-level event | ✅ **Reusable** (kernel_taint already signals kernel anomalies) |
| `BOOT_DELAY` | ❌ Boot-specific |
| `GENERAL` | ✅ **Fallback** — if no specific kind fits |

A new `FindingKind.OOM_EVIDENCE` = `"oom_evidence"` would follow existing
convention (e.g., `KERNEL_TAINT = "kernel_taint"`). Adding a value to an
existing `Enum` is a trivial change, but the assessment should note it.

### 3.2 `EvidenceType` enum (lines 719-730)

| Existing value | Can be reused? |
|---|---|
| `JOURNAL_EVENT` | ✅ **Existing** — used by segfault rules (line 843). Already designed for kernel journal evidence. |
| `SYSTEM_STATE` | ✅ Alternate — used by taint rule (line 978) |

`JOURNAL_EVENT` is the correct fit for OOM evidence — it is the same
type used for segfault journal evidence and requires no new enum value.

### 3.3 Severity values (from `Finding.severity` docstring, line 164)

| Value | Meaning |
|---|---|
| `"P0"` | Highest urgency (not used in any existing finding) |
| `"P1"` | Critical — used for BTRFS-ERR-001 (filesystem damage) and SEGFAULT-SYS-001 (system-wide segfault storms) |
| `"P2"` | Warning — used for kernel taint, failed systemd units, scrub issues, WirePlumber segfaults |
| `"P3"` | Informational warning — used for minor segfaults, slow boot |
| `"Info"` | Pure information — used for kernel count |

**There is no documented policy document assigning OOM to a specific
severity.** The assignment of P1, P2, P3, or Info for OOM would be a
product-policy decision, not derivable from source alone.

### 3.4 Confidence values (from `Finding.confidence` docstring, line 165)

| Value | Meaning |
|---|---|
| `"Certain"` | No ambiguity — used for deterministic matches (kernel taint with exact `Tainted:` pattern) |
| `"Likely"` | Some inference required |
| `"Guessing"` | Weakest — not used in any existing finding |

OOM evidence that matches an exact journal pattern could be `"Certain"`
in confidence, following the pattern of `KernelTaintRule` which also
matches a deterministic kernel output pattern.

### 3.5 `FindingClassificationPolicy._BY_CATEGORY` (lines 631-668)

Current registered categories:
- `"btrfs_error"` → `FILESYSTEM` / `DEVICE_ERROR` / `ACTIONABLE` / `VERIFY`
- `"btrfs_scrub"` → `FILESYSTEM` / `SCRUB_STATUS` / `ACTIONABLE` / `REMEDIATE`
- `"segfault_minor"` → `KERNEL` / `SEGFAULT` / `ACTIONABLE` / `MONITOR`
- `"tainted"` → `KERNEL` / `KERNEL_TAINT` / `CONDITIONAL` / `MONITOR`
- `"kernel_count"` → `PACKAGES` / `KERNEL_COUNT` / `INFORMATIONAL` / `INFORMATIONAL`
- `"boot_time"` → `BOOT` / `BOOT_DELAY` / `CONDITIONAL` / `MONITOR`

Plus runtime branches for `"segfault"`, `"systemd_failed"`, and
`"storage_usage"`.

A new `"oom_evidence"` category would need a `_BY_CATEGORY` entry or a
new runtime branch. An appropriate domain would be `KERNEL` (existing,
line 116) — mirroring `"tainted"`.

### 3.6 `EvidenceBuilder` (lines 780-1036)

Current supported categories: `systemd_failed`, `storage_usage`,
`segfault`, `segfault_minor`, `kernel_count`, `btrfs_scrub`,
`btrfs_error`, `tainted`, `boot_time`.

A new branch for `"oom_evidence"` returning `JOURNAL_EVENT` evidence would
follow the same pattern as the segfault branches. No new `EvidenceType`
value would be needed.

### 3.7 `build_default_rule_engine()` (lines 1635-1651)

Currently registers 11 rules. A new OOM rule would be the 12th.

---

## 4. Candidate-by-Candidate Readiness Table

### 4.1 RAM / swap / ZRAM candidates

| # | Candidate | Readiness | Rationale |
|---|---|---|---|
| 1 | **Low MemAvailable** | 🔴 Prerequisite + policy needed | Requires parsing `free -h` output (human-readable, locale-dependent) or adding `/proc/meminfo` collector. No threshold policy exists in the repository. All thresholds (10%, 500 MB, etc.) would be invented, not source-grounded. |
| 2 | **High RAM used percentage** | 🔴 Misleading | `used` excludes `buff/cache` via the formula `used = total − free − buff/cache`. A high `used / total` ratio is normal and does not indicate pressure. A diagnostic based on this would produce false positives on healthy systems. |
| 3 | **High swap usage percentage** | 🔴 Misleading alone | Swap occupancy from a single snapshot cannot distinguish stale occupancy from active thrashing. Systems with ZRAM show swap usage as normal behavior. |
| 4 | **ZRAM usage / compression ratio** | 🔴 Supporting evidence only | ZRAM usage is expected on configured systems. Poor compression ratio indicates incompressible data, not memory pressure. Does not independently diagnose any fault. |
| 5 | **No swap or ZRAM configured** | 🟢 Low-value boolean | Deterministic from `free -h` or `zramctl` output. However, many workstations deliberately run without swap; the finding would be `INFORMATIONAL` at best, with `Actionability.INFORMATIONAL` and `RecommendationIntent.INFORMATIONAL`. |
| 6 | **Swap enabled but unused** | 🟢 Low-value boolean | Deterministic. Information only — not actionable. |
| 7 | **`free -h` or `zramctl` unavailable** | 🟡 Prerequisite required | `_parallel()` returns error strings in Polish (`"(nie znaleziono: ...)"`, `"(błąd rc=...)"`, `"(błąd równoległy: ...)"`). A diagnostic would need to pattern-match these error strings, which is fragile. |
| 8 | **Combined pressure (MemAvailable + swap + ZRAM)** | 🔴 Multiple prerequisites | Requires parsing, threshold policy, and multi-signal rule logic. No source authority for any individual threshold. |

### 4.2 OOM evidence candidates

| # | Candidate | Readiness | Rationale |
|---|---|---|---|
| 9 | **OOM evidence from current boot** | 🟡 Separate assessment needed | Some OOM-related lines (those containing `"oom-killer:"` or `"oom_reaper"`) survive the display grep and appear in `kernel_errors_result.stdout`, but `"Out of memory:"` and memcg OOM lines are excluded. Exact markers, deduplication, path choice, and severity require a dedicated assessment before implementation. |

### 4.3 Collector classification summary

| Collector | Current status | Corrected classification |
|---|---|---|
| `free -h` | Report-only | **Report-only** — prerequisite for future structured memory pressure |
| `zramctl` | Report-only | **Report-only / supporting evidence** |
| Kernel errors (for OOM) | Report-only / display | **Separate activation candidate** — not part of RAM/ZRAM activation |

**OOM evidence does not activate the RAM/ZRAM collectors.** OOM data
comes from a different collector (`collect_kernel_hw()`) and a different
command (`journalctl -k`). The three data sources are independent.

---

## 5. Threshold Authority Analysis

### 5.1 Available source-grounded thresholds

| Threshold | Source | Authority |
|---|---|---|
| `INVALID_TEMPERATURE_CELSIUS = -100.0` | `constants.py:43` | Physical constant (below absolute zero is impossible) |
| `STORAGE_WARNING_PERCENT = 75` | `constants.py:46` | Product-defined threshold in `constants.py` |
| `STORAGE_CRITICAL_PERCENT = 90` | `constants.py:47` | Product-defined threshold in `constants.py` |
| `SEGFAULT_ALERT_THRESHOLD = 3` | `constants.py:40` | Product-defined threshold in `constants.py` |

**No memory-related threshold exists in the repository.** The following
would be invented rather than sourced:

- ❌ MemAvailable < 10% of total RAM (not in `constants.py`, not in any
  diagnostic policy)
- ❌ MemAvailable < 500 MB absolute floor (no source authority)
- ❌ Swap usage > 90% or > 20% (no source authority)
- ❌ ZRAM compression ratio < 2:1 (no source authority)
- ❌ P1 for any OOM event (no severity-policy document assigning OOM to P1)

### 5.2 Unsupported claims removed

The original assessment included several threshold claims that cannot be
grounded in repository source:

1. **"10% MemAvailable derived from kernel watermarks"** — The Linux
   kernel's `watermark_low` varies by zone size and is typically 5–10%,
   but this is not a documented repository policy. The repository has no
   watermark-reading mechanism and no product decision adopting this
   threshold.

2. **"20% swap usage as corroboration"** — No source-grounded rationale
   for 20% over any other value. Invented for the assessment.

3. **"500 MB absolute floor"** — Invented heuristic with no source
   authority. Would behave differently on 8 GB vs 128 GB systems.

4. **"P1 for OOM events"** — P1 severity is used in existing code for
   BTRFS-ERR-001 (filesystem damage) and SEGFAULT-SYS-001 (active
   system-wide segfault storms). Whether OOM merits P1 is a product-policy
   decision, not derivable from source.

### 5.3 What threshold evidence would be required for activation

For a MemAvailable diagnostic, the following would need to be established:

1. A threshold constant in `constants.py` (following the existing pattern
   of `STORAGE_WARNING_PERCENT` and `STORAGE_CRITICAL_PERCENT`)
2. A product decision documenting why the chosen value is appropriate
   across the supported RAM range (8 GB – 128 GB)
3. A parsing strategy for `free -h` output (human-readable units, locale
   variance) — or a new `/proc/meminfo` collector providing machine-readable
   bytes

---

## 6. OOM Matching and False-Positive Analysis

### 6.1 What `"oom"` matches in the current collector

The current kernel error collector (line 2127) runs:

```bash
journalctl -b -k --no-pager 2>/dev/null | grep -iE 'error|fail|BUG|lockup|hung|oom|taint|Call Trace' | tail -50
```

The `grep -iE` matches the contiguous substring `"oom"` case-insensitively
anywhere in a journal line. It does **not** match `"memory"`, `"Out of
memory"`, or any other word where the letters o-o-m are not adjacent.

The following table shows which kernel OOM-related line types the current
display grep does and does not capture:

| Line class | Example kernel line | Captured by current grep? | Reason |
|---|---|---|---|
| **Global OOM invocation** | `kernel: oom-killer: gfp_mask=0x...` | ✅ | Contains `"oom"` (in `"oom-killer"`) |
| **OOM reaper action** | `kernel: oom_reaper: reaped process ...` | ✅ | Contains `"oom"` (in `"oom_reaper"`) |
| **Global OOM outcome** | `kernel: Out of memory: Killed process 1234 (firefox)` | ❌ | Does NOT contain `"oom"`. `"Out of memory"` has no contiguous `oom`. |
| **memcg OOM** | `kernel: Memory cgroup out of memory: Killed process 1234` | ❌ | Does NOT contain `"oom"`. `"memory"` contains `"memo"`, not `"oom"`. |
| **systemd-oomd** | `systemd-oomd[123]: Killed ... due to memory pressure` | ✅ | Contains `"oom"` (in `"oomd"`) |
| **Incidental `oom` substring** | Process name containing `"boom"`, `"doom"`, `"room"` | ✅ | Contains `"oom"` |

**Key observation:** The current display grep captures only OOM lines
that literally contain the contiguous 3-character substring `"oom"`.
This includes `oom-killer` and `oom_reaper` (genuine kernel OOM events)
and `systemd-oomd` (userspace action, different mitigation). It also
catches incidental words containing `"oom"` (noise).

Crucially, it **excludes** lines that describe OOM outcomes without the
literal `"oom"` token — specifically `"Out of memory:"` and memcg OOM
messages. These describe the same memory-exhaustion events but use
different wording that the display filter does not select.

This means the existing `kernel_errors_result.stdout` is **not** a
complete OOM event collection. Any diagnostic based on parsing the
existing filtered output would capture `oom-killer` lines but miss
`Out of memory:` lines — even though both describe the same kernel OOM
kill event (the kernel emits multiple log lines per OOM: one for the
invocation and one for the outcome).

### 6.2 Prevalence of different OOM types

| Type | Captured by existing grep? | Likelihood on workstation | Significance |
|---|---|---|---|
| Global OOM invocation (`oom-killer:`) | ✅ Contains `"oom"` | Low on adequate-RAM systems, higher on 8 GB systems under load | **High** — indicates system-wide memory exhaustion |
| Global OOM outcome (`Out of memory:`) | ❌ Does NOT contain `"oom"` | Same event as above, different log line | **High** — same event, different wording. Missed by display grep. |
| memcg OOM | ❌ Does NOT contain `"oom"` | Moderate — container/podman workloads | **Medium** — indicates cgroup limit reached, not system-wide exhaustion |
| systemd-oomd | ✅ Contains `"oom"` | Low — not enabled by default on all distros | **Medium** — userspace-managed pressure, not kernel OOM |
| Incidental `"oom"` substring | ✅ Contains `"oom"` | Low — depends on process names in logs | **Low** — noise, not a real event |

### 6.3 What a presence-only OOM check would detect

**Key constraint: The existing filtered `kernel_errors_result.stdout` is
not a complete OOM record.** The display grep selects only lines
containing the contiguous substring `"oom"`. This means:

- `"oom-killer:"` lines **ARE** present in the filtered output.
- `"Out of memory:"` lines are **NOT** present — they were never selected
  by the display grep.
- memcg OOM lines are **NOT** present.

Any diagnostic based on the existing filtered output can therefore only
detect OOM events whose journal lines happen to contain the literal
substring `"oom"`. A diagnostic that searches for `"Out of memory:"`
inside `kernel_errors_result.stdout` would always return "not found" even
when the current boot had an OOM kill, because those lines were filtered
out before storage.

**Smallest contract on existing data (Path A):**

```text
"oom-killer:" in kernel_errors_result.stdout
```

This checks whether at least one `oom-killer:` invocation line survived
the display grep. It captures global kernel OOM invocations but **not**
the corresponding `"Out of memory:"` outcome lines (those are in a
different journal log line that the display grep excluded).

**Smallest contract requiring a new collector (Path B):**

```text
journalctl -b -k --no-pager | grep -iE 'oom-killer:|Out of memory:'
```

This captures both the invocation and the outcome lines. It would require
a new collector entry but would return complete OOM event data.

**Exact patterns for a precise OOM diagnostic (to be verified in a
separate assessment):**

| Pattern | Catches | Misses | Available in Path A? |
|---|---|---|---|
| `"oom-killer:"` | Global OOM invocations | Outcome lines, memcg OOM, systemd-oomd | ✅ Yes |
| `"Out of memory:"` | Global + memcg OOM outcomes | Invocations, systemd-oomd | ❌ No (not in filtered output) |
| `"systemd-oomd"` | systemd-oomd actions | Kernel OOM events | ✅ Yes |

### 6.4 Single-snapshot limitation for OOM

OOM evidence from `journalctl -b` (current boot) is **not** a single
snapshot — the journal contains the entire boot history. This is better
than `free -h` snapshot limitations because it captures events over time.
However:

- An OOM event from earlier in the current boot may have been resolved
  (process restarted, memory pressure ended). The diagnostic would still
  fire.
- This is not a false positive (the OOM did happen) but the system's
  current state may be healthy.
- A P1/P2 finding for historical OOM is still valuable (the issue may
  recur) but the finding text should distinguish "OOM occurred this boot"
  from "OOM is happening now."

---

## 7. OOM Matching: Implementation Considerations

### 7.1 Data access paths

Two implementation paths exist, with different coverage:

**Path A: Parse existing `kernel_errors_result.stdout`**

- Coverage: Can only detect lines that contain the literal substring
  `"oom"` — specifically `"oom-killer:"` and `"oom_reaper"` lines.
  Cannot detect `"Out of memory:"` lines because the display grep
  (which runs before storage) never selected them.
- Pro: No new shell command.
- Con: The grep already applied `tail -50`, so early-boot OOM events may
  be truncated if there are 50+ matching lines. The `kernel_errors_result`
  contains a mix of all kernel errors, so the OOM check must regex-search
  the already-filtered output.
- Con: An OOM event may be recorded only as an `"Out of memory:"` line
  without the `"oom-killer:"` invocation line (depending on kernel version
  and cgroup configuration). Path A would miss this.
- Risk: `tail -50` truncation plus the display-grep coverage gap means
  Path A cannot guarantee complete OOM detection.

**Path B: Add a dedicated OOM grep**

```bash
journalctl -b -k --no-pager 2>/dev/null | grep -iE 'oom-killer:|Out of memory:' | tail -20 || true
```

- Coverage: Captures both `"oom-killer:"` invocation lines and `"Out of
  memory:"` outcome lines. Not limited by the display grep's substring
  filter.
- Pro: Dedicated output with exact patterns; no competition with other
  kernel errors for `tail -50` truncation.
- Con: New shell command, new collector entry.

**Path A is not a reliable substitute for Path B.** The display-oriented
`RE_KERNEL_ERROR` grep was designed to show a human-readable sample of
kernel errors, not to collect complete OOM evidence. Relying on its
filtered output for a diagnostic would systematically miss OOM events
whose journal lines happen to use `"Out of memory"` wording without a
nearby `"oom-killer"` token. A dedicated OOM assessment must decide
whether Path A's limited coverage (only `oom-killer:` lines) is acceptable
or whether Path B (full coverage) is required.

### 7.2 Proposed minimal contract (presence-only)

```text
Diagnostic ID:   MEM-OOM-001
Category:        oom_evidence
Trigger:         At least one line matching "oom-killer:" in current-boot kernel
                 journal output (Path A) OR "oom-killer:|Out of memory:" (Path B)
Non-trigger:     No matching lines found
Payload:         {"oom_detected": true,
                  "oom_matched_lines": [str, ...]}   (preserve full matched lines)
Observation:     direct_measurement=True, data_complete=True
Evidence:        JOURNAL_EVENT (existing type, line 722)
FindingKind:     Either KERNEL_TAINT (reuse) or new OOM_EVIDENCE value
Domain:          KERNEL (existing, line 116)
Severity:        TBD by product policy (see section 7.3)
Confidence:      Certain (deterministic pattern match)
Actionability:   ACTIONABLE
Deduplication:   One RawDiagnostic per collection, regardless of match count
```

**Deliberate simplifications:**
- **Presence-only, not count-based.** No attempt to count unique OOM
  invocation events unless a separate assessment of actual OOM log format
  on kernel 6.x confirms reliable deduplication (one OOM kill can produce
  3-5 journal lines; counting lines ≠ counting events).
- **Pattern depends on implementation path.** With Path A (existing
  filtered output) only `"oom-killer:"` is reliably present. With Path B
  (dedicated grep) both `"oom-killer:"` and `"Out of memory:"` are
  available. The separate OOM assessment must decide which pattern set
  and which path to use.
- **`"systemd-oomd"` is a possible extension** but should be assessed
  separately since it reports userspace-managed actions rather than
  kernel OOM.
- **No severity decision in this assessment.** Severity requires a product
  policy decision (see section 7.3).

### 7.3 Severity discussion (not decided)

| Argument for P1 | Argument against P1 |
|---|---|
| OOM kills terminate processes — active harm | OOM may have been transient and resolved |
| Similar to SEGFAULT-SYS-001 (P1) — system instability | Similar to kernel taint (P2) — recorded event, not active crisis |
| User should act immediately | Always-present OOM on under-provisioned systems could desensitize users |

**Recommendation:** This assessment does not assign a severity. The
decision should be part of a dedicated OOM assessment that examines real
OOM log samples and decides severity policy.

### 7.4 What a dedicated OOM assessment must determine

Before implementation, a separate OOM assessment should resolve:

1. **Exact matching markers:** Inspect raw (unfiltered) `journalctl -b -k`
   output from real systems to determine which OOM-related log line
   patterns exist. Verify whether `"oom-killer:"` alone is sufficient or
   whether `"Out of memory:"` must also be covered. Determine whether
   memcg OOM and systemd-oomd should be in scope.

2. **Path A coverage gap:** Assess whether relying on the display-grep
   filtered output (which only preserves lines containing the literal
   `"oom"` substring) would miss any OOM events that a user would expect
   to be detected. If yes, Path B (dedicated grep) is required.

3. **Deduplication strategy:** Collect 5-10 real OOM log examples and
   decide whether presence-only (one RawDiagnostic) or event counting
   (unique OOM invocation events) is reliable.

4. **Severity assignment:** Produce a documented rationale for P1, P2,
   or context-dependent severity.

5. **Implementation path:** Choose Path A (parse existing output, limited
   to `oom-killer:` lines) vs Path B (dedicated grep covering `"oom-killer:"`
   and `"Out of memory:"`). If Path A, verify `tail -50` truncation does
   not miss OOM lines.

6. **systemd-oomd handling:** Decide whether to detect systemd-oomd
   separately (different mitigation: adjust MemoryMax vs add RAM) or
   defer it.

7. **Finding text and recommendation:** Draft user-facing Polish text
   for the finding and recommendation.

---

## 8. Comparison Against Other Collector Activation Candidates

| # | Candidate | Authority | User impact | FP risk | Scope | Current status |
|---|---|---|---|---|---|---|
| 1 | **OOM evidence** | MED-HIGH (kernel event, but broad grep) | HIGH (process death) | LOW with exact patterns; MEDIUM with substring `"oom"` | Separate assessment needed | Report-only (in kernel errors display) |
| 2 | **Temperature/sensors** | MED-HIGH (thermal issues) | MED-HIGH | MED-HIGH | Assessed as deferred | Report-only / deferred |
| 3 | **Firewall** | LOW-MED (policy, not fault) | MEDIUM | LOW | Assessed as rejected | Report-only |
| 4 | **Graphics logs** | MEDIUM (GPU errors) | MEDIUM | HIGH | Not assessed | Report-only |
| 5 | **CPU governor** | LOW (informational) | LOW | LOW | Not assessed | Report-only |
| 6 | **Timers** | LOW (informational) | LOW | LOW | Not assessed | Report-only |
| 7 | **MemAvailable** | LOW (no collector, no parser, no threshold policy) | HIGH | MED-HIGH (if threshold invented) | Prerequisite + policy | Report-only |

OOM evidence has the strongest authority-to-scope ratio, but requires a
dedicated assessment before implementation.

---

## 9. Final Decisions

### Decision C — RAM and ZRAM remain report-only / supporting evidence

| Collector | Classification | Rationale |
|---|---|---|
| `free -h` | **Report-only** | Human-readable output with locale-dependent units. No parser, no threshold policy, no MemAvailable extraction. Prerequisite for future structured memory pressure diagnostic. |
| `zramctl` | **Report-only / supporting evidence** | More structured than `free -h`, but ZRAM usage does not independently diagnose any fault. Could serve as supporting evidence for a combined pressure diagnostic in the future. |

**What would justify activation:**
1. A `/proc/meminfo` collector or `free -h` parser that extracts
   machine-readable `MemAvailable` bytes.
2. A product-defined threshold in `constants.py` (following the pattern
   of `STORAGE_WARNING_PERCENT` and `STORAGE_CRITICAL_PERCENT`).
3. A decision on whether percentage-based or absolute thresholds are
   appropriate for the supported RAM range.

**Neither is ready now.** Proceeding without these would require invented
thresholds with no source authority.

### Decision A — Separate OOM assessment required first

OOM evidence is the most promising activation candidate among the
report-only collectors, but it is **not ready for implementation without
a dedicated assessment** that resolves:

1. **Exact matching markers** — `"oom-killer:"` vs `"Out of memory:"` vs
   `"systemd-oomd"` vs `"oom"` substring. The current `RE_KERNEL_ERROR`
   display grep only matches lines containing the contiguous substring
   `"oom"` — it captures `"oom-killer:"` and `"systemd-oomd"` but does
   **not** capture `"Out of memory:"` or memcg OOM lines (because neither
   contains `"oom"` as adjacent characters).

2. **Deduplication** — presence-only is safe, but if event-counting is
   desired, real kernel log samples must verify that unique OOM
   invocations can be reliably extracted.

3. **Severity policy** — not derivable from source. A product decision
   is needed.

4. **Implementation path** — parse existing output (Path A, risk of
   `tail -50` truncation) vs dedicated grep command (Path B, cleaner
   but requires a new collector entry).

5. **Finding text and recommendation** — requires Polish-language output.

### Recommended ordering

```text
1. Assess OOM feasibility separately
   (resolve matching markers, deduplication, severity, path)
   ↓
2. If OOM assessment passes: implement MEM-OOM-001
   ↓
3. Add /proc/meminfo collector or free -h parser
   ↓
4. Define MemAvailable threshold policy
   ↓
5. Implement MEM-PRESSURE-001
```

---

## 10. Unresolved Uncertainties

| Uncertainty | Impact | Resolution |
|---|---|---|
| Exact `"oom-killer:"` format across kernel 6.x variants | Matching precision | Inspect journal output from 3+ kernel versions in a separate OOM assessment |
| `tail -50` truncation risk for OOM lines in Path A | May miss OOM events if 50+ kernel error lines exist | Verify worst-case kernel error volume on production systems |
| `Out of memory:` lines excluded by display grep | Path A cannot detect OOM events recorded only as `Out of memory:` | Assess whether `oom-killer:` alone is sufficient or Path B is required |
| systemd-oomd detection scope | Separate diagnostic or bundled with OOM? | Product decision on whether systemd-oomd is in scope |
| `free -h` locale variance | Column parsing reliability | Test `free -h` on 3+ locale configurations (pl_PL, de_DE, C) |
| `zramctl` column format across util-linux versions | Parsing reliability | Test `zramctl --help` and output on 3+ util-linux versions |
| MemAvailable threshold (percentage vs absolute) | Diagnostic contract shape | Product decision required; not derivable from source |
| Severity for OOM (P1 vs P2 vs context-dependent) | Finding severity assignment | Product policy decision; separate OOM assessment should recommend |
| `free` column header localization | `Mem:`, `Swap:` vs `Pamięć:`, `Wymiana:` | Currently unverified in repository |

---

## 11. Confirmation

No production code, tests, constants, or configuration were modified. No
collectors, commands, diagnostics, or architecture were introduced. Only
this assessment document was corrected at the required path.

### Git restrictions confirmed

- ❌ No `syscheck.py` modification
- ❌ No `test_syscheck.py` modification
- ❌ No `constants.py` modification
- ❌ No `FindingKind` values added or changed
- ❌ No diagnostic implementation
- ❌ No `git add` / staging
- ❌ No `git commit`
- ❌ No `git push`
- ❌ No `git reset`
- ❌ No `git restore`
- ❌ No branch creation
- ❌ No artifact renaming
- ❌ No history rewrite

---

*Assessment corrected by DeepSeek V4 Flash Max. RAM and ZRAM remain
report-only / supporting evidence. OOM evidence requires a separate
dedicated assessment before implementation.*
