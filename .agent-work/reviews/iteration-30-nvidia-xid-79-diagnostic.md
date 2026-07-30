# Iteration 30 — NVIDIA Xid 79 Diagnostic (GPU-NVIDIA-XID-79-001) — Corrected Regex

## 1. Repository checkpoint

```
pwd             : <REDACTED-PATH>
branch          : master
base commit     : 0f6526b feat: detect amdgpu reset failures
git status      :  M constants.py,  M test_syscheck.py
                   ?? .agent-work/reviews/iteration-30-nvidia-xid-79-diagnostic.md
git diff --check: clean (no whitespace errors)
```

No unrelated tracked changes detected. Base commit matches expected.

## 2. Problem: old regex matched stray `79` after other Xid codes

**Old regex:**
```python
RE_NVIDIA_XID_79 = r"(NVRM|nvidia):.*Xid.*\b79\b"
```

**Failure mode:** The greedy `.*` between `Xid` and `\b79\b` matches any characters, so `79` appearing anywhere *after* `Xid` on the same line triggers a false positive, even when another Xid code (e.g. 13, 31) is the actual code.

**Example false-positive input:**
```
NVRM: Xid (PCI:0000:01:00): 13, GPU at 79% load
```
- Old regex match trace:
  - `(NVRM|nvidia):` → `NVRM:`
  - `.*` → ` ` (backtracks to allow `Xid`)
  - `Xid` → `Xid`
  - `.*` → ` (PCI:0000:01:00): 13, GPU at ` (greedy, backtracks to match `79`)
  - `\b79\b` → matches `79` in `79%`
- **False positive: Xid code is 13, not 79**

## 3. Fix: bind `79` to the Xid-code position after the PCI segment

**New regex:**
```python
RE_NVIDIA_XID_79 = r"(?:NVRM|nvidia):\s*Xid\s*\(PCI:[^)]+\):\s*79\b"
```

**Components:**

| Fragment | Semantics |
|---|---|
| `(?:NVRM\|nvidia):` | Driver prefix (non-capturing group, compatible with `grep -E`) |
| `\s*` | Optional whitespace |
| `Xid` | Literal marker |
| `\s*` | Optional whitespace |
| `\(PCI:[^)]+\)` | PCI segment `(PCI:BB:DD.F)` — anchors the match to the canonical Xid line structure |
| `:\s*` | Colon separator after PCI segment |
| `79\b` | Xid code 79 with word boundary |

**Why this fixes the false positive:**
- `79` must appear immediately after the PCI segment's `)` + `:` + optional whitespace.
- Any `79` appearing elsewhere (in temperatures, percentages, timestamps, or descriptions after another Xid code) is **not** at that position → no match.

**Effect on the adversarial case:**
```
NVRM: Xid (PCI:0000:01:00): 13, GPU at 79% load
```
- `(?:NVRM|nvidia):\s*Xid\s*\(PCI:[^)]+\):\s*` → `NVRM: Xid (PCI:0000:01:00): `
- `79\b` → tries to match at position after `: `, finds `13` → **no match** ✅

## 4. Verified trigger / non-trigger matrix (shell-level)

| # | Input | Matches? | Test method |
|---|---|---|---|
| 1 | `nvidia: Xid (PCI:...): 79, GPU has fallen off the bus.` | ✅ | `test_match_success_nvidia_prefix` |
| 2 | `NVRM: Xid (PCI:...): 79, GPU has fallen off the bus.` | ✅ | `test_match_success_nvrm_prefix` |
| 3 | `NVRM: Xid (PCI:...:0): 79, GPU has fallen off the bus.` | ✅ | `test_match_pci_with_dot_zero` |
| 4 | `NVRM: Xid (PCI:...): 13, Graphics Engine Exception.` | ❌ | `test_no_match_other_xid` |
| 5 | `NVRM: Xid (PCI:...): 179, some error.` | ❌ | `test_no_match_xid_179` |
| 6 | `NVRM: Xid (PCI:...): 790, some error.` | ❌ | `test_no_match_xid_790` |
| 7 | `some kernel message with 79 somewhere` | ❌ | `test_no_match_unrelated_79` |
| 8 | `NVRM: Xid (PCI:...): 13, GPU at 79% load` ***new*** | ❌ | `test_no_match_xid13_with_later_79` |
| 9 | `NVRM: Xid (PCI:...): 31, temp 79C` ***new*** | ❌ | `test_no_match_xid31_with_later_79` |
| 10 | `79: NVRM: Xid (PCI:...): 13, GPU exception` ***new*** | ❌ | `test_no_match_bare_79_before_xid` |
| 11 | Upstream journalctl rc=42 → exit 42 | ❌ | `test_upstream_failure` |
| 12 | grep invalid regex rc=2 → exit 2 | ❌ | `test_grep_rc2_propagated` |
| 13 | Empty input → exit 0, stdout empty | ❌ | `test_zero_length_input` |
| 14 | stderr redirection preserves exit status | — | `test_stderr_suppressed_preserves_status` |

