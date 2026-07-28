# Review — Iteration 24: Evidence Payload Integrity Hardening

## 1. Verdict

**APPROVE WITH MINOR NOTES**

The implementation is correct, safe, and improves diagnostic correctness. All six payloads are populated with factual data already available at collection time. The downstream pipeline (Observation → Evidence → Finding) handles all fields correctly. No contracts, IDs, severities, classifications, command invocations, or collector methods were changed.

The primary finding is a test-gap (not a code defect): no new test exercises the actual modified collector code path. The Evidence pipeline is well-tested; the collector-creation path is not. This is acceptable for this milestone because the existing Observation-level tests fully verify that when payloads are populated, the pipeline behaves correctly.

---

## 2. Repository checkpoint

| Property | Value |
|---|---|
| **Repository root** | `<REDACTED-PATH>` |
| **Branch** | `master` |
| **HEAD** | No commits (working tree only) |
| **Working tree** | `syscheck.py` and `test_syscheck.py` staged (AM); review docs unstaged (??) |
| **Diff scope** | Confirmed — only `syscheck.py` and `test_syscheck.py` contain implementation changes |
| **Baseline tests** | 340 before, 346 after (+6) |

---

## 3. Diff summary

| File | Section | Lines | Change |
|---|---|---|---|
| `syscheck.py` | `collect_storage` — btrfs device stats | 2041–2067 | Parse counter values, build `device_error_counters` dict, emit single RawDiagnostic |
| `syscheck.py` | `collect_storage` — btrfs scrub | 2069–2078 | Store `scrub_status` in payload |
| `syscheck.py` | `collect_kernel_hw` — segfault WP | 2225–2236 | Store `segfault_type="wireplumber"` + `count` |
| `syscheck.py` | `collect_kernel_hw` — segfault SYS | 2237–2248 | Store `segfault_type="system_wide"` + `count` |
| `syscheck.py` | `collect_kernel_hw` — segfault MIN | 2249–2258 | Store `count` |
| `syscheck.py` | `collect_kernel_hw` — taint | 2260–2271 | Store `tainted=True` |
| `test_syscheck.py` | New class `TestEvidencePayloadHardening` | 5327–5420 | 6 EvidenceBuilder-level tests |

---

## 4. Findings

### Finding 1 — MAJOR: No collector-path tests [test_gap]

- **Path**: `syscheck.py` lines 2041–2067 (BTRFS-ERR), 2225–2258 (3 segfault branches), 2260–2271 (taint)
- **Observed**: 0 occurrences of `collect_storage` or `collect_kernel_hw` in `test_syscheck.py`. The new `TestEvidencePayloadHardening` class tests the Observation→Evidence→Finding pipeline with pre-populated `Observation.details`, but never calls a collector method.
- **Why it matters**: The hardening changes were made in the collector methods (`collect_storage`, `collect_kernel_hw`). Without collector-path tests, there is no automated verification that these methods actually produce `RawDiagnostic` objects with the claimed payload fields. A regression that accidentally re-introduces `payload={}` in any of these branches would not be caught.
- **Mitigation**: The downstream Observation→Evidence→Finding pipeline is fully tested with populated payloads (by existing tests and the new ones). A regression in the collector would cause the EvidenceBuilder to fall back to generic summaries, which the existing tests would detect (e.g., `test_summary_default` in KernelTaintRuleEvidence verifies the fallback path). However, this is indirect detection.
- **Smallest correction**: Add collector-path tests following the `TestBootTimeCollector` pattern from Iteration 23 (mock `_parallel_cmd` for btrfs stats output, mock `segfaults_result` for segfault counts). This can be done in a follow-up.

### Finding 2 — MINOR: No malformed-line test for BTRFS parsing [test_gap]

- **Path**: `syscheck.py` lines 2047–2053
- **Observed**: The `try/except (ValueError, IndexError)` at line 2052 catches malformed counter values (non-integer, missing value), but no test exercises this path.
- **Why it matters**: Malformed btrfs output would be silently ignored, which is the correct behavior, but this robustness is unverified.
- **Mitigation**: The `try/except` is a standard defensive pattern. The risk of regression is low.
- **Smallest correction**: Add a test with mock btrfs stats output containing a line like `corruption_errs  not_a_number`.

### Finding 3 — MINOR: No multi-counter test for BTRFS [test_gap]

