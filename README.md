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

The same command is the canonical local upgrade/reinstall path. Run
`./install.sh` again after changing checkout contents; it replaces the user-local
tool with `uv tool install --force` and retains existing reports. Verify the
installed command with:

```text
lde --version
```

To uninstall the tool without removing diagnostic data:

```text
uv tool uninstall linux-diagnostic-engine
```

Reports remain at `$XDG_DATA_HOME/lde/reports` or `~/.local/share/lde/reports`
after uninstall. Remove that directory separately only when its reports are no
longer needed.

## Installation from a wheel

Build a wheel in a disposable output directory:

```text
uv build --wheel --out-dir /tmp/lde-dist
```

Install it into an isolated virtual environment:

```text
uv venv /tmp/lde-venv
uv pip install --python /tmp/lde-venv/bin/python /tmp/lde-dist/linux_diagnostic_engine-0.6.0-py3-none-any.whl
```

The installed command is `lde`:

```text
/tmp/lde-venv/bin/lde --version
/tmp/lde-venv/bin/lde --help
/tmp/lde-venv/bin/lde run --help
/tmp/lde-venv/bin/lde compare --help
/tmp/lde-venv/bin/lde capabilities --help
/tmp/lde-venv/bin/lde sanitize --help
/tmp/lde-venv/bin/lde explain --help
/tmp/lde-venv/bin/lde verify --help
/tmp/lde-venv/bin/lde snapshot create --help
/tmp/lde-venv/bin/lde snapshot validate --help
/tmp/lde-venv/bin/lde snapshot compare --help
```

The public product version is `0.6.0`; `lde --version` prints
`Linux Diagnostic Engine 0.6.0`. Without `--output-dir`, reports are written
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

## Quick start and source limitations

Run a diagnostic and get the exact report path:

```text
lde run
```

Use `lde capabilities` to see which source families are authoritative on the
current workstation. The output distinguishes `AVAILABLE`, `LIMITED`,
`NOT_APPLICABLE`, `UNAVAILABLE`, and `FAILED`; an unavailable source is never
treated as a healthy source or as a diagnostic Finding. Use `--json` for a
stable machine-readable form.

The command is safe without sudo. Permission-limited journal, Btrfs, direct
kernel-log, or user-systemd sources are reported as limitations, and the
diagnostic pipeline does not infer health or failure from those limitations.
LDE does not add telemetry, network reachability probes, a daemon, or an AI
diagnosis layer.

Snapshots are schema 3 and can be checked before comparison:

```text
lde snapshot create --output /tmp/lde-first.json
lde snapshot validate /tmp/lde-first.json
lde snapshot compare /tmp/lde-first.json /tmp/lde-second.json
# equivalent compatibility spelling
lde compare /tmp/lde-first.json /tmp/lde-second.json

# after an external repair or change
lde verify /tmp/lde-first.json
```

`snapshot compare` is the nested public spelling; `lde compare` remains a
compatibility alias for the same structural comparison. `lde verify` reuses
the read-only diagnostic pipeline and classifies Finding
IDs as `NEW`, `PERSISTENT`, or `RESOLVED`. If a relevant source is unavailable,
failed, permission-limited, truncated, or malformed, the baseline Finding is
shown as `Unverified` instead of being falsely marked resolved. Use
`lde verify --json` for stable machine-readable lifecycle IDs and source
limitations.

Explain one Finding without running diagnostics:

```text
lde explain KERNEL-OOM-001
lde explain KERNEL-OOM-001 --json
lde explain KERNEL-OOM-001 --snapshot /tmp/lde-first.json
```

The static form is independent of the current machine. It gives the Finding
summary, evidence boundary, actionability class, safe investigation steps,
verification steps, sources, and limitations. Snapshot mode uses only the
persisted Finding lineage and includes the linked Evidence IDs and source
status. A Finding absent from the supplied snapshot is reported as absent; it
is not inferred from report text. Source limitations make snapshot
actionability `source_limited`, and no explain guidance changes packages,
services, filesystems, or configuration.

## Privacy and sharing

Reports and snapshots may contain hostnames, home paths, network addresses,
UUIDs, explicitly labelled serials, filesystem labels, and other workstation
details. Never publish a raw artifact blindly. Create a new, collision-safe
copy with:

```text
lde sanitize /path/to/report.md --output /path/to/report-sanitized.md
lde sanitize /path/to/snapshot.json --output /path/to/snapshot-sanitized.json
```

Sanitization is local-only, never overwrites the input, and preserves the
schema, Finding/Evidence identifiers, severity, confidence, and diagnostic
device paths where those paths carry meaning. It replaces known identifiers
with stable placeholders and is deterministic. It reduces known host
identifiers; it is not a guarantee of anonymity. Inspect the generated copy
for custom hostnames, service/process/package names, command-line arguments,
and other values that the explicit contract cannot safely classify.

## Direct execution from a checkout

The legacy checkout invocation remains supported:

```text
python3 syscheck.py --help
python3 syscheck.py run --output-dir /tmp/lde-reports --snapshot /tmp/lde-reports/first.json
python3 syscheck.py snapshot create --output /tmp/lde-reports/first.json
python3 syscheck.py verify /tmp/lde-reports/first.json
python3 syscheck.py explain KERNEL-OOM-001 --snapshot /tmp/lde-reports/first.json
python3 syscheck.py snapshot compare /tmp/lde-reports/first.json /tmp/lde-reports/second.json
python3 syscheck.py compare /tmp/lde-reports/first.json /tmp/lde-reports/second.json
python3 syscheck.py capabilities
python3 syscheck.py sanitize /tmp/lde-reports/report.md --output /tmp/report-sanitized.md
```

The distribution is released under the MIT License; see [LICENSE](LICENSE).