**3 new adversarial shell tests** (rows 8–10) that the old regex would false-positive on.

## 5. Source semantics (unchanged)

The collector uses `_oom_collector_command()` — the same safe PIPESTATUS helper as OOM, i915, and AMDGPU diagnostics:

```python
"gpu_nvidia_xid_79": (
    _oom_collector_command(
        "journalctl -b -k --no-pager 2>/dev/null",
        RE_NVIDIA_XID_79,
    ),
    TIMEOUT_LONG,
    False,
),
```

- **no `|| true`** — upstream failures are propagated.
- match → exit 0, stdout non-empty.
- no-match → exit 0, stdout empty.
- journalctl failure → rc propagated via PIPESTATUS → `is_ok()` returns False.
- grep failure → rc propagated.
- timeout → `_parallel_cmd` catches `TimeoutExpired` → `execution_status="timeout"`.

Safe on:
- Permission denied → `is_ok()` = False → no diagnostic emitted.
- Command not found → `is_ok()` = False → no diagnostic emitted.
- Timeout → `is_ok()` = False → no diagnostic emitted.

## 6. Collector-path trigger matrix

| Context | Input | Test | Triggers? |
|---|---|---|---|
| Standard NVRM prefix | `NVRM: Xid (PCI:0000:01:00): 79, GPU has fallen off the bus.` | `test_xid79_nvrm_prefix_triggers` | ✅ |
| `nvidia:` prefix | `nvidia: Xid (PCI:0000:01:00): 79, ...` | `test_xid79_nvidia_prefix_triggers` | ✅ |
| PCI with .0 suffix | `PCI:0000:01:00.0` | `test_xid79_pci_with_dot_zero_triggers` | ✅ |
| Xid 7 | `NVRM: Xid (PCI:...): 7, ...` | `test_xid7_no_trigger` | ❌ |
| Xid 9 | `NVRM: Xid (PCI:...): 9, ...` | `test_xid9_no_trigger` | ❌ |
| Xid 13 | `NVRM: Xid (PCI:...): 13, Graphics Engine Exception.` | `test_xid13_no_trigger` | ❌ |
| Xid 31 | `NVRM: Xid (PCI:...): 31, ...` | `test_xid31_no_trigger` | ❌ |
| Xid 43 | `NVRM: Xid (PCI:...): 43, ...` | `test_xid43_no_trigger` | ❌ |
| Xid 56 | `NVRM: Xid (PCI:...): 56, ...` | `test_xid56_no_trigger` | ❌ |
| Xid 74 | `NVRM: Xid (PCI:...): 74, ...` | `test_xid74_no_trigger` | ❌ |
| Xid 179 | `NVRM: Xid (PCI:...): 179, ...` | `test_xid179_no_trigger` | ❌ |
| Xid 790 | `NVRM: Xid (PCI:...): 790, ...` | `test_xid790_no_trigger` | ❌ |
| **Xid 13 + stray 79** ***new*** | `NVRM: Xid (PCI:...): 13, GPU at 79% load` | `test_xid13_with_later_79_no_trigger` | ❌ |
| **Xid 31 + stray 79** ***new*** | `NVRM: Xid (PCI:...): 31, temp 79C` | `test_xid31_with_later_79_no_trigger` | ❌ |
| **79 before Xid** ***new*** | `79: NVRM: Xid (PCI:...): 13, GPU exception` | `test_xid_bare_79_before_xid_no_trigger` | ❌ |
| i915 GPU HANG | `i915 ... GPU HANG: ...` | `test_i915_no_trigger` | ❌ |
| AMDGPU reset | `amdgpu ... GPU reset failed!` | `test_amdgpu_no_trigger` | ❌ |
| Nouveau | `nouveau ... fifo: read fault` | `test_nouveau_no_trigger` | ❌ |
| nvidia-modeset | `nvidia-modeset: ERROR: ...` | `test_nvidia_modeset_no_trigger` | ❌ |
| nvidia-drm | `nvidia-drm: some DRM message` | `test_nvidia_drm_no_trigger` | ❌ |
| Generic DRM | `[drm:...] *ERROR* Invalid constant` | `test_generic_drm_error_no_trigger` | ❌ |
| Empty output | (empty) | `test_empty_no_trigger` | ❌ |
| Command failure | rc=1 | `test_command_failure_safe` | ❌ |
| Permission denied | permission_denied | `test_permission_denied_safe` | ❌ |
| Command not found | not_found | `test_not_found_safe` | ❌ |
| Timeout | timeout | `test_timeout_safe` | ❌ |