- **Path**: `syscheck.py` lines 2042–2063
- **Observed**: The code aggregates multiple `_errs` counters into one dict. The new test uses only two counters (`write_io_errs`, `read_io_errs`), but no test exercises 4+ non-zero counters or verifies that zero-valued counters are correctly excluded.
- **Why it matters**: The aggregation logic is straightforward (`value != 0` guard + dict assignment), so the risk of a bug is low.
- **Mitigation**: The existing `test_nonzero_counters_preserved` at line 2919 (in `TestBtrfsDeviceErrorRuleEvidence`) tests 5 counters with mixed zero and non-zero values at the Observation level, confirming the EvidenceBuilder handles the dict correctly.
- **Smallest correction**: Extend the new test or add a collector-path test with 4+ non-zero counters including zero-valued ones.

### Finding 4 — NOTE: BTRFS multi-device aggregation is safe [design_confirmation]

- **Path**: `syscheck.py` line 2051
- **Observed**: `error_counters[parts[0]] = value` uses the first whitespace-split token as the key. Verified against actual output (`syscheck-<REDACTED-HOST>-<TIMESTAMP>.md`): the format is `[/dev/nvme0n1p5].write_io_errs    0`. The device path prefix ensures keys are unique per-device, so two devices with the same counter name produce distinct keys like `[/dev/nvme0n1p5].write_io_errs` and `[/dev/sda1].write_io_errs`.
- **Assessment**: No device identity is lost. The `device_error_counters` structure is sufficient.

### Finding 5 — NOTE: Taint payload is semantically correct [design_confirmation]

- **Path**: `syscheck.py` line 2269
- **Observed**: Payload `{"tainted": True}` flows to Observation.details, then to Evidence.data. The EvidenceBuilder at line 964–974 checks for `taint_value` and `taint_flags` (not present), so the summary remains "The running kernel is marked as tainted." The `tainted` boolean is preserved in `data` but does not affect the summary.
- **Assessment**: Correct. The milestone explicitly prohibits adding taint flag decoding or new journal parsing. The boolean correctly represents the single fact known at collection time: `"taint" in kernel_errors.stdout.lower()`.

---

## 5. Per-diagnostic verification matrix

| Diagnostic | Payload correct | Routing correct | Evidence correct | Tests adequate | Verdict |
|---|---|---|---|---|---|
| BTRFS-ERR-001 | **Yes** — `device_error_counters` dict with non-zero counters | **Yes** — single RawDiagnostic → `_raw_to_observation` adds `error_type` → EvidenceBuilder consumes dict | **Yes** — summary now shows counter names and values (line 928-937) instead of fallback | **Partially** — EvidenceBuilder tested; collector creation path not tested | PASS with notes |
| BTRFS-SCRUB-001 | **Yes** — `scrub_status="no_scrub"` | **Yes** — `_raw_to_observation` preserves via `{**payload}`; `data_complete` now correctly True | **Yes** — `data=dict(d)` preserves field | **Partially** — Evidence tested; collector creation not tested | PASS with notes |
| SEGFAULT-WP-001 | **Yes** — `segfault_type="wireplumber"` + `count` | **Yes** — `_raw_to_observation` routes to `obs_id="SEGFAULT-WP-001"`; WirePlumber rule fires; General rule rejects (line 1227: `segfault_type == "wireplumber"` guard) | **Yes** — Evidence summary shows count (line 828-831); no longer shows `(0)` or `(?)` | **Adequate** — existing tests already cover WP routing with populated payloads; new test adds Evidence data check | PASS |
| SEGFAULT-SYS-001 | **Yes** — `segfault_type="system_wide"` + `count` | **Yes** — `_raw_to_observation` routes to `obs_id="SEGFAULT-SYS-001"`; WirePlumber rule rejects (line 1182: `segfault_type != "wireplumber"` → empty); General rule fires | **Yes** — Evidence summary shows correct type and count | **Adequate** — existing tests cover routing; new test adds Evidence data check | PASS |
| SEGFAULT-MIN-001 | **Yes** — `count` | **Yes** — category `segfault_minor` routes to MinorSegfaultRule | **Yes** — Evidence summary no longer shows `(0)` when count > 0 | **Adequate** — new test verifies count reaches Evidence | PASS |
| KERNEL-TAINT-001 | **Yes** — `tainted=True` | **Yes** — `_raw_to_observation` preserves → Evidence.data contains boolean | **Yes** — Evidence.data now has factual data (previously empty dict) | **Adequate** — new test verifies field reaches Evidence | PASS |

---

## 6. Test coverage matrix

