# LDE Iteration 48R — Release Surface Remediation

Date: 2026-08-29
Repository: `<REDACTED-PATH>`
Checkpoint: `HEAD == origin/master == bbeca84`
Scope: RR-01 through RR-04 only; no diagnostics, features, schema changes, or
large refactor.

## 1. Executive verdict

**PASS — the four Iteration 48 release-surface findings are closed.**

The public installed surface now identifies the product as Linux Diagnostic
Engine / LDE, exposes product version `0.1.0`, retains `2.1.0` only as
explicitly labelled legacy report/snapshot compatibility metadata, and removes
the stale `2.2.0` module-header value. The claimed MIT license now exists in
the repository and is declared and shipped in the wheel. Packaging tests no
longer require Python 3.11-only `tomllib`.

Fresh evidence also confirms that the candidate wheel builds reproducibly,
installs into an isolated environment, runs outside the repository, produces
two real-machine schema-3 snapshots, compares them, and preserves the
existing read-only and destination-safety boundaries.

No tag, commit, push, or Brain write was performed. The next authorized gate is
**Iteration 48V — Release Blocker Re-Verification**.

## 2. Checkpoint and protected state

| Check | Evidence | Result |
|---|---|---|
| Branch | `master` | PASS |
| HEAD | `bbeca84f8d52edbc2e069f9e4946768df54fb861` | PASS |
| Local `origin/master` | `bbeca84f8d52edbc2e069f9e4946768df54fb861` | PASS |
| NeuralEngine status | Read-only `neural status`; Brain initialized; Trust `BINDING_MISSING` | PASS; no Brain write |
| `.codex/` | Pre-existing allowed local state; not touched | PASS |
| Index | No staged changes | PASS |

The working-tree changes are limited to the requested release remediation,
the new MIT `LICENSE`, focused packaging/public-surface tests, and this review
artifact. The pre-existing Iteration 48 review artifact and allowed `.codex/`
remain unmodified.

## 3. Remediation map

| Finding | Narrow change | Status |
|---|---|---|
| RR-01 BLOCKER | Replace user-visible old branding in help, banner, reports, report filename, and one diagnostic interpretation; retain internal `syscheck.py` and `lde = syscheck:main` | CLOSED |
| RR-02 BLOCKER | Add MIT `LICENSE`; declare `license = "MIT"` and `license-files = ["LICENSE"]`; use `setuptools>=77` for the supported metadata form | CLOSED |
| RR-03 HIGH | Add product constants/version output; label `2.1.0` as report/snapshot compatibility only; remove stale `2.2.0` | CLOSED |
| RR-04 MEDIUM | Replace packaging-test `tomllib` parsing with Python-3.10-compatible manifest text checks; add public version/help assertions | CLOSED |

No diagnostic rule logic, snapshot schema, lineage model, collector inventory,
runtime dependency, writer primitive, or command allowlist was expanded.

## 4. RR-01 — public identity

**CLOSED.** Public identity is now Linux Diagnostic Engine / LDE.

Changed public surfaces:

- `lde --version` prints exactly `Linux Diagnostic Engine 0.1.0`;
- `lde --help` describes `Linux Diagnostic Engine (LDE)`;
- the non-quiet banner uses `Linux Diagnostic Engine (LDE)` and product
  version `0.1.0`;
- report title is `Linux Diagnostic Engine (LDE) — Raport diagnostyczny`;
- generated report filenames use `lde-<hostname>-<timestamp>.md`;
- report footer and the NVIDIA Xid interpretation use the current product
  identity.

Fresh installed help and both real-machine reports contained no old public
phrases `syscheck —`, `Raport diagnostyczny syscheck`, or `SysCheck nie
rozróżnia`. The retained strings `syscheck.py`, `lde = syscheck:main`, and
`syscheck_version` are internal/compatibility surfaces explicitly required by
the remediation direction.

Evidence: `syscheck.py:2378-2390`, `syscheck.py:4446-4485`,
`syscheck.py:5828-5841`, `syscheck.py:5913-5921`,
`diagnostic_rules.py:1548`, and `test_packaging.py:57-78`.

