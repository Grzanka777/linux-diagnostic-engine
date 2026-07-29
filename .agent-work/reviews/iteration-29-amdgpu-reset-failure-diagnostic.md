# Iteration 29 — AMDGPU Reset Failure Diagnostic (AMDGPU-RESET-FAIL-001)

## 1. Repository checkpoint

```
pwd             : <REDACTED-PATH>
branch          : master
working tree    : modified (3 files) + untracked reviews
base commit     : 0fc3937 feat: detect i915 gpu hangs
git status      :  M constants.py,  M syscheck.py,  M test_syscheck.py
                  ?? .agent-work/reviews/deepseek-v4-flash-max-...assessment.md
                  ?? .agent-work/reviews/iteration-28-...md
                  ?? .agent-work/reviews/iteration-29-...md
git diff --stat : 3 files changed, 981 insertions(+)
```

No unrelated tracked changes. Base matches expected.

## 2. Exact query and failure semantics

The AMDGPU reset-fail collector uses `_oom_collector_command()` — the same safe status-preserving Bash helper as OOM (Iteration 27) and i915 (Iteration 28):

```python
"amdgpu_reset_fail": (
    _oom_collector_command(
        "journalctl -b -k --no-pager 2>/dev/null",
        RE_AMDGPU_RESET_FAIL,
    ),
    TIMEOUT_LONG,
    False,
),
```

The helper:
- Captures PIPESTATUS atomically: `statuses=("${PIPESTATUS[@]}")`
- Propagates upstream (journalctl) failure: `if [ "$js" -ne 0 ]; then exit "$js"`
- Normalises grep rc=1 to exit 0: `elif [ "$gs" -eq 1 ]; then exit 0`
- Propagates grep rc>1: `else exit "$gs"`
- Does **not** use `|| true`

Test-proven failure modes (7 shell-level tests pass):
- Match → rc 0, stdout non-empty
- Reverse-order match → rc 0, stdout non-empty
- Case-insensitive match → rc 0
- No match → rc 0, stdout empty
- Upstream failure (rc 42) → rc 42
- grep rc 2 (invalid regex) → rc 2
- Empty input → rc 0, stdout empty

## 3. Exact same-line trigger

Regex: `r"amdgpu.*GPU reset failed|GPU reset failed.*amdgpu"`

An accepted line must contain **both** `amdgpu` **and** the exact phrase `GPU reset failed` on the **same line**, in either order, matched case-insensitively (both `grep -iE` in shell path and `re.search(..., re.IGNORECASE)` in sideband).

### Verified non-trigger cases (all with dedicated collector-path tests)

| # | Input | Triggers? | Test method |
|---|---|---|---|
| 1 | `amdgpu ... GPU reset failed!` | ✅ | `test_reset_fail_triggers` |
| 2 | `GPU reset failed ... amdgpu` | ✅ | `test_reverse_order_triggers` |
| 3 | `[drm] GPU reset failed!` (no amdgpu) | ❌ | `test_no_amdgpu_no_trigger` |
| 4 | `amdgpu ... GPU reset begin!` | ❌ | `test_amdgpu_no_marker_no_trigger` |
| 5 | `amdgpu ... GPU reset begin!` | ❌ | `test_reset_begin_no_trigger` |
| 6 | `amdgpu ... GPU reset succeeded!` | ❌ | `test_reset_succeeded_no_trigger` |
| 7 | `amdgpu ... GPU reset end!` | ❌ | `test_reset_end_no_trigger` |
| 8 | `amdgpu ... amdgpu_job_timedout` | ❌ | `test_job_timedout_no_trigger` |
| 9 | `amdgpu ... ring gfx timeout` | ❌ | `test_ring_timeout_no_trigger` |
| 10 | `amdgpu ... VM fault` | ❌ | `test_vm_fault_no_trigger` |
| 11 | `amdgpu ... page fault` | ❌ | `test_page_fault_no_trigger` |
| 12 | `[drm] *ERROR*` (generic DRM) | ❌ | `test_drm_error_no_trigger` |
| 13 | `i915 ... GPU HANG:` | ❌ | `test_i915_no_trigger` |
| 14 | `nvidia: Xid ...` | ❌ | `test_nvidia_xid_no_trigger` |
| 15 | `nouveau ... fifo fault` | ❌ | `test_nouveau_no_trigger` |
| 16 | (empty output) | ❌ | `test_empty_no_trigger` |

The production trigger is not broadened beyond the exact same-line contract.

## 4. Production changes

### `constants.py` (+1 line)

```python
RE_AMDGPU_RESET_FAIL = r"amdgpu.*GPU reset failed|GPU reset failed.*amdgpu"
```

### `syscheck.py` (+177 lines)

