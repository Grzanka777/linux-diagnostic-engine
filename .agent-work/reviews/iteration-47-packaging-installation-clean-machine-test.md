# LDE Iteration 47 — Packaging + Installation + Clean-Machine Test

Date: 2026-08-29
Repository: `<REDACTED-PATH>`
Checkpoint: `HEAD == origin/master == 46010fe`
Baseline: `853/853 PASS`

## Scope and boundary

This iteration adds standards-based packaging, the canonical installed CLI,
installation documentation, focused packaging contract tests, and an
isolated clean-machine installation/runtime proof.

The flat source layout is preserved. `syscheck.py`, `constants.py`, and
`diagnostic_rules.py` remain at repository root; no source-tree relocation,
diagnostic redesign, dependency addition, or feature expansion was made.
The existing direct invocation `python3 syscheck.py` remains available.

No sudo, global package installation, service/system mutation, network access
for build or install, release/tag, Git mutation, or NeuralEngine Brain write
was performed. `.codex/` was not touched. Runtime artifacts were created only
under `/tmp/lde-iteration47.EeRS63/`.

## Changes

### Minimal package contract

`pyproject.toml` uses the setuptools PEP 517 backend and declares:

- distribution name `linux-diagnostic-engine`;
- package version `0.1.0`;
- Python `>=3.10`;
- no runtime dependencies (`dependencies = []`);
- flat modules `constants`, `diagnostic_rules`, and `syscheck`;
- canonical console script `lde = syscheck:main`.

The existing diagnostic metadata `SCRIPT_VERSION = 2.1.0` was not changed;
it remains report/snapshot metadata rather than a package version source.

### Documentation and contract tests

`README.md` documents offline-capable wheel-oriented build/install commands,
the installed `lde` help surface, the read-only runtime boundary, and the
preserved direct script path.

`test_packaging.py` adds five focused tests covering project metadata,
zero runtime dependencies, flat module declaration, the `lde` entry point,
the direct execution guard, and the installation documentation.

## Build and wheel inspection

A clean package export was created by extracting `git archive HEAD` into
`/tmp/lde-iteration47.EeRS63/clean-export` and adding only the candidate
`pyproject.toml` and `README.md`. The repository's private/dev tree was not
used as the build source.

Canonical build command:

```text
UV_PYTHON=/usr/bin/python3 uv build --wheel --offline --no-build-isolation \
  --out-dir /tmp/lde-iteration47.EeRS63/wheel-uv \
  /tmp/lde-iteration47.EeRS63/clean-export
```

Result: **PASS** —
`/tmp/lde-iteration47.EeRS63/wheel-uv/linux_diagnostic_engine-0.1.0-py3-none-any.whl`.
The build was offline. The default uv-managed interpreter did not have
setuptools in its offline cache; selecting the already-installed system
Python backend kept the same PEP 517 setuptools build path available without
network access.

The wheel contains exactly these eight files:

```text
constants.py
diagnostic_rules.py
syscheck.py
linux_diagnostic_engine-0.1.0.dist-info/METADATA
linux_diagnostic_engine-0.1.0.dist-info/WHEEL
linux_diagnostic_engine-0.1.0.dist-info/entry_points.txt
linux_diagnostic_engine-0.1.0.dist-info/top_level.txt
linux_diagnostic_engine-0.1.0.dist-info/RECORD
```

Independent zip inspection passed: metadata is version `0.1.0`,
`Requires-Python: >=3.10`, has no `Requires-Dist`, and exposes
`lde = syscheck:main`. No tests, backups, reports, `.git`, `.codex`,
`.agent-work`, or other private/dev leakage is present.

## Isolated installation and installed CLI

Fresh environment:

```text
/tmp/lde-iteration47.EeRS63/venv
```

`pyvenv.cfg` independently reports
`include-system-site-packages = false`. Offline installation with
`uv pip install --offline --no-deps` succeeded, and the environment contained
only `linux-diagnostic-engine==0.1.0`.

From `/tmp/lde-iteration47.EeRS63/outside`, with `PYTHONPATH` and `PYTHONHOME`
removed:

- `lde --help` — **PASS**;
- `lde run --help` — **PASS**;
- `lde compare --help` — **PASS**;
- `syscheck.__file__` — `/tmp/lde-iteration47.EeRS63/venv/lib/python3.14/site-packages/syscheck.py`;
- `diagnostic_rules.__file__` — the same venv `site-packages` tree;
- installed metadata version — `0.1.0`.

The import-path assertions passed and confirmed no repository `PYTHONPATH` or
source-tree import was involved.

## Installed real-machine runtime

Using the installed `lde` command from outside the repository:

1. a read-only real-machine run wrote report one and `snapshot-one.json`;
2. a second read-only real-machine run wrote report two and `snapshot-two.json`;
3. `lde compare snapshot-one.json snapshot-two.json --output comparison.md`
   exited `0` and wrote the comparison.

Both snapshots passed independent JSON checks:

```text
schema_version=3
commands_count=69
raw_diagnostics_count=2
observations_count=2
findings_count=2
restrictions=4
```

The comparison contained `No significant changes detected.`. Both reports
were traceback-free. Their executed-command sections passed a focused
read-only audit with no `sudo`, package mutation, service start/stop/disable,
destructive file/device command, or `tee` command.

Representative installed destination collision also passed: comparing to an
existing output file returned exit `1`, printed one controlled `already exists`
error, emitted no traceback, and preserved the existing file.

## Uninstall proof

`uv pip uninstall --python /tmp/lde-iteration47.EeRS63/venv/bin/python
linux-diagnostic-engine` succeeded. Post-uninstall checks passed:

- `venv/bin/lde` no longer exists;
- installed `syscheck.py`, `diagnostic_rules.py`, and `constants.py` no longer exist;
- `importlib.util.find_spec("syscheck")` and
  `find_spec("diagnostic_rules")` return `None`;
- package metadata lookup raises `PackageNotFoundError`.

## Validation

| Command | Result |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q test_packaging.py` | **PASS** — 5 passed |
| `ruff format .` | **PASS** — 5 files left unchanged |
| `ruff check .` | **PASS** — all checks passed |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest --collect-only -q` | **PASS** — 858 tests collected |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q` | **PASS** — 858 passed in 8.04s |
| `git diff --check` | **PASS** — no output after all tracked code/documentation changes |

The five new packaging tests account for the increase from the `853/853`
baseline to `858/858`.

## Repository safety

- Initial status contained only `?? .codex/`; it remains untouched.
- No `git add`, commit, push, reset, restore, stash, branch, merge, rebase,
  tag, or clean action was run.
- No package was installed globally and no service or system configuration was
  modified.
- The only intentional repository paths from this iteration are
  `pyproject.toml`, `README.md`, `test_packaging.py`, and this review.

## Final gates

```text
ITERATION_47_PACKAGING = PASS
PACKAGE_BUILD_VALIDATED = YES
ISOLATED_INSTALL_VALIDATED = YES
INSTALLED_CLI_VALIDATED = YES
UNINSTALL_VALIDATED = YES
READY_FOR_RELEASE_READINESS_AUDIT = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```

Next step: **Iteration 48 — Release Readiness Audit.**