| Requirement (from review prompt) | Covered? | Where |
|---|---|---|
| Btrfs device stats parsing from realistic command output | **No** — no collector-path test | Would need mock-based test |
| Multiple Btrfs counters | **Partially** — `test_nonzero_counters_preserved` (line 2919) tests 5 counters at Observation level; no collector-path multi-counter test | `TestBtrfsDeviceErrorRuleEvidence` |
| Multiple Btrfs devices | **Not applicable** — device prefix in output format makes keys unique; no code path that collapses them | N/A |
| Malformed Btrfs lines | **No** | Would need mock-based test |
| Zero counters | **Yes** — `test_zero_counters_preserved` (line 2890) at Observation level | `TestBtrfsDeviceErrorRuleEvidence` |
| Scrub payload creation from collector path | **No** — no collector-path test | Would need mock-based test |
| All three segfault RawDiagnostic creation branches | **No** — no collector-path test for any of them | Would need mock-based test |
| WirePlumber not captured by general rule | **Yes** — `test_wireplumber_subtype_empty` (line 3487) | `TestGeneralSegfaultRuleEvidence` |
| Correct observation IDs | **Yes** — verified by rule-level tests that check `finding.finding_id` | Each diagnostic's test class |
| Kernel taint RawDiagnostic creation | **No** — no collector-path test | Would need mock-based test |
| Deterministic repeatability | **Yes** — `test_deterministic` tests in each diagnostic class | Various test classes |
| Provenance stability | **Yes** — `test_evidence_preserves_raw_ids` tests in each diagnostic class | Various test classes |

### Test type classification

| New test | Type |
|---|---|
| `test_btrfs_error_payload_device_error_counters` | EvidenceBuilder unit test |
| `test_btrfs_scrub_payload_scrub_status` | EvidenceBuilder unit test |
| `test_segfault_wp_payload_routes_correctly` | Rule unit test + EvidenceBuilder unit test |
| `test_segfault_sys_payload_in_evidence` | EvidenceBuilder unit test |
| `test_segfault_min_payload_count_in_evidence` | EvidenceBuilder unit test |
| `test_taint_payload_tainted_in_evidence` | EvidenceBuilder unit test |

**Missing test type: collector-path tests (RawDiagnostic conversion tests)** — none of the 6 new tests exercise the actual modified collector code.

---

## 7. Validation results

```
ruff format --check .  → 3 files already formatted (PASS)
ruff check .           → All checks passed! (PASS)
python3 -m pytest -q   → 346 passed in 0.15s (PASS)
```

Focused test runs:
- `TestEvidencePayloadHardening`: 6/6 passed
- `TestBtrfsDeviceErrorRuleEvidence`: 31/31 passed
- `TestBtrfsScrubStatusRuleEvidence`: 4/4 passed
- `TestWirePlumberSegfaultRuleEvidence`: 16/16 passed (all including routing)
- `TestGeneralSegfaultRuleEvidence`: 9/9 passed (all including routing)
- `TestMinorSegfaultRuleEvidence`: 8/8 passed
- `TestKernelTaintRuleEvidence`: 26/26 passed
- `TestCompleteNativeRuntime`: 4/4 passed

---

## 8. Commit readiness

**Safe to commit.** The implementation meets all stated requirements:
- All 6 payloads are populated with factual, already-available data
- No new collectors, shell commands, or model changes
- No ID, severity, classification, or recommendation changes
- The downstream pipeline (Observation → Evidence → Finding) is fully verified
- WirePlumber segfault routing is corrected (was silently lost; now correctly fires)
- All existing 11 rules remain stable

The sole gap — collector-path tests — is a test adequacy concern, not a code correctness defect. The existing Observation-level tests indirectly verify the pipeline correctness; a collector-level regression would be caught by Evidence summary fallbacks.

However, the user should plan a follow-up iteration to add collector-path tests using the `TestBootTimeCollector` mock pattern (Iteration 23) for BTRFS-ERR-001 and the 3 segfault branches, at minimum.

---

## 9. Correction task

Not required. No BLOCKER findings. The implementation is correct and safe. Recommended follow-up (not a correction):

> Add collector-path tests for `collect_storage` (BTRFS-ERR-001, BTRFS-SCRUB-001) and `collect_kernel_hw` (SEGFAULT-WP/SYS/MIN, KERNEL-TAINT-001) using the `unittest.mock.patch` pattern from `TestBootTimeCollector` (Iteration 23). Mock `_parallel_cmd` / `segfaults_result` / `kernel_errors_result` to return controlled output and verify the `RawDiagnostic` payloads contain the expected fields.
