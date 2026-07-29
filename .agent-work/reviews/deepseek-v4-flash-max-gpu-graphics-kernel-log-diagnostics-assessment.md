# DeepSeek V4 Flash Max — GPU / Graphics Kernel Log Diagnostics Assessment

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   clean
Recent commits (git log -6 --oneline):
  514d488 feat: detect kernel oom events
  6804f70 fix: remove misleading temperature warning
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

Checkpoint matches expected state. Working tree clean. No prior GPU diagnostic has been implemented.

---

## 2. Corrected Current Data Inventory

### 2.1 `collect_graphics()` — Compositor / User-Session Graphics

| Task key | Command | Timeout | Optional | Display only? | Structured diagnostic? |
|----------|---------|---------|----------|---------------|------------------------|
| `drm_vendor` | `cat /sys/class/drm/card*/device/vendor 2>/dev/null` | SHORT 10s | No | Yes (report section 7.1) | No |
| `drm_device` | `cat /sys/class/drm/card*/device/device 2>/dev/null` | SHORT 10s | No | Yes | No |
| `drm_ls` | `ls /sys/class/drm/` | SHORT 10s | No | Yes | No |
| `niri_out` | `niri msg outputs` | SHORT 10s | No | Yes | No |
| `gfx_logs` | `journalctl -b --no-pager 2>/dev/null \| grep -iE 'niri\|dms\|wayland\|greetd\|i915\|drm' \| grep -iE 'error\|fail\|warn' \| tail -30 \|\| true` | LONG 60s | No | Yes | No |

**`gfx_logs` is a compositor/user-session collector, not a kernel GPU diagnostic source.**
- Uses `journalctl -b` (all journals) — captures Wayland compositor, display manager, and DRM messages alongside kernel messages.
- Two-stage grep: `niri|dms|wayland|greetd|i915|drm` then `error|fail|warn`.
- Uses `|| true` — upstream failure is masked.
- Truncated to 30 lines.
- **No structured diagnostic produced.** This collector is unsuitable as a kernel-GPU diagnostic source due to compositor-message mixing, `|| true`, and truncation.

### 2.2 `collect_kernel_hw()` — Kernel-Adjacent Collectors

| Task key | Command | Timeout | Optional | Display only? | Structured diagnostic? |
|----------|---------|---------|----------|---------------|------------------------|
| `kernel_errors` | `journalctl -b -k --no-pager 2>/dev/null \| grep -iE 'error\|fail\|BUG\|lockup\|hung\|oom\|taint\|Call Trace' \| tail -50 \|\| true` | LONG 60s | No | Yes + taint | KERNEL-TAINT-001 only |
| `firmware_msgs` | `journalctl -b --no-pager 2>/dev/null \| grep -iE 'firmware\|microcode\|ucode' \| tail -20 \|\| true` | LONG 60s | No | Yes | No |
| `segfaults` | `journalctl -b --no-pager 2>/dev/null \| grep -i 'segfault' \|\| true` | LONG 60s | No | No | SEGFAULT-* rules |
| `oom_events` | `_oom_collector_command(..., RE_OOM)` | LONG 60s | No | No | KERNEL-OOM-001 |
| `lspci` | `lspci -k` | SHORT 10s | No | Yes | No |
| `lsusb` | `lsusb` | SHORT 10s | No | Yes | No |

**Note on `kernel_errors`:** Uses `journalctl -b -k` (kernel journal only, current boot). Does NOT include GPU-specific patterns (`GPU HANG`, `amdgpu_job_timedout`, `NVRM: Xid`). Truncated to 50 lines. Uses `|| true`. This collector is insufficient as a GPU diagnostic source due to non-specific patterns, truncation, and failure masking.

**Note on `firmware_msgs`:** Uses `journalctl -b` (not `-k`), so it captures CPU microcode, GPU firmware, and system firmware messages together. No GPU-specific filtering. Uses `|| true` and truncation.

### 2.3 What SysCheck Does NOT Collect for Kernel-GPU Diagnostics

| Data source | Missing? | Impact |
|-------------|----------|--------|
| `journalctl -b -k` with GPU-specific driver markers | Not collected | No `GPU HANG`, `amdgpu_job_timedout`, `NVRM: Xid` queries exist |
| GPU driver identity from log-line prefix | In-message only | Sufficient for self-attributing markers (see section 3) |
| `/sys/class/drm/card*/device/driver` symlink | Not collected | Useful but not prerequisite for self-attributing markers |
| `glxinfo` / `vulkaninfo` | Not collected | Active-renderer identification not available |
| `nvidia-smi` | Not collected | NVIDIA state (but deferred in this assessment) |

---

## 3. Driver Attribution vs Active-Renderer Attribution

### 3.1 Three Distinct Concepts

```
driver attribution                → which driver produced the log line
active-renderer attribution       → which GPU drives the display / renders
user-impact attribution           → whether the event affects the user's workload
```

