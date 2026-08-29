# LDE Iteration 44 — Pre-Ship Coverage / Overlap / False-Positive Audit

## Gate verdict

```text
PRE_SHIP_DIAGNOSTIC_AUDIT = FAIL
READY_FOR_REAL_MACHINE_E2E = NO
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```

The release gate is **FAIL**. Feature expansion remains frozen, but the current
diagnostic engine has deterministic contract-level integrity and completeness
defects that must be resolved before Iteration 45 real-machine E2E validation.
No product code was modified during this audit.

The blockers are:

1. Multiple qualifying `/` or `/dev/*` mounts reuse one storage finding ID and
   abort interpretation with `DuplicateFindingError`.
2. Bounded current-boot journal capture can omit a real event without emitting
   a restriction or an incomplete observation.
3. Legacy Btrfs raw records do not propagate capture truncation and can become
   `Certain`/`complete` findings from incomplete input.
4. The broad kernel-error display query tails to 50 lines before taint
   detection, so an older taint line can be silently missed.
5. Persisted `SystemSnapshot` output drops Finding-to-Evidence references and
   does not persist Evidence or RawDiagnostic objects, breaking durable
   Raw → Observation → Evidence → Finding traceability.

These are audit findings, not fixes. Remediation is intentionally deferred.

## Scope and method

This was a read-only release-gate review of the complete current engine:

- `constants.py`
- `syscheck.py`
- `diagnostic_rules.py`
- `test_syscheck.py`
- repository-local documentation and the Iteration 43 review

The review covered inventory reconciliation, AST-level registry checks, source
inspection, isolated collector/rule executions with synthetic inputs, a
cross-family coexistence corpus, exact regex near-misses, snapshot round-trip
structure, and the full test/lint gates. No network, privilege escalation,
production data, Brain write, Git mutation, or real-machine diagnostic capture
was performed.

## Checkpoint and repository safety

| Check | Result |
|---|---|
| `HEAD` | `9ce5043cebe56fd18552056e7e6069822c121fc5` |
| `origin/master` | Same commit |
| Branch | `master` |
| Product tracked diff before audit | Empty |
| Product tracked diff after audit | Empty; only this allowed review file was added |
| Staged changes | None |
| Existing local state | `.codex/` untracked; preserved and not touched |
| NeuralEngine | `neural status` only; Brain initialized but `BINDING_MISSING` |
| Brain writes | None |
| Git mutations | None |

The expected operator checkpoint is therefore confirmed. The report itself is
under the user-authorized `.agent-work/reviews/` path.

## Complete diagnostic inventory

The runtime has 27 current observation categories, 29 registered rules, 29
unique rule IDs, 27 `FindingKind` values, and 30 raw-constructor sites. The
29-to-27 difference is intentional at the rule level: `segfault` has two
mutually gated rules and `systemd_failed` has two scope-gated rules.