## 5. RR-02 — MIT license and release metadata

**CLOSED.** The source already declared `Licencja: MIT`. The repository now
contains a complete MIT license at `LICENSE`, and the holder is the recorded
HEAD commit author `Grzegorz Pilich`; no placeholder or unverified holder was
invented.

`pyproject.toml` now declares:

```text
license = "MIT"
license-files = ["LICENSE"]
```

The build backend requirement is `setuptools>=77`, which supports this current
PEP 639 metadata form. The focused packaging test checks both declarations and
the repository file.

Fresh wheel metadata contains:

```text
License-Expression: MIT
License-File: LICENSE
```

The wheel contains
`linux_diagnostic_engine-0.1.0.dist-info/licenses/LICENSE`, and the complete
license text was inspected. No license warning was emitted by either fresh
candidate build.

Evidence: `LICENSE`, `pyproject.toml:1-19`,
`test_packaging.py:24-29`, and wheel
`/tmp/lde-iteration48r-final.mS87cu/repro-a/linux_diagnostic_engine-0.1.0-py3-none-any.whl`.

## 6. RR-03 — mandatory deep version-surface check

**CLOSED.** Product release version and compatibility metadata are now
separate and explicitly labelled.

| Surface | Final value/label | Interpretation |
|---|---|---|
| Distribution metadata | `0.1.0` | Public product release version |
| Wheel filename | `linux_diagnostic_engine-0.1.0-py3-none-any.whl` | Public product release version |
| `PRODUCT_VERSION` | `0.1.0` | Public product release version |
| `lde --version` | `Linux Diagnostic Engine 0.1.0` | Public product release version |
| `REPORT_COMPATIBILITY_VERSION` | `2.1.0` | Legacy report/snapshot compatibility metadata |
| `SCRIPT_VERSION` | Alias of `REPORT_COMPATIBILITY_VERSION` | Backward-compatible internal alias only |
| Report metadata | `Kompatybilność raportów/snapshotów: 2.1.0` | Explicit compatibility label |
| Report footer | Product `0.1.0`; compatibility `2.1.0` | Both values explicitly labelled |
| Schema-3 snapshot field | `metadata.syscheck_version: 2.1.0` | Legacy field/value retained for readers |
| Module header | Product `0.1.0`; compatibility `2.1.0` | No stale version |
| Stale module-header value | `2.2.0` | Removed |

The public CLI no longer presents `2.1.0` as an unlabeled script/product
version. Schema version remains `3`; the `syscheck_version` field and legacy
snapshot loading remain unchanged.

Evidence: `constants.py:8-19`, `syscheck.py:2-30`,
`syscheck.py:2378-2387`, `syscheck.py:4446-4475`,
`syscheck.py:4845-4894`, `syscheck.py:5451-5461`, and
`README.md:32-37`.

## 7. RR-04 — Python 3.10 test compatibility

**CLOSED.** `test_packaging.py` no longer imports `tomllib`. Manifest checks
use standard-library `pathlib` text reads, so the test file is compatible with
Python 3.10 without adding a runtime dependency. The project continues to
declare `dependencies = []` and `requires-python = ">=3.10"`.

Additional fresh evidence:

- AST parsing with `feature_version=(3, 10)` passed for all five repository
  Python files;
- no `tomllib` or identified post-3.10-only API was found in runtime modules;
- the focused packaging contract passed `7 passed`;
- the full suite passed `860 passed`.

Python 3.10 itself is not installed in this environment, so a live 3.10 venv
run remains unavailable. This is a verification limitation, not an open RR-04
defect; the test-harness incompatibility that caused RR-04 is removed.

## 8. Pyproject and README correctness

**PASS.** Final `pyproject.toml` declares:

- distribution name `linux-diagnostic-engine`;
- product version `0.1.0`;
- read-only diagnostics/snapshot description;
- README long description;
- MIT license and packaged license file;
- `requires-python = ">=3.10"`;
- empty runtime dependency list;
- flat modules `constants`, `diagnostic_rules`, `syscheck`;
- canonical console script `lde = syscheck:main`.

