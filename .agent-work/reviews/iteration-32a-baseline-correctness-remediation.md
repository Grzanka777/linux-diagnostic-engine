# Iteration 32A — Baseline Correctness Remediation

## Scope and precondition

Authoritative audit: `.agent-work/reviews/codex-repository-wide-audit-before-iteration-32.md`.

Precondition checked before editing: `git diff --name-only` and
`git diff --cached --name-only` showed no uncommitted changes to `syscheck.py`
or `test_syscheck.py`. The pre-existing modified `AGENTS.md` and untracked
review artifacts were preserved without modification.

## Remediation

1. Removed the invalid `str.__hash__` override from frozen
   `FindingClassification`, restoring the dataclass-generated value hash.
   Added a regression test that uses equal classifications as dictionary keys.
2. Removed the duplicated, unreachable renderer block after the return in
   `format_comparison_markdown()`.
3. Completed `TestClassificationPolicyCompleteness` with production-emitted
   `oom_event`, `gpu_i915_hang`, `amdgpu_reset_fail`, and
   `gpu_nvidia_xid_79` categories.

No diagnostic extraction, diagnostic additions, kernel package portability
work, SysCheck/LDE rename, or `AGENTS.md` modification was made.

## Validation

Baseline before edits:

```text
python3 -m pytest -q
519 passed in 0.43s
```

Focused regression tests:

```text
python3 -m pytest -q test_syscheck.py -k 'TestFindingClassificationModel or TestClassificationPolicyCompleteness or format_comparison_markdown'
5 passed, 515 deselected in 0.52s
```

Final required validation:

```text
ruff format --check .
3 files already formatted

ruff check .
All checks passed!

python3 -m pytest --collect-only -q
520 tests collected in 0.07s

python3 -m pytest -q
520 passed in 0.37s
```

`git diff --check` passed. No files were staged, committed, pushed, reset,
restored, stashed, branched, rebased, merged, or tagged.

## NeuralEngine usage

neural status:

```text
Neural Engine 1.1.0; resolved NEURAL_HOME <REDACTED-PATH>;
Brain state Initialized and accessible.
```

NeuralEngine search used: NO

Reason:

The task was a fully specified mechanical remediation. Current repository
source, tests, Git state, and the authoritative audit determined the allowed
changes; historical records could not materially affect the implementation.

Brain writes: NONE
