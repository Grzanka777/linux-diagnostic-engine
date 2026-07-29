# Iteration 27 — Kernel OOM Evidence Diagnostic

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   dirty (3 files modified, 2 untracked reviews)
Recent commits (git log -5 --oneline):
  6804f70 fix: remove misleading temperature warning
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

No unrelated tracked changes. Only intended files modified.

---

## 2. Selected Command / Query Form

### 2.1 Dedicated `oom_events` Task

The shell command is built by the `_oom_collector_command()` helper:

```python
def _oom_collector_command(upstream_cmd: str, regex: str) -> List[str]:
    return [
        "bash",
        "-c",
        f"{upstream_cmd} | "
        f"grep -iE '{regex}'; "
        'statuses=("${PIPESTATUS[@]}"); '
        "js=${statuses[0]}; gs=${statuses[1]}; "
        'if [ "$js" -ne 0 ]; then exit "$js"; '
        'elif [ "$gs" -eq 1 ]; then exit 0; '
        'else exit "$gs"; fi',
    ]
```

The task definition is now:

```python
"oom_events": (
    _oom_collector_command(
        "journalctl -b -k --no-pager 2>/dev/null",
        RE_OOM,
    ),
    TIMEOUT_LONG,
    False,
),
```

**Atomic PIPESTATUS capture:** The entire `PIPESTATUS` array is captured
into a bash variable in a single statement (`statuses=("${PIPESTATUS[@]}")`)
before individual elements are read. This avoids the race condition where
`${PIPESTATUS[0]}` itself is a command that resets `PIPESTATUS` before
`${PIPESTATUS[1]}` is read.

### 2.2 Why Not `|| true`

The existing display collectors use `|| true` which masks any
`journalctl` failure (rc≠0) as a successful exit. For a diagnostic
collector, this is unacceptable: a failed `journalctl` invocation must
not be indistinguishable from "no OOM events."

The PIPESTATUS-based approach:

| Scenario | Journalctl rc | Grep rc | Final rc | CmdResult status | Diagnostic produced |
|---|---|---|---|---|---|
| Matches found | 0 | 0 | 0 | `ok` | ✅ Yes |
| No matches | 0 | 1 | 0 (normalized) | `ok` | ❌ No (correct) |
| Journalctl failure | ≠0 | — | journalctl rc | `error` | ❌ No (safe) |
| Grep error (crash, rc=2) | 0 | 2 | 2 | `error` | ❌ No (safe) |
| Timeout | — | — | -2 | `timeout` | ❌ No (safe) |

The key distinction: `grep` exit code 1 (no matches) is the only exit
code normalized to success. All other non-zero exits propagate, so
`CmdResult.execution_status` correctly reflects the failure.

### 2.3 Sideband Check

The sideband check in `collect_kernel_hw()` uses:
```python
if oom_events_result.is_ok() and oom_events_result.stdout.strip():
    oom_matching = [
        line for line in oom_lines
        if re.search(RE_OOM, line, re.IGNORECASE)
        and "memory cgroup" not in line.lower()
    ]
```

This ensures:
- Only successful query results (status `ok`) are processed.
- Empty stdout (no matches) produces no diagnostic.
- The authoritative regex check is done in Python (not shell), so the
  exact marker contract is enforced regardless of shell escaping.
- Memcg lines containing "Memory cgroup" are excluded from the match
  even though they contain the substring "out of memory: killed process".
- Command failure (`is_ok()` returns False) produces no diagnostic.

---

## 3. No-Match vs Failure Handling

