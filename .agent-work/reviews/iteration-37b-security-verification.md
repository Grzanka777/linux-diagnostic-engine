# Iteration 37B — Security Verification

## Verdict

**A — PASS; checkpoint may proceed.**

The Iteration 37A controls are present in the live checkout, close the verified
Iteration 37 security paths, preserve legitimate no-match and failure semantics,
and pass the full required validation suite. This was a read-only verification;
no source, tests, Git state, or NeuralEngine Brain state was modified.

## Inputs and baseline

- `.agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md`
- `.agent-work/reviews/iteration-37a-security-boundary-hardening.md`
- Fresh baseline/full suite: **594 passed**.

The worktree remains dirty from earlier iterations. Those changes were preserved
and were not reclassified as Iteration 37B changes.

## Verification matrix

### 1. Produced stdout/stderr are bounded

`run_cmd()` uses `subprocess.Popen` with binary pipes and one concurrent drain per
stream. Each drain retains at most `TRUNCATE_NORMAL` bytes (5000) while reading;
it does not collect unlimited output and slice afterward. `CmdResult.truncated`
is set independently from exit status. Timeout kills the process group, returns
`-2`, and retains partial output.

Fresh runtime probe:

- 20,000-byte stdout: retained bytes ≤ 5000, `truncated=True`, status `ok`.
- 20,000-byte stderr followed by exit 7: retained bytes ≤ 5000, `truncated=True`,
  return code 7 and status `error`.
- Prefix followed by a sleeping process: status `timeout`, return code `-2`, and
  the prefix remains visible.

### 2. Truncation reaches evidence and confidence

`_capture_payload()` records `capture_truncated`; `_raw_to_observation()` maps it
to `data_complete=False` for kernel/journal diagnostic categories. The existing
evidence builders already map incomplete observations to partial evidence, and
confidence derivation maps incomplete data to `Guessing`. A fresh PCIe probe
confirmed all three states: incomplete observation, partial evidence, and
`Guessing` confidence.

The legacy string path is covered too: `cmd_ok()` delegates to
`CmdResult.to_fallback_text()`, so successful truncation and timeout partial output
retain explicit markers in base/resource/user-environment report sections.

### 3. Source failures are not masked as zero/no-event

The status-aware `_journal_filter_command()` and `_journal_count_command()` capture
`PIPESTATUS`. Upstream journal failure and grep errors remain failures; grep rc=1
is normalized only when it is the legitimate no-match case. Authentication count
returns `0` only for a successful source query.

Fresh probes confirmed:

- filter upstream rc=42 remains rc=42;
- authentication source rc=1 is `error` with fallback `(błąd rc=1)`, not a false
  zero or no-event result;
- successful no-match returns status `ok` and stdout `0`.

The remaining production `return_code == 1` checks are explicit, narrow behavior:
pacman orphan-query no-data handling requires empty stdout and stderr, and the DRM
device display has a read-fallback for rc=1. There is no production `|| true` or
`|| echo 0`.

### 4. Report/snapshot/compare destinations reject collisions and final symlinks

`_write_new_text()` is the sole production text-write helper. It rejects an
existing final-component symlink, opens with `O_CREAT|O_EXCL` and `O_NOFOLLOW`,
and never replaces an existing destination. Failed-write cleanup compares device
and inode before unlinking, so a raced replacement is not removed.

All three sinks route through it:

- `SysCheckEngine.run_all()` report output;
- `SystemSnapshot.to_json()` snapshot output;
- `compare --output` Markdown output.

Fresh temporary-path probes confirmed rejection and preservation for an existing
regular file, a targetable final symlink, and a dangling final symlink.

### 5. No alternate runtime path bypasses controls

Source tracing found only one production subprocess launch (`run_cmd()`), one
`run_cmd()` caller (`SysCheckEngine.cmd()`), and the two parallel dispatch paths
(`_parallel()` through `cmd_ok()` and `_parallel_cmd()` through `cmd()`). All use
the bounded runner or its metadata-preserving fallback.

Source tracing found no direct production `write_text()`, `open(..., "w")`, or
`Path.replace()` sink. The only `open()` outside the writer is read-only snapshot
loading. `capture_output=True` appears only in tests, not production modules.

### 6. `import sys` is a minimal baseline repair

`syscheck.py` has exactly one `import sys`. The only runtime uses are the existing
stderr logging and CLI argument/output paths (`sys.stderr`, `sys.argv`). The
pre-edit dirty checkout failed broadly because this import was absent; restoring
it was necessary for the stated baseline and full suite. The final 594-test run,
fresh import, Ruff checks, and the absence of any second import or unrelated new
`sys` path provide no evidence of a broader inconsistency.

## Remaining-pattern audit

| Search | Production result |
|---|---|
| `capture_output=True` | None in `syscheck.py`/`constants.py`; test subprocesses only |
| `|| true` | None |
| `|| echo 0` | None |
| `return_code == 1` / `returncode == 1` | Two explicit production branches: pacman orphan no-data and DRM read fallback |
| direct `write_text()` | None in production |
| `open(..., "w")` | None in production; writer uses `os.open` + `os.fdopen` after exclusive creation |

The explicit final-component boundary does not claim no-follow protection for
parent directories; that broader filesystem policy was outside Iteration 37A/37B.

## Validation

| Check | Result |
|---|---|
| `ruff format --check .` | **PASS** — 4 files already formatted |
| `ruff check .` | **PASS** — all checks passed |
| `python3 -m pytest --collect-only -q` | **PASS** — 594 tests collected |
| `python3 -m pytest -q` | **PASS** — 594 passed in 2.56s |
| `git diff --check` | **PASS** |

Current working-tree diff summary for the three pre-existing source/test paths:

```text
 constants.py     |   23 +-
 syscheck.py      | 1694 ++++++++++++++++++------------------------------------
 test_syscheck.py |  790 +++++++++++++++++++++++--
```

SHA-256 of that current three-file diff:

`149f8d459990921ae4e47eb42736cbf50a74c295a088767ba990c272a95bebb6`

## Scope audit

- No code, tests, `AGENTS.md`, Git history, or NeuralEngine Brain changes.
- No remediation commands, package/service mutations, PATH pinning, Markdown
  escaping, sandboxing, privilege separation, or architecture changes.
- No alternate AER/NVMe path was introduced; existing AER-only, NVMe-only, and
  combined-independence regressions remain included in the 594 passing tests.

## NeuralEngine usage

`neural status`:

```text
Brain state: Initialized
Brain Trust state: TRUSTED_CURRENT
Resolved Neural home: <REDACTED-PATH>
```

NeuralEngine search used: YES

Queries:

- `Iteration 37B security verification`

Returned records:

- No matching knowledge found.

Exact records inspected:

- None.

Material effect:

The targeted search returned no historical record and did not alter the
verification boundary or verdict; current repository source, supplied reviews,
and fresh probes remained authoritative. No Brain writes were performed.
