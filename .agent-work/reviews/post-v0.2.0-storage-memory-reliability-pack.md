# Post-v0.2.0 storage and memory reliability pack

Date: 2026-08-31

## 1. Checkpoint

- Baseline release commit, `HEAD`, `origin/master`, and peeled `v0.2.0` target: `76f9bdb6c8409bd3e982ec33eca9727f0edebf99`.
- Baseline product/report/schema: `0.2.0 / 2.1.0 / 3`.
- Baseline full suite: `910` tests.
- `neural status` was run read-only. Neural home was `/run/media/<USER>/<VOLUME>/NeuralEngine-State`, Brain Trust was `TRUSTED_CURRENT`, and no Brain write was performed.
- The initial worktree had no tracked changes. Existing untracked `.agent-work/reviews/v0.1.4-release-result.md`, `.agent-work/reviews/v0.1.5-release-result.md`, `.agent-work/reviews/v0.2.0-release-result.md`, `.codex/`, `build/`, and `linux_diagnostic_engine.egg-info/` were preserved. The untracked `uv.lock` created during the local `uv` status probe was also not removed or staged.

## 2. Existing coverage inventory

The inventory covers every current rule/source in the requested storage and memory area.

| Rule / Finding | Source and positive signature | Negative or limitation control | Evidence / aggregation / recommendation |
| --- | --- | --- | --- |
| `RULE-BTRFS-DEVICE-ERROR` / `BTRFS-ERR-001` | `btrfs device stats /` nonzero `*_errs`; structured `devid ... path ... MISSING` from `btrfs filesystem show /` | all counters zero, healthy device record, malformed/truncated output, permission-limited MISSING | filesystem state; one Btrfs device layer; P1; exact Btrfs state verification |
| `RULE-BTRFS-SCRUB-STATUS` / `BTRFS-SCRUB-001` | `btrfs scrub status /` reports no history | running/inactive scrub is not no-history; permission/tool failure is a restriction | filesystem state; one scrub-history finding; P2; scrub status/start commands |
| `RULE-NVME-CONTROLLER-RELIABILITY` / `NVME-CONTROLLER-RESET-001` | current-boot kernel lines for timeout, abort/reset, controller down, or failed reset | initialization, configured timeout, completed I/O, failed query, empty/truncated query | journal event; one aggregated event finding; P2/P1; exact journal replay plus external health-tool check |
| `RULE-FILESYSTEM-IO-ERROR` / `FS-IO-ERROR-001` | current-boot kernel Buffer I/O, block request, device I/O, EXT4/XFS/Btrfs errors, critical medium error, or explicit read-only remount | successful I/O, filesystem mount/info, unrelated service errors, failed/empty query | journal event; one finding with `event_families`; P2/P1; exact positive-signature grep |
| `RULE-KERNEL-OOM` / `KERNEL-OOM-001` | current-boot kernel `invoked oom-killer`, `oom-killer:`, or `Out of memory: Killed process` | systemd-oomd text, memcg-only text, oom_reaper-only text, pressure without a kill, failed/empty/truncated query | journal event; one kernel-OOM event; P2; `free`, swap, process, and journal checks |
| `RULE-HARDWARE-MCE-EDAC-ERROR` / `HW-MCE-EDAC-001` | current-boot MCE/Hardware Error/Machine Check or EDAC CE/UE | initialization-only lines and unrelated kernel errors | journal event; corrected/uncorrected aggregation; P2/P1; journal plus rasdaemon/edac-util if available |

Report-only signals with no Finding owner were identified: `free -h`, `zramctl`, memory-ranked `ps`, `sensors` temperatures, `lspci -k`, `nvme list`, and generic storage usage below thresholds. No threshold or interpretation was invented for them.

## 3. Real-machine baseline

Baseline run:

- Report: `/tmp/lde-v03-baseline.HUUi7v/reports/report-<HOST>-20260831-122503.md`
- Snapshot: `/tmp/lde-v03-baseline.HUUi7v/snapshot.json`
- Return code: `0`.
- Runtime counts: 69 commands, 6 RAW diagnostics, 6 Observations, 5 Evidence objects, 4 Findings, 4 Recommendations, 7 Restrictions.
- Btrfs `filesystem show` exposed a MISSING line with `Permission denied` in stderr; it was correctly treated as incomplete/non-authoritative. Device counters were all zero. Scrub status was unavailable without privilege. `nvme` was not installed; `sensors` exposed temperatures only.
- No current-boot NVMe event, filesystem I/O event, OOM event, positive MCE/EDAC event, or positive PCIe AER event was observed.
- Evidence classification: Btrfs MISSING and scrub failure were source-limited; zero device counters were healthy for that counter source only; NVMe temperatures/driver presence were informational; no OOM output did not prove absence of memory pressure; the user-systemd query failure remained explicit.

## 4. NVMe contract

PASS for the collected, bounded event contract. The existing source is the current-boot kernel journal and matches only explicit controller timeout/reset/failure signatures. Positive, near-miss, failed-query, empty-query, severity, provenance, and pipeline tests pass. PCIe AER plus NVMe recovery remains two independently actionable event layers.

NVMe SMART/health-counter coverage is not claimed. This checkout has no `nvme` executable, and the available `smartctl` probe could not open `/dev/nvme0` or `/dev/nvme1` in this environment. Critical warning, media/data-integrity error, unsafe-shutdown, SMART-unavailable, and health-counter semantics remain deferred.

## 5. Filesystem/block contract

PASS. The collector still emits one stable `FS-IO-ERROR-001` event finding for matching current-boot kernel evidence and does not emit for source failure, successful I/O, mount/info text, or unrelated services. The payload now records deterministic `event_families`: `block_io`, `filesystem`, `filesystem_corruption`, or `filesystem_read_only` where applicable. Device reset/recovery text without an exact filesystem/block signature remains a near miss and does not create a finding.

The recommendation grep was tightened to the same positive contract. The prior broad `Buffer I/O` pattern falsely matched `Buffer I/O completed successfully`; that defect is fixed and replay-tested.

## 6. Btrfs authority contract

PASS. MISSING is recognized only on a structured `devid ... path ... MISSING` device record. Healthy text such as `No missing devices found` is not a MISSING state. A successful, complete, permission-clean `filesystem show` capture produces the new raw source `BTRFS-DEVICE-MISSING-001` and the existing stable `BTRFS-ERR-001` Finding. Permission-limited, failed, malformed, or truncated captures preserve evidence or restrictions and cannot produce that Finding.

All-zero counters remain non-findings; nonzero counters remain one Btrfs device-error Finding. Scrub inactive remains distinct from no scrub history. No repair, replace, scrub start, or other mutating Btrfs command was executed.

## 7. Memory/OOM contract

PASS for the bounded kernel OOM and MCE/EDAC event contract. Kernel OOM requires an exact current-boot marker and excludes systemd-oomd, memcg-only, oom_reaper-only, ordinary pressure text, and failed/empty queries. The Finding states that it does not prove ongoing pressure. MCE/EDAC remains an independent hardware-memory signal and does not get merged with OOM.

Live PSI thresholds, systemd-oomd state, and application allocation failures are not collected by v0.2.0 and were not promoted into speculative Findings.

## 8. Overlap/aggregation analysis

PASS. Deterministic replay confirms:

- NVMe timeout plus block-I/O error: two Findings, NVMe and filesystem/block layers.
- NVMe reset failure plus filesystem read-only remount: two Findings, independently actionable.
- Btrfs counter error plus block-I/O error: two Findings, filesystem-state and kernel-event layers.
- OOM plus unrelated MCE: two Findings, resource event and hardware event.
- PCIe AER plus NVMe recovery: two Findings, bus event and controller event.

No probabilistic correlator or root-cause claim was added. Multiple matches within one source remain deterministically aggregated to one Finding per stable diagnostic layer.

## 9. Implemented changes

