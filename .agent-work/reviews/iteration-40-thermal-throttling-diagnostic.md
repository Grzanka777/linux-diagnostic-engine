# Iteration 40 — Thermal Throttling Diagnostic Review

## Verdict

PASS — `HW-THERMAL-THROTTLE-001` deterministically detects explicit current-boot kernel thermal-throttling events. Matches explicit thermal threshold + throttling kernel messages and maps to preferred severity P2 (medium). The diagnostic strictly rejects temperature-only readings, thermal initialization, fan/cooling device registrations, generic throttling, power/current-limit-only throttling, userspace logs, and unrelated diagnostic families. It records events without inferring cooling failure, bad thermal paste, blocked airflow, fan failure, BIOS defects, CPU damage, current throttling, or sustained performance loss.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Baseline supplied for this iteration: 668 tests passing (`HEAD == origin/master == 0f58d6e`).
- Final suite: 691 tests collected; 691 tests passing (23 new focused test cases collected).
- No staging, committing, pushing, resetting, restoring, stashing, checking out, branching, rebasing, merging, tagging, or cleaning operation was performed. Unstaged changes preserved; `.codex/` untouched.

## Contract Audit

| Contract item | Evidence | Result |
| --- | --- | --- |
| Diagnostic ID | `HW-THERMAL-THROTTLE-001` across Raw, Observation, Finding | PASS |
| Category & FindingKind | `category="hardware_thermal_throttling"`, `FindingKind.HARDWARE_THERMAL_THROTTLING` | PASS |
| Explicit triggers | Matches `Core temperature above threshold, cpu clock throttled`, `Package temperature above threshold, cpu clock throttled`, `critical temperature threshold reached, cpu clock throttled`, `temperature above thermal threshold, throttling CPU` | PASS |
| False positive rejection | Strictly rejects temperature-only, thermal init, cooling device registration, clearing events (`normal`), generic throttle, power/current limit throttling, userspace logs, AER, MCE/EDAC, NVMe, FS I/O, GPU hang, OOM | PASS |
| Severity mapping | Deterministic P2 (medium) for hardware thermal throttling events | PASS |
| Status-aware journal collector | Current-boot `journalctl -b -k` through `_oom_collector_command`; `is_ok()` guards emission | PASS |
| Truncation / completeness | Propagates `capture_truncated` → `data_complete=False` → `completeness=PARTIAL` | PASS |
| Non-causal wording | Finding explicitly avoids inferring cooling failure, bad paste, blocked airflow, fan failure, BIOS defect, CPU damage, current throttling, or sustained performance loss | PASS |
| Architecture & runtime seam | Registered in `DiagnosticRuleRegistry`, re-exported via `syscheck`, typed classification policy | PASS |

## Changed Paths

- `constants.py` — `RE_HARDWARE_THERMAL_THROTTLE` regex constant matching explicit thermal threshold + throttling kernel lines.
- `syscheck.py` — `FindingKind.HARDWARE_THERMAL_THROTTLING`, classification policy entry, `EvidenceBuilder` branch, collector task in `collect_kernel_hw`, `RawDiagnostic` emission, `_raw_to_observation` mapping, and rule re-export.
- `diagnostic_rules.py` — `HardwareThermalThrottlingRule` class definition and registration in `build_default_rule_engine`.
- `test_syscheck.py` — `TestHardwareThermalThrottlingDiagnostic` test suite (22 test cases) + `TestCaptureCompleteness` parametrization (+1 test case) + import boundary verification.
- `.agent-work/reviews/iteration-40-thermal-throttling-diagnostic.md` — this review.

## Per-File Summary

- `constants.py`:
  - Defined `RE_HARDWARE_THERMAL_THROTTLE` requiring both thermal/temperature threshold and throttling (`Core/Package temperature above threshold, cpu clock throttled`, `critical temperature threshold reached... throttl*`).
- `syscheck.py`:
  - Added `FindingKind.HARDWARE_THERMAL_THROTTLING = "hardware_thermal_throttling"`.
  - Classified `hardware_thermal_throttling` under `DiagnosticDomain.HARDWARE` as `Actionability.ACTIONABLE` and `RecommendationIntent.INVESTIGATE`.
  - Added `EvidenceBuilder` branch emitting `EvidenceType.JOURNAL_EVENT` with completeness propagation.
  - Added `"hardware_thermal_throttling"` collector task using `_oom_collector_command` with current-boot kernel journal query (`journalctl -b -k --no-pager 2>/dev/null`).
  - Added `RawDiagnostic` emission guarded by `is_ok()`, non-empty stdout, and regex match.
  - Added `Observation` mapping in `_raw_to_observation()`.
  - Re-exported `HardwareThermalThrottlingRule`.
- `diagnostic_rules.py`:
  - Implemented `HardwareThermalThrottlingRule` evaluating `Observation` to `Finding` (P2 severity) with non-causal interpretation.
  - Registered `HardwareThermalThrottlingRule` in `build_default_rule_engine()`.
- `test_syscheck.py`:
  - Added `TestHardwareThermalThrottlingDiagnostic` validating explicit patterns, false positive rejection (temperature-only, init, normal/clearing, fan registration, generic throttle, power/current limit throttling), P2 severity, command failure safety, observation/evidence/finding pipeline contract, rule registration/re-export, and isolation from other subsystems.
  - Updated `TestCaptureCompleteness` and `TestDiagnosticRuleImportBoundary`.

## Validation Commands and Results

- `ruff check .` — PASS (`All checks passed!`).
- `ruff format --check .` — PASS (`4 files already formatted`).
- `python3 -m pytest --collect-only -q` — PASS (`691 tests collected`).
- `python3 -m pytest -q` — PASS (`691 passed in 6.78s`).
- `git diff --check` — PASS (clean, no whitespace or formatting issues).
- `git diff --cached --quiet` — PASS (no staged changes).

## Scope Audit

- In scope: Single deterministic kernel thermal-throttling diagnostic, runtime integration, and comprehensive focused tests.
- Excluded: No root cause attribution, no claims of permanent hardware failure/cooling defect/paste issues, no changes to unrelated collectors, no Git publication or history modification.

## NeuralEngine Usage

- `neural status`:
  Initialized Brain resolved through `NEURAL_HOME` at `<REDACTED-PATH>`; command exited 0.
- NeuralEngine search used: YES (searched "thermal throttle", "diagnostic", listed records).
- Outcome:
  Historical records consulted (persistence/provenance rules). Current repository source, rules runtime, and explicit user specification were controlling.
- Brain writes: NONE.
