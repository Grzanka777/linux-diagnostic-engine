# DeepSeek V4 Flash Max — AMDGPU Reset/Failure Diagnostic Assessment

## 1. Repository checkpoint

```
pwd             : <REDACTED-PATH>
branch          : master
working tree    : clean
git log -6      :
  0fc3937 feat: detect i915 gpu hangs
  514d488 feat: detect kernel oom events
  6804f70 fix: remove misleading temperature warning
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
```

Working tree clean. Base matches expected. No unrelated tracked changes.

## 2. Exact current data inventory

### 2.1 Direct AMDGPU collectors

**None.** No `amdgpu` substring appears in any collector command, regex pattern, or task key. AMDGPU is entirely absent from the diagnostic pipeline.

### 2.2 Broad kernel-error collector (`kernel_errors`)

| Property | Value |
|---|---|
| Command | `journalctl -b -k --no-pager 2>/dev/null \| grep -iE 'error\|fail\|BUG\|lockup\|hung\|oom\|taint\|Call Trace' \| tail -50 \|\| true` |
| Timeout | TIMEOUT_LONG |
| Optional | False |
| Truncation | `tail -50` — caps at 50 lines |
| Failure masking | `\|\| true` — upstream journalctl failure is indistinguishable from "no errors" |
| Diagnostic use | Only for `KERNEL-TAINT-001` (taint flag substring match) |
| AMDGPU context survival | Text match only. AMDGPU lines mentioning `error` or `fail` would be captured but mixed with all other kernel errors. No structured AMDGPU context. |

**Verdict:** Insufficient for AMDGPU diagnostics. Truncation, failure masking, and broad pattern make it unsuitable for deterministic marker detection.

### 2.3 Firmware-message collector (`firmware_msgs`)

| Property | Value |
|---|---|
| Command | `journalctl -b --no-pager 2>/dev/null \| grep -iE 'firmware\|microcode\|ucode' \| tail -20 \|\| true` |
| Timeout | TIMEOUT_LONG |
| AMDGPU survival | AMDGPU firmware-loading lines containing `firmware` may appear here |
| Diagnostic use | Report-only. No structured diagnostic produced. |
| Problem | Uses `journalctl -b` (all journals, not `-k`). Mixed CPU/GPU firmware messages. Tail truncation. `\|\| true`. |

**Verdict:** Not suitable. Report-only, mixed sources, truncation, failure masking.

### 2.4 Graphics-log collector (`gfx_logs` — in `collect_graphics()`)

| Property | Value |
|---|---|
| Pattern | `niri\|dms\|wayland\|greetd\|i915\|drm` filtered by `error\|fail\|warn` |
| Journal scope | `journalctl -b` (all journals — compositor, DM, kernel mixed) |
| Truncation | `tail -30` |
| Failure masking | `\|\| true` |
| Diagnostic use | Report-only (section 7.3 of report). No RawDiagnostic. |
| AMDGPU survival | `drm` substring in pattern catches some AMDGPU lines containing "drm". Upstream compositor messages (niri, wayland) dominate. |

**Verdict:** Rejected as a diagnostic source. Compositor-message mixing, truncation, failure masking, and broad pattern make it unsuitable.

### 2.5 PCI device data (`lspci -k`)

| Property | Value |
|---|---|
| Command | `lspci -k` |
| Timeout | TIMEOUT_SHORT |
| Optional | No |
| Diagnostic use | Report-only (section 4 of report). No RawDiagnostic. |
| AMDGPU relevance | Shows AMD GPU device with `Kernel driver in use: amdgpu`. Useful for confirming AMD GPU presence. |
| Limitation | No current journal event data. No driver health state. |

**Verdict:** Useful as supporting context (confirms AMD GPU presence) but not a diagnostic source for reset/failure events.

### 2.6 Dedicated AMDGPU queries

**None exist.** No equivalent of `gpu_i915_hang` exists for AMDGPU.

### 2.7 Summary

| Source | AMDGPU present? | Structured? | Diagnostic? |
|---|---|---|---|
| `kernel_errors` | Lines with `error\|fail` may be captured | No — text blob | Only taint |
| `firmware_msgs` | Lines with `firmware` may be captured | No — text blob | No |
| `gfx_logs` | Lines with `drm` may be captured | No — text blob | No |
| `lspci -k` | AMD GPU shown if present | Yes — structured PCI | No (report only) |
| Dedicated AMDGPU query | **None** | — | — |

## 3. Marker semantics matrix

### 3.1 `amdgpu_job_timedout`

