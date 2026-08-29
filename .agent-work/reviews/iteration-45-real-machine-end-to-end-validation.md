# LDE Iteration 45 — Real-Machine End-to-End Validation

Date: 2026-08-29
Repository: `<REDACTED-PATH>`
Checkpoint: `HEAD == origin/master == 1d20cd65ca214883af14045b0102a298e5a0c58c`
Baseline: `839/839 PASS`

## Scope and boundary

This was a read-only real-machine release gate on the actual CachyOS
workstation. No product code, tests, configuration, packages, services,
production data, Git history, or NeuralEngine Brain state was modified.

The only disposable outputs were created below:

`/tmp/lde-iteration45.gDPQ7T/`

The only repository artifact created was this review. `.codex/` was not
accessed or changed.

No OOM, panic, thermal, GPU, storage, or other machine fault was injected or
triggered.

## Verdict

**PASS — real-machine CLI, snapshot, lineage, compare, safety, and regression
validation completed.** The frozen feature set remains ready for the planned
CLI/UX stabilization iteration.

## Requirement-to-evidence matrix

| Requirement or risk | Fresh evidence | Result |
|---|---|---|
| Discover real CLI syntax | `python3 syscheck.py --help` exposed `run`/`diagnose` and `compare`; `run` options include `--output-dir`, `--quiet`, `--full`, and `--snapshot`; `compare` accepts two snapshots and `--output`. | PASS |
| Normal real diagnostic/report run | Two real `run` invocations completed with exit `0` in 2.28 s and 1.78 s. Each produced a Markdown report and schema-3 JSON snapshot in the disposable directory. | PASS |
| Finding → Evidence → Observation → RawDiagnostic lineage | Both snapshots contain 2 Findings, 2 Evidence objects, 2 Observations, and 2 RawDiagnostic objects. `SYSD-USR-FAIL-001` and `BOOT-SLOW-001` each resolve through matching Evidence, Observation, and Raw IDs; all RAW provenance statuses are `ok`. | PASS |
| Source failure behavior | A real `run_cmd` probe against a nonexistent command returned `execution_status=not_found`, return code `-1`, and no output. A nonzero command preserved stdout, stderr, status `error`, and return code `7`. | PASS |
| Bounded capture/truncation | A disposable bounded-output probe retained exactly 5000 bytes, returned status `ok`, and set `truncated=true`; fallback text contained the truncation marker. No machine failure was involved. | PASS |
| Completeness propagation | A bounded RAW record produced `Observation.data_complete=false` and Evidence `completeness=partial`. The real reports also recorded a runtime truncation restriction for the affected systemd command. | PASS |
| Real snapshot write/load | Both CLI `run --snapshot` writes succeeded. Both JSON files loaded as schema 3 and passed independent structural checks. | PASS |
| Second snapshot | A second independent real-machine run and snapshot completed successfully. | PASS |
| Real snapshot compare | CLI compare of the two real snapshots exited `0`, wrote `comparison.md`, and reported `No significant changes detected.` | PASS |
| Compare semantic determinism | Real compare outputs under `PYTHONHASHSEED=1` and `2` were byte-identical. The normalized real snapshots were equal after excluding expected timestamps and collection times. | PASS |
| Known ordering-only issue | A disposable multi-mount comparison fixture under hash seeds `1` and `2` produced the same storage change mapping and different dictionary order only. Semantic equality was true; the known set-iteration presentation issue remains visible and unfixed. | PASS with known non-gating observation |
| Safe negative CLI cases | Invalid command and missing compare arguments returned `2`. Existing-file and symlink output/snapshot destinations returned `1`. | PASS |
| Overwrite/symlink protection | Existing output and snapshot contents retained their original hashes/content; symlinks remained symlinks and their targets were unchanged. | PASS |
| Runtime determinism/performance | Real diagnostic wall times were 2.28 s and 1.78 s; compare wall time was 0.14 s. Both real reports had 69 commands and identical normalized snapshot content. | PASS |
| Human-facing normal output | Both reports contained the expected 13 sections, Stage 1/2/3 markers, summary counts, restrictions, and executed-command section; neither contained traceback or `None` markers. | PASS |
| Runtime security boundary | The real reports contained 69 executed commands with zero matches for mutating command forms (`sudo`, package mutation, service mutation, destructive file/device commands, or `tee`). The fixed collector wrappers use subprocess pipes without `shell=True`; `bash -c` appears only for fixed read-only pipelines. | PASS |