These three concepts are often conflated but must be kept separate.

### 3.2 Self-Attributing Markers

A kernel log line such as:

```
i915 0000:00:02.0: [drm] *ERROR* GPU HANG: ecode ...
amdgpu 0000:03:00.0: [drm] GPU reset failed
NVRM: Xid (PCI:0000:01:00): 79, ...
nouveau 0000:01:00.0: fifo: SCHED_ERROR 0d ...
```

**Each of these lines already identifies the driver that produced it.** The driver name appears as a prefix (`i915`, `amdgpu`, `NVRM`, `nouveau`) or in the PCI address context. No separate identity parser is needed to know which driver experienced the event.

### 3.3 What Driver Identity Does NOT Tell Us

A structured driver identity collector (reading `/sys/class/drm/card*/device/driver`, parsing `lspci -k`) would tell us:

- What GPU drivers are loaded.
- How many DRM cards exist.
- PCI addresses and vendor/device IDs.

It does **NOT** tell us:

- Which GPU is driving the display outputs.
- Which GPU is the active renderer (for PRIME render offload).
- Whether a logged GPU event impacted the user's visible session.

### 3.4 Inactive-GPU Events Are Not False Positives

If an NVIDIA GPU in an Optimus system logs `NVRM: Xid 79` but is not the active renderer, that is:

- ✅ A **true event** — the GPU did experience a failure.
- ✅ **Driver-attributed** — the log line identifies NVIDIA.
- ⚠️ **Lower user impact** — the user may not have been actively using that GPU.

This is **not** a false positive. It is a real hardware event with potentially lower severity. The diagnostic interpretation should state: "An NVRM Xid error was logged. If the affected GPU is not the active renderer, user impact may be limited."

Calling inactive-GPU events "false positives" is incorrect — they are true events whose interpretation must account for the possibility that the user was not actively using that GPU.

### 3.5 Implication for Prerequisites

For a narrow driver-specific diagnostic, the marker itself already provides driver attribution. **A separate driver identity parser is not a prerequisite** for implementing a diagnostic on a self-attributing marker such as:

- `i915 ... GPU HANG:` — driver attribution i915 from message prefix
- `amdgpu ... GPU reset failed` — driver attribution amdgpu from message prefix
- `NVRM: Xid` — driver attribution NVRM from message prefix (but see section 4.4 for deferral reasons)

Active-renderer determination is a separate concern that affects interpretation and severity, not event detection. The diagnostic can report the event with contextual language that acknowledges renderer ambiguity.

---

## 4. Architecture Suitability for GPU Inventory as Structured Data

### 4.1 RawDiagnostic Is Not a Generic Container

The SysCheck pipeline is:

```
Collector → CmdResult → RawDiagnostic → _raw_to_observation() → Observation → Rule → Finding + Evidence
```

`_raw_to_observation()` handles these categories: `btrfs_error`, `btrfs_scrub`, `segfault`, `segfault_minor`, `tainted`, `systemd_failed`, `kernel_count`, `boot_time`, `storage_usage`, `oom_event`. Each has a concrete consumer.

Proposing a `RawDiagnostic` with `category="gpu_drivers"` and no corresponding `_raw_to_observation()` handler would either:
1. Be silently dropped (the `elif` chain has no match, returns `None`).
2. Require adding a handler that produces an Observation with no rule consumer — creating dead pipeline data.

**Conclusion:** A raw-only GPU inventory container is architecturally invalid. If the goal is report enrichment, the data should remain in `CmdResult` form (like the existing `drm_vendor`, `drm_device`, `drm_ls` tasks) — not in the diagnostic pipeline.

### 4.2 Structured GPU Inventory

A structured GPU inventory parser that reads `/sys/class/drm/card*/device/driver` and/or parses `lspci -k` for `Kernel driver in use:` is architecturally valid as:

- A **new collector command** within `collect_graphics()` (report enrichment).
- Or a **helper function** used by `collect_graphics()` for display enhancement.
- **Not** a `RawDiagnostic` — because there is no diagnostic rule consuming it.

This structured inventory is useful for report quality (showing "Intel i915" instead of "0x8086") but is **not a prerequisite** for implementing a narrow self-attributing GPU diagnostic.

---

## 5. Corrected Marker Matrix

### 5.1 Intel i915

