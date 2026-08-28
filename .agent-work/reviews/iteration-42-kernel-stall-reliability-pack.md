# Iteration 42 — Kernel Stall & Scheduler Reliability Pack Review

## Verdict

PASS — Implemented four deterministic current-boot kernel diagnostics:
1. `KERNEL-SOFT-LOCKUP-001` (category `kernel_soft_lockup`, `FindingKind.KERNEL_SOFT_LOCKUP`, severity P1) detects explicit kernel watchdog soft lockup events.
2. `KERNEL-HARD-LOCKUP-001` (category `kernel_hard_lockup`, `FindingKind.KERNEL_HARD_LOCKUP`, severity P1) detects explicit watchdog / NMI hard lockup events.
3. `KERNEL-HUNG-TASK-001` (category `kernel_hung_task`, `FindingKind.KERNEL_HUNG_TASK`, severity P2) detects explicit hung task events (`task ... blocked for more than N seconds`).
4. `KERNEL-RCU-STALL-001` (category `kernel_rcu_stall`, `FindingKind.KERNEL_RCU_STALL`, severity P1) detects explicit kernel RCU stall and starvation detector messages.

A single shared bounded, status-aware current-boot kernel journal capture (`kernel_stall_reliability`) queries events for all four families simultaneously while strictly preserving truncation, completeness, and security semantics. The pack strictly rejects generic watchdog/lockup/blocked/stall text, userspace messages, normal boot RCU initialization, and unrelated existing LDE diagnostics. At most one RawDiagnostic and one DiagnosticRule is emitted per family per pass, while independent valid families coexist cleanly without mutual interference. All diagnostics adhere to strict non-causal language without root-cause attribution.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Baseline supplied for this iteration: 715 tests passing (`HEAD == origin/master == a3379b7`).
- Final suite: 770 tests collected; 770 tests passing (55 new focused test cases collected; within 40–60 target range).
- No staging, committing, pushing, resetting, restoring, stashing, checking out, branching, rebasing, merging, tagging, or cleaning operation was performed. Unstaged changes preserved; `.codex/` untouched.

## Contract Audit

| Contract item | Evidence | Result |
| --- | --- | --- |
| Diagnostic IDs | `KERNEL-SOFT-LOCKUP-001`, `KERNEL-HARD-LOCKUP-001`, `KERNEL-HUNG-TASK-001`, `KERNEL-RCU-STALL-001` | PASS |
| Categories & FindingKinds | `kernel_soft_lockup` (`KERNEL_SOFT_LOCKUP`), `kernel_hard_lockup` (`KERNEL_HARD_LOCKUP`), `kernel_hung_task` (`KERNEL_HUNG_TASK`), `kernel_rcu_stall` (`KERNEL_RCU_STALL`) | PASS |
| Explicit triggers | Watchdog soft lockup CPU stuck, NMI/watchdog hard lockup, hung task blocked > N seconds, RCU stall/starvation detector lines | PASS |
| False positive rejection | Strictly rejects generic watchdog/lockup/blocked/stall keywords, userspace messages, normal boot RCU announcements/initialization, and existing LDE diagnostics (panic/oops, MCE, AER, NVMe, FS I/O, thermal throttle, segfaults) | PASS |
| Severity mapping | Soft lockup (P1), Hard lockup (P1), Hung task (P2), RCU stall (P1) | PASS |
| Shared status-aware journal collector | One shared task `"kernel_stall_reliability"` via bounded `_oom_collector_command("journalctl -b -k --no-pager 2>/dev/null", RE_KERNEL_STALL_RELIABILITY)` | PASS |
| Truncation / completeness | Propagates `capture_truncated` → `data_complete=False` → `completeness=PARTIAL` across all 4 families | PASS |
| Non-causal wording | All findings report recorded journal events without attributing root cause to specific hardware, faulty modules, or userspace workloads | PASS |
| Architecture & runtime seam | Registered in `DiagnosticRuleRegistry`, re-exported via `syscheck`, typed classification policy (`DiagnosticDomain.KERNEL`, `Actionability.ACTIONABLE`, `RecommendationIntent.INVESTIGATE`) | PASS |
| Coexistence | Independent valid families may coexist within the same collection pass | PASS |

## Changed Paths

