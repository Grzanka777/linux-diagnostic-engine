# Codex Repository-Wide Audit Before Iteration 32

## Scope and authority

This audit uses the immutable pre-Iteration-32 baseline
`2385be1efffa13a12936c8b1eef942936650d357` (`master`, also
`origin/master`) as its code/history authority. `git fsck --no-dangling
--no-progress` succeeded; the commit chain is linear from `55049c2` through
the four later diagnostic additions and the guidance commit. `HEAD` reflog
also ends at `2385be1` with the expected commit action.

The live worktree is **not** that baseline: Git records an existing modified
`AGENTS.md`, an existing untracked Iteration 31 review, and uncommitted
Iteration 32 extraction files (`syscheck.py`, `diagnostic_rules.py`, and its
review). Those facts override any review declaration that this checkout is
“before Iteration 32.” They were not changed by this audit. Baseline source was
read through `git show HEAD:<path>`; current-tree validation is reported
separately below.

## Executive result

The baseline has a coherent three-stage diagnostic pipeline and strong
diagnostic-specific regression coverage, but it is not ready to treat an
extraction as its next corrective action. Correctness and safety-contract
defects exist in the committed baseline and are not covered by the test suite.

## Architecture and diagnostic coverage

The intended flow is sound:

```text
collector command -> RawDiagnostic -> Observation -> DiagnosticRuleResult
                                      -> Finding + runtime-only Evidence
                                      -> Recommendation / report / snapshot
```

The rule registry is deterministic, rejects duplicate rule IDs, detects
ambiguous findings and duplicate Evidence/Finding IDs, and keeps the rule
engine independent of collectors. All fifteen concrete rules are present in
the baseline: Btrfs device error/scrub, three segfault paths, kernel taint,
OOM, i915 hang, AMDGPU reset failure, NVIDIA Xid 79, system/user failed units,
kernel count, boot delay, and storage usage.

Collector-to-rule paths are implemented for each of those diagnostics. The
kernel journal collectors use current-boot queries; OOM/GPU pipelines preserve
upstream `journalctl` status and distinguish grep no-match from upstream
failure. The later GPU and OOM additions have useful positive, negative,
timeout, failure, output-cap, provenance, and cross-diagnostic regression
tests. Btrfs, boot, systemd, storage, and segfault paths also have focused
collector tests.

Regex and parser assessment:

- The Xid 79 expression anchors `79` after the PCI segment, and its tests
  exercise confusable Xid codes and stray `79` values.
- OOM/i915/AMDGPU pipelines are static command constructions; no untrusted
  data is interpolated into `bash -c`.
- Btrfs and storage parsing have targeted fixtures, but the kernel package
  parser is Arch-shaped while the product claims Debian/Ubuntu and RHEL/Fedora
  support. `_count_kernel_packages()` takes the first whitespace token; for
  `dpkg -l` this is the package status (`ii`) or header text, not the package
  name. The RHEL/Debian command/output formats have no corresponding parser
  tests. Therefore the cross-distribution kernel-count diagnostic is not
  established as correct.

## Confirmed findings

### 1. Broken public hash contract — corrective defect

`FindingClassification` is frozen and advertises a `__hash__`, but baseline
line 652 assigns `str.__hash__` to a non-string dataclass. A direct runtime
probe raises:

```text
TypeError: descriptor '__hash__' requires a 'str' object but received a
'FindingClassification'
```

This is not a hypothetical style concern: a value intended to be immutable and
hashable cannot be used in a set or dictionary key. Tests cover immutability
and equality but do not call `hash()`.

### 2. Unreachable duplicate comparison renderer — corrective defect

`format_comparison_markdown()` returns at baseline line 4882, followed by a
duplicated new/resolved/changed/environment rendering block through line 4922.
It is dead code, makes later changes error-prone, and is not detected by Ruff
or a source-level test. Snapshot comparison tests only verify output behavior,
so they cannot expose this maintenance defect.