**3 new adversarial collector-path tests** (rows 15–17).

## 7. Production changes

### 7.1 `constants.py` — regex corrected (1 line changed)

```python
# Old (false-positive on stray 79 after other Xid codes):
RE_NVIDIA_XID_79 = r"(NVRM|nvidia):.*Xid.*\b79\b"

# New (binds 79 to Xid-code position after PCI segment):
RE_NVIDIA_XID_79 = r"(?:NVRM|nvidia):\s*Xid\s*\(PCI:[^)]+\):\s*79\b"
```

### 7.2 `test_syscheck.py` — 6 new tests (3 shell + 3 collector-path)

**Shell-level (`TestNvidiaXid79CommandStatus`):**
| Test | Assertion |
|---|---|
| `test_no_match_xid13_with_later_79` | `NVRM: Xid (PCI:...): 13, GPU at 79% load` → exit 0, stdout empty |
| `test_no_match_xid31_with_later_79` | `NVRM: Xid (PCI:...): 31, temp 79C` → exit 0, stdout empty |
| `test_no_match_bare_79_before_xid` | `79: NVRM: Xid (PCI:...): 13, GPU exception` → exit 0, stdout empty |

**Collector-path (`TestNvidiaXid79CollectorPath`):**
| Test | Assertion |
|---|---|
| `test_xid13_with_later_79_no_trigger` | Xid 13 + stray 79 → no GPU-NVIDIA-XID-79-001 diagnostic |
| `test_xid31_with_later_79_no_trigger` | Xid 31 + stray 79 → no diagnostic |
| `test_xid_bare_79_before_xid_no_trigger` | bare 79 before Xid 13 → no diagnostic |

## 8. Payload (unchanged)

```python
RawDiagnostic(
    source_id="GPU-NVIDIA-XID-79-001",
    category="gpu_nvidia_xid_79",
    payload={
        "xid_detected": True,
        "xid_code": 79,
        "matched_lines": [...],        # first 20 lines
        "match_count": N,               # total matching lines
        "driver": "nvidia",
        "driver_attribution_source": "in_message",
        "journal_scope": "current_boot_kernel",
        "source_query": "gpu_nvidia_xid_79",
    },
)
```

## 9. Mappings (unchanged)

### Observation

```python
Observation(
    obs_id="GPU-NVIDIA-XID-79-001",
    category="gpu_nvidia_xid_79",
    details=payload,
    direct_measurement=True,
    data_complete=True,
    contradictory_evidence=False,
    inference_required=False,
    independent_sources=1,
    source_raw_ids=(src_id,),
)
```

### Evidence