| Observation category | Rule ID(s) | FindingKind | Domain | Severity |
|---|---|---|---|---|
| `amdgpu_reset_fail` | `RULE-AMDGPU-RESET-FAIL` | `AMDGPU_RESET_FAIL` | hardware | P2 |
| `boot_time` | `RULE-BOOT-DELAY` | `BOOT_DELAY` | boot | P3 |
| `btrfs_error` | `RULE-BTRFS-DEVICE-ERROR` | `DEVICE_ERROR` | filesystem | P1 |
| `btrfs_scrub` | `RULE-BTRFS-SCRUB-STATUS` | `SCRUB_STATUS` | filesystem | P2 |
| `filesystem_io_error` | `RULE-FILESYSTEM-IO-ERROR` | `FILESYSTEM_IO_ERROR` | filesystem | P2 / P1 |
| `gpu_i915_hang` | `RULE-GPU-I915-HANG` | `GPU_I915_HANG` | hardware | P2 |
| `gpu_nvidia_xid_79` | `RULE-GPU-NVIDIA-XID-79` | `GPU_NVIDIA_XID_79` | hardware | P2 |
| `hardware_mce_edac_error` | `RULE-HARDWARE-MCE-EDAC-ERROR` | `HARDWARE_MCE_EDAC_ERROR` | hardware | P2 / P1 |
| `hardware_thermal_throttling` | `RULE-HARDWARE-THERMAL-THROTTLING` | `HARDWARE_THERMAL_THROTTLING` | hardware | P2 |
| `iommu_fault` | `RULE-IOMMU-FAULT` | `IOMMU_FAULT` | hardware | P1 |
| `kernel_count` | `RULE-KERNEL-COUNT` | `KERNEL_COUNT` | packages | Info |
| `kernel_firmware_load_fail` | `RULE-KERNEL-FIRMWARE-LOAD-FAIL` | `KERNEL_FIRMWARE_LOAD_FAIL` | kernel | P2 |
| `kernel_hard_lockup` | `RULE-KERNEL-HARD-LOCKUP` | `KERNEL_HARD_LOCKUP` | kernel | P1 |
| `kernel_hung_task` | `RULE-KERNEL-HUNG-TASK` | `KERNEL_HUNG_TASK` | kernel | P2 |
| `kernel_oops_panic` | `RULE-KERNEL-OOPS-PANIC` | `KERNEL_OOPS_PANIC` | kernel | P1 / P0 |
| `kernel_rcu_stall` | `RULE-KERNEL-RCU-STALL` | `KERNEL_RCU_STALL` | kernel | P1 |
| `kernel_soft_lockup` | `RULE-KERNEL-SOFT-LOCKUP` | `KERNEL_SOFT_LOCKUP` | kernel | P1 |
| `nvme_controller_reliability` | `RULE-NVME-CONTROLLER-RELIABILITY` | `NVME_CONTROLLER_RELIABILITY` | hardware | P2 / P1 |
| `oom_event` | `RULE-KERNEL-OOM` | `OOM_EVENT` | kernel | P2 |
| `pcie_aer_error` | `RULE-PCIE-AER-ERROR` | `PCIE_AER_ERROR` | hardware | P3 / P2 / P1 |
| `platform_acpi_firmware_error` | `RULE-PLATFORM-ACPI-FIRMWARE-ERROR` | `PLATFORM_ACPI_FIRMWARE_ERROR` | hardware | P2 |
| `segfault` | `RULE-SEGFAULT-WIREPLUMBER`, `RULE-SEGFAULT-GENERAL` | `SEGFAULT` | audio or kernel | P2 / P1 |
| `segfault_minor` | `RULE-SEGFAULT-MINOR` | `SEGFAULT` | kernel | P3 |
| `storage_usage` | `RULE-STORAGE-USAGE` | `STORAGE_USAGE` | storage | P1 / P2 |
| `systemd_failed` | `RULE-SYSTEMD-FAILED-SYSTEM`, `RULE-SYSTEMD-FAILED-USER` | `FAILED_UNIT` | systemd | P2 |
| `tainted` | `RULE-KERNEL-TAINT` | `KERNEL_TAINT` | kernel | P2 |
| `usb_enumeration_fail` | `RULE-USB-ENUMERATION-FAIL` | `USB_ENUMERATION_FAIL` | hardware | P2 |

The complete `FindingKind` enum also contains `GENERAL`. It is not a current
producer category; it is the dataclass default and the snapshot-migration
fallback (`syscheck.py:196`, `syscheck.py:230`, `syscheck.py:5276`). That is
acceptable as a compatibility fallback, but it is not an active diagnostic
classification.

### Registry and orphan reconciliation

Static reconciliation found:

- 27 unique current categories in the raw-to-observation mapping.
- 27 categories classified by policy: 24 direct `_BY_CATEGORY` entries plus
  special handling for `segfault`, `systemd_failed`, and `storage_usage`.
- 27 categories supported by the registered rule set.
- 29 registered rules with unique IDs.
- No current category without a rule, policy classification, or observation
  mapping.
- No rule category outside the policy or observation mapping.
- No duplicate raw source IDs in the 30 constructor sites.

The runtime rule engine correctly rejects an unsupported observation category
and detects duplicate Finding/Evidence IDs. The defect below is that a current
collector can generate those duplicates before the engine gets a chance to
protect the output.

## Findings

### I44-01 — Storage threshold findings collide across qualifying mounts

**Severity:** High — release blocker  
**Confidence:** Certain  
**Status:** Reproduced

`collect_storage()` emits the fixed source IDs
`STORAGE-USAGE-CRITICAL` and `STORAGE-USAGE-WARNING` for every qualifying
mount (`syscheck.py:2477-2505`). The raw-to-observation mapping uses the same
observation ID for each such record, and the rule uses that ID as the Finding
ID.

Exact synthetic reproduction input:

