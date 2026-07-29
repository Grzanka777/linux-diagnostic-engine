# Iteration 28 — i915 GPU Hang Diagnostic (GPU-I915-HANG-001)

## 1. Repository checkpoint

```
pwd             : <REDACTED-PATH>
branch          : master
base commit     : 514d488 feat: detect kernel oom events
git status      :  M constants.py,  M syscheck.py,  M test_syscheck.py
                  ?? .agent-work/reviews/deepseek-v4-flash-max-...assessment.md
                  ?? .agent-work/reviews/iteration-28-i915-gpu-hang-diagnostic.md
git diff --check: clean (no whitespace errors)
git diff --stat : 3 files changed, 702 insertions(+)
```

No unrelated tracked changes detected. Base commit matches expected.

## 2. Exact diff scope and stat

| File | Insertions | Deletions | Intent |
|---|---|---|---|
| `constants.py` | 1 | 0 | `RE_GPU_I915_HANG` regex constant |
| `syscheck.py` | 170 | 0 | Enum, classification, EvidenceBuilder, collector task + sideband, rule, raw-to-obs |
| `test_syscheck.py` | 531 | 0 | Import, mock updates, 2 new test classes (31 tests) |
| **Total** | **702** | **0** | |

**The diff stat shows 0 deletions.** The `_make_segfault_line()` modification was fully reverted in a prior correction. A deletion does not appear in this diff because the reverted code (`self` parameter removal) was restored to its original state. The earlier review draft incorrectly attributed a phantom deletion to the reverted edit; no deletion exists in the current working tree.

## 3. Disposition of the unrelated segfault edit

The `_make_segfault_line()` modification was **reverted** in the prior correction. The pre-existing code (`def _make_segfault_line(self, ...)`) is unchanged from base commit `514d488`.

The only required changes to existing test classes are:
- `+ "gpu_i915_hang": self._cmd_ok("")` in `TestSegfaultAndTaintCollectorPath._collect_with_mock()` — required because `collect_kernel_hw()` now accesses `r["gpu_i915_hang"]` with bracket syntax.
- Same addition in `TestOomCollectorPath._collect_with_mock()` — same reason.
- `RE_GPU_I915_HANG` import added at the top of `test_syscheck.py`.

These are the minimal mechanical adjustments needed for existing mocks to interoperate with the new `tasks_cmd` entry. Not scope violations.

## 4. Exact query and failure semantics

The i915 collector task uses `_oom_collector_command()` — the same safe status-preserving Bash helper as the OOM diagnostic:

```python
"gpu_i915_hang": (
    _oom_collector_command(
        "journalctl -b -k --no-pager 2>/dev/null",
        RE_GPU_I915_HANG,
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
- Does **not** use `|| true` — grep failure is propagated, not masked

Test-proven failure modes (7 shell-level tests pass):
- Match → rc 0, stdout non-empty
- No match → rc 0, stdout empty
- Upstream failure (rc 42) → rc 42
- grep invalid regex (rc 2) → rc 2
- Stderr redirection does not affect status
- Empty input → rc 0, stdout empty

## 5. Exact same-line trigger

Regex: `r"i915.*GPU HANG:|GPU HANG:.*i915"`

An accepted line must contain **both** `i915` **and** `GPU HANG:` on the **same line**, in either order, matched case-insensitively (both `grep -iE` and `re.search(..., re.IGNORECASE)`).

### Verified non-trigger cases (all with dedicated collector-path tests)

| # | Input | i915? | GPU HANG:? | Test method |
|---|---|---|---|---|
| 1 | `i915 ... GPU HANG:` (standard) | ✅ | ✅ | `test_hang_triggers` — **triggers** |
| 2 | `GPU HANG: ... i915` (reverse) | ✅ | ✅ | `test_reverse_order_triggers` — **triggers** |
| 3 | `[drm] GPU HANG: ecode ...` (no i915) | ❌ | ✅ | `test_non_i915_hang_no_trigger` |
| 4 | `i915 ... reset controller` (no GPU HANG:) | ✅ | ❌ | `test_i915_no_hang_no_trigger` |
| 5 | `[drm:atom_op_constant_fs ...] *ERROR*` (generic DRM) | ❌ | ❌ | `test_drm_error_no_trigger` |
| 6 | `i915 ... Resetting chip ...` | ✅ | ❌ | `test_resetting_chip_no_trigger` |
| 7 | `i915 ... GPU seems wedged ...` | ✅ | ❌ | `test_wedged_no_trigger` |
| 8 | `amdgpu ... GPU reset begin!` | ❌ | ❌ | `test_amdgpu_reset_no_trigger` |
| 9 | `nvidia: Xid ... GPU has fallen off the bus` | ❌ | ❌ | `test_nvidia_xid_no_trigger` |
| 10 | `nouveau ... mmu fault` | ❌ | ❌ | `test_nouveau_no_trigger` |
| 11 | `nouveau ... fifo: read fault ... indicates a bug` | ❌ | ❌ | `test_nouveau_hang_no_trigger` |
| 12 | (empty output) | ❌ | ❌ | `test_empty_gpu_hang_no_trigger` |

The production trigger is not broadened.

## 6. Diagnostic contract

| Property | Value |
|---|---|
| obs_id | `GPU-I915-HANG-001` |
| Category | `gpu_i915_hang` |
| FindingKind | `GPU_I915_HANG` |
| Domain | `DiagnosticDomain.HARDWARE` |
| Severity | P2 (not P1 — historical event, not guaranteed active) |
| Confidence | Certain (direct measurement, complete data, no inference) |
| Actionability | `Actionability.ACTIONABLE` |
| RecommendationIntent | `RecommendationIntent.INVESTIGATE` |
| EvidenceType | `EvidenceType.JOURNAL_EVENT` |
| Evidence strength | STRONG (regressible to MODERATE if contradictory) |
| Evidence directness | DIRECT (regressible to INFERRED if inference required) |
| Evidence completeness | COMPLETE (regressible to PARTIAL if data incomplete) |

### The Finding does NOT:
- claim hardware failure (`"Diagnostyka nie potwierdza defektu sprzętowego"`)
- claim the GPU is currently hung (`"mogło mieć charakter historyczny i może nie być już aktywne"`)
- claim the affected GPU is the active renderer (`"nie określa, czy dotknięte GPU było aktywnym rendererem"`)
- prescribe `i915.enable_guc=0` or any kernel parameter
- claim the journal entry disappears after remediation (`"czy znacznik nadal występuje"`)

## 7. Payload provenance

| Key | Value | Source |
|---|---|---|
| `hang_detected` | `true` | Inferred from non-empty match |
| `matched_lines` | first 20 matching lines | Journal output |
| `match_count` | total match count | Line count |
| `driver` | `"i915"` | Hard-coded constant |
| `driver_attribution_source` | `"in_message"` | Hard-coded constant |
| `journal_scope` | `"current_boot_kernel"` | Hard-coded constant |
| `source_query` | `"gpu_i915_hang"` | Hard-coded constant |

## 8. Exact tests added

### `TestGpuI915HangCommandStatus` — **7 tests** (unchanged)

| Test | What it verifies |
|---|---|
| `test_match_success` | `i915.*GPU HANG:` → exit 0, stdout contains match |
| `test_match_reverse_order` | `GPU HANG:.*i915` → exit 0 |
| `test_no_match` | Harmless input → exit 0, empty stdout |
| `test_upstream_failure` | Upstream rc=42 propagated |
| `test_grep_rc2_propagated` | grep rc=2 (invalid regex) propagated |
| `test_stderr_suppressed_preserves_status` | stderr redirection doesn't mask rc |
| `test_zero_length_input_no_match` | Empty input → exit 0, empty stdout |

### `TestGpuI915HangCollectorPath` — **24 tests** (+7 new negatives)

**Positive triggers** (3):
- `test_hang_triggers` — standard `i915 ... GPU HANG:` triggers
- `test_reverse_order_triggers` — `GPU HANG: ... i915` also triggers
- `test_multiple_hangs` — multiple matching lines → one diagnostic

**Negative / no-trigger** (10 total, 7 newly added in **bold**):
- `test_non_i915_hang_no_trigger` — `GPU HANG:` without i915
- `test_nouveau_no_trigger` — nouveau mmu fault
- **`test_i915_no_hang_no_trigger`** — i915 line without `GPU HANG:`
- **`test_drm_error_no_trigger`** — generic DRM `*ERROR*`
- **`test_resetting_chip_no_trigger`** — `Resetting chip` alone
- **`test_wedged_no_trigger`** — `wedged` alone
- **`test_amdgpu_reset_no_trigger`** — AMDGPU reset
- **`test_nvidia_xid_no_trigger`** — NVIDIA Xid
- **`test_nouveau_hang_no_trigger`** — nouveau hang/error
- `test_empty_gpu_hang_no_trigger` — empty output

**Command failure / edge** (4):
- `test_command_failure_safe`
- `test_timeout_safe`
- `test_payload_provenance`
- `test_output_cap`

**Pipeline** (4):
- `test_observation_mapping`
- `test_evidence_journal_event_type`
- `test_finding_gpu_i915_hang_kind`
- `test_rule_registered`

**Regression** (3):
- `test_existing_oom_unchanged`
- `test_existing_segfault_unchanged`
- `test_existing_taint_unchanged`

**Total new: 31** (7 command-status + 24 collector-path)

## 9. Focused validation

```
python3 -m pytest test_syscheck.py -k "GpuI915" -v
→ 31 passed, 395 deselected in 0.82s
```

All 31 i915-specific tests pass, including the 7 newly added negative cases.

## 10. Full repository validation

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
426 tests collected in 0.06s
```

### `python3 -m pytest -q`
```
426 passed in 1.08s
exit 0
```

## 11. Exact final test count

```
Pre-existing tests          : 395
TestGpuI915HangCommandStatus:   7
TestGpuI915HangCollectorPath:  24  (17 original + 7 new negative)
Total                       : 426
```

## 12. Files changed

```
 constants.py     |   1 +
 syscheck.py      | 170 ++++++++++++++++++
 test_syscheck.py | 531 +++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 702 insertions(+)
```

Zero deletions. No remaining trace of the reverted `_make_segfault_line()` edit.

## 13. No-go boundaries

This diagnostic does **not**:
- Detect AMDGPU, NVIDIA, Nouveau, or generic DRM hangs
- Correlate with GPU reset, wedge, or chip-reset events
- Identify the active renderer at the time of the hang
- Prescribe kernel parameters (e.g. `i915.enable_guc=0`)
- Claim hardware failure or current unavailability

## 14. Known limitations

- The regex `i915.*GPU HANG:|GPU HANG:.*i915` requires both substrings on the same **journal line**. Multi-line GPU HANG reports (where `i915` and `GPU HANG:` appear on adjacent lines) are not matched.
- The diagnostic relies on `_oom_collector_command`, which uses `journalctl -b -k` — only the current boot's kernel journal is scanned. Past boots are not inspected.
- Non-English kernel messages are not handled.
- The `driver` and `driver_attribution_source` fields are hard-coded constants, not derived from PCI ID lookup.

## 15. Git restriction confirmation

- No `git add`, `git commit`, `git push`, `git reset`, `git restore`, `git branch`, or artifact renaming was performed.
- All changes remain unstaged working-tree modifications.
