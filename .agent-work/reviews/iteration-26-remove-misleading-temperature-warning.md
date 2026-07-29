# Iteration 26 — Remove Misleading Temperature Critical-Limit Warning

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   modified (2 tracked files: syscheck.py, test_syscheck.py)
Untracked:      .agent-work/reviews/deepseek-v4-flash-max-sensors-temperature-diagnostics-assessment.md
Recent commits (git log -4 --oneline):
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

All changes are limited to the two required files. No other production files
are modified.

---

## 2. Root Cause

The `collect_resources()` method in `syscheck.py` contained a display-layer
correctness defect at lines 1971–1974:

```python
if "crit=" in sensors_raw:
    self.report_lines.append(
        "⚠️ Wykryto krytyczne limity temperatur w sensors.\n\n"
    )
```

This substring match fires on **any** `sensors` output that contains the
string `crit=` — which is virtually every Linux sensor configuration (most
sensors define a critical threshold). The warning does **not** detect
threshold exceedance; it only detects threshold **definition**. As a
result, the warning appeared on every report regardless of actual
temperature state, making it meaningless and misleading.

---

## 3. Production Change

**File:** `syscheck.py`

**Action:** Removed the 4-line `crit=` warning block (the `if "crit=" in sensors_raw:`
branch).

**Lines removed:** 1971–1974 (original numbering).

**What was preserved:**
- Sensors display: `self.report_lines.append(codeblock(sensors_filtered))` (unchanged)
- Invalid-temperature filtering: `_filter_invalid_temperatures()` call (unchanged)
- Invalid-reading count note: `if sensors_raw != sensors_filtered: ... Pominięto ...` (unchanged)
- All other `collect_resources()` report lines (unchanged)

**Diff summary:**

```diff
-        if "crit=" in sensors_raw:
-            self.report_lines.append(
-                "⚠️ Wykryto krytyczne limity temperatur w sensors.\n\n"
-            )
```

---

## 4. Tests Added

**File:** `test_syscheck.py`

**New class:** `TestSensorsCollectorPath` (86 lines added)

The class follows the repository's established collector-path mocking
pattern (`patch.object(SysCheckEngine, "_parallel", return_value=...)`),
providing controlled `sensors` input to `collect_resources()` and
verifying report output.

### Test cases

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_sensors_with_crit_still_displayed` | Sensors output containing `crit=` (e.g., `Package id 0: +52.0°C (high = +100.0°C, crit = +100.0°C)`) still appears in the report. |
| 2 | `test_misleading_crit_warning_absent` | The string `"krytyczne limity"` does **not** appear in report lines when sensors contain `crit=`. |
| 3 | `test_invalid_readings_still_filtered` | Invalid `-273.3°C` readings are still removed by `_filter_invalid_temperatures()` and the `"Pominięto"` info line is still emitted. |
| 4 | `test_valid_readings_remain_visible` | Normal temperature readings (e.g., `+25.0°C`) remain in the report. |
| 5 | `test_no_raw_diagnostic_from_sensors` | No `RawDiagnostic` with a sensor/temperature category is created — confirming the data remains report-only. |

### Test design notes

- Tests avoid mocking private implementation details and instead assert
  on the observable `report_lines` output.
- The `_parallel` method is patched to return controlled dict results,
  following the same pattern used by `TestBootTimeCollector` (which
  patches `_parallel_cmd` for systemd collection).
- All five tests are collector-path tests — they exercise the actual
  `collect_resources()` method end-to-end through the mock boundary.
- No real `sensors` command, host hardware, network, sudo, or
  locale-specific output is required.

---

## 5. Focused Test Result

```
$ python3 -m pytest -v -k "TestSensorsCollectorPath"
============================= test session starts ==============================
collected 369 items / 364 deselected / 5 selected

test_syscheck.py::TestSensorsCollectorPath::test_sensors_with_crit_still_displayed PASSED
test_syscheck.py::TestSensorsCollectorPath::test_misleading_crit_warning_absent PASSED
test_syscheck.py::TestSensorsCollectorPath::test_invalid_readings_still_filtered PASSED
test_syscheck.py::TestSensorsCollectorPath::test_valid_readings_remain_visible PASSED
test_syscheck.py::TestSensorsCollectorPath::test_no_raw_diagnostic_from_sensors PASSED

====================== 5 passed, 364 deselected in 0.06s =======================
```

---

## 6. Full Validation Results

### Ruff

```
$ ruff format --check .
3 files already formatted

$ ruff check .
All checks passed!
```

### Full test suite

```
$ python3 -m pytest -q
........................................................................ [ 19%]
........................................................................ [ 39%]
........................................................................ [ 58%]
........................................................................ [ 78%]
........................................................................ [ 97%]
.........                                                                [100%]
369 passed in 0.64s
```

**Test count increased from 364 → 369** (5 new collector-path tests).

### Existing temperature regression

```
$ python3 -m pytest -v -k "TestInvalidTemperatures"
... 4 passed ...  (all existing filter tests unchanged)
```

---

## 7. Files Changed

| File | Status | Lines |
|---|---|---|
| `syscheck.py` | Modified | −5 (removed `crit=` warning block) |
| `test_syscheck.py` | Modified | +86 (new `TestSensorsCollectorPath` class) |

No other files were created, modified, or deleted.

---

## 8. Confirmation: Sensors Remain Report-Only

- No `RawDiagnostic` was introduced for sensors data.
- No `Observation`, `Evidence`, `Finding`, or `Recommendation` was added.
- No new collector or shell command was introduced.
- No threshold parser was added.
- The `test_no_raw_diagnostic_from_sensors` test explicitly confirms that
  sensors output does not enter the structured diagnostic pipeline.

**Sensors remain report-only / deferred.**

---

## 9. Confirmation: No Diagnostic Pipeline Contracts Changed

- No `FindingKind` enum values were added or modified.
- No `DiagnosticDomain` values were added or modified.
- No `EvidenceType` values were added or modified.
- No `DiagnosticRule` subclass was added or modified.
- No `FindingClassificationPolicy` entries were added or modified.
- No `_raw_to_observation()` branches were added or modified.
- No `EvidenceBuilder.build()` branches were added or modified.
- No `build_default_rule_engine()` registration was added or modified.

The diagnostic pipeline is completely unaffected by this change.

---

## 10. Unresolved Issues

None. This was a narrow, self-contained removal of a misleading report
warning. No new issues were discovered during implementation.

The corrected sensors/temperature assessment
(`deepseek-v4-flash-max-sensors-temperature-diagnostics-assessment.md`)
recommended this fix as the first step in the ordering:

```
1. Fix misleading temperature report warning  ← DONE (this iteration)
2. Keep sensors as report-only/deferred
3. Assess ZRAM/RAM pressure as next Existing Data Activation candidate
```

---

## 11. Git Restrictions Confirmed

- ✅ No `git add` / staging
- ✅ No `git commit`
- ✅ No `git push`
- ✅ No `git reset`
- ✅ No `git restore`
- ✅ No branch creation
- ✅ No artifact renaming
- ✅ No history rewrite

All changes remain unstaged in the working tree:

```
$ git status --short
 M syscheck.py
 M test_syscheck.py
```
