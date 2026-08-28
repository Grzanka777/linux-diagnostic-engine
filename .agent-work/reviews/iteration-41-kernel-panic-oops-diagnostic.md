# Iteration 41 — Kernel Panic / Oops Diagnostic Review

## Verdict

PASS — `KERNEL-OOPS-PANIC-001` deterministically detects explicit current-boot kernel panic, oops, and BUG events (`Kernel panic - not syncing`, `Oops:`, `kernel BUG at`, `BUG: unable to handle kernel ...`). Maps explicit kernel panic to P0 and oops/BUG events to P1, with deterministic highest-severity arbitration (P0 wins). The diagnostic strictly rejects generic panic/bug/oops/error/warning text, userspace panics, ordinary page faults, and existing LDE diagnostic families. It records events without inferring root cause, attributing fault to specific hardware/modules, or performing multi-boot crash dump reconstruction.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Baseline supplied for this iteration: 691 tests passing (`HEAD == origin/master == 1effe8c`).
- Final suite: 715 tests collected; 715 tests passing (24 new focused test cases collected).
- No staging, committing, pushing, resetting, restoring, stashing, checking out, branching, rebasing, merging, tagging, or cleaning operation was performed. Unstaged changes preserved; `.codex/` untouched.

## Contract Audit

| Contract item | Evidence | Result |
| --- | --- | --- |
| Diagnostic ID | `KERNEL-OOPS-PANIC-001` across Raw, Observation, Finding | PASS |
| Category & FindingKind | `category="kernel_oops_panic"`, `FindingKind.KERNEL_OOPS_PANIC` | PASS |
| Explicit triggers | Matches `Kernel panic - not syncing`, `Oops:`, `kernel BUG at`, `BUG: unable to handle kernel ...` | PASS |
| False positive rejection | Strictly rejects generic panic/bug/oops/error/warning text, userspace panics (Go/Rust/Python), ordinary page faults (`segfault at`, `do_page_fault`), MCE/EDAC, PCIe AER, NVMe reset, thermal throttle, FS I/O, GPU hang, OOM | PASS |
| Severity mapping | Deterministic P0 for explicit kernel panic, P1 for Oops/BUG; highest explicit severity wins | PASS |
| Status-aware journal collector | Current-boot `journalctl -b -k` through bounded `_oom_collector_command`; `is_ok()` guards emission | PASS |
| Truncation / completeness | Propagates `capture_truncated` → `data_complete=False` → `completeness=PARTIAL` | PASS |
| Non-causal wording | Finding explicitly avoids root-cause attribution to specific hardware, kernel modules, or userspace software | PASS |
| Architecture & runtime seam | Registered in `DiagnosticRuleRegistry`, re-exported via `syscheck`, typed classification policy | PASS |

## Changed Paths

- `constants.py` — `RE_KERNEL_PANIC`, `RE_KERNEL_OOPS_BUG`, and `RE_KERNEL_OOPS_PANIC` regex constants matching explicit kernel panic, oops, and BUG events.
- `syscheck.py` — `FindingKind.KERNEL_OOPS_PANIC`, classification policy entry (`DiagnosticDomain.KERNEL`, `Actionability.ACTIONABLE`, `RecommendationIntent.INVESTIGATE`), `_kernel_oops_panic_severity` helper, `EvidenceBuilder` branch, collector task in `collect_kernel_hw`, `RawDiagnostic` emission, `_raw_to_observation` mapping, and rule re-export.
- `diagnostic_rules.py` — `KernelOopsPanicRule` class definition and registration in `build_default_rule_engine`.
- `test_syscheck.py` — `TestKernelOopsPanicDiagnostic` test suite (23 test cases) + `TestCaptureCompleteness` parametrization (+1 test case) + import boundary verification.
- `.agent-work/reviews/iteration-41-kernel-panic-oops-diagnostic.md` — this review.

## Per-File Summary

- `constants.py`:
  - Defined `RE_KERNEL_PANIC` for `\bKernel panic - not syncing\b`.
  - Defined `RE_KERNEL_OOPS_BUG` for `\bOops:\s*`, `\bkernel BUG at\b`, and `\bBUG:\s*unable to handle kernel\b`.
  - Defined `RE_KERNEL_OOPS_PANIC` combining all trigger patterns.
- `syscheck.py`:
  - Added `FindingKind.KERNEL_OOPS_PANIC = "kernel_oops_panic"`.
  - Added `_kernel_oops_panic_severity()` mapping lines to P0 or P1.
  - Classified `kernel_oops_panic` under `DiagnosticDomain.KERNEL` as `Actionability.ACTIONABLE` and `RecommendationIntent.INVESTIGATE`.
  - Added `EvidenceBuilder` branch emitting `EvidenceType.JOURNAL_EVENT` with completeness propagation and severity details.
  - Added `"kernel_oops_panic"` collector task using bounded `_oom_collector_command` with current-boot kernel journal query (`journalctl -b -k --no-pager 2>/dev/null`).
  - Added `RawDiagnostic` emission guarded by `is_ok()`, non-empty stdout, and regex match with P0-precedence arbitration.
  - Added `Observation` mapping in `_raw_to_observation()`.
  - Re-exported `KernelOopsPanicRule`.
- `diagnostic_rules.py`:
  - Implemented `KernelOopsPanicRule` evaluating `Observation` to `Finding` (P0 or P1 severity) with non-causal interpretation and remediation/verification guidance.
  - Registered `KernelOopsPanicRule` in `build_default_rule_engine()`.
- `test_syscheck.py`:
  - Added `TestKernelOopsPanicDiagnostic` validating explicit patterns, false positive rejection (generic panic/bug/oops, userspace panics, ordinary page faults, soft lockup, unrelated hardware subsystems), P0/P1 severity mapping, highest-severity-wins arbitration, command failure safety, observation/evidence/finding pipeline contract, rule registration/re-export, and isolation from other subsystems.
  - Updated `TestCaptureCompleteness` and import boundary test.

## Validation Commands and Results

- `ruff check .` — PASS (`All checks passed!`).
- `ruff format --check .` — PASS (`4 files already formatted`).
- `python3 -m pytest --collect-only -q` — PASS (`715 tests collected`).
- `pytest` — PASS (`715 passed in 3.98s`).
- `git diff --check` — PASS (clean, no whitespace or formatting issues).
- `git diff --cached --quiet` — PASS (no staged changes).

## Scope Audit

- In scope: Single deterministic current-boot kernel panic/oops/BUG diagnostic, runtime integration, and comprehensive focused tests.
- Excluded: No root cause attribution, no multi-boot reconstruction, no pstore/ramoops/kdump/crash dump additions, no Git publication or staging.

## NeuralEngine Usage

- `neural status`:
  Initialized Brain resolved through `NEURAL_HOME` at `<REDACTED-PATH>`; command exited 0.
- NeuralEngine search used: YES (searched "kernel panic", "diagnostic", listed records).
- Outcome:
  Historical records consulted. Current repository authority and explicit user specification were controlling.
- Brain writes: NONE.
