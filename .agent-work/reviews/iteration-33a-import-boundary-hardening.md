# Iteration 33A — Import-Boundary Hardening

## Verdict

PASS

## Checkpoint

Started from the accepted Iteration 33 worktree with 522 passing tests. The
existing unstaged Iteration 32/33 files were preserved. No production module,
`AGENTS.md`, or Git publication/history state was modified.

## Changed paths

- `test_syscheck.py`
- `.agent-work/reviews/iteration-33a-import-boundary-hardening.md`

## Tests added

Exactly three focused regression tests in `TestDiagnosticRuleImportBoundary`:

1. fresh-process `diagnostic_rules`-first import, asserting that `syscheck` is
   not loaded until explicitly imported and that default-engine construction
   then works;
2. fresh-process `syscheck`-first import, asserting that default-engine
   construction works;
3. complete identity check of all 27 public diagnostic-rule runtime symbols:
   `syscheck.Symbol is diagnostic_rules.Symbol`.

The subprocess tests set `PYTHONDONTWRITEBYTECODE=1` and use the repository
directory as their working directory, so they test real fresh interpreter
imports without writing bytecode artifacts.

## Validation

- focused boundary tests: PASS (3 passed)
- `ruff format --check .`: PASS (4 files already formatted)
- `ruff check .`: PASS
- `python3 -m pytest --collect-only -q`: PASS (525 tests collected)
- `python3 -m pytest -q`: PASS (525 passed)
- `git diff --check`: PASS

## Diff stat and diff check

The tracked worktree diff includes pre-existing Iteration 32 baseline changes
in `AGENTS.md`, `syscheck.py`, and `test_syscheck.py`. This slice adds only the
three boundary tests to `test_syscheck.py` and this untracked review artifact.
`git diff --check` passed.

## Per-file hunk summary

- `test_syscheck.py`: adds one private subprocess helper and exactly three
  boundary regression tests; no existing test behavior was changed.
- Review file: records scope and final validation evidence.

## Scope audit

- No production code was modified.
- No diagnostic rule behavior, public symbol, CLI, collector, evidence,
  recommendation, report, or snapshot behavior was changed.
- No stage, commit, push, reset, restore, stash, checkout, branch, rebase,
  merge, or tag operation was performed.

## Blockers or deviations

None. The new tests did not reveal a production defect.

## NeuralEngine usage

neural status:
Initialized Brain at `<REDACTED-PATH>` via
`NEURAL_HOME` override.

NeuralEngine search used: NO

Reason:
The exact boundary contract, source modules, and current test suite determine
this narrowly scoped regression-test task; no historical record was needed.

Brain writes:
NONE