README now documents `lde --version`, the exact public version string, wheel
installation, direct legacy checkout execution, the compatibility distinction,
read-only behavior, and the MIT license link. Its use of `syscheck.py` is
explicitly labelled a legacy/internal compatibility path.

## 9. Clean candidate wheel and privacy

**PASS.** Two clean exports were made from `git archive HEAD` and overlaid only
with the current authorized remediation files. They were built offline with
the setuptools backend, no build isolation, and `SOURCE_DATE_EPOCH=0`:

```text
/tmp/lde-iteration48r-final.mS87cu/repro-a/linux_diagnostic_engine-0.1.0-py3-none-any.whl
/tmp/lde-iteration48r-final.mS87cu/repro-b/linux_diagnostic_engine-0.1.0-py3-none-any.whl
```

Both builds emitted no warnings or errors and had the identical SHA-256:

```text
8122c00ddc60a4839680a2dc82d227adfb90fd030c1ffb49b0dd19ac670b99fc
```

The candidate wheel has exactly these nine members:

```text
constants.py
diagnostic_rules.py
linux_diagnostic_engine-0.1.0.dist-info/METADATA
linux_diagnostic_engine-0.1.0.dist-info/RECORD
linux_diagnostic_engine-0.1.0.dist-info/WHEEL
linux_diagnostic_engine-0.1.0.dist-info/entry_points.txt
linux_diagnostic_engine-0.1.0.dist-info/licenses/LICENSE
linux_diagnostic_engine-0.1.0.dist-info/top_level.txt
syscheck.py
```

The wheel path scan found no `.git`, `.codex`, `.agent-work`, tests, reports,
snapshots, environments, credentials, secrets, caches, or private workstation
path members. Payload inspection found no credential/private-key markers. The
wheel does not contain a `Requires-Dist` entry.

## 10. Fresh isolated install and uninstall

**PASS.** The candidate wheel was installed into the fresh venv:

```text
/tmp/lde-iteration48r-final.mS87cu/venv
```

The environment reported `include-system-site-packages = false`, Python
`3.14.7`, and only `linux-diagnostic-engine==0.1.0` in its package list.
From an outside-repository directory, with `PYTHONPATH` and `PYTHONHOME`
removed:

- `lde --version` printed the exact required string;
- `lde --help` exposed the LDE identity and `run`, `diagnose`, `compare`;
- `syscheck.__file__` resolved to the venv site-packages directory;
- installed distribution metadata reported version `0.1.0`.

The installed distribution was then uninstalled. Post-uninstall evidence:

- `venv/bin/lde` absent;
- `find_spec("syscheck")` returned `None`;
- distribution metadata lookup returned `PackageNotFoundError`;
- no product package remained in `uv pip list`.

## 11. CLI help/error contract

**PASS.** Fresh installed CLI results from outside the repository:

| Invocation | Exit | Result |
|---|---:|---|
| `lde --version` | 0 | Exact `Linux Diagnostic Engine 0.1.0` |
| `lde --help` | 0 | Current identity and all public commands |
| `lde run --help` | 0 | PASS |
| `lde diagnose --help` | 0 | Compatibility alias PASS |
| `lde compare --help` | 0 | PASS |
| `lde unknown-command` | 2 | Controlled argparse error |
| `lde compare` | 2 | Controlled missing-argument error |
| malformed snapshot compare | 1 | Controlled `Invalid snapshot input` error |

No captured contract output contained a traceback or old public brand.

## 12. Installed real-machine run, snapshots, and compare

**PASS.** The installed command was run from outside the repository against
the real machine twice:

```text
lde run --quiet --output-dir <run-a> --snapshot <snapshot-a.json>
lde run --quiet --output-dir <run-b> --snapshot <snapshot-b.json>
lde compare snapshot-a.json snapshot-b.json --output comparison.md
```