- Hardened Btrfs MISSING parsing and authority gating in `syscheck.py`.
- Added authoritative Btrfs missing-device raw source `BTRFS-DEVICE-MISSING-001`; the public Finding ID remains `BTRFS-ERR-001`.
- Added explicit non-authoritative restriction for malformed/unavailable Btrfs device inventory.
- Added filesystem event-family attribution and explicit read-only-remount signature in `constants.py` and `syscheck.py`.
- Tightened exact filesystem recommendation/verification commands in `diagnostic_rules.py`.
- Added focused contract tests and the sanitized replay corpus under `.agent-work/replay/v0.3-storage-memory-reliability/`.

High-confidence defects fixed: `2`. New diagnostic source IDs: `1`. Existing diagnostics hardened: `2` (`BTRFS-ERR-001`, `FS-IO-ERROR-001`). No new public snapshot schema or Finding ID was introduced.

## 10. Rejected/deferred candidates

- No NVMe SMART parser or health counter Finding: tool availability, device access, output variants, and counter semantics were not proven.
- No memory-pressure threshold Finding: `free -h`, zram, process listings, and temperatures are measurements without a validated threshold/aggregation contract here.
- No systemd-oomd Finding: it is not collected and must not be inferred from pressure text.
- No generic storage/kernel-error correlator: layer ownership and independent actionability are not sufficient for a probabilistic inference.
- No compatibility/version/schema change, release preparation, Git publication, or Brain write.

## 11. Replay corpus

The deterministic sanitized corpus is at `.agent-work/replay/v0.3-storage-memory-reliability/` and contains 17 text fixtures plus a manifest README. It includes healthy/authoritative-missing/limited-missing/malformed/truncated Btrfs, zero/nonzero counters, scrub healthy/no-history, NVMe failure/near miss, filesystem block/near miss/read-only, OOM failure/near miss, and overlap events. Fixtures contain no live hostnames, UUIDs, usernames, serial numbers, or live command output.

The corpus manifest test verifies the exact file set and sanitation checks. Corpus tests exercise both positive reachability and negative/rejection behavior through the production collector, Observation, Evidence, Finding, and recommendation paths.

## 12. Recommendation execution proof

PASS. The authoritative Btrfs Finding's exact `btrfs filesystem show /` recommendation and verification command were executed against a disposable fake `btrfs` executable emitting the sanitized replay. The filesystem Finding's exact `journalctl ... | grep -iP ...` recommendation and verification commands were executed against a disposable fake `journalctl` executable. Positive output and negative return behavior were asserted.

The negative replay `Buffer I/O completed successfully` now returns no match. No invasive remediation command was executed.

## 13. Pipeline accounting

PASS. Final instrumented workstation run: `69 commands → 6 RAW → 6 OBS → 5 Evidence → 4 Findings`, with 4 Recommendations and 7 Restrictions. Every Observation ended in a Finding or stable rejection:

| RAW | OBS | Outcome |
| --- | --- | --- |
| `BTRFS-MISSING-INCOMPLETE-001` | `BTRFS-ERR-001` | rejected: `privilege_limited_btrfs_missing` |
| `SEGFAULT-WP-001` | `SEGFAULT-WP-001` | Finding |
| `KERNEL-TAINT-001` | `KERNEL-TAINT-001` | Finding |
| `PLATFORM-ACPI-FIRMWARE-ERROR-001` | `PLATFORM-ACPI-FIRMWARE-ERROR-001` | Finding |
| `SYSD-USR-SOURCE-FAIL-001` | `SYSD-USR-SOURCE-FAIL-001` | rejected: `user_systemd_query_unavailable` |
| `KRNL-INFO-001` | `KRNL-INFO-001` | Finding |

The same RAW/OBS/Finding/Recommendation/Restriction ID sets were observed before and after; the built-in comparator reported no significant changes.

## 14. Focused tests

- Command: `env -u PYTEST_ADDOPTS TMPDIR=/tmp TMP=/tmp TEMP=/tmp PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -k 'V03StorageMemoryReliabilityReplayCorpus or BtrfsClassification or BtrfsCollectorPath or FilesystemIoErrorDiagnostic'`
- Result: `60 passed, 876 deselected`.
- This includes authority boundary, malformed/truncated handling, event-family attribution, exact recommendation execution, positive/negative corpus replay, and all five overlap cases.

