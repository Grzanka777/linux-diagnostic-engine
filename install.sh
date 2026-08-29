#!/usr/bin/env bash
set -eu

if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' 'Error: uv is required; install uv and rerun ./install.sh.' >&2
    exit 1
fi

: "${HOME:?Error: HOME must be set for the supported user installation.}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if [ -n "${XDG_DATA_HOME:-}" ]; then
    reports_dir=${XDG_DATA_HOME%/}/lde/reports
else
    reports_dir=$HOME/.local/share/lde/reports
fi

uv tool install --force "$script_dir"
mkdir -p "$reports_dir"

tool_bin_dir=$(uv tool dir --bin)
lde_bin=$tool_bin_dir/lde
if [ ! -x "$lde_bin" ]; then
    printf '%s\n' "Error: uv installed the package but lde was not found at $lde_bin." >&2
    exit 1
fi
printf 'lde --version: '
"$lde_bin" --version
printf 'Reports directory: %s\n' "$reports_dir"