Results were `run_a=0`, `run_b=0`, and `compare=0`. Both reports used the
`lde-*` filename pattern and current product header. Both report stderr files
were empty. Compare output was:

```text
# System comparison
No significant changes detected.
```

The fresh snapshots were structurally summarized without printing local raw
payloads:

| Snapshot | Schema | RAW | OBS | Evidence | Findings | Restrictions | Lineage | Compatibility value |
|---|---:|---:|---:|---:|---:|---:|---|---|
| A | 3 | 3 | 3 | 3 | 3 | 4 | complete | `2.1.0` |
| B | 3 | 3 | 3 | 3 | 3 | 5 | complete | `2.1.0` |

The differing restriction count is recorded machine evidence, not a schema or
lineage failure. Observation IDs and finding IDs were equal and stable across
the two captures.

## 13. Diagnostic architecture and inventory

**PASS.** No diagnostic architecture or inventory code was changed. Fresh
runtime inventory reported:

```text
registered_rules=29
unique_rule_ids=29
finding_kinds=27
pipeline_methods=True
schema=3
```

The established pipeline remains:

```text
Collector -> RawDiagnostic -> Observation -> Evidence -> Finding -> Recommendation
```

The targeted regression set covering import boundaries, pipeline separation,
classification completeness, stable IDs, snapshot lineage, and destination
safety passed `109 passed, 751 deselected`. The full suite passed `860 passed`.

## 14. Bounded false-positive and overlap sanity

**PASS for the bounded gate.** The targeted set included the repository's
near-miss, non-match, isolation, and coexistence checks across the diagnostic
families; all selected checks passed. The final change to the NVIDIA Xid
interpretation changed only visible product wording and did not change its
matching or classification behavior.

This remains bounded evidence, not an exhaustive claim about all kernel-log
vocabulary or every distribution.

## 15. Schema-3 lineage and legacy compatibility

**PASS.** `SNAPSHOT_SCHEMA_VERSION` remains `3`. The schema-3
`metadata.syscheck_version` key remains present with compatibility value
`2.1.0`. No snapshot fields were added, removed, or renamed. Existing legacy
schema migration and schema-3-without-lineage compatibility tests passed in
the full suite and targeted snapshot set.

Fresh real-machine snapshots contained complete raw-to-observation-to-evidence-
to-finding lineage. The retained field name is documented as legacy metadata,
not presented as the product release version.

## 16. Deterministic IDs and comparison

**PASS.** Fresh installed compare runs over the same two snapshots under
`PYTHONHASHSEED=1`, `2`, and `3` produced identical output hashes:

```text
5214216a644db8069880c8e2240089d35a8162371551f84dde72415c241b4c0d
```

The two fresh snapshots also produced the same observation and finding ID
sequences. The full and targeted suites passed the deterministic ID and
comparison tests.

## 17. Bounded capture and completeness

**PASS.** Existing bounded command-capture, timeout, truncation, explicit
completeness, evidence, and lineage behavior was not modified. The targeted
set including `TestBoundedCommandCapture` and `TestCaptureCompleteness` passed;
the complete `860`-test suite passed. No runtime dependency or unbounded
collector path was introduced by the release-surface changes.

## 18. O_EXCL/O_NOFOLLOW and writer-bypass check

**PASS.** `_write_new_text()` remains the sole production text sink. It:

- rejects a final symlink;
- opens with `O_CREAT | O_EXCL`;
- adds `O_NOFOLLOW` when available;
- performs inode-safe cleanup after a write failure.

Reports, snapshots, and compare output all route through this writer. The only
ordinary `open()` outside this path is the read-only snapshot input reader.

Fresh installed collision tests returned exit `1` for both an existing file
and a symlink destination. Existing bytes, symlink target bytes, and symlink
identity were retained. The destination-safety tests in the full suite also
passed.

## 19. Read-only runtime command safety

**PASS.** Each real-machine report listed `69` executed commands. A refined
command-section scan found no `sudo`, package installation/removal, service
start/stop/enable/disable, destructive filesystem/device command, network
client, telemetry, Git mutation, or Brain command. Query commands such as
`pacman -Qdt` were treated as read-only queries, not package mutation.