| Marker | Kernel log source | Currently collected? | Classification |
|--------|------------------|---------------------|----------------|
| `GPU HANG:` | `journalctl -b -k` | No | **diagnostic-ready** — authoritative i915 hang marker. Self-attributing (line includes `i915`). Never benign. |
| `Resetting chip` / `Resetting rcs` | `journalctl -b -k` | No | supporting evidence only — driver recovery action. Not a diagnostic by itself. |
| `.* wedged` | `journalctl -b -k` | No | **diagnostic-ready** — permanent GPU wedge. Rare. Self-attributing. |
| `GuC firmware load failed` | `journalctl -b -k` | Partial (via `firmware_msgs`) | vendor-specific — may be fallback to execlist, not a hardware fault |
| `HuC firmware load failed` | `journalctl -b -k` | Partial (via `firmware_msgs`) | vendor-specific — media decoding degraded, GPU otherwise works |
| `flip_done timed out` | `journalctl -b -k` | No | transient/noisy — display cable, monitor sleep, resolution change |
| `vblank wait timed out` | `journalctl -b -k` | No | transient/noisy — VSync timeout often benign |
| `Atomic update failure` | `journalctl -b -k` | No | report-only — usually transient, DRM atomic commit can fail temporarily |
| `*ERROR*` (i915-specific) | `journalctl -b -k` | Partial (via `kernel_errors` `error` match) | too broad — i915 ERROR macros cover many benign conditions (HPD, link training) |

**Marker-stability note:** `GPU HANG:` is a literal string in the i915 driver source. [External observation — subject to kernel version changes but has been stable across 5.x and 6.x kernels.]

### 5.2 Intel Xe (new DRM driver)

| Marker | Kernel log source | Currently collected? | Classification |
|--------|------------------|---------------------|----------------|
| All Xe markers | `journalctl -b -k` | **None** | not collected. `xe` substring is absent from all patterns and collectors. Xe is a newer driver for discrete Arc GPUs with lower deployment than i915. Not recommended for first diagnostic. |

### 5.3 AMDGPU

| Marker | Kernel log source | Currently collected? | Classification |
|--------|------------------|---------------------|----------------|
| `amdgpu_job_timedout` | `journalctl -b -k` | No | **diagnostic-ready** — authoritative, self-attributing (amdgpu prefix). Job timeout is a true event. |
| `GPU reset begin` | `journalctl -b -k` | No | supporting evidence only — reset may succeed |
| `GPU reset succeeded` | `journalctl -b -k` | No | report-only — positive recovery, not a fault |
| `GPU reset failed` | `journalctl -b -k` | No | **diagnostic-ready** — authoritative, self-attributing. The driver explicitly reports failure. |
| `ring .* timeout` | `journalctl -b -k` | No | vendor-specific — ring timeout may be transient or fatal; requires reset result context |
| `VM fault` / `page fault` | `journalctl -b -k` | No | requires corroboration — may be application bug or GPU fault |
| `failed to load firmware` (amdgpu) | `journalctl -b` | Partial (via firmware_msgs) | vendor-specific — firmware fallback possible |
| `RAS` | `journalctl -b -k` | No | requires corroboration — RAS events may be corrected or uncorrected |
| `SMU` / `DCN` messages | `journalctl -b -k` | No | too broad — SMU/DCN messages vary widely in severity |
| `amdgpu: SE .* SH .* CU` | `journalctl -b -k` | No | report-only — GPU topology info, not an error |

### 5.4 NVIDIA Proprietary — Deferred

| Marker | Log source | Currently collected? | Classification |
|--------|-----------|---------------------|----------------|
| `NVRM: Xid` (any code) | `dmesg` / `journalctl -b -k` | No | **deferred for first milestone.** Multiple complications: (1) Xid codes range from informational to catastrophic with no single interpretable contract. (2) Log destination is uncertain — NVIDIA writes to `printk` which goes to `dmesg`, but capture in `journalctl -b -k` varies. (3) `dmesg` access may be restricted by `dmesg_restrict=1`. |
| `NVRM: Xid 79` (GPU fallen off bus) | `dmesg` / `journalctl -b -k` | No | **deferred.** Requires distinguishing intentional eGPU detach from spontaneous failure. |
| `GPU has fallen off the bus` | `dmesg` / `journalctl -b -k` | No | **deferred.** Same eGPU-detach ambiguity. |
| `RmInitAdapter failed` | `dmesg` / `journalctl -b -k` | No | **deferred.** Driver init failure — requires context. |
| `nvidia-modeset: ERROR` | `dmesg` / `journalctl -b -k` | No | too broad — modeset errors may be transient |
| `nvidia-drm` messages | `dmesg` / `journalctl -b -k` | No | too broad — many benign DRM messages |

**Decision: NVIDIA is deferred from the first milestone due to (a) uncertain log capture path, (b) Xid code complexity requiring subtype-level policy, and (c) dmesg_restrict dependency.**

### 5.5 Nouveau

| Marker | Kernel log source | Currently collected? | Classification |
|--------|------------------|---------------------|----------------|
| `nouveau .* fifo` | `journalctl -b -k` | No | vendor-specific — nouveau FIFO errors are diagnostic-relevant but nouveau has limited deployment on modern GPUs (no reclocking, no power management). Not recommended for first diagnostic. |
| `nouveau .* fault` | `journalctl -b -k` | No | requires corroboration — may be application-induced |
| `nouveau .* timeout` | `journalctl -b -k` | No | vendor-specific — timeout may be context-dependent |
| `nouveau .* gr` | `journalctl -b -k` | No | vendor-specific — GR engine errors |
| `nouveau .* DRM` | `journalctl -b -k` | No | too broad — many benign DRM messages |

