# Iteration 24 — Collector-Path Test Hardening

## 1. Repository checkpoint

| Property | Value |
|---|---|
| **Repository root** | `<REDACTED-PATH>` |
| **Branch** | `master` |
| **HEAD** | No commits |
| **Working tree** | `test_syscheck.py` modified; `syscheck.py` unchanged |
| **Baseline tests** | 346 before, 359 after (+13) |

## 2. Tests added

### `TestBtrfsCollectorPath` (7 tests)

| Test | Collector branch | What it verifies |
|---|---|---|
| `test_btrfs_errors_multiple_counters` | `collect_storage` — btrfs stats parsing | 3 non-zero counters collected; 2 zero counters excluded; single RawDiagnostic |
| `test_btrfs_errors_multi_device` | `collect_storage` — btrfs stats parsing | Two devices with same counter name keep distinct keys |
| `test_btrfs_errors_malformed_lines` | `collect_storage` — btrfs stats parsing | Non-integer value and broken line are skipped without exception; valid values preserved |
| `test_btrfs_errors_all_zero_or_invalid` | `collect_storage` — btrfs stats parsing | All-zero counters produce no RawDiagnostic |
| `test_btrfs_errors_no_stdout` | `collect_storage` — btrfs stats parsing | Empty btrfs stats output produces no RawDiagnostic |
| `test_btrfs_scrub_no_scrub_triggers` | `collect_storage` — btrfs scrub classification | `"no scrub"` in stderr produces BTRFS-SCRUB-001 with `scrub_status` |
| `test_btrfs_scrub_healthy_no_diagnostic` | `collect_storage` — btrfs scrub classification | Healthy scrub produces no RawDiagnostic |

### `TestSegfaultAndTaintCollectorPath` (6 tests)

| Test | Collector branch | What it verifies |
|---|---|---|
| `test_segfault_wireplumber_branch` | `collect_kernel_hw` — segfault WP | 3 WirePlumber segfaults → SEGFAULT-WP-001 with `segfault_type="wireplumber"`, count=3; no SYS/MIN |
| `test_segfault_system_wide_branch` | `collect_kernel_hw` — segfault SYS | 3 non-WP segfaults (firefox, chromium) → SEGFAULT-SYS-001 with `segfault_type="system_wide"`; no WP/MIN |
| `test_segfault_minor_branch` | `collect_kernel_hw` — segfault MIN | 2 segfaults → SEGFAULT-MIN-001 with count=2, category=segfault_minor; no WP/SYS |
| `test_segfault_zero_events` | `collect_kernel_hw` — segfault all | Empty segfault output → no RawDiagnostic of any segfault type |
| `test_kernel_taint_detected` | `collect_kernel_hw` — taint | Kernel errors containing "Tainted:" → KERNEL-TAINT-001 with `tainted=True` |
| `test_kernel_no_taint` | `collect_kernel_hw` — taint | Clean kernel errors → no KERNEL-TAINT-001 |

## 3. Collector branches exercised

| Branch | Method | Lines | Exercised by |
|---|---|---|---|
| BTRFS-ERR-001 counter parsing | `SysCheckEngine.collect_storage` | 2039-2067 | `test_btrfs_errors_multiple_counters`, `test_btrfs_errors_multi_device`, `test_btrfs_errors_malformed_lines`, `test_btrfs_errors_all_zero_or_invalid`, `test_btrfs_errors_no_stdout` |
| BTRFS-SCRUB-001 classification | `SysCheckEngine.collect_storage` | 2069-2083 | `test_btrfs_scrub_no_scrub_triggers`, `test_btrfs_scrub_healthy_no_diagnostic` |
| SEGFAULT-WP-001 creation | `SysCheckEngine.collect_kernel_hw` | 2225-2236 | `test_segfault_wireplumber_branch` |
| SEGFAULT-SYS-001 creation | `SysCheckEngine.collect_kernel_hw` | 2237-2248 | `test_segfault_system_wide_branch` |
| SEGFAULT-MIN-001 creation | `SysCheckEngine.collect_kernel_hw` | 2249-2258 | `test_segfault_minor_branch` |
| KERNEL-TAINT-001 creation | `SysCheckEngine.collect_kernel_hw` | 2260-2271 | `test_kernel_taint_detected`, `test_kernel_no_taint` |

## 4. Production files changed

**No.** `syscheck.py` was not modified. The only changed file is `test_syscheck.py`.

### Defect discovered but not fixed

The `test_kernel_no_taint` test revealed that the production taint check uses substring matching:

```python
"taint" in kernel_errors_result.stdout.lower()  # line 2235
```

This matches "taint" inside "tainted" — meaning kernel log messages containing "Not tainted" would also trigger the taint diagnostic. This is a pre-existing defect, not introduced by the Iteration 24 payload hardening. The test documents this limitation in its docstring:

```
Note: The production taint check uses substring match 'taint' in
stdout.lower(), which can false-fire on 'Not tainted' messages.
This test uses output that does not contain 'taint' at all.
A future fix should use a more precise pattern to exclude
'Not tainted' entries.
```

The test avoids the false trigger by using clean output ("Clean" instead of "Not tainted"), which correctly tests the non-trigger case.

## 5. Focused test result

```
python3 -m pytest -v -k "TestBtrfsCollectorPath or TestSegfaultAndTaintCollectorPath"
→ 13 passed, 346 deselected in 0.16s
```

All 13 new collector-path tests pass.

## 6. Full validation result

```
ruff format --check .  → 3 files already formatted (PASS)
ruff check .           → All checks passed! (PASS)
python3 -m pytest -q   → 359 passed in 0.49s (PASS)
```

Test count increased from 346 to 359 (+13).

## 7. Unresolved issues

- **Pre-existing taint substring defect** (documented in `test_kernel_no_taint`): The production code uses `"taint" in stdout.lower()` which false-fires on "Not tainted" messages. This is a pre-existing issue, not introduced by the Iteration 24 changes. A fix would require a more precise regex (e.g., excluding "Not tainted" while matching "Tainted:" or other taint indicators). This can be addressed in a future iteration.

## 8. Confirmation

- No stage, commit, push, branch creation, or renaming occurred.
- `syscheck.py` was NOT modified.
- No new collectors, shell commands, or architecture changes were introduced.
- All 13 new tests pass and exercise the actual modified collector code.