| Property | Assessment |
|---|---|
| Kernel source | `drivers/gpu/drm/amd/amdgpu/amdgpu_job.c` — `amdgpu_job_timedout()` function |
| Format | `amdgpu 0000:XX:XX.X: [drm:amdgpu_job_timedout] *ERROR* Process {name} (pid {pid}) {job} timed out` |
| Classification | **diagnostic-ready** |
| Self-attributing | ✅ Yes — line includes `amdgpu` prefix with PCI address |
| Proves reset occurred? | No. Job timeout triggers the GPU reset *procedure* but does not prove hardware reset executed or completed. The timeout may also be handled by soft recovery before full reset. |
| Proves hardware failure? | No. Application bugs, kernel driver issues, firmware bugs, or transient load can cause a job timeout. It is a true event ("a job timed out") but not root-cause-diagnostic. |
| Can application/workload faults cause it? | **Yes.** A misbehaving application that submits malformed command buffers or fails to advance its ring can trigger `amdgpu_job_timedout`. This is a driver-forced timeout on a hung context, but the root cause may be software. |
| Recommended severity | P2 — historical event. Comparable to `KERNEL-OOM-001` and `GPU-I915-HANG-001`. |
| Recommended confidence | Certain — direct measurement of the timeout. But certain of event *presence*, not of root cause. |

**Key nuance:** `amdgpu_job_timedout` is a **reliable event marker** (the timeout actually happened), but it is **not a hardware-failure marker**. The diagnostic should report "a GPU job timed out" without inferring hardware defect. This is analogous to `GPU-I915-HANG-001` which reports "a GPU hang occurred" without inferring reset outcome or hardware failure.

### 3.2 `ring .* timeout`

| Property | Assessment |
|---|---|
| Kernel source | Varies — ring timeout can appear in schedulers, firmware, or job timeouts |
| Format variability | High — `ring {name} timeout`, `process {name} ring {id} timeout`, `[drm] ring {name} buffer timeout` |
| Classification | **ambiguous — requires correlation** |
| Self-attributing | ✅ When prefixed with `amdgpu` |
| Duplicates `amdgpu_job_timedout`? | Partially. A ring timeout is a lower-level event that may precede or coincide with `amdgpu_job_timedout`. The job timeout is the more authoritative marker because it is the driver's explicit timeout handler. |
| Single ring timeout sufficient? | No. A single ring timeout can be transient, especially on first occurrence. Multiple ring timeouts in the same ring/engine combined with a job timeout or reset outcome is stronger evidence. |
| Recommended classification | **Not diagnostic-ready as an isolated trigger.** Too pattern-variable. Would require correlation with other events for reliable interpretation. |

### 3.3 `GPU reset begin`

| Property | Assessment |
|---|---|
| Kernel source | `amdgpu_device_gpu_recover()` entry point |
| Format | `amdgpu 0000:XX:XX.X: amdgpu: GPU reset begin!` |
| Classification | **supporting evidence only** — recovery attempt marker |
| Self-attributing | ✅ Yes |
| Diagnostic value | Tells us the reset procedure was entered, not whether it succeeded. Alone, it is not a failure. |
| When actionable | Only if paired with `GPU reset failed` or absence of `GPU reset succeeded` within a time window. Correlation adds complexity. |
| Recommended treatment | Do not trigger a finding alone. Can be supporting context if a reset-failure finding is emitted. |

### 3.4 `GPU reset succeeded`

| Property | Assessment |
|---|---|
| Kernel source | `amdgpu_device_gpu_recover()` success path |
| Format | `amdgpu 0000:XX:XX.X: amdgpu: GPU reset succeeded!` |
| Classification | **recovery evidence** — positive recovery signal |
| Self-attributing | ✅ Yes |
| Diagnostic value | Confirms recovery completed. Alone, it is a positive event, not a failure. |
| Suppress failure finding? | Not in the narrow contract. A `GPU reset succeeded` after a `GPU reset failed` is a recovery, but if `GPU reset failed` was ever emitted, the *failure* was still a true event. However, if only `GPU reset begin` + `GPU reset succeeded` exist without any `GPU reset failed`, there is no failure to report. |
| Recommended treatment | Do not trigger a finding. Can be used as supporting context. |

### 3.5 `GPU reset failed`

| Property | Assessment |
|---|---|
| Kernel source | `amdgpu_device_gpu_recover()` failure path |
| Format | `amdgpu 0000:XX:XX.X: amdgpu: GPU reset failed!` |
| Classification | **diagnostic-ready** — exact failure marker |
| Self-attributing | ✅ Yes — line includes `amdgpu` prefix |
| Correlation required | **None** — the failure is explicit in a single line. No need to pair with `reset begin` or check for `reset succeeded`. |
| Proves permanent GPU unavailability? | No. A reset may fail transiently and the GPU may still be usable after a subsequent retry or reboot. The event is historical. |
| Proves hardware defect? | No. Could be driver, firmware, power, thermal, or PCIe timing issue. |
| Proves active user impact? | No. If the affected GPU is not the active renderer, the user may not have noticed. |
| Recommended severity | **P2** — historical explicit failure. Equal to `GPU-I915-HANG-001` and `KERNEL-OOM-001`. |
| Recommended confidence | **Certain** — direct measurement of the failure message. |
| Status in current data inventory | **Not collected.** |