| Change | Location |
|---|---|
| Import `RE_AMDGPU_RESET_FAIL` | Top of file (alphabetically) |
| `FindingKind.AMDGPU_RESET_FAIL = "amdgpu_reset_fail"` | FindingKind enum |
| `"amdgpu_reset_fail"` classification entry | `_BY_CATEGORY` (HARDWARE, ACTIONABLE, INVESTIGATE) |
| `EvidenceBuilder.build()` branch for `amdgpu_reset_fail` | After i915 branch |
| `AmdgpuResetFailRule` class (`RULE-AMDGPU-RESET-FAIL`) | After `GpuI915HangRule` |
| Rule registration in `build_default_rule_engine()` | After `GpuI915HangRule(eb)` |
| Collector task in `tasks_cmd` | Between `gpu_i915_hang` and `lspci` |
| `amdgpu_reset_fail_result = r["amdgpu_reset_fail"]` | After `gpu_i915_hang_result` |
| Sideband check block | After i915 sideband check |
| `_raw_to_observation()` handler for `amdgpu_reset_fail` | After `gpu_i915_hang` handler |

### `test_syscheck.py` (+803 lines)

| Change | Purpose |
|---|---|
| `RE_AMDGPU_RESET_FAIL` import | Access regex constant |
| `"amdgpu_reset_fail": self._cmd_ok("")` in 3 mock methods | Prevent KeyError when `collect_kernel_hw()` accesses `r["amdgpu_reset_fail"]` |
| `TestAmdgpuResetFailCommandStatus` | 7 shell-level command-status tests |
| `TestAmdgpuResetFailCollectorPath` | 34 collector-path tests |

## 5. RawDiagnostic payload

```python
RawDiagnostic(
    source_id="AMDGPU-RESET-FAIL-001",
    category="amdgpu_reset_fail",
    payload={
        "reset_failure_detected": True,
        "matched_lines": [...],             # max 20, original order
        "match_count": N,                   # total before cap
        "driver": "amdgpu",
        "driver_attribution_source": "in_message",
        "journal_scope": "current_boot_kernel",
        "source_query": "amdgpu_reset_fail",
    },
)
```

## 6. Observation/Evidence mapping

### Observation

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

### Evidence

| Property | Value |
|---|---|
| EvidenceType | `JOURNAL_EVENT` |
| Strength | STRONG (MODERATE if contradictory) |
| Directness | DIRECT (INFERRED if inference required) |
| Completeness | COMPLETE (PARTIAL if data incomplete) |
| Summary | `"AMDGPU reset failure detected during current boot (N matching journal line(s))"` |

Evidence data preserves: `reset_failure_detected`, `match_count`, `matched_lines`, `driver`, `driver_attribution_source`, `journal_scope`, `source_query`.

## 7. Finding and recommendation semantics

| Property | Value |
|---|---|
| Finding ID | `AMDGPU-RESET-FAIL-001` |
| Title (Polish) | `Wykryto nieudany reset GPU obsługiwanego przez sterownik amdgpu` |
| Severity | **P2** |
| Confidence | **Certain** |
| Domain | `DiagnosticDomain.HARDWARE` |
| Actionability | `Actionability.ACTIONABLE` |
| Intent | `RecommendationIntent.INVESTIGATE` |
| FindingKind | `AMDGPU_RESET_FAIL` |

### Finding boundaries — confirmed via tests

| Boundary | Test | Passes |
|---|---|---|
| Does NOT claim hardware failure | `test_no_hardware_failure_claim` | ✅ |
| Does NOT claim current GPU unavailability | `test_no_current_unavailability_claim` | ✅ |
| Recommends no Arch-only `pacman -Q` command | `test_no_arch_only_command` | ✅ |
| Recommends no arbitrary kernel parameters | `test_no_kernel_parameters` | ✅ |
| Verification does not claim journal entry disappears | `test_verification_no_disappearance_claim` | ✅ |

### Interpretation (Polish)

> Dziennik jądra odnotował zdarzenie `GPU reset failed` dla sterownika amdgpu w bieżącym bocie. Zdarzenie mogło mieć charakter historyczny i może nie być już aktywne. Diagnostyka nie potwierdza defektu sprzętowego — możliwe przyczyny obejmują usterki jądra/sterownika, interakcję z firmware lub platformą, obciążenie wywołujące błąd, niestabilność zasilania/termiczna/PCIe, lub niestabilność sprzętową. Diagnostyka nie określa, czy dotknięte GPU było aktywnym rendererem — wpływ na użytkownika może być różny. Uwaga: brak wykrytego zdarzenia nie dowodzi, że nie wystąpił reset — retencja dziennika jądra może być niepełna.

## 8. Exact tests by class and count

### `TestAmdgpuResetFailCommandStatus` — **7 tests**

| Test | Verifies |
|---|---|
| `test_match_success` | Standard `amdgpu ... GPU reset failed` matches |
| `test_match_reverse_order` | `GPU reset failed ... amdgpu` matches |
| `test_case_insensitive` | Case variations match |
| `test_no_match` | No match → rc 0, empty stdout |
| `test_upstream_failure` | Upstream rc=42 propagated |
| `test_grep_rc2_propagated` | grep rc=2 (invalid regex) propagated |
| `test_zero_length_input_no_match` | Empty input → rc 0 |

