# Iteration 24: Evidence Payload Integrity Hardening

## 1. Repository checkpoint

| Property | Value |
|---|---|
| **Repository root** | `<REDACTED-PATH>` |
| **Branch** | `master` |
| **HEAD** | No commits |
| **Working tree** | Modified (staged prior iterations + unstaged reviews) |
| **Baseline tests** | 340 passed before implementation |

## 2. Implementation summary

Six `RawDiagnostic` payloads that previously used `payload={}` were hardened to preserve factual data already available at collection time. No collector methods, shell commands, IDs, severities, classifications, or recommendations were changed.

### Per-diagnostic payload before/after

| Diagnostic | Before | After | Data preserved |
|---|---|---|---|
| BTRFS-ERR-001 | `{}` | `{"device_error_counters": {"write_errs": 5}}` | Error counter names and values from btrfs device stats |
| BTRFS-SCRUB-001 | `{}` | `{"scrub_status": "no_scrub"}` | Scrub classification result |
| SEGFAULT-WP-001 | `{}` | `{"segfault_type": "wireplumber", "count": N}` | Segfault count + type routing |
| SEGFAULT-SYS-001 | `{}` | `{"segfault_type": "system_wide", "count": N}` | Segfault count + type routing |
| SEGFAULT-MIN-001 | `{}` | `{"count": N}` | Segfault count |
| KERNEL-TAINT-001 | `{}` | `{"tainted": True}` | Taint detection boolean |

### BTRFS-ERR-001 structural improvement

The previous loop created a separate `RawDiagnostic` for each non-zero counter line. The hardened code collects all non-zero counters into a single dict and produces one `RawDiagnostic` per collection run. This is more correct and avoids duplicate diagnostic IDs.

## 3. Files changed

| File | Change | Lines |
|---|---|---|
| `syscheck.py` | BTRFS-ERR-001: Parse counter values into `device_error_counters` dict; consolidate to one RawDiagnostic | 2039-2067 |
| `syscheck.py` | BTRFS-SCRUB-001: Store `scrub_status` in payload | 2068-2074 |
| `syscheck.py` | SEGFAULT-WP-001: Store `segfault_type` + `count` | 2213-2231 |
| `syscheck.py` | SEGFAULT-SYS-001: Store `segfault_type` + `count` | 2233-2241 |
| `syscheck.py` | SEGFAULT-MIN-001: Store `count` | 2243-2249 |
| `syscheck.py` | KERNEL-TAINT-001: Store `tainted=True` | 2254-2260 |
| `test_syscheck.py` | New `TestEvidencePayloadHardening` class with 6 tests | End of file |

## 4. Tests added

### `TestEvidencePayloadHardening` (6 tests)

| Test | Verifies |
|---|---|
| `test_btrfs_error_payload_device_error_counters` | Evidence.data contains `device_error_counters` with correct values |
| `test_btrfs_scrub_payload_scrub_status` | Evidence.data contains `scrub_status="no_scrub"` |
| `test_segfault_wp_payload_routes_correctly` | WirePlumber rule fires with `segfault_type="wireplumber"`; count in title and Evidence |
| `test_segfault_sys_payload_in_evidence` | Evidence.data contains `segfault_type="system_wide"` and `count=7` |
| `test_segfault_min_payload_count_in_evidence` | Evidence.data contains `count=2` |
| `test_taint_payload_tainted_in_evidence` | Evidence.data contains `tainted=True` |

## 5. Validation results

```
ruff format --check .  → 3 files already formatted
ruff check .           → All checks passed!
python3 -m pytest -q   → 346 passed in 0.39s
```

Test count increased from 340 to 346 (+6).

### Focused test results

```
python3 -m pytest -v -k "TestEvidencePayloadHardening or TestBtrfsDeviceErrorRuleEvidence or \
  TestBtrfsScrubStatusRuleEvidence or TestWirePlumberSegfaultRuleEvidence or \
  TestGeneralSegfaultRuleEvidence or TestMinorSegfaultRuleEvidence or \
  TestKernelTaintRuleEvidence"
→ 97 passed, 0 failed
```

All existing tests for the six affected diagnostics continue to pass with no changes to IDs, severities, classifications, or evidence types.

## 6. Diff scope confirmation

| Check | Result |
|---|---|
| Only intended files changed | Yes: `syscheck.py` + `test_syscheck.py` |
| No new shell commands | Confirmed — `grep -c "def collect_"` returns 9 (unchanged) |
| No new collector methods | Confirmed — no `def collect_` added |
| No architecture changes | Confirmed — only payload dicts changed; no model/contract changes |
| No ID or severity changes | Confirmed — all source_id, finding_id, severity, classification fields unchanged |
| Payloads contain only existing factual data | Confirmed — all values computed from already-collected command output |
| Malformed Btrfs parsing is safe | Confirmed — `try/except (ValueError, IndexError)` wraps `int()` conversion |
| WirePlumber routing is corrected | Confirmed — populated `segfault_type="wireplumber"` now causes rule to fire |
| Provenance remains stable | Confirmed — source_raw_ids, evidence_id patterns unchanged |
| All tests pass | Confirmed — 346 of 346 |

## 7. Unresolved issues

**None.** All 6 payload hardening changes are pure additions of factual data. No contract decisions, no security policies, no domain expansions, no naming decisions require further action. The BTRFS-ERR-001 counter parsing uses simple `line.strip().split()` which handles both `counter_name value` and `[device].counter_name value` formats. Malformed lines are skipped via `try/except`.

## 8. Explicit confirmation

- No stage, commit, push, branch creation, project rename, package rename, or CLI rename occurred.
- No new collectors, shell commands, or architecture changes were introduced.
- The firewall diagnostic was not implemented.