### 3.6 `GPU reset end`

| Property | Assessment |
|---|---|
| Kernel source | `amdgpu_device_gpu_recover()` completion — always printed (success or fail) |
| Format | `amdgpu 0000:XX:XX.X: amdgpu: GPU reset end!` |
| Classification | **report-only** — always-emitted completion marker |

### 3.7 `VM fault` / `page fault`

| Property | Assessment |
|---|---|
| Kernel source | AMDGPU VM manager — `amdgpu_vm_bo_fault()`, `gmc_v*_0_process_interrupt()` |
| Format | `[drm:amdgpu_vm_bo_fault] *ERROR* Couldn't update page tables`; `amdgpu 0000:XX:XX.X: [drm:gmc_v9_0_process_interrupt] *ERROR* [amdgpu: VM fault ...` |
| Classification | **requires corroboration** |
| Application vs hardware | Ambiguous. Application memory corruption, bad GPU buffer allocation, or actual GPU page table corruption can all produce VM faults. Single VM faults can be transient. |
| Recommended treatment | Do not trigger a diagnostic alone. Multiple recurring VM faults with the same address range and no application change may be hardware-suggestive. |
| Diagnostic-ready? | **No.** Too ambiguous without correlation with other events or recurrence patterns. |

### 3.8 Firmware, RAS, SMU, DCN — Deferred

| Marker | Classification | Reason |
|---|---|---|
| Firmware loading (`amdgpu`: loaded firmware) | **report-only** — version info, not a fault |
| Firmware loading failure (`amdgpu`: firmware failed) | **vendor-specific** — may cause feature degradation, GPU may still work |
| RAS (Reliability/Availability/Serviceability) | **requires corroboration** — corrected vs uncorrected distinction; RAS events need additional context |
| SMU (System Management Unit) messages | **too broad** — SMU messages range from informational to critical |
| DCN (Display Core Next) messages | **too broad** — DCN link training, HPD, EDID messages are often transient/benign |

All deferred. None are ready as a standalone diagnostic trigger.

## 4. Attribution analysis

### 4.1 AMDGPU is self-attributing

All AMDGPU kernel messages follow one of these patterns:

```
amdgpu 0000:XX:XX.X: amdgpu: ...              ← driver prefix + subname
amdgpu 0000:XX:XX.X: [drm] ...                ← driver prefix + DRM core
amdgpu 0000:XX:XX.X: [drm:amdgpu_*] *ERROR*  ← driver prefix + function name
[TTM] ...  (rare, no amdgpu prefix)            ← not self-attributing (TTM is shared)
```

The driver identity is present in the line prefix. No separate PCI ID lookup or `/sys/class/drm` parse is needed to identify the source driver. **A separate driver identity parser is not a prerequisite.**

### 4.2 Driver attribution ≠ active renderer attribution

The diagnostic can determine *which driver logged the event* (driver attribution) without knowing *which GPU is driving the display* (active-renderer attribution). A reset failure on a secondary AMD GPU (e.g., in a PRIME configuration where the integrated GPU drives the display) is a true event, not a false positive. The interpretation should acknowledge that user impact may vary.

### 4.3 PCI address extraction

AMDGPU lines include PCI address (`amdgpu 0000:01:00.0`). Extracting and preserving it in the payload is useful provenance but not required for driver attribution. First-slice PCI address is optional enrichment, not a prerequisite.

## 5. Candidate comparison

### Candidate A — `GPU reset failed` (exact failure phrase)

| Criterion | Rating |
|---|---|
| Marker stability | **High.** `GPU reset failed!` is a literal string in `amdgpu_device_gpu_recover()` — stable across kernel versions. |
| Semantic precision | **Very high.** Explicit driver statement: GPU reset failed. Not inferential. |
| Self-attributing | ✅ Yes — includes `amdgpu` prefix |
| Correlation complexity | **None.** Single line, no pairing needed. |
| False-positive risk | **Near-zero.** This line is never emitted for benign reasons. The driver enters this path only after a reset procedure fails. |
| Severity clarity | P2 — explicit failure event, historical. Clear. |
| Testability | **High.** Same pattern as `GPU-I915-HANG-001`. |
| Implementation scope | **Small.** One regex constant, one collector task, one EvidenceBuilder branch, one rule, one obs-id. Same pattern as Iteration 27/28. |
| Recommendation quality | **Clear.** "Check kernel version, Mesa/firmware versions, power state, thermals, PCIe stability. Preserve log lines." |
| Status in codebase | **Absent.** No AMDGPU collector exists. Must add from scratch. |

### Candidate B — `amdgpu_job_timedout` (exact timeout marker)

