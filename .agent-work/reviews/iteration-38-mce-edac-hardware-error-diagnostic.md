# Iteration 38 — MCE / EDAC Hardware Error Diagnostic Review

## Verdict

PASS — `HW-MCE-EDAC-001` deterministically detects explicit current-boot kernel MCE and EDAC hardware error events. Corrected errors map to P2 (medium), while Machine Check exceptions/events and uncorrected errors map to P1 (critical). The diagnostic records events without inferring failed RAM/CPU/motherboard or asserting permanent hardware defects.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Baseline supplied for this iteration: 594 tests passing.
- Final suite: 646 tests collected; 646 tests passing.
- No staging, committing, pushing, resetting, restoring, stashing, checking out, branching, rebasing, merging, tagging, or cleaning operation was performed.

## Contract Audit

| Contract item | Evidence | Result |
| --- | --- | --- |
| Diagnostic ID | `HW-MCE-EDAC-001` across Raw, Observation, Finding | PASS |
| Category & FindingKind | `category="hardware_mce_edac_error"`, `FindingKind.HARDWARE_MCE_EDAC_ERROR` | PASS |
| Explicit MCE / EDAC triggers | Matches `mce: [Hardware Error]`, explicit Machine Check context, EDAC CE/UE/corrected/uncorrected errors | PASS |
| False positive rejection | Strictly rejects EDAC init/registration, generic mce/banks, AER, NVMe, GPU, OOM | PASS |
| Severity mapping | Corrected → P2; Machine Check / Uncorrected → P1 | PASS |
| Highest severity precedence | Multiple journal lines reduce to highest severity (P1 > P2) | PASS |
| Status-aware journal collector | Current-boot `journalctl` through `_oom_collector_command`; `is_ok()` guards emission | PASS |
| Truncation / completeness | Propagates `capture_truncated` → `data_complete=False` → `completeness=PARTIAL` | PASS |
| Non-causal wording | Finding explicitly rejects inferring failed RAM/CPU/motherboard or permanent hardware defects | PASS |
| Architecture & runtime seam | Registered in `DiagnosticRuleRegistry`, re-exported via `syscheck`, typed classification policy | PASS |

## Changed Paths

- `constants.py` — `RE_HARDWARE_MCE_EDAC` regex constant matching explicit MCE and EDAC error lines.
- `syscheck.py` — `FindingKind.HARDWARE_MCE_EDAC_ERROR`, `_hardware_mce_edac_severity`, classification policy entry, `EvidenceBuilder` branch, collector task in `collect_kernel_hw`, severity reduction & `RawDiagnostic` emission in `check_kernel_logs`, `raw_to_observations` mapping, and rule re-export.
- `diagnostic_rules.py` — `HardwareMceEdacRule` class definition and registration in `build_default_rule_engine`.
- `test_syscheck.py` — `TestHardwareMceEdacDiagnostic` test suite (18 test methods covering 51 test cases) + `TestCaptureCompleteness` parametrization + import boundary verification.
- `.agent-work/reviews/iteration-38-mce-edac-hardware-error-diagnostic.md` — this review.

## Per-File Summary

- `constants.py`:
  - Defined `RE_HARDWARE_MCE_EDAC` matching `mce:\s*\[Hardware Error\]`, `\[Hardware Error\]:.*Machine Check`, `Machine Check Exception`, `Machine check events logged`, and `EDAC` CE/UE/corrected/uncorrected lines.
- `syscheck.py`:
  - Added `FindingKind.HARDWARE_MCE_EDAC_ERROR`.
  - Added `_hardware_mce_edac_severity` helper parsing lines into `"uncorrected"` vs `"corrected"`.
  - Classified `hardware_mce_edac_error` under `DiagnosticDomain.HARDWARE` as `Actionability.ACTIONABLE` and `RecommendationIntent.INVESTIGATE`.
  - Added `EvidenceBuilder` builder emitting `EvidenceType.JOURNAL_EVENT` with completeness propagation.
  - Added `"hardware_mce_edac"` collector using `_oom_collector_command` with current-boot journal query.
  - Added severity reduction (`uncorrected` > `corrected`) in `check_kernel_logs()`.
  - Added `Observation` mapping in `raw_to_observations()`.
- `diagnostic_rules.py`:
  - Implemented `HardwareMceEdacRule` evaluating `Observation` to `Finding` (P2 for corrected, P1 for uncorrected/machine-check) with non-causal interpretation.
  - Registered `HardwareMceEdacRule` in `build_default_rule_engine()`.
- `test_syscheck.py`:
  - Added `TestHardwareMceEdacDiagnostic` validating explicit MCE/EDAC patterns, false positive rejection (EDAC driver init, generic mce banks, AER, NVMe, GPU hang/reset, OOM), deterministic severity mapping, mixed event precedence, command failure safety, observation/evidence/finding pipeline contract, rule registration/re-export, and isolation from other subsystems.
  - Updated `TestCaptureCompleteness` and `TestDiagnosticRuleImportBoundary`.

## Validation Commands and Results

- `ruff format --check .` — PASS (`4 files already formatted`).
- `ruff check .` — PASS (`All checks passed!`).
- `python3 -m pytest --collect-only -q` — PASS (`646 tests collected`).
- `python3 -m pytest -q` — PASS (`646 passed in 6.52s`).
- `git diff --check` — PASS (clean, no whitespace or formatting issues).
- `git diff --cached --quiet` — PASS (no staged changes).

## Scope Audit

- In scope: Single deterministic MCE / EDAC hardware error diagnostic, runtime integration, and comprehensive tests.
- Excluded: No root cause attribution, no permanent hardware failure claims, no changes to unrelated collectors, no Git publication or history modification.

## NeuralEngine Usage

- `neural status`:
  Initialized Brain resolved through `NEURAL_HOME` at `<REDACTED-PATH>`; command exited 0.
- NeuralEngine search used: NO
- Reason:
  Current repository source, rules runtime, and explicit user specification fully defined the required contract and patterns.
- Brain writes: NONE