```text
Filesystem Size Used Avail Use% Mounted on
/dev/sda1  100G  95G  5G  95%  /
/dev/sdb1  100G  96G  4G  96%  /dev/data
```

With the other storage command results successful and empty, the observed
result was:

```text
raw_ids = ['STORAGE-USAGE-CRITICAL', 'STORAGE-USAGE-CRITICAL']
observation_ids = ['STORAGE-USAGE-CRITICAL', 'STORAGE-USAGE-CRITICAL']
interpretation_error = DuplicateFindingError: Duplicate finding_id: STORAGE-USAGE-CRITICAL
```

This is a current supported input shape because the collector explicitly
accepts `/dev/*` mountpoints. A report can therefore abort instead of
returning a complete diagnostic result. The analogous warning path has the
same collision mechanism.

### I44-02 — Bounded current-boot capture can silently lose findings

**Severity:** High — release blocker  
**Confidence:** Certain  
**Status:** Reproduced

`run_cmd()` retains only the first 5000 bytes per stream while draining the
complete subprocess stream and setting `CmdResult.truncated`
(`syscheck.py:318-334`). The current-boot diagnostic extraction emits a raw
record only when the retained output contains a matching line. If a matching
event is in the omitted suffix, no RawDiagnostic, Observation, Finding, or
restriction is emitted.

Exact reproduction shape:

```python
full = ("kernel: routine message\n" * 300) + \
       "kernel: Out of memory: Killed process 123 (worker)\n"
result.stdout = full[:5000]
result.truncated = True
```

The collector result was:

```text
captured_truncated = True
oom_raws = 0
oom_observations = 0
restrictions = []
```

The same omission shape applies to the i915, AMDGPU, NVIDIA Xid, PCIe,
NVMe, MCE/EDAC, filesystem I/O, thermal, oops/panic, stall, platform,
firmware, USB, and IOMMU event paths when their matching event is outside the
retained prefix. The new event families correctly propagate truncation when a
record is emitted (`_capture_payload`, `syscheck.py:438-442`), but that does
not make the no-record path complete.

### I44-03 — Legacy Btrfs completeness is overstated

**Severity:** High — release blocker  
**Confidence:** Certain  
**Status:** Reproduced

The Btrfs device-stats collector creates `RawDiagnostic` directly from the
parsed `CmdResult` without `_capture_payload`
(`syscheck.py:2431-2455`). `_raw_to_observation()` then forces
`btrfs_error.data_complete=True` (`syscheck.py:3948-3959`) regardless of the
source capture marker.

Exact reproduction input:

```text
btrfs_stats.stdout = "write_io_errs 1\n"
btrfs_stats.execution_status = "ok"
btrfs_stats.truncated = True
```

Observed pipeline output:

```text
raw_payload = {'device_error_counters': {'write_io_errs': 1}}
observation_data_complete = True
finding_confidence = Certain
evidence_completeness = complete
```

This violates the declared confidence and completeness semantics. Similar
legacy direct raw producers exist for Btrfs scrub, systemd failed units, boot
delay, kernel count, and storage usage (`syscheck.py:2461-2505`,
`syscheck.py:3448-3531`, `syscheck.py:3625-3658`). They do not carry the
originating command's `truncated` state into the raw payload.

### I44-04 — Kernel-error tail hides older taint events

**Severity:** High — release blocker  
**Confidence:** Certain  
**Status:** Reproduced

The `kernel_errors` task filters current-boot kernel output with the broad
`RE_KERNEL_ERROR` expression and then applies `tail -50`
(`syscheck.py:2520-2528`). Taint detection later searches only that retained
output (`syscheck.py:2785-2796`).

Exact adversarial stream:

```text
kernel: Tainted: G W
kernel: BUG: benign 00
kernel: BUG: benign 01
...
kernel: BUG: benign 49
```

The generated status-aware pipeline returned 50 lines, all benign `BUG`
lines; `Tainted:` was not retained. Passing that result to
`collect_kernel_hw()` produced:

```text
command_status = ok
tainted_line_retained = False
taint_raws = 0
restrictions = []
```

The deliberate `tail` is not marked as truncation, so confidence and
completeness metadata cannot warn that older matching lines were discarded.
This is an obvious contract-level false-negative risk for kernel taint.

### I44-05 — Snapshot persistence breaks evidence lineage