**Decision: Nouveau is deferred from the first milestone due to limited deployment and lower diagnostic yield on modern hardware (NVIDIA proprietary driver is the primary target for NVIDIA GPU users).**

### 5.6 Generic DRM / Display — Rejected

| Marker | Kernel log source | Currently collected? | Classification |
|--------|------------------|---------------------|----------------|
| `drm:.*ERROR` | `journalctl -b -k` | Partial (via `kernel_errors` `error` + `gfx_logs` `drm`) | **rejected.** Generic `drm:.*ERROR` appears in many drivers for transient conditions (HPD, link training, EDID). Not suitable for deterministic diagnostic. |
| connector/link-training failure | `journalctl -b -k` | No | transient/noisy — hotplug, monitor sleep, cable |
| EDID errors | `journalctl -b -k` | No | requires corroboration — bad cable, monitor, or transient |
| atomic commit failures | `journalctl -b -k` | No | transient/noisy — can occur during mode switches |
| vblank timeout | `journalctl -b -k` | No | transient/noisy — usually benign |
| hotplug noise (HPD) | `journalctl -b -k` | No | transient/noisy — docks, USB-C, monitor power cycles |
| VRR/FreeSync/G-Sync warnings | `journalctl -b -k` | No | transient/noisy — monitor-specific, often benign |

**Decision: Generic DRM/display markers are rejected for the first diagnostic. They lack the specificity required for a deterministic, low-FP diagnostic.**

---

## 6. Source-Path Comparison

### Path A — Reuse existing `kernel_errors` output

**Evaluate:**
- **Marker coverage:** Insufficient. `GPU HANG`, `amdgpu_job_timedout`, `GPU reset failed` are NOT in `RE_KERNEL_ERROR`. Only broad `error|fail` matching catches some GPU messages — too broad.
- **Truncation:** `tail -50`. GPU-specific lines may be pushed out by earlier non-GPU errors.
- **Competition with unrelated errors:** Merged output — driver attribution is text-based and unreliable.
- **Failure masking:** Uses `|| true` — upstream `journalctl` failure is indistinguishable from "no errors."
- **Driver attribution:** None structured. Pure text blob.

**Verdict: REJECTED.** Path A is insufficient for any GPU diagnostic.

### Path B — Dedicated current-boot GPU query (RECOMMENDED for first diagnostic)

**Evaluate:**
- Uses `journalctl -b -k` (kernel journal only, current boot).
- Uses `_oom_collector_command()` PIPESTATUS pattern (Iteration 27) for safe exit code handling — no `|| true`.
- Single exact marker per query — no truncation needed (GPU fault lines are naturally low volume).
- Pipeline-only: RawDiagnostic → Observation → Evidence → Finding (same pattern as KERNEL-OOM-001).
- **Driver attribution:** Self-attributing — the marker itself includes the driver prefix.
- **Active-renderer not needed for event detection:** The diagnostic reports that a GPU event occurred. Active-renderer affects interpretation, not detection.
- Supports safe no-match (grep rc=1 → exit 0) and failure (journalctl rc≠0 → propagate) consistent with Iteration 27.

**Verdict: RECOMMENDED.** Path B with a single self-attributing marker is implementation-ready.

### Path C — Parse existing GPU-specific report output

**Evaluate:**
- `gfx_logs` output is display-only, uses `|| true`, broad patterns, `tail -30`.
- `firmware_msgs` output is display-only with `|| true` and `tail -20`.
- Converting display-only paths to structured diagnostics is more work than adding a dedicated query.

**Verdict: REJECTED.** Existing display output is unsuitable as a diagnostic source.

### Path D — Prerequisite driver identity parser

**Evaluate:**
- Reading `/sys/class/drm/card*/device/driver` and/or parsing `lspci -k` for `Kernel driver in use:` would provide structured driver inventory.
- **Useful for:** Report enrichment (showing driver names instead of hex codes), confirming which DRM cards exist, detecting multi-GPU systems.
- **Not a prerequisite for self-attributing markers.** Markers like `i915 ... GPU HANG:` and `amdgpu ... GPU reset failed` already contain driver identity in the log line.
- **Architecture note:** Must NOT be a `RawDiagnostic` without a consumer. Should remain as `CmdResult`/report data.

**Verdict: USEFUL BUT NOT A PREREQUISITE.** Can be implemented as a separate report-enrichment task without blocking the first GPU diagnostic.

### Path Selection

**Selected: Path B (dedicated current-boot GPU query) for a single self-attributing marker.**

Path D (structured GPU inventory) is a lower-priority follow-up for report quality, not a prerequisite.

---

## 7. False-Positive Analysis

### 7.1 Events That Are NOT False Positives