- `constants.py` — Added `RE_KERNEL_SOFT_LOCKUP`, `RE_KERNEL_HARD_LOCKUP`, `RE_KERNEL_HUNG_TASK`, `RE_KERNEL_RCU_STALL`, and unified shared regex `RE_KERNEL_STALL_RELIABILITY`.
- `syscheck.py` — Added `FindingKind` members, classification policies, `EvidenceBuilder` branches, shared capture task in `collect_kernel_hw`, RawDiagnostic extractions, Observation mappings, and rule re-exports.
- `diagnostic_rules.py` — Implemented `KernelSoftLockupRule`, `KernelHardLockupRule`, `KernelHungTaskRule`, and `KernelRcuStallRule`; registered all four in `build_default_rule_engine()`.
- `test_syscheck.py` — Added 55 new test cases (4 in `TestCaptureCompleteness`, 1 in re-exports test, 50 in `TestKernelStallReliabilityPack`).
- `.agent-work/reviews/iteration-42-kernel-stall-reliability-pack.md` — this review.

## Per-File Summary

- `constants.py`:
  - `RE_KERNEL_SOFT_LOCKUP`: matches `watchdog: BUG: soft lockup - CPU#<N> stuck for <N>s!`.
  - `RE_KERNEL_HARD_LOCKUP`: matches `Watchdog detected hard LOCKUP` and `BUG: hard LOCKUP`.
  - `RE_KERNEL_HUNG_TASK`: matches `task ... blocked for more than <N> seconds`.
  - `RE_KERNEL_RCU_STALL`: matches `rcu... detected stalls on CPUs/tasks:` and `kthread starved`.
  - `RE_KERNEL_STALL_RELIABILITY`: combines all 4 patterns into a single expression for shared bounded journal capture.
- `syscheck.py`:
  - Defined `FindingKind.KERNEL_SOFT_LOCKUP = "kernel_soft_lockup"`, `KERNEL_HARD_LOCKUP = "kernel_hard_lockup"`, `KERNEL_HUNG_TASK = "kernel_hung_task"`, and `KERNEL_RCU_STALL = "kernel_rcu_stall"`.
  - Added classification policy mappings for all 4 categories to `DiagnosticDomain.KERNEL`, `Actionability.ACTIONABLE`, `RecommendationIntent.INVESTIGATE`.
  - Implemented `EvidenceBuilder` branches emitting `EvidenceType.JOURNAL_EVENT` with completeness propagation.
  - Added shared task `"kernel_stall_reliability"` to `tasks_cmd` in `collect_kernel_hw()`.
  - Extracted individual RawDiagnostics guarded by `is_ok()` and stdout content.
  - Mapped raw entries to Observations in `_raw_to_observation()`.
  - Re-exported the four rule classes from `diagnostic_rules`.
- `diagnostic_rules.py`:
  - Implemented `KernelSoftLockupRule` (`RULE-KERNEL-SOFT-LOCKUP`, P1).
  - Implemented `KernelHardLockupRule` (`RULE-KERNEL-HARD-LOCKUP`, P1).
  - Implemented `KernelHungTaskRule` (`RULE-KERNEL-HUNG-TASK`, P2).
  - Implemented `KernelRcuStallRule` (`RULE-KERNEL-RCU-STALL`, P1).
  - Registered all four rules in `build_default_rule_engine()`.
- `test_syscheck.py`:
  - Extended `TestCaptureCompleteness` with the four new categories.
  - Added `TestKernelStallReliabilityPack` covering positive detection, generic/userspace rejection, normal RCU boot rejection, unrelated diagnostic rejection, individual collector runs, coexistence in shared capture, failure/empty handling, observation/evidence/finding contracts, and isolation from other diagnostic domains.

## Validation Commands and Results

- `ruff check .` — PASS (`All checks passed!`).
- `ruff format --check .` — PASS (`4 files already formatted`).
- `python3 -m pytest --collect-only -q` — PASS (`770 tests collected`).
- `pytest` — PASS (`770 passed in 4.11s`).
- `git diff --check` — PASS (clean, no whitespace or formatting errors).
- `git diff --cached --quiet` — PASS (no staged changes).

## Scope Audit

- In scope: Four deterministic current-boot kernel stall & scheduler reliability diagnostics, single shared journal collection pass, complete runtime integration, comprehensive test suite (55 new collected tests).
- Excluded: No root cause attribution, no invasive system actions, no Git publication, staging, or committing.

## NeuralEngine Usage

- `neural status`:
  Initialized Brain resolved through `NEURAL_HOME` at `<REDACTED-PATH>`; command exited 0.
- NeuralEngine search used: YES (searched "kernel stall", listed knowledge records).
- Outcome: Historical records consulted. Current repository authority and explicit user specification were controlling.
- Brain writes: NONE.