## 15. Full validation

- Exact final command: `env -u PYTEST_ADDOPTS TMPDIR=/tmp TMP=/tmp TEMP=/tmp PYTHONDONTWRITEBYTECODE=1 python -m pytest -q`
- Result: `936 passed in 3.99s`.
- `ruff format --check .`: PASS; 8 files already formatted.
- `ruff check .`: PASS.
- `git diff --check`: PASS.

The tracked diff exceeds 500 lines, so the full diff is not reproduced here. SHA-256 of `git diff --binary`: `f88f028c974cfc45dda75870689e4da88b1127d3228fcecbde8a35583a7bbafe`.

## 16. Real-machine before/after

Final candidate run:

- Report: `/tmp/lde-v03-final2.2Xir8y/reports/report-<HOST>-20260831-124758.md`.
- Snapshot: `/tmp/lde-v03-final2.2Xir8y/snapshot.json`.
- Return code: `0`; 69 commands; 6 actionable observations in CLI summary.

Baseline and candidate snapshots both contain 6 RAW diagnostics, 6 Observations, 5 Evidence objects, 4 Findings, 4 Recommendations, and 7 Restrictions. The raw IDs, Finding IDs, recommendation IDs, restrictions, and execution counts are unchanged; only time-dependent capture metadata differs. `python3 syscheck.py compare` returned `No significant changes detected.` No unexplained new Finding was introduced.

## 17. Compatibility/version proof

- `PRODUCT_VERSION`: `0.2.0`.
- Report compatibility: `2.1.0` (`SCRIPT_VERSION` compatibility alias remains unchanged).
- Snapshot schema: `3`.
- `python3 syscheck.py --version`: `Linux Diagnostic Engine 0.2.0`.
- Snapshot loading/validation and existing comparator behavior remain covered by the full suite.

## 18. Git verification

- `git status --short --branch`: branch `master...origin/master`; four tracked files modified; task-owned replay directory untracked; pre-existing untracked artifacts preserved.
- `git diff --stat`: `constants.py 4 +-, diagnostic_rules.py 60 +-, syscheck.py 122 +-, test_syscheck.py 542 +`; total `706 insertions, 22 deletions`.
- `git diff --check`: PASS.
- `git log -5 --oneline --decorate`: `HEAD`, `origin/master`, and `v0.2.0` remain at the original release commit.
- `git rev-parse HEAD`: `76f9bdb6c8409bd3e982ec33eca9727f0edebf99`.
- `git rev-parse origin/master`: `76f9bdb6c8409bd3e982ec33eca9727f0edebf99`.
- `git rev-parse v0.2.0^{commit}`: `76f9bdb6c8409bd3e982ec33eca9727f0edebf99`.
- No stage, commit, push, tag, reset, rebase, or history rewrite was performed.

Per-file hunk summary: `constants.py` adds the read-only-remount signature; `diagnostic_rules.py` adds authoritative-missing wording and exact filesystem grep; `syscheck.py` adds structured Btrfs authority, malformed-source restriction, and filesystem event families; `test_syscheck.py` adds focused regression, recommendation, overlap, and corpus tests. No unrelated tracked path changed.

## 19. Deferred backlog

There are `3` deferred backlog items:

1. Add validated NVMe SMART/health-counter collection for critical warning, media/data-integrity errors, unsafe shutdowns, and unavailable-source outcomes.
2. Add a separate memory-pressure source contract for PSI/systemd-oomd/application allocation failures, with explicit thresholds and no conflation with kernel OOM.
3. Add a privileged/portable Btrfs capture path and replay contract for complete filesystem inventory and scrub/counter availability.

These items require a new bounded design and validation pass; they are not release blockers for this development pack.

## 20. Verdict

`POST_V0_2_0_STORAGE_MEMORY_RELIABILITY_PACK = PASS`.

The verified high-confidence defects are closed, false-positive controls and exact recommendation execution pass, the real-machine before/after is stable, the replay corpus passes, and Git history/version/schema remain unchanged. The repository is ready for the next product decision, not for an implicit release action.
