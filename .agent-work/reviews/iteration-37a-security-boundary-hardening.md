# Iteration 37A — Security Boundary Hardening

## Verdict

**FIXED — the three requested security-boundary hardenings are implemented and verified.**

The patch is limited to bounded subprocess capture, source-status integrity, and
exclusive report/snapshot/compare destination creation. No PATH pinning, Markdown
escaping, sandboxing, privilege separation, SECURITY.md, or architecture rewrite
was added.

## Checkpoint

- Authoritative input: `.agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md`.
- The stated 571-test baseline did not reproduce in the live dirty worktree: the
  pre-edit full run was 426 passed / 145 failed because a pre-existing dirty
  `syscheck.py` state lacked `import sys`, causing `SysCheckEngine.log_section()`
  `NameError`. The import was restored as the minimum baseline-compatibility
  correction required for meaningful validation.
- The final suite contains 594 tests: the original 571 plus 23 focused hardening
  regressions.

## Implemented boundary controls

### Subprocess capture

`run_cmd()` now drains stdout and stderr concurrently as bytes, retains at most
`TRUNCATE_NORMAL` bytes per stream while the command is producing output, and
marks `CmdResult.truncated`. Exit codes remain authoritative; timeout returns
`-2`, preserves captured partial output, and terminates the process group. Fallback
rendering exposes retained partial stdout/stderr and timeout/truncation markers.

Kernel diagnostic payloads carry capture truncation into `Observation.data_complete`,
so downstream evidence becomes partial and confidence cannot remain falsely certain.
The legacy string-returning `cmd_ok()` path now uses the same fallback renderer, so
parallel base/resource/user-environment collectors retain truncation and timeout
markers instead of silently presenting incomplete output as complete.

### Source-status integrity

Journal filters use `PIPESTATUS`: upstream failures and grep errors remain failures,
while grep’s legitimate no-match status is normalized to success. Authentication
counting emits `0` only after a successful source query. The global rc=1/empty
success mapping was removed; package orphan handling now requires empty stderr too.
The kernel-package, governor, kernel/firmware/segfault, graphics, and authentication
pipelines no longer mask source failures.

### Destination writes

Report, snapshot, and compare output all use `_write_new_text()`, which rejects an
existing destination (including final-component symlinks), uses `O_EXCL` and
`O_NOFOLLOW`, and never replaces an existing file. Failed-write cleanup compares the
opened inode before unlinking, avoiding deletion of a raced replacement.

The requested boundary is the final path component. Parent-directory symlink
resolution remains unchanged and is intentionally outside the user’s explicit
final-component scope.

## Changed paths

Task changes are confined to:

- `constants.py` — status-preserving Arch kernel package pipeline.
- `syscheck.py` — bounded command runner, status-aware journal helpers, incomplete
  evidence propagation, and exclusive report/snapshot/compare writes; plus the
  pre-existing missing-`sys` baseline correction described above.
- `test_syscheck.py` — 23 focused regressions for stream limits, timeout partial
  output, strict rc=1 behavior, journal source/no-match semantics, incomplete
  observations, and regular/symlink destination rejection.
- `.agent-work/reviews/iteration-37a-security-boundary-hardening.md` — this review.

Existing dirty paths and prior review artifacts were preserved. No staging, commit,
push, reset, restore, stash, checkout, branch, rebase, merge, tag, or clean action
was performed.

## Validation

| Check | Result |
|---|---|
| Focused hardening tests | **23 passed**, 571 deselected |
| `ruff format --check .` | **PASS** — 4 files already formatted |
| `ruff check .` | **PASS** |
| `python3 -m pytest --collect-only -q` | **PASS** — 594 tests collected |
| `python3 -m pytest -q` | **PASS** — 594 passed |
| `git diff --check` | **PASS** |

The current worktree includes substantial pre-existing Iteration 31–35 changes.
For the three source/test paths, the final working-tree diff was:

```text
 constants.py     |   23 +-
 syscheck.py      | 1694 ++++++++++++++++++------------------------------------
 test_syscheck.py |  790 +++++++++++++++++++++++--
```

SHA-256 of that current three-file diff:

`149f8d459990921ae4e47eb42736cbf50a74c295a088767ba990c272a95bebb6`

### Per-file hunk summary

- `syscheck.py`: byte-bounded Popen drains and process-group timeout handling;
  fallback/incomplete markers through both `CmdResult` and `cmd_ok()`;
  status-aware journal/count helpers; replacement of masked collector pipelines;
  capture metadata on kernel diagnostics; incomplete
  observation completeness; exclusive report/snapshot/compare writes.
- `constants.py`: explicit `PIPESTATUS` handling for the Arch kernel package query.
- `test_syscheck.py`: focused command-capture, status-propagation, evidence-
  completeness, and destination collision/symlink regressions; existing snapshot
  roundtrips now use absent destinations as required by the new contract.

## Scope audit

- No changes to `AGENTS.md`, `diagnostic_rules.py`, Git metadata/history, NeuralEngine
  Brain, PATH/environment pinning, Markdown escaping, sandboxing, privilege
  separation, or unrelated remediation behavior.
- No permanent SSD/data-corruption claim or automatic remediation was introduced.
- AER-only, NVMe-only, and combined independence remains covered by the existing
  Iteration 35 regressions and passes in the final suite.

## Bypass/regression review reconciliation

A fresh read-only bypass reviewer identified stderr-only timeout visibility, a
write-cleanup race, and the legacy `cmd_ok()` metadata bypass. All three were
reproduced, fixed, and rechecked against the live candidate. The reviewer’s
parent-directory symlink observation is outside the explicit final-component-only
requirement and was not expanded into this slice.

## Blockers / deviations

No implementation blocker remains. The only deviation is the incorrect supplied
baseline count; the live pre-edit failure was diagnosed, minimally corrected, and
the final 594-test suite is green.

## NeuralEngine usage

`neural status`:

```text
Brain state: Initialized
Brain Trust state: TRUSTED_CURRENT
Resolved Neural home: <REDACTED-PATH>
```

NeuralEngine search used: YES

Queries:

- `Iteration 37 security boundary hardening`

Returned records:

- No matching knowledge found.

Exact records inspected:

- None.

Material effect:

The search added no historical constraint; it corroborated that the current
repository assessment and source/tests were the controlling evidence. No Brain
writes were performed.
