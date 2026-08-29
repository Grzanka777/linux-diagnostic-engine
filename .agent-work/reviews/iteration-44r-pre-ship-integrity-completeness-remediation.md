# Iteration 44R — Pre-Ship Integrity & Completeness Remediation

Date: 2026-08-29
Repository checkpoint: `HEAD == origin/master == 6aa43a1` before remediation
Baseline: `826/826 PASS`

## Scope

Closed all findings I44-01 through I44-08 within the frozen feature set.
No new diagnostics, no architecture rewrite, and no real-machine E2E were
introduced. Iteration 37A/37B bounded subprocess behavior remains covered by
the existing suite and was not weakened.

## Remediation disposition

| Finding | Disposition | Evidence |
|---|---|---|
| I44-01 | PASS | Storage source IDs preserve the historical root IDs and add deterministic, injective mount-specific suffixes for other qualifying mounts. Multiple critical mounts now produce unique raw, observation, and finding IDs. |
| I44-02 | PASS | Every bounded current-boot query records an explicit non-authoritative restriction when `CmdResult.truncated` is true. A truncated no-match result does not imply absence of an event. |
| I44-03 | PASS | Btrfs, systemd, boot, kernel-count, and storage raw producers use the common result-to-raw path. Truncation reaches observations, confidence, and Evidence completeness. |
| I44-04 | PASS | The `kernel_errors` query no longer applies `tail -50`; the bounded capture marker remains authoritative and older retained-prefix taint matches are preserved. |
| I44-05 | PASS | Snapshots now persist Finding evidence references, Evidence objects, RawDiagnostic objects, Observation raw references, and validation of the complete reference chain. Missing lineage fields remain optional for legacy schema-3 snapshots. |
| I44-06 | PASS | Kernel taint interpretation is descriptive and explicitly leaves the cause unresolved; unsupported out-of-tree-module and open-driver claims were removed. |
| I44-07 | PASS | Btrfs scrub classification distinguishes `scrub_inactive` from `no_scrub`/no-history. Inactive status produces informational report text without a never-run Finding. |
| I44-08 | PASS | All collector RawDiagnostic creation is centralized through the CmdResult helper, carrying `collected_at`, command/status provenance, and truncation metadata. Snapshot JSON round-trip preserves the metadata. |

## Changed files

- `syscheck.py`
  - centralized CmdResult-to-RawDiagnostic metadata propagation;
  - deterministic mount-specific storage IDs;
  - truncation restrictions and legacy completeness propagation;
  - taint query tail removal and descriptive taint wording support;
  - Btrfs scrub semantic split;
  - typed Evidence/RawDiagnostic snapshot persistence and lineage validation;
  - recommendation object conversion needed for runtime snapshot round-trip.
- `diagnostic_rules.py`
  - mount-safe storage Finding IDs;
  - generic kernel taint interpretation/remediation;
  - inactive Btrfs scrub suppression and no-history title.
- `test_syscheck.py`
  - direct regressions for I44-01 through I44-08;
  - legacy schema-3 snapshot compatibility coverage;
  - final suite expanded from 826 to 839 tests.

Required artifact created:
`.agent-work/reviews/iteration-44r-pre-ship-integrity-completeness-remediation.md`

## Validation

Exact required command:

```text
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q
839 passed in 7.64s
```

Additional checks:

```text
ruff check .
All checks passed!

ruff format --check .
4 files already formatted

git diff --check
PASS
```

Focused 44R regression run:

```text
12 passed
```

The focused run covered the eight named finding regressions plus the
parameterized legacy completeness and legacy snapshot compatibility cases.

`mypy syscheck.py diagnostic_rules.py` still reports 11 pre-existing errors in
the extracted rule-engine result narrowing and existing severity/comprehension
typing. The new SnapshotBuilder Optional defaults introduced no remaining
MyPy errors and no MyPy fixes outside the 44R scope were made.

## Safety and boundary checks

- `.codex/` was not touched; it remains the allowed unrelated untracked path.
- No Git add, commit, push, merge, reset, clean, or remote mutation was run.
- No NeuralEngine Brain write was performed.
- No production or real-machine diagnostic capture was run.
- No new diagnostic family or provider was added.
- The next step is Iteration 44V re-audit; do not advance directly to
  real-machine E2E.

```text
ITERATION_44R_REMEDIATION = PASS
READY_FOR_REAUDIT = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```