**Severity:** Medium/High — release blocker if snapshots are the durable
diagnostic artifact  
**Confidence:** Certain  
**Status:** Reproduced

Runtime `Finding` objects contain `evidence_ids`, and runtime Evidence objects
carry source observation and raw IDs. However, `FindingSnapshot` has no
`evidence_ids` field (`syscheck.py:4875-4930`), `SystemSnapshot` has no Evidence
or RawDiagnostic collection (`syscheck.py:4933-4957`), and `build_snapshot()`
does not copy them (`syscheck.py:5188-5213`).

Exact isolated result:

```text
finding_has_evidence_ids = False
top_level_evidence = False
top_level_raw_diagnostics = False
```

The persisted snapshot retains Finding-to-Observation references but cannot
reconstruct the Evidence or Raw source for a Finding. Snapshot validation also
does not validate evidence references. This makes the durable artifact
incomplete for the required Raw → Observation → Evidence → Finding model.

### I44-06 — Kernel taint wording asserts an unproven cause

**Severity:** Medium  
**Confidence:** Certain  
**Status:** Reproduced

`KernelTaintRule` unconditionally states
`Załadowano moduł spoza drzewa jądra.` and recommends switching to open
drivers (`diagnostic_rules.py:286-314`). The rule receives only a generic
`Tainted:` observation and does not decode or condition its wording on the
taint flags.

Two identical rule evaluations with `taint_flags=('W',)` and
`taint_flags=('O',)` produced the same interpretation and remediation. The
finding therefore converts a generic taint marker into a specific module
cause and driver recommendation without evidence in the current pipeline.

### I44-07 — Btrfs scrub classifier can overstate “never executed”

**Severity:** Medium  
**Confidence:** Medium  
**Status:** Reproduced semantic risk

`_classify_btrfs_status()` maps any stdout/stderr containing `no scrub` to
`no_scrub` (`syscheck.py:2462` call site and helper near the storage helpers),
and the rule title is “Btrfs scrub nigdy nie był wykonany”
(`diagnostic_rules.py:118-146`). The exact synthetic phrase
`No scrub is running` maps to `no_scrub`.

The local `btrfs-scrub` manual page states that `scrub status` reports the
last finished or cancelled scrub when no scrub is currently running. The
classifier does not distinguish “not currently running” from “no history”;
the resulting title can therefore be a false positive or an overclaim when
the command reports an inactive scrub rather than no completed scrub.

### I44-08 — Timestamp/source identity is not carried into Raw records

**Severity:** Medium  
**Confidence:** Certain  
**Status:** Confirmed by AST inventory

`CmdResult` records `collected_at` and `truncated`
(`syscheck.py:103-114`, `syscheck.py:316`, `syscheck.py:385-394`), but all 30
`RawDiagnostic(...)` constructor sites omit `collected_at`. An AST inventory
reported:

```text
RAW_CONSTRUCTORS = 30
RAW_WITH_COLLECTED_AT = []
RAW_WITHOUT_COLLECTED_AT_COUNT = 30
```

New kernel event payloads do record `journal_scope=current_boot_kernel` and a
logical `source_query` (`syscheck.py:2827-3379`), which is useful and was
verified. The durable lineage still lacks the exact collection timestamp,
boot identity, command result status, and raw source object.

## Classification completeness and status-aware safety

### Classification

The runtime policy is complete for all 27 current categories. The special
branching is coherent:

- `segfault` selects WirePlumber/audio or system-wide/kernel based on the
  subtype, and its two rules are mutually gated.
- `systemd_failed` selects system or user based on scope, and its two rules
  are mutually gated.
- `storage_usage` uses the storage classification with severity selected by
  threshold state.

The existing test named `TestClassificationPolicyCompleteness` only enumerates
13 categories (`test_syscheck.py:2494-2522`) and omits all categories added by
the later reliability packs. Runtime reconciliation found no missing mapping,
but the test is not a complete guard for the current inventory.

### Collector status handling

The shared command runner is bounded, non-shell by default, timeout-aware,
captures stdout/stderr, drains streams, and distinguishes `ok`, `not_found`,
`permission_denied`, `timeout`, and `error` (`syscheck.py:302-428`). New
current-boot event extractors require `is_ok()` and retain a capture marker.
The shared journal pipeline preserves upstream and grep statuses using
`PIPESTATUS` (`syscheck.py:758-816`). Those are positive controls.

