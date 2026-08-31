# Post-v0.1.4 Real-World Quality Pack Review

Date: 2026-08-31

## Verdict

`POST_V0_1_4_REAL_WORLD_QUALITY_PACK = PASS`

The current v0.1.4 checkout correctly routes the real ACPI and kernel-taint
events through the existing diagnostic pipeline. The quality-pack changes are
limited to two executable recommendation fixes and their regression assertions.
No diagnostic domain, finding type, severity, public version, compatibility
contract, or snapshot schema was added or changed.

## Checkpoint and scope

- Release checkpoint: `8906700440cc0f2f0f1b01e11418767c89c125b6`
- Branch: `master`, tracking `origin/master`
- Exact tag at checkpoint: `v0.1.4`
- Product version: `0.1.4`
- Report compatibility: `2.1.0`
- Snapshot schema: `3`
- Brain writes: none
- Release actions: none; no commit, push, tag, amend, reset, rebase, or history rewrite

The following untracked paths were present before this quality-pack work and
were preserved: `.agent-work/reviews/v0.1.4-release-result.md`, `.codex/`,
`build/`, and `linux_diagnostic_engine.egg-info/`.

## Current diagnostic inventory

The default registry contains 29 existing rule instances. No rule instance was
added or removed:

| Area | Existing rule IDs |
| --- | --- |
| Btrfs/storage | `RULE-BTRFS-DEVICE-ERROR`, `RULE-BTRFS-SCRUB-STATUS`, `RULE-STORAGE-USAGE` |
| Segfaults | `RULE-SEGFAULT-WIREPLUMBER`, `RULE-SEGFAULT-GENERAL`, `RULE-SEGFAULT-MINOR` |
| Kernel state/events | `RULE-KERNEL-TAINT`, `RULE-KERNEL-OOM`, `RULE-KERNEL-COUNT`, `RULE-KERNEL-OOPS-PANIC`, `RULE-KERNEL-SOFT-LOCKUP`, `RULE-KERNEL-HARD-LOCKUP`, `RULE-KERNEL-HUNG-TASK`, `RULE-KERNEL-RCU-STALL` |
| GPU/hardware/storage reliability | `RULE-GPU-I915-HANG`, `RULE-AMDGPU-RESET-FAIL`, `RULE-GPU-NVIDIA-XID-79`, `RULE-PCIE-AER-ERROR`, `RULE-NVME-CONTROLLER-RELIABILITY`, `RULE-HARDWARE-MCE-EDAC-ERROR`, `RULE-FILESYSTEM-IO-ERROR`, `RULE-HARDWARE-THERMAL-THROTTLING` |
| Firmware/platform/device | `RULE-PLATFORM-ACPI-FIRMWARE-ERROR`, `RULE-KERNEL-FIRMWARE-LOAD-FAIL`, `RULE-USB-ENUMERATION-FAIL`, `RULE-IOMMU-FAULT` |
| systemd/boot | `RULE-SYSTEMD-FAILED-SYSTEM`, `RULE-SYSTEMD-FAILED-USER`, `RULE-BOOT-DELAY` |

The real-machine run exposed five actionable observation categories:

| Raw source | Observation | Existing rule outcome |
| --- | --- | --- |
| `BTRFS-MISSING-INCOMPLETE-001` | `BTRFS-ERR-001` | deterministic rejection: privilege-limited `MISSING` |
| `SEGFAULT-WP-001` | `SEGFAULT-WP-001` | finding `P2` |
| `KERNEL-TAINT-001` | `KERNEL-TAINT-001` | finding `P2` |
| `PLATFORM-ACPI-FIRMWARE-ERROR-001` | `PLATFORM-ACPI-FIRMWARE-ERROR-001` | finding `P2` |
| `KRNL-INFO-001` | `KRNL-INFO-001` | informational finding |

## Real-machine evidence

Baseline source run:

`/tmp/lde-post-v014-real-world-baseline.Ig0ODd`

After-fix source run:

`/tmp/lde-post-v014-real-world-after.SbUaWq`

Both runs used the current source, read-only collection, no sudo/root, and
disposable report and snapshot destinations. Both completed with RC 0 and
reported:

- 69 commands executed;
- 5 actionable observations;
- 5 raw diagnostics;
- 4 evidence objects;
- 4 findings;
- 4 recommendations;
- 6 restrictions/limitations.

