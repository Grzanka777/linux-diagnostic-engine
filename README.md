# Linux Diagnostic Engine

Linux Diagnostic Engine (LDE) is a read-only Linux diagnostics CLI. It
collects bounded system evidence, writes a Markdown report and can persist a
JSON snapshot for later comparison. It does not require third-party Python
runtime dependencies.

## Supported installation

From a checkout, run the no-sudo installer:

```text
./install.sh
```

It uses `uv tool install` for the local package, creates the reports directory
at `$XDG_DATA_HOME/lde/reports` (or `~/.local/share/lde/reports` when
`XDG_DATA_HOME` is unset), prints the installed version and reports path, and
does not modify shell startup files or system services. Add the uv tool bin
directory to `PATH` manually if your shell does not already include it.

## Installation from a wheel

Build a wheel in a disposable output directory:

```text
uv build --wheel --out-dir /tmp/lde-dist
```

Install it into an isolated virtual environment:

```text
uv venv /tmp/lde-venv
uv pip install --python /tmp/lde-venv/bin/python /tmp/lde-dist/linux_diagnostic_engine-0.4.0-py3-none-any.whl
```

The installed command is `lde`:

```text
/tmp/lde-venv/bin/lde --version
/tmp/lde-venv/bin/lde --help
/tmp/lde-venv/bin/lde run --help
/tmp/lde-venv/bin/lde compare --help
```

The public product version is `0.4.0`; `lde --version` prints
`Linux Diagnostic Engine 0.4.0`. Without `--output-dir`, reports are written
to `$XDG_DATA_HOME/lde/reports` or `~/.local/share/lde/reports`; an explicit
`--output-dir` still overrides this default. A successful `lde run` prints a
compact English summary with the exact absolute report path. Use
`--print-report` to print the complete Markdown report and `--verbose` to show
detailed diagnostic progress. The legacy flat module remains named
`syscheck.py`, and the package entry point remains `lde = syscheck:main` for
compatibility. The schema-3 snapshot field `syscheck_version` and the related
report metadata retain `2.1.0` only as explicitly labelled legacy
report/snapshot compatibility metadata. It is not the product version.

The package contains no network, database, service, or system-mutation
installation step. The diagnostic run itself is read-only and writes only the
report and optional snapshot destinations supplied by the user.

## Direct execution from a checkout

The legacy checkout invocation remains supported:

```text
python3 syscheck.py --help
python3 syscheck.py run --output-dir /tmp/lde-reports --snapshot /tmp/lde-reports/first.json
python3 syscheck.py compare /tmp/lde-reports/first.json /tmp/lde-reports/second.json
```

The distribution is released under the MIT License; see [LICENSE](LICENSE).
