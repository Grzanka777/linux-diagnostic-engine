# LDE Iteration 46 — CLI + UX / Output Stabilization

Date: 2026-08-29
Repository: `<REDACTED-PATH>`
Checkpoint: `HEAD == origin/master == cae3464`
Baseline: `839/839 PASS`

## Scope and boundary

This iteration is limited to release-critical CLI/output stabilization:

1. make snapshot comparison rendering independent of process hash seed;
2. render expected report, snapshot, and compare destination collisions as
   concise controlled CLI errors;
3. handle malformed and nonexistent compare snapshot inputs without raw
   tracebacks;
4. add focused behavioral regressions for the above.

No diagnostics, diagnostic rules, severity/confidence semantics, schema
version, CLI design, dependencies, package artifacts, system state, or
NeuralEngine Brain state were changed. `.codex/` was not touched. No Git
mutation was performed.

## Changes

### Deterministic compare output

`SnapshotComparator._environment_changes()` now sorts the union of storage
mountpoint keys before building the rendered change mapping. Failed-unit change
groups retain their existing values and shape, but are sorted by scope and
unit names before rendering. This removes set-derived ordering variance while
preserving comparison semantics and the existing output format.

### Controlled CLI failures

The CLI now catches only expected boundary failures:

- `FileExistsError` from report, snapshot, and compare destination writes is
  rendered as one `Error:` line and exits non-zero;
- missing, unreadable, malformed, non-object, or unsupported snapshot input
  failures are rendered as controlled input errors;
- the exclusive writer still uses `O_EXCL` and `O_NOFOLLOW` and was not
  weakened.

Unexpected exceptions remain uncaught. Existing-file, symlink, and target
integrity behavior remains protected by the exclusive writer.

## Regression evidence

The new `TestIteration46CliUxStabilization` coverage adds 14 collected tests:

| Area | Fresh evidence | Result |
|---|---|---|
| Storage ordering | Direct comparison asserts sorted mountpoint keys. | PASS |
| Failed-unit ordering | Direct comparison asserts stable scope/unit ordering with unchanged values. | PASS |
| Cross-process determinism | Three child Python processes with `PYTHONHASHSEED=1`, `2`, and `3` produce byte-identical Markdown. | PASS |
| Report destination | Existing file, live symlink, and dangling symlink remain unchanged; CLI exits 1 without traceback. | PASS |
| Snapshot destination | Existing file, live symlink, and dangling symlink remain unchanged; CLI exits 1 without traceback. | PASS |
| Compare destination | Existing file and live symlink remain unchanged; CLI exits 1 without traceback. | PASS |
| Snapshot inputs | Nonexistent, syntactically malformed, non-object, and unsupported-schema inputs produce controlled non-zero errors without traceback. | PASS |

## Bounded real-process CLI audit

Disposable fixtures were created under `/tmp`. The actual command
`python3 syscheck.py compare` was exercised in separate processes:

| Case | Result |
|---|---|
| Successful compare under hash seeds 1/2/3 | Byte-identical stdout, exit 0, no traceback. |
| Existing compare output | Non-zero exit, concise `already exists` error, content retained. |
| Compare output symlink | Non-zero exit, concise `is a symlink` error, link and target retained. |
| Malformed snapshot input | Non-zero exit, `Invalid snapshot input`, no traceback. |
| Nonexistent snapshot input | Non-zero exit, `Snapshot input not found`, no traceback. |

## Validation

| Command | Result |
|---|---|
| `ruff format .` | **PASS** — one modified source/test file formatted; remaining files unchanged. |
| `ruff check .` | **PASS** — `All checks passed!` |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest --collect-only -q` | **PASS** — `853 tests collected`. |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q` | **PASS** — `853 passed in 7.99s`. |
| `git diff --check` | **PASS** — no output. |

Focused pre-gate validation also passed: `29 passed, 824 deselected` for the
new stabilization, exclusive-destination, and typed-comparison tests.

## Safety and repository state

- Initial checkpoint was `cae3464`; `git status --short` initially contained
  only `?? .codex/`.
- The required review artifact and the two source/test changes are the only
  intentional paths changed by this iteration; `.codex/` remains untouched.
- No `git add`, commit, push, reset, restore, stash, branch, merge, rebase,
  tag, or clean action was run.
- No package installation, sudo, service mutation, system configuration
  change, or diagnostic capture was run.
- `neural status` and read-only knowledge listing were performed; no Brain
  write was attempted.

## Final gates

```text
ITERATION_46_CLI_UX_STABILIZATION = PASS
COMPARE_OUTPUT_DETERMINISTIC = YES
CLI_EXPECTED_WRITE_FAILURES_CLEAN = YES
HUMAN_OUTPUT_STABLE = YES
READY_FOR_PACKAGING = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```

Next step: **Iteration 47 — Packaging + Installation + Clean-Machine Test.**