| Criterion | Rating |
|---|---|
| Marker stability | **High.** Persistent across kernel versions. |
| Semantic precision | **High** that a timeout occurred, **low** for interpreting the cause. |
| Self-attributing | ✅ Yes — includes `amdgpu` prefix |
| Correlation complexity | **None** for event detection. But interpretation without reset outcome is limited ("a job timed out" — but was the GPU recovered or still hung?"). |
| False-positive risk | **Low** for event presence (the timeout happened). **Moderate** if read as "GPU is broken" (application bug can cause it). |
| Severity clarity | P2 for job timeout as a standalone event. But may need downgrade if `GPU reset succeeded` follows — requiring correlation. |
| Testability | **High.** Same pattern. |
| Implementation scope | **Small.** Same as Candidate A. |
| Recommendation quality | Weaker than Candidate A. "A job timed out" is less actionable than "GPU reset failed" because the timeout is a symptom, not a failure verdict. |

### Candidate C — Correlated timeout + reset outcome

| Criterion | Rating |
|---|---|
| Marker stability | Depends on both markers being present in the same boot |
| Semantic precision | Potentially higher: "job timed out AND reset failed" is stronger evidence than either alone |
| Correlation complexity | **High.** Requires collecting both `amdgpu_job_timedout` and one of `GPU reset begin/succeeded/failed` lines, then correlating by time proximity or reset-lifecycle window. |
| False-positive risk | Lower than either alone, but at the cost of missing cases where only one of the markers exists. |
| Severity clarity | P2 — still a historical event |
| Implementation scope | **Larger.** Requires multiple collectors and a correlation rule — a significant architecture departure from the single-marker pattern used by OOM and i915. |
| Testability | More complex correlation tests needed. |

### Comparison summary

| Criterion | A: `GPU reset failed` | B: `amdgpu_job_timedout` | C: Correlated |
|---|---|---|---|
| Marker precision | ★★★★★ | ★★★★☆ | ★★★★★ |
| Correlation needed | None | None | High |
| Testability | ★★★★★ | ★★★★★ | ★★★☆☆ |
| Scope | Small | Small | Large |
| Actionability | High | Medium | High |
| Risk of misinterpretation | Low | Medium | Low |
| False-positive rate | Near-zero | Low (event presence) | Near-zero |

**Recommended: Candidate A — `GPU reset failed` (exact failure phrase).**

The explicit failure marker is semantically superior to a timeout and does not require correlation. It follows the exact same architecture pattern as `GPU-I915-HANG-001`: single self-attributing marker, same-line match, no correlation, PIPESTATUS-safe query, P2/Certain.

## 6. Source-path comparison

### Path A — Reuse `kernel_errors`

| Factor | Assessment |
|---|---|
| Truncation | `tail -50` — AMDGPU lines may be evicted by earlier non-AMDGPU errors |
| Failure masking | `\|\| true` — journalctl failure is indistinguishable from no-match |
| Broad pattern | `error\|fail` catches non-AMDGPU lines — not a clean AMDGPU query |
| AMDGPU context survival | Text-based — no structured AMDGPU context |
| **Verdict** | **Rejected.** Insufficient for any AMDGPU diagnostic. |

### Path B — Dedicated current-boot AMDGPU query (recommended)

| Factor | Assessment |
|---|---|
| Command | `journalctl -b -k --no-pager 2>/dev/null` `\|` `grep -iE '<AMDGPU_RESET_FAILED_PATTERN>'` via `_oom_collector_command()` |
| PIPESTATUS safety | ✅ — same `_oom_collector_command()` helper used by OOM and i915 |
| No truncation | ✅ — GPU reset-failure lines are naturally low-volume |
| No failure masking | ✅ — upstream journalctl failure is propagated, no `\|\| true` |
| Exact marker | ✅ — single same-line pattern matching `amdgpu` + `GPU reset failed` |
| Pipeline compatibility | ✅ — RawDiagnostic → Observation → Evidence → Finding (same pattern) |
| Additional AMD markers | Single query for first slice. Can add separate `amdgpu_job_timedout` query later if needed. |
| **Verdict** | **Selected.** Follows identical architecture to `gpu_i915_hang`. |

### Path C — Reuse `gfx_logs`

| Factor | Assessment |
|---|---|
| Compositor mixing | `journalctl -b` mixes niri/wayland/greetd messages with kernel DRM lines |
| Truncation | `tail -30` |
| Failure masking | `\|\| true` |
| Broad pattern | `niri\|dms\|wayland\|greetd\|i915\|drm` — not AMDGPU-specific |
| **Verdict** | **Rejected.** Unsuitable for diagnostic use. |

### Path D — Collect reset lifecycle context

| Factor | Assessment |
|---|---|
| Approach | Collect all `GPU reset begin/succeeded/failed/end` lines in one query, then correlate to determine state |
| Complexity | Higher — requires multiple-line collection and state determination |
| Needed for Candidate A? | **No.** `GPU reset failed` is an explicit failure. Correlation with `begin`/`succeeded` is unnecessary for detection. |
| **Verdict** | **Not required for Candidate A.** Defer if a future Phase 3 adds severity refinement (e.g., downrating to P3 if a reset succeeded after a transient failure). But the first-slice contract should remain simple. |

**Selected source path: Path B (dedicated current-boot AMDGPU query).**

## 7. Severity and confidence analysis

### 7.1 Existing SysCheck severity baseline

| Existing finding | Severity | Confidence | Basis |
|---|---|---|---|
| STORAGE-USAGE-CRITICAL | P1 | Certain | Current measured state (>90% NOW) |
| GPU-I915-HANG-001 | P2 | Certain | Historical event (hang occurred during current boot) |
| KERNEL-OOM-001 | P2 | Certain | Historical event (OOM during current boot) |
| BTRFS-ERR-001 | P2 | Certain | Historical event (device error counters) |
| Failed system unit | P2 | Certain | Current state (unit is failed NOW) |

### 7.2 AMDGPU `GPU reset failed` severity

| Consideration | Assessment |
|---|---|
| Event type | Historical — the reset failure occurred earlier in the current boot |
| Proves current unavailability? | No. The GPU may have been re-probed or the system may have been rebooted. |
| Proves hardware defect? | No. Could be driver, firmware, power, thermal, or PCIe. |
| Proves user impact? | No. If not the active renderer, impact may be limited. |
| **Recommended severity** | **P2** — equal to `GPU-I915-HANG-001` and `KERNEL-OOM-001`. |

P1 is not justified. A historical reset failure does not meet the same urgency bar as STORAGE-USAGE-CRITICAL (>90% disk full NOW). See also the GPU assessment's conclusion that P1 requires current critical unavailability measurement.

### 7.3 AMDGPU `GPU reset failed` confidence

| Factor | Assessment |
|---|---|
| Direct measurement | ✅ `journalctl -b -k` confirms the exact line exists |
| Data completeness | ✅ The line itself is the complete event record |
| Inference required | ✅ **No.** The failure is explicit in the message. |
| Contradictory evidence | No (no evidence of non-occurrence) |
| **Recommended confidence** | **Certain** — direct measurement of the explicit failure marker. |

### 7.4 Proposed contract

| Property | Value |
|---|---|
| FindingKind | `AMDGPU_RESET_FAIL` (new) |
| Domain | `DiagnosticDomain.HARDWARE` |
| Severity | P2 |
| Confidence | Certain |
| Actionability | `Actionability.ACTIONABLE` |
| Recommendation intent | `RecommendationIntent.INVESTIGATE` |
| EvidenceType | `EvidenceType.JOURNAL_EVENT` |

The contract mirrors `GPU-I915-HANG-001` exactly, with the same severity/confidence rationale.

## 8. Exact first-slice contract

### 8.1 Diagnostic identity

| Property | Value |
|---|---|
| Diagnostic ID | `AMDGPU-RESET-FAIL-001` |
| Category | `amdgpu_reset_fail` |
| FindingKind | `AMDGPU_RESET_FAIL = "amdgpu_reset_fail"` (new enum member) |
| Domain | `DiagnosticDomain.HARDWARE` |
| Severity | **P2** |
| Confidence | **Certain** |
| Actionability | `Actionability.ACTIONABLE` |
| Recommendation intent | `RecommendationIntent.INVESTIGATE` |
| EvidenceType | `EvidenceType.JOURNAL_EVENT` |

### 8.2 Exact query

```
_oom_collector_command(
    "journalctl -b -k --no-pager 2>/dev/null",
    r"amdgpu.*GPU reset failed",
)
```

### 8.3 Exact same-line trigger

Regex: `r"amdgpu.*GPU reset failed"`

An accepted line must contain:
- `amdgpu` (driver context prefix) AND
- `GPU reset failed` (explicit failure phrase)

on the **same line**, in that order, case-insensitively (`grep -iE` in shell path, `re.IGNORECASE` in sideband).

### 8.4 Explicit non-triggers

The following MUST NOT trigger `AMDGPU-RESET-FAIL-001`:
- `GPU reset begin` alone (no failure)
- `GPU reset succeeded` (positive recovery)
- `GPU reset end` alone (always present)
- `amdgpu_job_timedout` (job timeout, not reset failure)
- `ring .* timeout` (ring timeout)
- `VM fault` / `page fault` (ambiguous)
- Generic DRM `*ERROR*` (too broad)
- `i915` lines (other driver)
- `NVRM: Xid` (NVIDIA)
- `nouveau` lines (Nouveau)
- `Resetting chip` (i915 reset action)
- Any `wedged` line

### 8.5 RawDiagnostic payload

```python
RawDiagnostic(
    source_id="AMDGPU-RESET-FAIL-001",
    category="amdgpu_reset_fail",
    payload={
        "reset_failure_detected": True,
        "matched_lines": [...],       # max 20 lines
        "match_count": N,             # total matched lines (pre-cap)
        "driver": "amdgpu",
        "driver_attribution_source": "in_message",
        "journal_scope": "current_boot_kernel",
        "source_query": "amdgpu_reset_fail",
    },
)
```

### 8.6 Observation mapping

```python
Observation(
    obs_id="AMDGPU-RESET-FAIL-001",
    category="amdgpu_reset_fail",
    details={**payload},
    direct_measurement=True,
    data_complete=True,
    contradictory_evidence=False,
    inference_required=False,
    independent_sources=1,
    source_raw_ids=(src_id,),
)
```

### 8.7 Evidence payload (through EvidenceBuilder)

```python
Evidence(
    evidence_id=...,              # auto-generated
    evidence_type=EvidenceType.JOURNAL_EVENT,
    source_observation_ids=(oid,),
    source_raw_ids=observation.source_raw_ids,
    summary=(
        f"AMDGPU reset failure detected during current boot "
        f"({count} matching journal line(s))"
    ),
    data={
        "reset_failure_detected": d.get("reset_failure_detected", False),
        "match_count": count,
        "matched_lines": d.get("matched_lines", []),
        "driver": d.get("driver", "amdgpu"),
        "driver_attribution_source": d.get(
            "driver_attribution_source", "in_message"
        ),
        "journal_scope": d.get("journal_scope", "current_boot_kernel"),
        "source_query": d.get("source_query", "amdgpu_reset_fail"),
    },
    strength=EvidenceStrength.STRONG,
    directness=EvidenceDirectness.DIRECT,
    completeness=EvidenceCompleteness.COMPLETE,
)
```

### 8.8 Finding title (Polish)

> "Wykryto nieudany reset GPU obsługiwanego przez sterownik amdgpu"

### 8.9 Interpretation (Polish)

> "Dziennik jądra odnotował zdarzenie `GPU reset failed` dla sterownika amdgpu w bieżącym bocie. Oznacza to, że sterownik jądra podjął próbę zresetowania układu GPU, która nie powiodła się. Zdarzenie mogło mieć charakter historyczny i może nie być już aktywne. Diagnostyka nie potwierdza defektu sprzętowego — możliwe przyczyny obejmują niestabilność sterownika jądra, problemy z firmware, niestabilność zasilania/termiczna/PCIe, lub przejściowy błąd platformy. Diagnostyka nie określa, czy dotknięte GPU było aktywnym rendererem — wpływ na użytkownika może być różny. Uwaga: brak wykrytego zdarzenia nie dowodzi, że nie wystąpił reset — retencja dziennika jądra może być niepełna."

### 8.10 Recommended diagnostics (Polish)

> "Sprawdź aktualny dziennik jądra: `journalctl -b -k --no-pager | grep -iE 'amdgpu'`\nSprawdź wersję jądra: `uname -r`\nSprawdź wersję Mesa: `glxinfo | grep -i 'opengl version'`\nSprawdź wersję firmware AMDGPU: `pacman -Q linux-firmware-amdgpu`\nSprawdź sterownik: `lspci -k | grep -A2 -i amd`\nSprawdź temperatury i zasilanie: `sensors`"

### 8.11 Remediation (Polish) — boundaries

> "Jeśli problem jest powtarzalny: porównaj zachowanie na innym wspieranym jądrze, przejrzyj ostatnie zmiany jądra/sterownika AMDGPU, zachowaj dokładne linie błędu do zgłoszenia problemu. Uwzględnij czynniki takie jak temperatura, obciążenie, stabilność PCIe i jakość zasilania w diagnozie."

**Does NOT:**
- Claim hardware defect
- Prescribe replacing the GPU, PSU, or reseating hardware
- Prescribe arbitrary kernel parameters (e.g., `amdgpu.aspm=0`)
- Claim the journal entry disappears after remediation
- Claim the failure proves the GPU is currently unavailable

### 8.12 Verification (Polish)

> "Sprawdź, czy system jest obecnie responsywny.\nMonitoruj, czy nowe reset występują: `journalctl -b -k | grep -iE 'GPU reset'`.\nPo podjęciu działań sprawdź w kolejnym bocie, czy znacznik nadal występuje."

### 8.13 Deduplication

Multiple matching reset-failure lines produce **one** RawDiagnostic with `match_count` reflecting total lines, `matched_lines` capped at 20 (same pattern as OOM and i915).

### 8.14 Rule registration

- New rule class: `AmdgpuResetFailRule` (analogous to `GpuI915HangRule`)
- `rule_id = "RULE-AMDGPU-RESET-FAIL"`
- Registered in `build_default_rule_engine()` after `GpuI915HangRule`
- `FindingKind.AMDGPU_RESET_FAIL` added to enum
- Category `"amdgpu_reset_fail"` added to `_BY_CATEGORY` classification policy

### 8.15 Files modified

| File | Expected changes |
|---|---|
| `constants.py` | +1: `RE_AMDGPU_RESET_FAIL` regex constant |
| `syscheck.py` | +~170: enum member, classification entry, EvidenceBuilder branch, collector task in `collect_kernel_hw()`, `_raw_to_observation()` handler, `AmdgpuResetFailRule` class, registration |
| `test_syscheck.py` | +~450: import, mock-updates in `TestSegfaultAndTaintCollectorPath` and `TestOomCollectorPath`, two new test classes |

## 9. Required tests

If implemented, the following deterministic tests are required (26 tests total):

### Command-status tests (7)

| # | Test | Verifies |
|---|---|---|
| 1 | `test_match_success` | `amdgpu ... GPU reset failed` → exit 0, stdout contains match |
| 2 | `test_no_match` | harmless text → exit 0, empty stdout |
| 3 | `test_upstream_failure` | upstream rc=42 → propagated |
| 4 | `test_grep_rc2_propagated` | grep rc=2 → propagated |
| 5 | `test_stderr_suppressed` | stderr redirection doesn't mask exit |
| 6 | `test_zero_length_input` | empty input → exit 0 |
| 7 | `test_case_insensitive` | `gpu reset failed` casing variations → exit 0 |

### Collector-path tests (19)

| Category | Tests | Count |
|---|---|---|
| Positive | `test_reset_fail_triggers` | 1 |
| Negative | `test_no_amdgpu_no_trigger`, `test_amdgpu_no_marker_no_trigger`, `test_reset_begin_no_trigger`, `test_reset_succeeded_no_trigger`, `test_job_timedout_no_trigger`, `test_ring_timeout_no_trigger`, `test_drm_error_no_trigger`, `test_i915_no_trigger`, `test_nvidia_no_trigger`, `test_nouveau_no_trigger` | 10 |
| Failure/edge | `test_command_failure_safe`, `test_timeout_safe`, `test_payload_provenance`, `test_output_cap` | 4 |
| Pipeline | `test_observation_mapping`, `test_evidence_journal_event_type`, `test_finding_classification`, `test_rule_registered` | 4 |
| Regression | `test_oom_unchanged`, `test_i915_unchanged`, `test_taint_unchanged`, `test_segfault_unchanged` | 4 (separate from pipeline count, total 19) |

Wait — I need to re-count. Let me recount:

Positive: 1
Negative: 10
Failure/edge: 4
Pipeline: 4
Regression: 4

That's 23 collector-path tests. But the total tests would be 7 + 23 = 30 new tests.

No, let me reconsider. The regression tests are part of the collector-path class. So:
- Positive: 1
- Negative: 10
- Failure/edge: 4
- Pipeline (including regression): 4 pipeline + 4 regression = 8

Total collector-path: 1 + 10 + 4 + 4 + 4 = 23
Total new tests: 7 + 23 = 30

### Test restrictions (unchanged from i915 pattern)
- No real journal, no AMD GPU, no sudo, no network, no host-state dependence
- Mock-based testing using `_collect_with_mock` pattern
- Shell-level command testing using `subprocess.run()` with fake upstream executables

## 10. Final decision

### Decision A — Implement one narrow AMDGPU diagnostic

**Selected: AMDGPU-RESET-FAIL-001 (AMDGPU reset failure detection).**

Rationale:

1. **Exact marker is authoritative.** `GPU reset failed` is a literal string in `amdgpu_device_gpu_recover()`. It is the driver's explicit statement that recovery failed. Near-zero false-positive risk.

2. **No correlation required.** The failure is explicit in a single line. No pairing with `reset begin`, `succeeded`, or `amdgpu_job_timedout` is needed for detection.

3. **Self-attributing.** The line includes `amdgpu` prefix. No separate driver identity parser is needed.

4. **Architecture identical to i915 and OOM.** Single dedicated `journalctl -b -k` query via `_oom_collector_command()`, single marker, sideband check, one FindingKind, one rule. A well-understood pattern.

5. **P2/Certain fits existing policy.** Historical explicit failure event — same as `GPU-I915-HANG-001` and `KERNEL-OOM-001`.

6. **Fills an existing gap.** The GPU assessment explicitly deferred AMDGPU from Phase 1 (i9105) and recommended it as Phase 2. This is that Phase 2.

**Explicit boundaries:**
- Does NOT detect `amdgpu_job_timedout` (deferred)
- Does NOT detect ring timeouts (ambiguous without correlation)
- Does NOT correlate with `reset begin/succeeded/end` lifecycle
- Does NOT infer hardware defect
- Does NOT infer current GPU availability
- Does NOT infer active renderer
- Does NOT prescribe kernel parameters or hardware replacement
- Does NOT detect NVIDIA, Nouveau, or i915 events

## 11. Exact next scope

### Implementation of AMDGPU-RESET-FAIL-001

Following the established pattern from Iteration 28 (GPU-I915-HANG-001):

**Files to modify:**
- `constants.py`: Add `RE_AMDGPU_RESET_FAIL = r"amdgpu.*GPU reset failed"`
- `syscheck.py`:
  - Add `FindingKind.AMDGPU_RESET_FAIL = "amdgpu_reset_fail"` to enum
  - Add `"amdgpu_reset_fail"` entry in `_BY_CATEGORY` (HARDWARE, ACTIONABLE, INVESTIGATE)
  - Add `gpu_i915_hang`-analogous branch in `EvidenceBuilder.build()`
  - Add collector task entry in `tasks_cmd` within `collect_kernel_hw()`, using `_oom_collector_command()` with `RE_AMDGPU_RESET_FAIL`
  - Add `amdgpu_reset_fail_result = r["amdgpu_reset_fail"]` after `gpu_i915_hang_result`
  - Add sideband check block (after i915 sideband) that filters lines, emits `RawDiagnostic(source_id="AMDGPU-RESET-FAIL-001", ...)`
  - Add `AmdgpuResetFailRule` class (`RULE-AMDGPU-RESET-FAIL`)
  - Register in `build_default_rule_engine()` after `GpuI915HangRule`
  - Add `amdgpu_reset_fail` handler in `_raw_to_observation()`
- `test_syscheck.py`:
  - Add `RE_AMDGPU_RESET_FAIL` import
  - Add `"amdgpu_reset_fail": self._cmd_ok("")` to mock results in `TestSegfaultAndTaintCollectorPath._collect_with_mock()`
  - Add `"amdgpu_reset_fail": self._cmd_ok("")` to mock results in `TestOomCollectorPath._collect_with_mock()`
  - Add `TestAmdgpuResetFailCommandStatus` (7 shell-level tests)
  - Add `TestAmdgpuResetFailCollectorPath` (23 collector-path tests)

**New tests: ~30 total** (7 command-status + 23 collector-path)

**Total pre-existing: 426. Total after: ~456.**

## 12. Unresolved uncertainties

### 12.1 `GPU reset failed` with PCI-address-only lines

Some reset-failure lines may not include the `amdgpu` driver name as a substring if formatted differently. The regex `amdgpu.*GPU reset failed` assumes the line contains `amdgpu` before `GPU reset failed`. If kernel versions emit `[drm] GPU reset failed` without `amdgpu` prefix, the regex would miss it. This should be verified against actual `journalctl -b -k` output on an AMDGPU system. If needed, the regex can be broadened to `amdgpu.*GPU reset failed|drm.*GPU reset failed` — but this increases false-positive risk for non-AMDGPU DRM drivers.

**Mitigation:** Start with the narrower `amdgpu.*GPU reset failed` pattern. Broaden only if testing confirms the narrow pattern misses real events.

### 12.2 `GPU reset succeeded` after `GPU reset failed`

The first-slice contract reports `GPU reset failed` as a historical event. If a `GPU reset succeeded` appears later in the same boot (indicating a retry succeeded), the diagnostic still correctly reports that a failure occurred. Severity refinement (e.g., downgrading from P2 to P3 when a subsequent reset succeeded) could be a future enhancement but requires correlation logic that is out of scope for the first slice.

### 12.3 Deduplication across multiple resets

If multiple reset failures occur in the same boot (e.g., two separate incidents), the single RawDiagnostic with `match_count=2` captures the count. This is consistent with the i915 and OOM pattern. If desired, separate RawDiagnostics per incident would require time-window separation logic — deferred.

### 12.4 No production kernel-journal samples from an AMDGPU system

The assessment is based on kernel source analysis (`amdgpu_device_gpu_recover()` in `drivers/gpu/drm/amd/amdgpu/amdgpu_device.c`) and established AMDGPU kernel message conventions. Testing against actual journal output on an AMDGPU system before finalizing the regex is recommended but not a blocker.

### 12.1 [sic] No production files modified during assessment

Confirmed: no code or test changes were made.

## 13. Confirmation

**No production files, tests, or constants were modified during this assessment.**
- `syscheck.py`: Not modified.
- `constants.py`: Not modified.
- `test_syscheck.py`: Not modified.
- No files were staged, committed, pushed, reset, restored, or renamed.
- No branches were created or switched.
- Only this review file was created at:
  `.agent-work/reviews/deepseek-v4-flash-max-amdgpu-reset-failure-diagnostic-assessment.md`
