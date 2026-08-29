# Linux Diagnostic Engine

Linux Diagnostic Engine (LDE) is a read-only Linux diagnostics CLI. It
collects bounded system evidence, writes a Markdown report and can persist a
JSON snapshot for later comparison. It does not require third-party Python
runtime dependencies.

## Installation from a wheel

Build a wheel in a disposable output directory:

```text
uv build --wheel --out-dir /tmp/lde-dist
```

Install it into an isolated virtual environment:

```text
uv venv /tmp/lde-venv
uv pip install --python /tmp/lde-venv/bin/python /tmp/lde-dist/linux_diagnostic_engine-0.1.0-py3-none-any.whl
```

The installed command is `lde`:

```text
/tmp/lde-venv/bin/lde --help
/tmp/lde-venv/bin/lde run --help
/tmp/lde-venv/bin/lde compare --help
```

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

Installed package version: `0.1.0`. The diagnostic report's existing
`SCRIPT_VERSION` metadata is kept separately for snapshot/report compatibility.