### 3. “Read-only” is system-state-only, not output-safe — contract debt

No privileged system mutation, `shell=True`, `sudo`, or dynamically composed
shell input was found. Commands are static argv lists or static internal
pipelines, which is a good security property.

However, `run_all()` creates an output directory and writes a timestamped
report; `SystemSnapshot.to_json()` opens any supplied path with `"w"`; and
`compare --output` uses `Path.write_text()`. These can overwrite existing
user files (the report name can also collide within the same hostname/second).
The documentation itself says a report is written. The product should state
this accurately as non-invasive system diagnostics with report/snapshot output,
or later introduce explicit non-overwrite behavior. It must not be represented
as filesystem read-only.

### 4. Coverage claim is incomplete — test-quality debt

The baseline has 8,602 lines of tests and broad per-diagnostic fixtures, but
they live in one monolithic module with repeated import blocks. More
importantly, `TestClassificationPolicyCompleteness` lists only nine legacy
categories and omits OOM plus the three GPU categories that production emits.
It therefore does not prove its stated “every emitted category” contract.
There is also no test for the hash contract, the unreachable renderer tail,
the CLI write/overwrite behavior, or Debian/RHEL kernel-count parsing.

## Evidence / Observation / Finding / snapshot assessment

The evidence payloads preserve observation/raw provenance, and the rule engine
uses `DiagnosticRuleResult` to keep Findings and Evidence together. Evidence
is intentionally runtime-only; snapshots retain Findings, Observations,
recommendations, restrictions, and execution counts. That boundary is
consistent with current comparison behavior.

The v2-to-v3 migration table deliberately covers historical finding IDs only;
the later OOM/GPU IDs are not in it and would receive fallback classification
if encountered in a synthetic v2 snapshot. This is low current risk because
those diagnostics were introduced after schema v3, but it should be documented
or tested if externally supplied v2 snapshots are a supported input.

## Prior reviews versus repository evidence

Older DeepSeek reviews are historical records, not current authority. Their
then-current test totals (for example 330, 346, 364, 467, and 519) may describe
their checkpoints but cannot establish present correctness. In particular,
the post-migration claim that the architecture was sufficient predates the four
subsequent OOM/GPU diagnostic commits; it also did not identify the baseline
hash failure, dead renderer duplicate, portability gap, or output-write
contract. Iteration 31 correctly identified the rule runtime as the smallest
future extraction seam, but its cleanliness declaration cannot override the
actual dirty worktree.

## Naming and maintainability

The project/repository name is Linux Diagnostic Engine while the executable,
runtime class, snapshot metadata, and output filename use SysCheck. This is
manageable if deliberately defined as project name versus tool name; a rename
is not the priority.

The main maintainability pressure is concentration: baseline `syscheck.py` is
5,036 lines while `test_syscheck.py` is 8,602 lines. The rule runtime is a
real coherent extraction seam, but extracting it first would move code around
before correcting known semantics and tests. Do not pursue a full restructure:
models, Evidence, snapshots, collectors, CLI, and recommendations have stable
current contracts.

## Validation run

The required commands ran against the current worktree because Git shows it
already contains uncommitted Iteration 32 changes; they are not proof of a
literal baseline checkout:

```text
ruff format --check .  PASS (4 files already formatted)
ruff check .           PASS
python3 -m pytest -q   PASS (519 passed in 0.39s)
```

These passing checks do not invalidate the confirmed hash probe or the
baseline dead-code and coverage findings above.

## NeuralEngine usage

neural status:

```text
Neural Engine 1.1.0; resolved NEURAL_HOME <REDACTED-PATH>;
Brain state Initialized and accessible.
```

NeuralEngine search used: YES

Queries:

- `linux diagnostic engine diagnostics evidence observations findings audit architecture security`

Returned records:

- None — no matching knowledge record.

Exact records inspected:

- None.

Material effect:

No material change; Git history and baseline source controlled the audit.

Brain writes: NONE

Decision C — remediation before extraction