The production launcher remains argument-list `subprocess.Popen` with bounded
capture and process-group timeout handling. No shell or writer bypass was
introduced.

## 20. Network, telemetry, Git, Brain, and privacy boundary

**PASS.** A bounded source scan of the shipped modules found no requests,
`urllib.request`, `urlopen`, socket, HTTP client, telemetry, Git mutation, or
NeuralEngine integration. The only `urllib` use is `urllib.parse.quote` for
deterministic identifiers. `neural status` was read-only and no Brain write was
attempted.

The wheel contains only product modules and distribution metadata/license.
Real reports naturally contain local diagnostic evidence and remain local
files at user-selected destinations; no report, snapshot, credential, or
machine payload was copied into this review artifact.

## 21. Bounded secret scan

**PASS.** A bounded scan of all `54` tracked files checked private-key headers,
credential prefixes (`sk-`, `gh*`, `github_pat_`, `AKIA`), and assignment-style
`password`, `token`, and `api_key` markers. It returned zero matching lines and
zero matching files. The new MIT license and this review content contain no
secret values.

## 22. Repository hygiene and zero Git mutation

**PASS within the authorized scope.** Final status shows only the expected
release-remediation files, the new `LICENSE`, the required 48R review artifact,
and pre-existing allowed `.codex/` / Iteration 48 review state. No wheel,
virtualenv, report, snapshot, cache, or temporary build directory was created
inside the repository.

The only Git operations used were read-only inspection (`status`, `diff`,
`diff --check`, `rev-parse`, `grep`, `ls-files`, and `archive` to a temporary
export). No `git add`, commit, push, reset, restore, stash, checkout, switch,
branch, merge, rebase, tag, clean, or configuration mutation was performed.

## 23. Final validation commands

| Command | Result |
|---|---|
| `ruff format .` | PASS — 5 files left unchanged |
| `ruff check .` | PASS — all checks passed |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest --collect-only -q` | PASS — 860 tests collected |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q` | PASS — 860 passed in 8.44s |
| `git diff --check` | PASS — no output |

## 24. Findings closure

| ID | Original severity | Final status | Release consequence |
|---|---|---|---|
| RR-01 | BLOCKER | CLOSED | No public old-brand leakage found in final installed help/reports/wheel |
| RR-02 | BLOCKER | CLOSED | MIT terms are present in repository, metadata, and wheel |
| RR-03 | HIGH | CLOSED | Product `0.1.0` and compatibility `2.1.0` are explicitly separated; `2.2.0` removed |
| RR-04 | MEDIUM | CLOSED | Packaging tests run without Python-3.11-only `tomllib` |

## 25. Non-gating verification notes

`KNOWN_NON_GATING_ISSUES = 2`:

1. Python `3.10` is not installed here; live compatibility execution was not
   possible. AST feature-version validation, API scan, dependency-free wheel
   metadata, and current runtime evidence passed.
2. Server-side remote refresh was not available in the prior audit environment
   because SSH configuration/key access was blocked. The supplied checkpoint
   and local `origin/master` ref match exactly; no release-tree mutation
   depends on remote access in this remediation.

These notes do not reopen RR-01 through RR-04 and do not create a release
blocker or high issue.

## 26. Final gates

```text
ITERATION_48R_RELEASE_SURFACE_REMEDIATION = PASS
RR_01_PUBLIC_IDENTITY = CLOSED
RR_02_LICENSE_METADATA = CLOSED
RR_03_VERSION_SURFACE = CLOSED
RR_04_PY310_TEST_COMPAT = CLOSED
READY_FOR_RELEASE_REVERIFICATION = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
RELEASE_BLOCKERS = 0
HIGH_ISSUES = 0
KNOWN_NON_GATING_ISSUES = 2
```

## 27. Next step

Proceed only to **Iteration 48V — Release Blocker Re-Verification**. Do not
tag, commit, push, or expand features in this iteration.