The before/after snapshot IDs, severities, lineage IDs, counts, and restriction
counts are identical. The only semantic report difference is the intended
ACPI recommendation/verification command change from `grep -iE` to `grep -iP`.

## End-to-end routing

### ACPI

`journal` source lines included:

```text
ACPI BIOS Error ... AE_NOT_FOUND
ACPI Error: Aborting method ... (AE_NOT_FOUND)
```

The collector produced a successful PCRE-filtered `CmdResult`; the raw
diagnostic was `PLATFORM-ACPI-FIRMWARE-ERROR-001`; the observation retained
that source ID; `EvidenceBuilder` produced
`EVIDENCE-PLATFORM-ACPI-FIRMWARE-ERROR-001-001` with direct/strong evidence;
`RULE-PLATFORM-ACPI-FIRMWARE-ERROR` emitted exactly one finding with the same
stable finding ID. The real report contains the finding and its recommendation.

### Kernel taint

The real journal contained all of the following existing event forms:

```text
Setting dangerous option enable_dc - tainting kernel
Setting dangerous option enable_psr - tainting kernel
vboxdrv: loading out-of-tree module taints kernel.
vboxdrv: module verification failed: signature and/or required key missing - tainting kernel
```

These four matches produced raw `KERNEL-TAINT-001`, observation
`KERNEL-TAINT-001`, direct/strong evidence
`EVIDENCE-KERNEL-TAINT-001-001`, and exactly one `KERNEL-TAINT-001` `P2`
finding. Existing precision semantics and negative controls remain intact.

### Btrfs privilege-limited output

The real source returned a `MISSING` line together with an unprivileged
inspection failure. The collector preserved the line in raw
`BTRFS-MISSING-INCOMPLETE-001` and retained `privilege_limited = true` in
`BTRFS-ERR-001`. The Btrfs rule deterministically emitted no finding, with
pipeline reason `privilege_limited_btrfs_missing`.

The report presents the raw output adjacent to an explicit warning that the
capture is incomplete and non-authoritative. The restriction list repeats the
same authority boundary. No Btrfs evidence object or finding is manufactured
from `MISSING` alone.

## Defect counts and disposition

- `CONFIRMED_FALSE_NEGATIVES = 0` in the current v0.1.4 real-machine run.
- `DQ_01_ACPI_FALSE_NEGATIVE = CLOSED`: the real ACPI event reaches one finding and lineage is preserved.
- `DQ_02_KERNEL_TAINT_FALSE_NEGATIVE = NOT_CONFIRMED`: all four real taint forms reach one finding; exact positive and negative replay passes.
- `CONFIRMED_FALSE_POSITIVES = 0`.
- `CONFIRMED_INCOMPLETE_EVIDENCE_DEFECTS = 0`: Btrfs authority and restriction handling are explicit and correct.
- `CONFIRMED_OVERLAP_OR_DEDUP_DEFECTS = 0`: shared-category and duplicate controls pass; no duplicate finding or evidence IDs are emitted.
- `CONFIRMED_RECOMMENDATION_DEFECTS = 2`.
- `HIGH_CONFIDENCE_DEFECTS_FIXED = 2`.
- `SPECULATIVE_NEW_DIAGNOSTICS = 0`.

## Implemented fixes

Both confirmed defects were executable-command dialect mismatches. Their
patterns use PCRE non-capturing groups, but the commands declared ERE mode.

- `diagnostic_rules.py`: ACPI recommended-diagnostics and verification commands now use `grep -iP`.
- `diagnostic_rules.py`: RCU recommended-diagnostics and verification commands now use `grep -iP`.
- `test_syscheck.py`: exact replay tests assert the corrected ACPI and RCU command forms.

No rule matching expression, finding classification, severity, recommendation
intent, evidence confidence, or public schema was changed.

## Replay, negative, lineage, and accounting coverage

Focused replay and control tests passed (`206 passed` for the diagnostic
selection, including ACPI, taint, Btrfs, RCU, overlap, stall, deduplication,
and pipeline-accounting coverage; `2 passed` for the packaging/version
selection).

The corpus covers:

- exact real ACPI positive lines, including `AE_NOT_FOUND`;
- ACPI near-miss rejection before raw emission;
- exact real taint forms for dangerous options, out-of-tree modules, and signature failure;
- taint near-misses and duplicate aggregation;
- Btrfs privilege-limited `MISSING` with raw preservation and deterministic rejection;
- exact RCU positive replay and the corrected executable recommendation;
- shared stall-family coexistence and no cross-family duplicate findings;
- raw → observation → evidence → finding IDs and source lineage;
- one finding per matched observation or a stable rejection reason.