| Event | Diagnostic interpretation |
|-------|--------------------------|
| `GPU HANG:` on active renderer | True event. User was likely affected. |
| `GPU HANG:` on inactive secondary GPU | True event. User may not have been affected. Diagnostic should note ambiguity. |
| `GPU reset failed` on any GPU | True event. Driver explicitly reports failure. |
| `amdgpu_job_timedout` on any GPU | True event. Job timeout is a measurable event. |

**A real driver event on an inactive GPU is not a false positive.** It is a true event with potentially lower user impact. The diagnostic interpretation must acknowledge this but should not suppress the event.

### 7.2 Events That Require Caution

| Scenario | Risk | Mitigation |
|----------|------|------------|
| `GPU HANG:` followed by successful reset | Medium | Do not infer reset outcome from hang marker alone. Report only that a hang occurred. |
| Laptop suspend/resume | Low for `GPU HANG:` | Suspend/resume does not generate `GPU HANG:` markers. |
| Display hotplug | Low for `GPU HANG:` | Hotplug does not generate `GPU HANG:` markers. |
| Debug kernels with verbose logging | Low for exact markers | Verbose logging adds extra messages but does not fabricate `GPU HANG:`. |
| eGPU detach | Low for i915 | i915 is integrated. eGPU detach affects NVIDIA/AMD, which are deferred. |
| Firmware fallback | N/A | Not included in first-slice scope. |

### 7.3 Events Excluded by Marker Specificity

The first diagnostic uses an exact marker (`GPU HANG:`). This excludes by design:

- Generic `drm.*ERROR` — not matched.
- `flip_done timed out` — not matched.
- `vblank wait timed out` — not matched.
- `hotplug` / `link training` / `EDID` — not matched.
- `atomic commit failure` — not matched.
- Any `error|fail|warn` substring — not matched.

This zero-FP-on-non-target design is the same approach used by KERNEL-OOM-001 (exact markers, no substring matching).

---

## 8. Severity and Confidence Analysis

### 8.1 Existing SysCheck Severity Baseline

| Existing finding | Severity | Confidence | Basis |
|-----------------|----------|------------|-------|
| STORAGE-USAGE-CRITICAL | P1 | Certain | Current measured state (>90% full NOW) — proven current unavailability risk |
| BTRFS-ERR-001 | P2 | Certain | Historical event (device error counters from current boot) |
| KERNEL-TAINT-001 | P2 | Certain | Current measured state (taint flag is live) |
| KERNEL-OOM-001 | P2 | Certain | Historical event (OOM occurred during current boot) |
| SEGFAULT-WP-001 | P2 | Likely | Historical event with inference |
| Failed system unit | P2 | Certain | Current measured state (unit is failed NOW) |
| BOOT-SLOW-001 | P3 | Likely | Historical measurement with threshold inference |
| STORAGE-USAGE-WARNING | P3 | Certain | Current measured state (moderate usage) |

### 8.2 Severity Distinctions

```
event severity     = how significant the event type is
current urgency    = whether the user is affected RIGHT NOW
hardware-failure   = whether the event proves a hardware defect
```

These three must be evaluated separately.

- `GPU HANG:` is a **historical event** (it occurred earlier in the current boot). It does not prove the GPU is currently hung, does not prove hardware failure (could be a driver bug), and does not prove the user is currently affected. This aligns with KERNEL-OOM-001 (P2).
- `GPU reset failed` is a **historical event** indicating the driver explicitly reported failure to recover. Still does not prove current unavailability (the GPU may have been re-probed or the system may have been rebooted). P2 baseline.

### 8.3 Candidate Severity

| Event | Severity | Reasoning |
|-------|----------|-----------|
| `GPU HANG:` (i915) | **P2** | Historical event. Comparable to KERNEL-OOM-001. Requires investigation. Does not prove current unavailability or hardware failure. |
| `.* wedged` (i915) | **P2** | Historical event indicating permanent wedge state. More severe than hang but still historical — does not prove current state without live check. |
| `GPU reset failed` (AMDGPU) | **P2** | Historical event. Driver explicitly reported failure. Requires investigation. |
| `amdgpu_job_timedout` | **P2** | Historical event. Job timeout occurred. Requires investigation. |
| GPU hang with successful recovery | **P3 or report-only** | Driver recovered. Lower impact. |
| Firmware fallback | **P3 or report-only** | Degraded functionality, GPU works. |