The safety boundary is incomplete for:

- omitted matches after bounded capture;
- deliberate `tail -50` loss in the taint source;
- direct legacy raw constructors that lose command status/truncation metadata;
- the duplicate storage IDs described in I44-01.

## Current-boot and source provenance

The new kernel reliability families use `journalctl -b -k --no-pager` and
payload fields that identify `current_boot_kernel` plus the logical query name.
The segfault path uses current-boot `journalctl -b` and restricts counting to
kernel lines. This is sufficient for the intended current-boot scope at the
live collector boundary.

The provenance is only partial as a durable contract: no raw record carries
the `CmdResult.collected_at`, exact command status, exact boot ID, or raw
command output object. The report output shows fallback command output, but
the snapshot model does not preserve the complete source lineage.

## Regex and predicate precision

The focused adversarial corpus exercised one positive representative for each
of the 18 current kernel event predicate families and these near-misses:

| Family | Positive representative | Near-miss / expected result |
|---|---|---|
| OOM | `Out of memory: Killed process 123` | cgroup-only OOM line is excluded by collector policy |
| i915 | `i915 ... GPU HANG:` | GuC firmware loaded successfully: no hit |
| AMDGPU | `amdgpu ... GPU reset failed` | `GPU reset succeeded`: no hit |
| NVIDIA | `NVRM: Xid (...): 79` | Xid 179 and Xid 790: no hit |
| PCIe AER | `Uncorrected (Non-Fatal) error received` | `Corrected error received`: intentional P3 hit |
| NVMe | `nvme nvme0: I/O timeout, aborting` | normal queue announcement: no hit |
| MCE/EDAC | `[Hardware Error] ... Machine Check` | MCE capability information: no hit |
| filesystem I/O | `BTRFS error ... I/O failure` | no matching normal-success line: no hit |
| thermal | `temperature above threshold ... throttled` | normal 45 C temperature: no hit |
| oops/panic | `BUG: unable to handle kernel ...` | ordinary non-kernel BUG text was not used as a positive corpus item |
| soft lockup | `BUG: soft lockup ... CPU#2` | unrelated watchdog text was not used as a positive corpus item |
| hard lockup | `Watchdog detected hard LOCKUP` | unrelated normal watchdog text was not used as a positive corpus item |
| hung task | `task ... blocked for more than 120 seconds` | ordinary task line: no hit |
| RCU | `rcu_preempt detected stalls` | RCU grace-period starved for 1 jiffies: no hit |
| ACPI | `ACPI BIOS Error ...` | generic ACPI initialization: no hit |
| firmware load | `firmware: failed to load ...` | direct-loading firmware successfully: no hit |
| USB | `device descriptor read/64, error -71` | New USB device found: no hit |
| IOMMU | `DMAR: [DMA Read] ... Request device` | `IOMMU enabled`: no hit |

The executed exact-regex result had one intended family hit for every positive
representative. The only near-miss hit was corrected AER, which is explicitly
part of `RE_PCIE_AER` and is mapped to P3. No cross-family false hit appeared
in this corpus.

This result supports predicate precision for the tested lines; it does not
prove completeness across kernel/vendor message variants. The most important
precision residual is semantic rather than regex-based: Btrfs scrub status and
kernel taint wording can overstate what the matched marker proves.

## Cross-family collision and coexistence matrix

The shared union captures intentionally overlap at the source-query level:

| Shared source | Split diagnostic families | Collision result |
|---|---|---|
| `kernel_errors` | display errors, taint | taint can be lost to `tail -50`; no duplicate when retained |
| `kernel_stall_reliability` | soft lockup, hard lockup, hung task, RCU stall | separate category extraction; intended coexistence |
| `platform_device_reliability` | ACPI, firmware load, USB, IOMMU | separate category extraction; intended coexistence |
| `segfault` | WirePlumber vs system-wide rule | mutually exclusive subtype gates |
| `systemd_failed` | system vs user rule | mutually exclusive scope gates |
| `df -h` | critical/warning storage thresholds | same-state multi-mount ID collision; blocker |

The full synthetic coexistence corpus contained valid representatives for
OOM, i915, AMDGPU, NVIDIA, PCIe, NVMe, MCE/EDAC, filesystem I/O, thermal,
oops, soft lockup, hard lockup, hung task, RCU, ACPI, firmware, USB, IOMMU,
and a three-line system-wide segfault. It produced:

```text
raw categories = 19
observations = 19
findings = 19
duplicate finding IDs = False
engine ambiguity = none
```

This is a PASS for independent-family coexistence when each source returns a
single valid result. It does not override the multi-mount storage failure or
the bounded omission findings.

## Raw → Observation → Evidence → Finding semantics

### Positive controls

- `RawDiagnostic` is intended to contain source/category/payload only and not
  severity or interpretation (`syscheck.py:263-275`).
- `_derive_observations()` consumes only raw records and creates deterministic
  observations (`syscheck.py:3930-3940`).
- `derive_confidence()` degrades to `Guessing` for contradictory,
  incomplete, or source-less observations and returns `Certain` only for a
  complete direct non-inferred observation (`syscheck.py:280-299`).
- `EvidenceBuilder` has branches for all 27 current categories and runtime
  Findings carry Evidence IDs and source observation IDs.
- The rule engine enforces one nonempty finding per observation and rejects
  duplicate Finding/Evidence IDs (`diagnostic_rules.py:1832-1868`).

### Failures and gaps

- Legacy raw producers bypass capture metadata, creating the I44-03
  confidence/completeness defect.
- Unknown raw categories are silently ignored by `_raw_to_observation()`
  rather than becoming an explicit unsupported/orphan error
  (`syscheck.py:3941-4295`). No current collector emits an unknown category,
  but this weakens future registry-integrity detection.
- Runtime Evidence is not included in `SystemSnapshot` and Finding evidence
  references are dropped, as shown by I44-05.
- `FindingClassification.__post_init__` validates domain/kind but does not
  runtime-validate actionability or recommendation-intent values. Normal
  policy output is typed correctly, but malformed direct construction is not
  fully guarded.

## Truncation and completeness matrix

| Boundary | Intended behavior | Audit result |
|---|---|---|
| subprocess stream → `CmdResult` | retain bounded output and mark truncation | PASS |
| `CmdResult` → new journal Raw | add `capture_truncated` | PASS when a matching raw is emitted |
| new journal Raw → Observation | `data_complete=False` when marked | PASS |
| Observation → confidence/Evidence | incomplete data degrades confidence and completeness | PASS for marked observations |
| omitted event after bounded capture | emit absence/incomplete restriction | FAIL; silent false negative, I44-02 |
| `kernel_errors` tail omission | preserve incomplete status | FAIL; deliberate tail is unmarked, I44-04 |
| Btrfs stats Raw → Observation | carry source truncation | FAIL; forced complete, I44-03 |
| systemd/boot/kernel-count/storage Raw → Observation | carry source truncation | FAIL-risk; direct raw constructors omit it |
| runtime evidence → snapshot | preserve complete lineage | FAIL; I44-05 |

## False-positive and non-causal wording audit

Most later reliability rules explicitly say that a journal event is recorded,
may be historical, does not confirm hardware failure, and does not establish
root cause. That is appropriate for descriptive diagnostics.

Exceptions or residual risks:

- Kernel taint unconditionally asserts an out-of-tree module and recommends
  open drivers (I44-06).
- General segfault wording says hardware damage is possible, and Btrfs device
  wording says possible hardware; both are qualified hypotheses, but neither
  is established by the matching marker alone.
- Boot-delay remediation says to disable unnecessary services based on a
  duration threshold without a causal service finding
  (`diagnostic_rules.py:1728-1737`).
- Kernel-count Info output includes `sudo pacman -Rs <kernel>` despite its
  informational classification and without a precise removable-package
  finding (`diagnostic_rules.py:1688-1698`). This is guarded by a warning to
  retain a fallback kernel but remains operationally stronger than the
  evidence warrants.
- Btrfs scrub title overstates “never executed” for an ambiguous inactive
  status (I44-07).

No rule executes these recommendations. They are output-only, but the
recommendation text should remain non-causal and proportionate to evidence.

## Severity consistency

The explicit dynamic mappings are internally coherent:

- PCIe AER: corrected P3, non-fatal P2, fatal P1.
- NVMe timeout/reset P2, reset failure P1.
- MCE/EDAC corrected P2, uncorrected P1.
- filesystem I/O ordinary P2, critical/fatal P1.
- kernel oops P1, kernel panic P0.
- storage warning P2, critical P1.

The remaining calibration concerns are not treated as proven threshold
violations because the repository does not provide a severity policy with
numerical acceptance criteria:

- kernel taint is P2 while its risk text says low/informational and policy
  actionability is conditional/monitor;
- kernel-count is Info but includes a potentially destructive package-removal
  command;
- the general multi-segfault P1 is a severe classification for an event whose
  interpretation remains only “possible hardware.”

These are policy-review items, not grounds for inventing new thresholds in
this frozen audit.

## Test architecture and coverage

Observed test structure:

- one test module, `test_syscheck.py`;
- 89 `Test*` classes;
- 648 `test_*` methods;
- 51 parametrization decorators;
- no pytest fixtures;
- no Hypothesis/property-test references;
- no installed `coverage` executable and no pytest-cov/coverage configuration
  references;
- `pytest --collect-only -q`: 826 tests collected.

The suite has valuable focused coverage for command status handling, bounded
capture markers for the 14 newest event families, policy/rule behavior,
Evidence construction, recommendations, snapshots, and each later diagnostic
pack.

Coverage gaps relevant to this release gate:

- `TestCaptureCompleteness` covers the 14 newest categories only
  (`test_syscheck.py:929-961`), not the legacy Btrfs/systemd/boot/kernel-count
  /storage producers.
- `TestClassificationPolicyCompleteness` covers only 13 categories
  (`test_syscheck.py:2494-2522`).
- `TestMixedRuntimeElevenNative` remains named and structured around the old
  eleven-rule set (`test_syscheck.py:4298-4363`) and does not provide a full
  current 29-rule invariant.
- The confidence tests include a membership-only assertion and an empty
  `pass` test (`test_syscheck.py:1199-1210`).
- No test asserts persisted Finding evidence IDs, Evidence objects, Raw
  records, or source timestamp retention.
- No test exercises multiple qualifying storage mounts.
- No test exercises matches beyond the 5000-byte retained prefix or beyond
  the `kernel_errors` tail.
- No checked-in adversarial kernel-line corpus or property-based predicate
  test exists.

The 826-test suite is a meaningful regression suite, but its green result is
not sufficient to close the blockers found by this audit.

## Validation evidence

### Before report creation

```text
ruff check .                         PASS — All checks passed!
pytest -q                           environment collision: 817 passed, 9 errors
TMPDIR=/tmp pytest -q                PASS — 826 passed in 3.02s
```

The first plain pytest invocation attempted to use the unwritable project
temporary path `<REDACTED-PATH>`. The 9 errors were
`FileExistsError`/cleanup failures from that environment collision, not
product test failures. Re-running with the writable `/tmp` temporary path
collected and passed the complete 826-test suite.

### After report creation

```text
ruff check .                         PASS — All checks passed!
ruff format --check .                PASS — 4 files already formatted
PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp pytest -q
                                    PASS — 826 passed in 3.03s
```

The post-report run did not alter product code or tests.

### Read-only audit executions

- rule/category/FindingKind/registry AST reconciliation — PASS for current
  inventory; counts recorded above;
- exact-regex positive/near-miss corpus — PASS for tested cases;
- 19-family coexistence corpus — PASS, 19 observations and 19 findings,
  no duplicate IDs or ambiguity;
- two qualifying storage mounts — FAIL, exact `DuplicateFindingError`
  reproduction I44-01;
- bounded omitted OOM event — FAIL, silent no-record reproduction I44-02;
- truncated Btrfs stats — FAIL, `Certain`/`complete` reproduction I44-03;
- taint older than the `tail -50` window — FAIL, silent no-record
  reproduction I44-04;
- snapshot lineage probe — FAIL, evidence/raw persistence omission I44-05;
- taint wording with two flag sets — FAIL, invariant unproven causal text
  I44-06;
- local `btrfs-scrub` manual-page semantic check — supports I44-07 risk;
- raw timestamp AST inventory — FAIL, 30/30 constructors omit
  `collected_at` I44-08.

## Required disposition

Do not advance this checkpoint to real-machine E2E under the current state.
The next authorized work should remain stabilization within the frozen feature
set: address the duplicate-ID and completeness/lineage contracts, add focused
regression tests for the exact reproductions above, rerun the full release
gate, and only then reassess Iteration 45.

```text
FEATURE_EXPANSION_REMAINS_FROZEN = YES
NEXT_MILESTONE = Iteration 45 — Real-Machine End-to-End Validation (blocked by this FAIL gate)
```
