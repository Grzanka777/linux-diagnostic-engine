# Iteration 32B — Kernel Package Portability

## Result

DEFECT CONFIRMED and corrected.

`_count_kernel_packages()` treated the first whitespace token as the package
name. With `dpkg -l`, that token is the status (`ii`), while the five table
headers were also treated as bootable packages. The isolated Debian fixture
reproduced the failure before any repository edit:

```text
assert bootable == 2
E       assert 9 == 2
```

## Commands inspected

- Arch/CachyOS: `pacman -Q 2>/dev/null | grep -E '^linux'`
- Debian/Ubuntu: `dpkg -l linux-image-*`
- Fedora/RHEL: `rpm -qa kernel*`

## Remediation

The existing function now recognizes the three command-output shapes without
introducing a parser framework or changing package-manager commands:

- Arch/CachyOS retains the existing `linux*` filtering behavior.
- Debian/Ubuntu processes only installed `dpkg` package rows, uses the package
  and version columns, and counts versioned `linux-image-*` packages while
  excluding headers, firmware, metapackages, table headers, and removed rows.
- Fedora/RHEL recognizes versioned `kernel` and `kernel-core` entries,
  excludes module/devel/header packages, and deduplicates a version represented
  by both `kernel` and `kernel-core`.

New focused fixtures cover the Debian and RPM forms; the existing Arch/CachyOS
fixtures continue to cover the original behavior.

## Validation

Baseline before edits:

```text
python3 -m pytest -q
520 passed in 0.41s
```

Focused checks:

```text
python3 -m pytest -q test_syscheck.py -k KernelCounting
4 passed, 516 deselected in 0.07s

Temporary isolated Debian reproduction
1 failed (assertion: 9 bootable instead of 2)

python3 -m pytest -q test_syscheck.py -k KernelCounting
6 passed, 516 deselected in 0.10s
```

Final required validation:

```text
ruff format --check .
3 files already formatted

ruff check .
All checks passed!

python3 -m pytest --collect-only -q
522 tests collected in 0.10s

python3 -m pytest -q
522 passed in 0.42s
```

No diagnostic extraction/addition, SysCheck/LDE rename, `AGENTS.md` edit,
parser framework, or Git publication/history operation was performed. All
changes are unstaged.

## NeuralEngine usage

neural status:

```text
Neural Engine 1.1.0; resolved NEURAL_HOME <REDACTED-PATH>;
Brain state Initialized and accessible.
```

NeuralEngine search used: NO

Reason:

Current source, the configured package-manager commands, deterministic local
fixtures, and live tests fully determined this narrow portability correction;
historical records could not materially affect the implementation.

Brain writes: NONE