`PIPELINE_ROUTING_ACCOUNTING = PASS`.

## False-positive and overlap audit

Existing negative controls continue to reject generic, incomplete, or unrelated
text. Shared `segfault` and `systemd_failed` categories retain their existing
mutually exclusive rule outcomes. Hardware/filesystem/stall families coexist
without cross-family swallowing or duplicate findings. No broad error/failed
regex, severity inflation, or new source domain was introduced.

## Recommendation audit

The four recommendations produced on the real machine remain present with the
same IDs and severities. The ACPI recommendation was corrected and executed
against the real journal: it returned 13 lines with RC 0 and no regex warning.
The RCU recommendation was corrected and exact positive replay passes; the
current machine had no RCU match, so its live command correctly returned RC 1
for no match.

## Evidence-based deferred backlog

`DEFERRED_BACKLOG_COUNT = 2`

1. User-session graphics/dms/quickshell warnings and errors were visible in the
   report source material, but no existing rule contract owns them. A future
   item needs an exact source signature, attribution boundary, replay corpus,
   and product decision before any finding is added.
2. `systemctl --user --failed` could not connect to the user scope bus in this
   run. The current report exposes this as a collection limitation rather than
   a failed-unit finding. A future item may assess whether an explicit
   source-failure presentation contract is warranted.

These are observed inputs, not new findings, and were intentionally not
implemented in this quality pack.

## Validation

- Focused replay tests: PASS (`206 passed`); focused packaging/version tests: PASS (`2 passed`).
- Full pytest: PASS (`902 passed in 3.87s`).
- `ruff format --check .`: PASS (`8 files already formatted`).
- `ruff check .`: PASS (`All checks passed!`).
- `git diff --check`: PASS.
- Real-machine source run before/after: PASS; RC 0 for both, no unexplained routing/count change.
- Real recommendation probes: PASS; ACPI exact command RC 0, RCU no-match RC 1.

## Changed paths and Git audit

Tracked working-tree changes:

- `diagnostic_rules.py`: 4 recommendation/verification string substitutions (`4 insertions, 4 deletions`).
- `test_syscheck.py`: 4 exact command assertions (`12 insertions`).

Review artifact created:

- `.agent-work/reviews/post-v0.1.4-real-world-quality-pack.md`

Tracked diff stat: `2 files changed, 16 insertions(+), 4 deletions(-)`.

`HEAD` remains `8906700440cc0f2f0f1b01e11418767c89c125b6`; the release tag
remains `v0.1.4`; the existing Git history is unchanged. No commit, push, tag,
or Brain write was performed.

## Compatibility and release boundary

- `PRODUCT_VERSION = 0.1.4`.
- `REPORT_COMPATIBILITY_VERSION = 2.1.0`.
- `SNAPSHOT_SCHEMA_VERSION = 3`.
- `REPORT_COMPATIBILITY_2_1_0_PRESERVED = YES`.
- `SNAPSHOT_SCHEMA_3_PRESERVED = YES`.
- `FALSE_POSITIVE_CONTRACT_PRESERVED = YES`.
- `NEW_DIAGNOSTIC_DOMAINS = 0`.

## NeuralEngine audit

`neural status` confirmed the configured Brain is initialized and
`TRUSTED_CURRENT`. The concrete read-only search `neural knowledge search
"LDE v0.1.4 post-release quality"` returned no matching knowledge. No Brain
record was read or written, and no historical record influenced the result;
the current checkout and fresh probes were authoritative.

## Final decision

- `POST_V0_1_4_REAL_WORLD_QUALITY_PACK = PASS`
- `HIGH_CONFIDENCE_CORRECTNESS_DEFECTS = CLOSED`
- `DQ_01_REAL_WORLD_REPLAY = PASS`
- `DQ_02_REAL_WORLD_REPLAY = PASS`
- `PIPELINE_ROUTING_ACCOUNTING = PASS`
- `BTRFS_INCOMPLETE_EVIDENCE_PRESENTATION = PASS`
- `FULL_TEST_SUITE = PASS`
- `RUFF = PASS`
- `REAL_MACHINE_PROOF = PASS`
- `GIT_HISTORY_UNCHANGED = YES`
- `READY_FOR_NEXT_PRODUCT_DECISION = YES`