### `TestAmdgpuResetFailCollectorPath` — **34 tests**

| Category | Tests | Count |
|---|---|---|
| Positive | `test_reset_fail_triggers`, `test_reverse_order_triggers` | 2 |
| Negative (no-trigger) | `test_no_amdgpu_no_trigger`, `test_amdgpu_no_marker_no_trigger`, `test_reset_begin_no_trigger`, `test_reset_succeeded_no_trigger`, `test_reset_end_no_trigger`, `test_job_timedout_no_trigger`, `test_ring_timeout_no_trigger`, `test_vm_fault_no_trigger`, `test_page_fault_no_trigger`, `test_drm_error_no_trigger`, `test_i915_no_trigger`, `test_nvidia_xid_no_trigger`, `test_nouveau_no_trigger`, `test_empty_no_trigger` | 14 |
| Multiple matches | `test_multiple_matches` | 1 |
| Failure/edge | `test_command_failure_safe`, `test_timeout_safe`, `test_payload_provenance`, `test_output_cap` | 4 |
| Pipeline | `test_observation_mapping`, `test_evidence_journal_event_type`, `test_finding_classification`, `test_rule_registered` | 4 |
| Wording boundaries | `test_no_hardware_failure_claim`, `test_no_current_unavailability_claim`, `test_no_arch_only_command`, `test_no_kernel_parameters`, `test_verification_no_disappearance_claim` | 5 |
| Regression | `test_existing_oom_unchanged`, `test_existing_i915_unchanged`, `test_existing_segfault_unchanged`, `test_existing_taint_unchanged` | 4 |

**Total new: 41** (7 + 34)

## 9. Focused validation

```
python3 -m pytest test_syscheck.py -k "Amdgpu" -v
→ 42 passed, 425 deselected in 0.89s
```

All 42 AMDGPU-specific tests pass (including the pre-existing `test_amdgpu_reset_no_trigger` in the i915 test class).

```
python3 -m pytest test_syscheck.py -k "GpuI915" -v
→ 31 passed, 436 deselected in 0.44s
```

All 31 i915 tests pass — no regression from AMDGPU addition.

## 10. Full validation

### `ruff format --check .`
```
3 files already formatted
exit 0
```

### `ruff check .`
```
All checks passed!
exit 0
```

### `python3 -m pytest --collect-only -q`
```
467 tests collected in 0.06s
```

### `python3 -m pytest -q`
```
467 passed in 1.58s
exit 0
```

## 11. Exact final test count

| Category | Count |
|---|---|
| Pre-existing (no GpuI915, no Amdgpu) | 395 |
| `TestGpuI915HangCommandStatus` | 7 |
| `TestGpuI915HangCollectorPath` | 24 |
| `TestAmdgpuResetFailCommandStatus` | 7 |
| `TestAmdgpuResetFailCollectorPath` | 34 |
| **Total** | **467** |

## 12. Files changed

```
 constants.py     |   1 +
 syscheck.py      | 177 ++++++++++++
 test_syscheck.py | 803 +++++++++++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 981 insertions(+)
```

Zero deletions.

## 13. No-go boundaries

This diagnostic does **not**:
- Detect `amdgpu_job_timedout`, ring timeouts, VM/page faults
- Correlate with `GPU reset begin/succeeded/end` lifecycle
- Infer hardware failure
- Infer current GPU unavailability
- Infer active renderer
- Prescribe kernel parameters (e.g. `amdgpu.aspm=0`)
- Prescribe Arch-only package manager commands
- Claim the historical journal entry disappears after remediation
- Detect NVIDIA, i915, or Nouveau events

## 14. Known limitations

- The regex `amdgpu.*GPU reset failed|GPU reset failed.*amdgpu` requires both substrings on the same **journal line**. Multi-line reset failure reports are not matched.
- The diagnostic relies on `_oom_collector_command`, which uses `journalctl -b -k` — only the current boot's kernel journal is scanned. Past boots are not inspected.
- Non-English kernel messages are not handled.
- The `driver` and `driver_attribution_source` fields are hard-coded constants, not derived from PCI ID lookup.
- A `GPU reset succeeded` line in the same boot does not suppress or downgrade the `GPU reset failed` finding — no lifecycle correlation is performed.
- Multiple distinct reset failures in the same boot produce one RawDiagnostic with `match_count` reflecting total lines — no temporal separation.

## 15. Git restriction confirmation

- No `git add`, `git commit`, `git push`, `git reset`, `git restore`, `git branch`, or artifact renaming was performed.
- All changes remain unstaged working-tree modifications.
- The assessment review file (`.agent-work/reviews/deepseek-v4-flash-max-amdgpu-reset-failure-diagnostic-assessment.md`) was not modified.