## Real-machine observations

The two real runs produced these runtime counts in each snapshot:

```text
commands_count       = 69
raw_diagnostics_count = 2
observations_count    = 2
findings_count        = 2
restrictions          = 4
raw truncated         = 0
```

The captured findings were:

```text
SYSD-USR-FAIL-001 -> EVIDENCE-SYSD-USR-FAIL-001-001
                   -> observation SYSD-USR-FAIL-001
                   -> raw SYSD-USR-FAIL-001 (systemd_failed, status=ok)

BOOT-SLOW-001     -> EVIDENCE-BOOT-SLOW-001-001
                   -> observation BOOT-SLOW-001
                   -> raw BOOT-SLOW-001 (boot_time, status=ok)
```

Both reports were regular files, not symlinks. The real report command
sections contained 69 entries and no dangerous command hits. The presence of
`sudo` in recommendations or explanatory restrictions is not execution of
`sudo`; no `sudo` command was run.

## Negative and destination-integrity results

| CLI case | Exit | Integrity result |
|---|---:|---|
| Unknown command | 2 | argparse rejected the command |
| `compare` without required paths | 2 | argparse rejected missing arguments |
| Compare to existing output file | 1 | Existing content preserved |
| Compare to output symlink | 1 | Symlink and target preserved |
| Run with existing snapshot destination | 1 | Existing snapshot hash preserved |
| Run with snapshot symlink destination | 1 | Symlink and target preserved |

The destination-safety cases currently expose an uncaught `FileExistsError`
traceback on stderr after safely rejecting the write. This is a non-gating
CLI/UX observation for Iteration 46; the safety property itself passed.

## Mandatory post-E2E validation

All commands were run after the real-machine E2E scenarios, exactly within the
read-only boundary requested:

| Command | Result |
|---|---|
| `ruff format --check .` | **PASS** — `4 files already formatted` |
| `ruff check .` | **PASS** — `All checks passed!` |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest --collect-only -q` | **PASS** — `839 tests collected in 0.96s` |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q` | **PASS** — `839 passed in 7.72s` |
| `git diff --check` | **PASS** — no output |

An initial attempt to use `/usr/bin/time` returned `127` because that optional
utility is absent; it did not launch LDE. The real runs were then measured
with the Bash `time -p` builtin and completed successfully.

## Known non-gating observations

1. `SnapshotComparator._environment_changes()` still iterates a set for
   multi-entry storage/failed-unit changes. Fresh cross-process evidence
   reproduced different Markdown ordering with equal semantics. This remains
   the known ordering-only issue and is appropriate for CLI/UX stabilization.
2. Collision rejection is safe and non-overwriting, but the CLI currently
   renders the underlying `FileExistsError` traceback. No fix was made under
   this read-only gate.

These observations do not invalidate the requested Iteration 45 gates.

## Safety and repository state

- Initial `git status --short` was exactly `?? .codex/`.
- `HEAD` and `origin/master` both resolved to
  `1d20cd65ca214883af14045b0102a298e5a0c58c`.
- After the authorized report write, this report is the only additional
  repository path; `.codex/` remains untouched.
- No Git add, commit, push, reset, restore, stash, branch, merge, rebase, tag,
  or clean action was run.
- No package install/removal, `sudo`, service start/stop, system configuration
  change, or production data mutation was performed.
- NeuralEngine `status` and read-only knowledge inspection were performed; no
  Brain write was attempted.

## Final gates

```text
REAL_MACHINE_E2E = PASS
CLI_RUNTIME_VALIDATED = YES
SNAPSHOT_RUNTIME_VALIDATED = YES
COMPARE_RUNTIME_VALIDATED = YES
READY_FOR_CLI_UX_STABILIZATION = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```

Next step: **Iteration 46 — CLI + UX / Output Stabilization.**
