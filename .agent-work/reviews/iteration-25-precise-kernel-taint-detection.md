# Iteration 25: Precise Kernel Taint Detection

## 1. Repository Checkpoint

```
Branch:  master
Working tree: clean (before implementation)
Recent commits (git log -3 --oneline):
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

Checkpoint matches expected state. No repair needed.

## 2. Root Cause

In `syscheck.py` `collect_kernel_hw()`, kernel taint detection used broad substring matching:

```python
"taint" in kernel_errors_result.stdout.lower()
```

This matches any occurrence of the substring `taint` anywhere in the text, causing false positives on:
- `Not tainted`
- `Kernel is not tainted`
- `untainted`
- Any incidental word containing the characters `taint`

The Linux kernel always emits its taint marker as `Tainted:` (capital T, colon, whitespace) via `print_tainted()`. The genuine marker is a specific token, not a general substring.

## 3. Exact Production Change

**File:** `syscheck.py` (lines 2260–2271)

**Before:**
```python
# Sprawdź taint
if (
    kernel_errors_result.is_ok()
    and "taint" in kernel_errors_result.stdout.lower()
):
```

**After:**
```python
# Sprawdź taint — używamy precyzyjnego wzorca 'Tainted:' zamiast
# substring match by uniknąć false positives na 'Not tainted' itp.
if (
    kernel_errors_result.is_ok()
    and re.search(r"\bTainted:\s", kernel_errors_result.stdout, re.IGNORECASE)
):
```

The regex `\bTainted:\s` with `re.IGNORECASE` matches:
- Word boundary before `Tainted:`
- The literal marker `Tainted:` (case-insensitive)
- A whitespace character following the colon (prevents matching `Tainted:` as a substring of something like `TaintedXXX`)

This is identical in intent to matching the kernel's `Tainted:` marker but rejects negative phrases like `Not tainted`, `Kernel is not tainted`, and `untainted`.

## 4. Tests Added or Changed

**File:** `test_syscheck.py` — five new test methods added to the existing `TestSegfaultAndTaintCollectorPath` class:

| Test Method | Coverage |
|---|---|
| `test_taint_not_tainted_negative` | `Not tainted` produces no KERNEL-TAINT-001 |
| `test_taint_kernel_is_not_tainted_negative` | `Kernel is not tainted` produces no KERNEL-TAINT-001 |
| `test_taint_untainted_negative` | Incidental substring `untainted` produces no KERNEL-TAINT-001 |
| `test_taint_multiple_positive_no_duplicate` | Multiple `Tainted:` lines produce exactly one KERNEL-TAINT-001 |
| `test_segfault_branches_unaffected_by_taint_change` | Existing segfault-WP branch unaffected by taint fix; `Not tainted` in kernel_errors does not cross-contaminate |

The existing `test_kernel_no_taint` had its docstring cleaned up (limitation note removed since the fix addresses it).

No existing tests were removed or modified in behavior. No new test classes or imports were added.

## 5. Positive and Negative Matching Cases

### Positive (trigger KERNEL-TAINT-001):

| Input | Match |
|---|---|
| `kernel: Tainted: G        W` | `Tainted: ` matched by `\bTainted:\s` |
| `kernel: CPU: 4 PID: 123 Comm: foo Tainted: P           OE` | `Tainted: ` matched after word boundary |

### Negative (do NOT trigger KERNEL-TAINT-001):

| Input | Why no match |
|---|---|
| `kernel: Not tainted` | Contains `tainted`, not `Tainted:` |
| `kernel: Kernel is not tainted` | Contains `tainted`, not `Tainted:` |
| `filesystem was untainted after reboot` | Contains `untainted`, not `Tainted:` |
| `kernel: CPU: 0 PID: 1 Comm: swapper Clean` | No match at all |

## 6. Diagnostic Contract Unchanged

| Property | Value |
|---|---|
| diagnostic ID | `KERNEL-TAINT-001` |
| category | `tainted` |
| severity | `P2` |
| confidence | Derived from observation flags unchanged |
| observation mapping | `tainted` → `KERNEL/KERNEL_TAINT/CONDITIONAL/MONITOR` |
| rule mapping | `KernelTaintRule` unchanged |
| recommendation | Unchanged |
| EvidenceBuilder | Unchanged |
| collector command set | Unchanged |
| shell commands | Unchanged |
| CLI interface | Unchanged |
| **RawDiagnostic payload** | **`{"tainted": True}` — confirmed identical** |
| Finding title | `"Kernel tainted"` — unchanged |

The production change replaces only the detection predicate. The downstream pipeline (RawDiagnostic → Observation → KernelTaintRule → Finding → Evidence) is untouched.

## 7. Focused Test Result

```
python3 -m pytest -v -k "Taint or taint"
...
40 passed, 324 deselected in 0.27s
```

All 40 taint-related tests pass, including:
- 26 existing `TestKernelTaintRuleEvidence` and `TestKernelTaintEngineIntegration` tests
- 1 existing `TestEvidencePayloadHardening::test_taint_payload_tainted_in_evidence`
- 8 existing `TestSegfaultAndTaintCollectorPath` tests
- 5 new regression tests

## 8. Full Validation Results

### Ruff format
```
ruff format --check .
3 files already formatted
```

### Ruff check
```
ruff check .
All checks passed!
```

### Full pytest suite
```
python3 -m pytest -q
...
364 passed in 0.65s
```

All 364 tests pass, no regression.

## 9. Files Changed

| File | Change |
|---|---|
| `syscheck.py` | 1 production line changed (substring → regex), 2 comment lines added |
| `test_syscheck.py` | 5 new test methods added; formatting normalized by ruff |

No other files touched.

## 10. Unresolved Issues

None. The fix is minimal, deterministic, and addresses all specified positive and negative cases.

## 11. Git Restrictions Confirmed

- ❌ No `git add` / staging
- ❌ No `git commit`
- ❌ No `git push`
- ❌ No `git reset`
- ❌ No `git restore`
- ❌ No branch creation
- ❌ No artifact renaming
- ❌ No history rewrite

All changes are unstaged file edits as required.