```python
Evidence(
    evidence_id="EVIDENCE-GPU-NVIDIA-XID-79-001-001",
    evidence_type=EvidenceType.JOURNAL_EVENT,
    data={
        "xid_detected": True,
        "xid_code": 79,
        "match_count": N,
        "matched_lines": [...],
        "driver": "nvidia",
        "driver_attribution_source": "in_message",
        "journal_scope": "current_boot_kernel",
        "source_query": "gpu_nvidia_xid_79",
    },
)
```

### Finding

| Property | Value |
|---|---|
| ID | `GPU-NVIDIA-XID-79-001` |
| Title | `Wykryto zdarzenie NVIDIA Xid 79 — utrata połączenia GPU z magistralą` |
| Severity | P2 |
| Confidence | Certain |
| Domain | HARDWARE |
| Kind | GPU_NVIDIA_XID_79 |
| Actionability | ACTIONABLE |
| Intent | INVESTIGATE |

## 10. Wording boundaries (unchanged)

The Finding interpretation states:

- ✅ NVIDIA Xid 79 was recorded in the current-boot kernel journal
- ✅ It is a historical event and may no longer be active
- ✅ It does not prove current GPU unavailability
- ✅ It does not prove hardware failure
- ✅ It does not identify the active renderer
- ✅ Possible contexts: spontaneous PCIe/power-state loss, intentional eGPU detach, suspend/resume failure, or driver/firmware interaction
- ✅ SysCheck cannot distinguish these causes from one event line
- ✅ Missing detection does not prove the event never occurred

The Finding does NOT state:
- ❌ That the GPU definitely physically disconnected
- ❌ That any component is defective
- ❌ A prescription for hardware replacement, reseating, ASPM changes, kernel parameters, driver branch changes, reinstalling drivers, or distro-specific package-manager commands

## 11. Focused validation

```
uv run pytest -k "NvidiaXid79" -v
→ 52 passed, 467 deselected in 2.66s
```

6 new tests pass (3 shell + 3 collector-path). All 46 original tests remain passing.

## 12. Full repository validation

```
ruff format --check .
→ 3 files already formatted

ruff check .
→ All checks passed!

python3 -m pytest --collect-only -q
→ 519 tests collected

python3 -m pytest -q
→ 519 passed in 1.83s
```

**519 tests total** (467 pre-existing + 46 original Xid + 6 new adversarial).

## 13. Final test count

```
Pre-existing tests                          : 467
TestNvidiaXid79CommandStatus  (original)    :  11
TestNvidiaXid79CommandStatus  (adversarial) :   3
TestNvidiaXid79CollectorPath  (original)    :  35
TestNvidiaXid79CollectorPath  (adversarial) :   3
Total                                       : 519
```

## 14. Files changed

```
 constants.py     |   2 +-
 test_syscheck.py |  61 +++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 62 insertions(+), 1 deletion(-)
```

No changes to `syscheck.py` — only the regex constant and tests.

## 15. No-go boundaries (unchanged)

This diagnostic does **not**:
- Detect any Xid code other than 79
- Use `|| true` or silent masking
- Add `dmesg`, `nvidia-smi`, or other new infrastructure
- Claim hardware failure, current GPU unavailability, or active-renderer status
- Prescribe hardware replacement, reseating, ASPM changes, kernel parameters, or driver reinstallation
- Use lookbehind/lookahead regex unsupported by grep

## 16. Known limitations (updated)

- The regex `(?:NVRM|nvidia):\s*Xid\s*\(PCI:[^)]+\):\s*79\b` requires both NVIDIA prefix and the canonical PCI segment format. If the message format changes (e.g., future driver drops the PCI segment), the diagnostic may miss events. This is an acceptable trade-off to eliminate false positives from stray `79` occurrences.
- The diagnostic covers only Xid code 79. Other Xid codes are not detected.
- `data_complete=True` means only that the available query output was processed successfully. It does not imply complete journal retention or historical coverage.
- Non-English kernel messages are not handled.
- The `driver` and `driver_attribution_source` fields are hard-coded constants, not derived from PCI ID lookup.

## 17. Git restriction confirmation

- No `git add`, `git commit`, `git push`, `git reset`, `git restore`, `git branch`, or artifact renaming was performed.
- All changes remain unstaged working-tree modifications.