**P1 is not justified for any historical GPU event** in the current-boot window. P1 requires proof of current critical unavailability (like STORAGE-USAGE-CRITICAL's >90% full NOW measurement). A past GPU hang or reset failure does not meet that bar.

### 8.4 Confidence

| Event | Confidence | Reasoning |
|-------|------------|-----------|
| `GPU HANG:` in kernel journal | **Certain** | Direct measurement. The log line is an authoritative i915 message. |
| `GPU reset failed` in kernel journal | **Certain** | Direct measurement. Driver explicitly reports failure. |
| `amdgpu_job_timedout` in kernel journal | **Certain** that job timed out. Cause inference (GPU vs application) would be Likely if attempted. |

### 8.5 Actionability

| Event | Actionable? | Recommendation intent |
|-------|------------|----------------------|
| `GPU HANG:` (i915) | ✅ Yes — check kernel version, i915 parameters, known issues, reproduce | INVESTIGATE |
| `GPU reset failed` (AMDGPU) | ✅ Yes — check hardware, PSU, thermals, reseat GPU | INVESTIGATE |

---

## 9. Candidate Comparison: i915 `GPU HANG:` vs AMDGPU `GPU reset failed`

### 9.1 Comparison Table

| Criterion | i915 `GPU HANG:` | AMDGPU `GPU reset failed` |
|-----------|------------------|---------------------------|
| **Exact marker** | `GPU HANG:` (verbatim i915 printk) | `GPU reset failed` (amdgpu context) |
| **Self-attributing** | ✅ Yes — log line includes `i915` | ✅ Yes — log line includes `amdgpu` |
| **False-positive risk** | Near-zero — `GPU HANG:` is never benign | Near-zero — `GPU reset failed` is never benign |
| **Correlation required** | None — single marker, no need to pair with reset outcome | None — single marker, failure is explicit |
| **Query complexity** | Simple `journalctl -b -k \| grep 'GPU HANG:'` | Simple `journalctl -b -k \| grep 'GPU reset failed'` |
| **Severity clarity** | P2 — historical hang event | P2 — historical reset failure |
| **Kernel log source** | `journalctl -b -k` — confirmed | `journalctl -b -k` — confirmed |
| **Existing codebase presence** | i915 in `RE_GFX_ERROR` (display-only) | amdgpu absent from all patterns |
| **Prevalence on workstations** | Intel integrated graphics on most laptops/desktops | AMD dedicated/discrete on subset |
| **Driver maturity** | Mature, long-standing driver | Mature, long-standing driver |

### 9.2 Recommendation

**i915 `GPU HANG:` is recommended as the first diagnostic slice.**

Reasons:
1. Exact marker is a literal kernel printk string — stable and unambiguous.
2. Self-attributing — no separate driver identity parser needed.
3. Near-zero false-positive risk — `GPU HANG:` never appears for benign reasons.
4. No correlation with reset outcome needed for the narrow contract.
5. Single dedicated query with PIPESTATUS pattern — identical architecture to KERNEL-OOM-001 (Iteration 27).
6. i915 has partial existing collection (display-only via `RE_GFX_ERROR`), providing conceptual continuity.

**AMDGPU `GPU reset failed` is equally strong as a candidate** but is deferred for the first slice because amdgpu has zero existing collection in SysCheck, making the i915 candidate incrementally closer to the existing codebase. The AMDGPU candidate is recommended as a follow-up Phase 2 slice.

---

## 10. Diagnostic Contract: GPU-I915-HANG-001

### 10.1 Contract

| Property | Value |
|----------|-------|
| Diagnostic ID | `GPU-I915-HANG-001` |
| Category | `gpu_i915_hang` |
| FindingKind | `GPU_I915_HANG` |
| Domain | `HARDWARE` |
| Severity | **P2** |
| Confidence | **Certain** |
| Actionability | `ACTIONABLE` |
| Recommendation intent | `INVESTIGATE` |
| EvidenceType | `JOURNAL_EVENT` |
| Source query | `journalctl -b -k --no-pager 2>/dev/null \| grep -iE 'GPU HANG:'` using `_oom_collector_command()` PIPESTATUS pattern |

### 10.2 Trigger

- **Exact marker:** `GPU HANG:` (case-insensitive match) in kernel journal, current boot.
- The matched line is expected to include `i915` in driver context, but the marker itself is sufficiently specific.

### 10.3 Explicit Exclusions

- `Resetting chip` / `Resetting rcs` without preceding `GPU HANG:` — not a hang event.
- `.* wedged` — separate wedge detection (deferred to Phase 2).
- `flip_done timed out` — transient display event.
- `vblank wait timed out` — transient display event.
- `Atomic update failure` — transient modeset event.
- Generic `drm.*ERROR` — too broad.
- `GPU reset` messages from non-i915 drivers.

### 10.4 RawDiagnostic Payload

```python
{
    "hang_detected": True,
    "matched_lines": ["..."],           # max 20 lines in original order
    "match_count": 1,                    # total matched lines (pre-cap)
    "driver": "i915",
    "driver_attribution_source": "in_message",
    "journal_scope": "current_boot_kernel",
    "source_query": "gpu_i915_hang",
}
```

### 10.5 Observation Mapping

```python
Observation(
    obs_id="GPU-I915-HANG-001",
    category="gpu_i915_hang",
    details=payload,
    direct_measurement=True,
    data_complete=True,
    contradictory_evidence=False,
    inference_required=False,
    independent_sources=1,
    source_raw_ids=(src_id,),
)
```

### 10.6 Evidence Payload

```python
{
    "hang_detected": True,
    "match_count": N,
    "matched_lines": [...],
    "driver": "i915",
    "journal_scope": "current_boot_kernel",
}
```

### 10.7 Finding

| Property | Value |
|----------|-------|
| Title | "i915 GPU hang detected" |
| Severity | P2 |
| Confidence | Certain |
| Interpretation | "The kernel log indicates that an i915 GPU hang occurred during the current boot. A GPU hang means the graphics driver detected that the GPU stopped responding. This does not necessarily prove a hardware defect — driver bugs, kernel issues, or transient conditions can cause hangs. If the hang occurred on a secondary GPU that is not the active display, user impact may be limited." |
| Recommendation | "Check kernel version for known i915 hang issues. Review dmesg for additional context. If hangs recur, try: (1) updating the kernel, (2) adding i915 parameters (e.g., i915.enable_guc=0), (3) testing with a different kernel version." |
| Verification | "Run `journalctl -b -k | grep 'GPU HANG'` to confirm the event. Monitor for recurrence." |
| Risk level | Medium |

### 10.8 Rule Registration

- New rule class: `GpuI915HangRule` (analogous to `KernelOomRule`).
- Registered in `build_default_rule_engine()` after `KernelOomRule`.
- FindingKind added to `FindingKind` enum: `GPU_I915_HANG = "gpu_i915_hang"`.
- Category `"gpu_i915_hang"` added to `_BY_CATEGORY` classification policy.

---

## 11. Required Tests

### 11.1 Collector Command Tests (analogous to `TestOomCommandStatus`)

| Test | Verifies |
|------|----------|
| `GPU HANG:` line match → exit 0, stdout contains line | Match success |
| No match → exit 0, stdout empty | No-match normalization |
| journalctl failure (rc=42) → exit 42 | Upstream failure propagated |
| grep rc=2 (invalid regex) → exit 2 | Grep error propagated |
| Zero-length input → exit 0 | Empty input handled |

### 11.2 Pipeline Tests (analogous to `TestOomCollectorPath`)

| Test | Verifies |
|------|----------|
| `GPU HANG:` line → `GPU-I915-HANG-001` RawDiagnostic emitted | Hang detection |
| Ordinary kernel errors no-trigger | No false positive on non-GPU errors |
| `drm:*ERROR*` no-trigger | Generic DRM error excluded |
| `GPU HANG:` from non-i915 context (hypothetical) no-trigger | Driver context preserved |
| Multiple `GPU HANG:` lines → one diagnostic | Deduplication |
| Payload preserves provenance | matched_lines, match_count, driver, scope |
| Matched lines capped at 20 | Output cap |
| Command failure → no diagnostic | journalctl error safe |
| Timeout → no diagnostic | Timeout safe |
| Observation mapping | Correct fields, category |
| Evidence mapping | JOURNAL_EVENT type |
| Finding classification | P2, Certain, ACTIONABLE, INVESTIGATE, HARDWARE |
| Rule registered | Exists in default engine |
| No regression to OOM | Existing OOM tests pass |
| No regression to taint | Existing taint tests pass |
| No regression to segfault | Existing segfault tests pass |

### 11.3 Test Restrictions

- No real journal, no actual GPU, no current hardware, no sudo, no network.
- Mock-based testing using `_collect_with_mock` pattern (same as `TestOomCollectorPath`).
- Shell-level command testing using `subprocess.run()` with fake upstream executables (same as `TestOomCommandStatus`).

---

## 12. False-Positive Reassessment Summary

| Previous claim | Corrected position |
|----------------|-------------------|
| "Inactive GPU events are false positives" | **Inactive GPU events are true events with potentially lower user impact.** The diagnostic interpretation should note this but not suppress the event. |
| "Driver identity prerequisite is required for hybrid systems" | **Driver identity is not a prerequisite.** Self-attributing markers provide sufficient driver context. Active-renderer ambiguity affects interpretation, not detection. |
| "GPU HANG: + wedged + reset should be bundled" | **First slice is only `GPU HANG:`.** Wedged and reset outcome are deferred. |
| "GPU reset failed = P1" | **Corrected to P2.** Historical event, not proven current unavailability. |
| "NVIDIA Xid ready with code-based severity" | **NVIDIA deferred.** Uncertain log capture, Xid code complexity, dmesg_restrict dependency. |
| "Nouveau markers are diagnostic-ready" | **Nouveau deferred.** Limited deployment, lower diagnostic yield. |
| "`is_active` field in driver payload" | **Removed.** Active-renderer identification is unresolved. |
| "GPU-DRIVERS-001 RawDiagnostic as container" | **Removed.** RawDiagnostic without consumer is architecturally invalid. GPU inventory is report data. |

---

## 13. Unresolved Uncertainties

### 13.1 Active-Renderer Determination

The first slice (GPU-I915-HANG-001) reports i915 GPU hang events without determining whether the affected GPU is the active renderer. The interpretation text acknowledges this ambiguity.

Active-renderer determination remains unresolved for future phases. Potential sources include:
- `glxinfo` / `vulkaninfo` parsing (renderer string).
- Xorg/Wayland session information (which GPU drives outputs).
- PRIME render offload configuration.

This is not a blocker for the first slice.

### 13.2 GPU-I915-HANG-001 vs GPU-HANG-001 Naming

The diagnostic ID `GPU-I915-HANG-001` is driver-specific. This allows future parallel diagnostics for other drivers (`GPU-AMDGPU-RESET-001`, `GPU-XID-001`) without ID collision. If a cross-driver generalization is desired later, IDs can be aligned.

### 13.3 NVIDIA Log Destination

NVIDIA `NVRM: Xid` messages may appear in `dmesg` but capture in `journalctl -b -k` is not fully verified. This uncertainty is documented but does not block the i915 first slice.

### 13.4 Kernel Version Variation

`GPU HANG:` has been a stable i915 message across 5.x and 6.x kernels. This assessment assumes continued stability. If a future kernel changes the message format, the query pattern would need adjustment.

---

## 14. Final Decision

### Decision A — Implement One Narrow GPU Diagnostic

**Selected: GPU-I915-HANG-001 (i915 GPU hang detection).**

**Exact contract:**
- Driver family: Intel i915
- Marker: `GPU HANG:` in kernel journal (current boot)
- Query: `journalctl -b -k --no-pager 2>/dev/null | grep -iE 'GPU HANG:'` using `_oom_collector_command()` PIPESTATUS pattern
- Severity: P2
- Confidence: Certain
- Finding: i915 GPU hang detected — investigation required
- No inference about reset outcome, hardware failure, or current availability

**Why this diagnostic is ready now:**
1. The marker is self-attributing (log line includes `i915`). No driver identity prerequisite.
2. The marker is authoritative and never benign. Near-zero false-positive risk.
3. No correlation with other events needed. No pairing with reset outcome or timeout.
4. Implementation architecture is identical to KERNEL-OOM-001 (Iteration 27): single dedicated `journalctl -b -k` query, PIPESTATUS handling, single rule, single FindingKind.
5. Active-renderer ambiguity is acknowledged in the interpretation but does not block detection.
6. Not dependent on `dmesg`, `glxinfo`, `nvidia-smi`, or any other uncollected data source.

**Explicit boundaries:**
- Does NOT infer reset outcome (no `Resetting chip` tracking).
- Does NOT detect `wedged` state (deferred to Phase 2).
- Does NOT provide driver identity inventory (deferred to separate report-enrichment task).
- Does NOT handle non-i915 drivers (AMDGPU, NVIDIA, Nouveau deferred).
- Does NOT attempt active-renderer determination.
- Does NOT claim hardware failure — only that a GPU hang event was logged.

---

## 15. Exact Next Scope

### Implementation of GPU-I915-HANG-001

Following the established pattern from Iteration 27 (KERNEL-OOM-001):

**Files to modify:**
- `constants.py`: Add regex pattern for GPU HANG marker.
- `syscheck.py`: Add `GPU_I915_HANG` FindingKind, add `gpu_i915_hang` category to `_BY_CATEGORY`, add dedicated collector task with `_oom_collector_command()` in `collect_kernel_hw()` or as a new collector, add `_raw_to_observation()` handler for `gpu_i915_hang` category, add `EvidenceBuilder.build()` branch, add `GpuI915HangRule` class, register in `build_default_rule_engine()`.
- `test_syscheck.py`: Add `TestGpuI915HangCommandStatus` (shell-level command tests) and `TestGpuI915HangCollectorPath` (pipeline tests following `TestOomCollectorPath` pattern).

**No-go boundaries:**
- No `wedged` detection.
- No `Resetting chip` tracking.
- No driver identity inventory (separate task).
- No AMDGPU, NVIDIA, or Nouveau diagnostics.
- No active-renderer determination.
- No generic `drm.*ERROR` matching.
- No changes to existing OOM, taint, segfault, or boot-time diagnostics.

**Structured GPU inventory (report enrichment)** can be implemented as a separate follow-up task with smaller scope: reading `/sys/class/drm/card*/device/driver` symlinks and displaying structured driver names in the report. This is not a `RawDiagnostic` — it is a `CmdResult`-based collector in `collect_graphics()`.

---

## 16. Confirmation

**No production files, tests, or constants were modified during this assessment.**

- `syscheck.py`: Not modified.
- `constants.py`: Not modified.
- `test_syscheck.py`: Not modified.
- No files were staged, committed, pushed, reset, restored, or renamed.
- No branches were created or switched.
- No project artifacts were renamed.
- Only this review file was created at:
  `.agent-work/reviews/deepseek-v4-flash-max-gpu-graphics-kernel-log-diagnostics-assessment.md`
