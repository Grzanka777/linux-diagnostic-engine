# Iteration 35A — PCIe/NVMe control-flow fix

## Verdict

PASS. The PCIe AER diagnostic append now executes only after PCIe AER
severities are established. The NVMe branch emits only its own diagnostic.

## Checkpoint

Working tree inspected after the Iteration 34 AER and Iteration 35 NVMe work.
The baseline required suite exposed the defect: 11 failures, including
`UnboundLocalError` for NVMe-only input and missing AER diagnostics for
AER-only input.

## Changed paths

- `syscheck.py`
- `test_syscheck.py`
- `.agent-work/reviews/iteration-35a-fix-pcie-nvme-control-flow.md`

## Per-file hunk summary

- `syscheck.py`: moved the unchanged `PCIE-AER-001` raw-diagnostic append into
  the successful PCIe AER severity branch; removed it from the NVMe branch.
- `test_syscheck.py`: extended the collector fixture with an independent NVMe
  result and added NVMe-only, AER-only, and combined-input regressions.
- This review: records scope and validation evidence.

## Validation

- `ruff format --check .` — PASS (`4 files already formatted`)
- `ruff check .` — PASS
- `python3 -m pytest --collect-only -q` — PASS (`570 tests collected`)
- `python3 -m pytest -q` — PASS (`570 passed in 0.54s`)
- `git diff --check` — PASS
- Focused PCIe/NVMe regressions — PASS (`6 passed, 36 deselected`)

## Diff stat and check

The pre-existing dirty worktree makes the repository-wide diff stat unsuitable
as an Iteration 35A-only measure: `814 insertions(+), 1002 deletions(-)` across
`AGENTS.md`, `constants.py`, `syscheck.py`, and `test_syscheck.py`.
Its 2033-line full diff was inspected locally and has SHA-256
`a5298a8dd71808515c54c51d330a9a4ecc46ee774d9cf3e3dc1071db650d2053`.
`git diff --check` passes.

## Scope audit

Only the allowed code, tests, and this review artifact were changed for this
iteration. No broader NVMe behavior, rules, schemas, CLI behavior, or Git
state operations were added. Existing unrelated working-tree changes remain
untouched.

## Blockers or deviations

None.