| Condition | Execution path | Outcome |
|---|---|---|
| Query succeeds, markers found | `is_ok()` + `stdout.strip()` + regex match | RawDiagnostic emitted |
| Query succeeds, no markers | `is_ok()` + `stdout.strip()` empty or no regex match | No diagnostic (correct: no OOM evidence) |
| Query fails (journalctl error) | `is_ok()` returns False | No diagnostic (correct: can't determine) |
| Query not found | `execution_status='not_found'` → `is_ok()` False | No diagnostic |
| Permission denied | `execution_status='permission_denied'` → `is_ok()` False | No diagnostic |
| Timeout | `execution_status='timeout'` → `is_ok()` False | No diagnostic |

The diagnostic is **presence-only**: a positive match is authoritative.
Absence of a match does not prove that no OOM event occurred (the
journal could have lost the message, or the query could have failed
silently). The Finding interpretation explicitly documents this
limitation.

---

## 4. Exact Production Changes

### 4.1 `constants.py`

Added:
```python
RE_OOM = r"invoked oom-killer|oom-killer:|Out of memory: Killed process"
```

### 4.2 `syscheck.py`

| Location | Change |
|---|---|
| Import block (line 55) | Added `RE_OOM` import |
| `FindingKind` enum (line 137) | Added `OOM_EVENT = "oom_event"` |
| `_BY_CATEGORY` (line 668) | Added `"oom_event"` classification entry |
| Helper function (line ~595) | New `_oom_collector_command()` with atomic PIPESTATUS |
| `collect_kernel_hw()` tasks (line ~2267) | Replaced hardcoded command with `_oom_collector_command(...)` |
| `collect_kernel_hw()` result extraction (line ~2290) | Added `oom_events_result = r["oom_events"]` |
| `collect_kernel_hw()` sideband (line ~2438) | New OOM sideband check after taint |
| `_raw_to_observation()` (line ~2940) | Added `"oom_event"` branch returning `KERNEL-OOM-001` |
| `EvidenceBuilder.build()` (line ~1044) | Added `"oom_event"` branch with `JOURNAL_EVENT` |
| New class `KernelOomRule` (line ~1385) | Full rule with P2, Certain, investigation guidance |
| `build_default_rule_engine()` (line ~1706) | Registered `KernelOomRule` after `KernelTaintRule` |

### 4.3 `test_syscheck.py`

| Location | Change |
|---|---|
| `_collect_with_mock` in `TestSegfaultAndTaintCollectorPath` | Added `"oom_events": self._cmd_ok("")` as default |
| New class `TestOomCollectorPath` | 20 test methods (details below) |
| New class `TestOomCommandStatus` | 6 shell-level tests (details below) |

---

## 5. Diagnostic Contract

| Property | Value |
|---|---|
| Diagnostic ID | `KERNEL-OOM-001` |
| Category | `oom_event` |
| FindingKind | `OOM_EVENT` |
| Domain | `DiagnosticDomain.KERNEL` |
| Severity | `P2` |
| Confidence | `Certain` |
| Actionability | `Actionability.ACTIONABLE` |
| Recommendation intent | `RecommendationIntent.INVESTIGATE` |
| EvidenceType | `EvidenceType.JOURNAL_EVENT` |
| Rule ID | `RULE-KERNEL-OOM` |

### In-Scope Markers

- `invoked oom-killer` (case-insensitive, exact phrase)
- `oom-killer:` (case-insensitive, exact phrase with colon)
- `Out of memory: Killed process` (case-insensitive, exact phrase)

### Explicit Exclusions

- `oom_reaper` alone
- `Memory cgroup out of memory` / memcg / cgroup OOM
- `systemd-oomd`
- Incidental words containing `oom` (`bloom`, `doom`, `room`)
- Prior-boot events (excluded by `journalctl -b`)
- Event counting, PID grouping, timestamp parsing
- Ongoing-pressure inference, swap thresholds, MemAvailable thresholds
- cgroup recommendations
- Automatic remediation

---

## 6. Payload Provenance

### RawDiagnostic Payload

```python
{
    "oom_detected": True,
    "matched_lines": ["..."],       # max 20 lines, original order
    "match_count": 1,                # total matched lines (pre-cap)
    "match_classes": ["oom_invocation"],  # deduplicated, first-seen order
    "journal_scope": "current_boot_kernel",
    "source_query": "oom_events",
}
```

### Match Classes

| Value | Trigger |
|---|---|
| `oom_invocation` | Line contains `invoked oom-killer` (case-insensitive) |
| `oom_killer_marker` | Line contains `oom-killer:` (case-insensitive) |
| `oom_kill_outcome` | Line contains `out of memory: killed process` (case-insensitive) |

### Observation Mapping

```python
Observation(
    obs_id="KERNEL-OOM-001",
    category="oom_event",
    details=payload,
    direct_measurement=True,
    data_complete=True,        # query completed successfully
    contradictory_evidence=False,
    inference_required=False,
    independent_sources=1,
    source_raw_ids=(src_id,),
)
```

### Evidence Data

```python
{
    "oom_detected": True,
    "match_count": N,
    "matched_lines": [...],
    "match_classes": [...],
    "journal_scope": "current_boot_kernel",
    "source_query": "oom_events",
}
```

---

## 7. Tests Added

### Test Class: `TestOomCollectorPath`

20 test methods in `test_syscheck.py`:

| # | Method | Verifies |
|---|---|---|
| 1 | `test_oom_invocation_triggers` | `invoked oom-killer` produces KERNEL-OOM-001 with `oom_invocation` class |
| 2 | `test_oom_killer_marker_triggers` | `oom-killer:` produces KERNEL-OOM-001 with `oom_killer_marker` class |
| 3 | `test_oom_kill_outcome_triggers` | `Out of memory: Killed process` produces KERNEL-OOM-001 with `oom_kill_outcome` class |
| 4 | `test_ordinary_kernel_errors_no_trigger` | BUG/lockup/error do not trigger |
| 5 | `test_empty_output_no_trigger` | Empty stdout does not trigger |
| 6 | `test_incidental_oom_substrings_no_trigger` | `bloom`, `doom`, `room` do not trigger |
| 7 | `test_systemd_oomd_no_trigger` | systemd-oomd text does not trigger |
| 8 | `test_memcg_oom_no_trigger` | Memcg OOM ("Memory cgroup out of memory") does not trigger |
| 9 | `test_oom_reaper_alone_no_trigger` | oom_reaper alone does not trigger |
| 10 | `test_multiple_matching_lines_one_diagnostic` | 3 matching lines → 1 RawDiagnostic |
| 11 | `test_payload_preserves_provenance` | Payload has oom_detected, matched_lines, match_count, classes, scope, source |
| 12 | `test_matched_lines_capped_at_20` | 25 lines → capped at 20, match_count=25 |
| 13 | `test_command_failure_no_trigger` | Error status → no diagnostic |
| 14 | `test_timeout_no_trigger` | Timeout status → no diagnostic |
| 15 | `test_observation_mapping` | RawDiagnostic → correct Observation fields |
| 16 | `test_evidence_journal_event_type` | Evidence uses JOURNAL_EVENT, preserves provenance |
| 17 | `test_finding_oom_event_kind` | Finding uses OOM_EVENT, KERNEL, P2, Certain, ACTIONABLE, INVESTIGATE |
| 18 | `test_rule_registered` | RULE-KERNEL-OOM exists in default engine |
| 19 | `test_existing_segfault_unchanged` | Segfault detection with oom_events key present |
| 20 | `test_existing_taint_unchanged` | Taint detection with oom_events key present |

### Test Class: `TestOomCommandStatus`

6 direct shell-level tests that execute the actual bash command
built by `_oom_collector_command()` against `subprocess.run()`,
using real `printf`, `grep`, and `bash` executables (no mocks):

| # | Method | Verifies |
|---|---|---|
| 1 | `test_match_success` | grep finds a match → exit 0, stdout contains the line |
| 2 | `test_no_match` | grep finds nothing → exit 0, empty stdout |
| 3 | `test_upstream_failure` | journalctl fails (rc=42) → exit 42 |
| 4 | `test_grep_rc2_propagated` | grep exits 2 (invalid regex) → propagated as-is |
| 5 | `test_stderr_suppressed_preserves_status` | journalctl stderr → exit 0 preserved |
| 6 | `test_zero_length_input_no_match` | Empty upstream output → exit 0, no match |

These tests protect against regressions in:
- Atomic PIPESTATUS array capture
- Journalctl failure propagation
- Grep error (non-0, non-1) propagation
- Grep exit-code 1 normalization to success
- Empty-input handling

---

## 8. Focused Validation

```
$ python3 -m pytest test_syscheck.py::TestOomCollectorPath -v
------------------------------ 20 passed in 0.35s ------------------------------

$ python3 -m pytest test_syscheck.py::TestOomCommandStatus -v
------------------------------ 6 passed in 0.34s -------------------------------
```

All 26 OOM-specific tests pass.

---

## 9. Full Validation

```
$ ruff format --check .     → 2 files left unchanged
$ ruff check .              → All checks passed
$ python3 -m pytest -q      → 395 passed in 0.65s
```

All 395 tests pass: 369 existing tests continue to pass with no
regressions, plus 26 new OOM tests (20 collector-path + 6 command-status).

---

## 10. Files Changed

| File | Status | Lines changed |
|---|---|---|
| `constants.py` | Modified | +1 (RE_OOM) |
| `syscheck.py` | Modified | ~+140 net (FindingKind, classification, `_oom_collector_command` helper, collector, observation, evidence, rule, registration) |
| `test_syscheck.py` | Modified | ~+380 net (existing mock updated, TestOomCollectorPath with 20 tests, TestOomCommandStatus with 6 tests) |
| `.agent-work/reviews/iteration-27-kernel-oom-evidence-diagnostic.md` | New | This review |

---

## 11. PIPESTATUS Race Fix

The original implementation read PIPESTATUS sequentially:

```bash
s=${PIPESTATUS[0]}; g=${PIPESTATUS[1]};
```

This is racy because `${PIPESTATUS[0]}` itself is a command that resets
`PIPESTATUS` before `${PIPESTATUS[1]}` is read. The corrected command
captures the entire array atomically:

```bash
statuses=("${PIPESTATUS[@]}");
js=${statuses[0]}; gs=${statuses[1]};
```

The helper `_oom_collector_command()` encapsulates this pattern and
is tested directly by `TestOomCommandStatus` with fake upstream
executables (printf, bash -c) to verify all status-code paths.

---

## 12. No-Go Boundaries Preserved

The implementation does **not** include:
- Memcg/cgroup OOM detection
- `oom_reaper`-only detection
- `systemd-oomd` detection
- Prior-boot detection
- Event counting or kill counting
- Ongoing-pressure assessment
- Swap-size thresholds
- MemAvailable thresholds
- cgroup recommendations
- Automatic remediation
- Timestamp parsing

---

## 13. Known Limitations

1. **Presence-only diagnostic:** A successful no-match query is
   indistinguishable from a `journalctl` failure masked by `|| true` in
   existing collectors. The OOM task uses PIPESTATUS to distinguish these
   cases, but `journalctl` could fail silently if systemd-journald is
   operational but returns no kernel messages. The Finding interpretation
   explicitly states that missed events are possible.

2. **Journal completeness not guaranteed:** Journald rate-limiting,
   rotation, or prior journald state could cause OOM messages to be
   dropped before the diagnostic query runs. `data_complete=True` means
   the query completed, not that the journal contains every kernel
   message from the boot.

3. **Shell `2>/dev/null` suppresses journalctl stderr:** If journalctl
   emits a warning on stderr (e.g., about journal corruption), it is
   hidden. The exit code is still propagated, so this doesn't cause false
   positives, but diagnostic output for troubleshooting journalctl issues
   is lost.

4. **Memcg exclusion is pattern-based (not semantic):** Lines containing
   "Memory cgroup" are excluded regardless of context. A kernel message
   mentioning "Memory cgroup" in a non-OOM context would also be
   excluded, but such messages would not match the OOM markers anyway.

5. **Cross-boot events are not distinguished within the current boot:**
   If the journal contains OOM events from the current boot and they
   were resolved earlier, they are still reported. The Finding
   interpretation notes that the diagnostic detects presence, not
   ongoing pressure.

---

## 14. Git Confirmation

- No `git add`, `git commit`, `git push` was run.
- No branches were created or switched.
- No history was rewritten.
- No project artifacts were renamed.
- All changes remain unstaged working-tree modifications.

```
$ git status --short
 M constants.py
 M syscheck.py
 M test_syscheck.py
?? .agent-work/reviews/deepseek-v4-flash-max-oom-evidence-diagnostic-feasibility-assessment.md
?? .agent-work/reviews/deepseek-v4-flash-max-zram-ram-pressure-diagnostics-assessment.md
?? .agent-work/reviews/iteration-27-kernel-oom-evidence-diagnostic.md
```
