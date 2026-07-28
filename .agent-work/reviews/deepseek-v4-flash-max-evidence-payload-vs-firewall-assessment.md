# DeepSeek V4 Flash Max — Evidence Payload Integrity vs Firewall Activation Assessment

## 1. Executive decision

**Selected option: A — Implement Evidence Payload Integrity Hardening first.**

The decisive reason: **Empty payloads cause demonstrable diagnostic correctness bugs, not cosmetic quality gaps.**

Source tracing confirms that when `SEGFAULT-WP-001` fires with `payload={}`, the WirePlumber segfault Finding is silently **lost entirely** — the rule engine produces no Finding for it because the empty payload fails the `segfault_type == "wireplumber"` guard. A P2 AUDIO finding disappears from the report without warning.

Candidate B (Firewall Status Activation) has lower false-positive risk than assumed in the prior assessment, but has a real false-assurance risk from the nftables check (`bool(nft_output.strip())` does not prove effective firewall filtering). More importantly, it adds a new diagnostic domain while existing diagnostics have correctness defects.

Evidence-first product identity requires existing Evidence to be factual before new Evidence is added.

---

## 2. Repository checkpoint

| Property | Value |
|---|---|
| **Repository root** | `<REDACTED-PATH>` |
| **Branch** | `master` |
| **HEAD** | No commits — working tree only |
| **Working tree status** | Modified (staged: `syscheck.py`, `test_syscheck.py`, `constants.py` from prior iterations; unstaged: review documents) |
| **Source inspection reliability** | **Reliable** — all prior iterations stable, 340 tests pass, source intact |

---

## 3. Verification of prior assessment

### Confirmed claims

| # | Claim | Source verification |
|---|---|---|
| 1 | BTRFS-ERR-001 has `payload={}` | Confirmed — line 2049 |
| 2 | BTRFS-SCRUB-001 has `payload={}` | Confirmed — line 2062 |
| 3 | SEGFAULT-WP-001 has `payload={}` | Confirmed — line 2215 |
| 4 | SEGFAULT-SYS-001 has `payload={}` | Confirmed — line 2222 |
| 5 | SEGFAULT-MIN-001 has `payload={}` | Confirmed — line 2228 |
| 6 | KERNEL-TAINT-001 has `payload={}` | Confirmed — line 2239 |
| 7 | Firewall backends checked: firewalld, ufw, nftables | Confirmed — lines 2687-2699 |
| 8 | `firewall_found` boolean computed | Confirmed — line 2666, set at lines 2678, 2690, 2696 |
| 9 | No new shell commands needed for firewall activation | Confirmed — all commands already exist |
| 10 | `_classify_btrfs_status` returns `"no_scrub"` | Confirmed — line 507-508 |

### Corrected claims

| # | Prior claim | Correction | Source |
|---|---|---|---|
| 1 | Candidate A is "payload quality" only | **Empty payloads cause wrong diagnostic output** — WirePlumber segfault Finding is silently lost; obs_id is corrupted for all segfault types | Lines 1182, 2830-2839 |
| 2 | Firewall detection false-positive risk is "low" | **False-assurance risk is medium** — `nft_result.stdout.strip()` at line 2677 treats ANY non-empty nftables output as active firewall, even if rules don't filter | Line 2677 |
| 3 | KERNEL-TAINT-001 payload can be trivially hardened | **Partial** — adding `{"tainted": True}` is trivial, but taint_value/taint_flags would require new journalctl parsing beyond current collection scope | Lines 2232-2241 |

### Unsupported claims (from prior assessment, not verified)

| # | Claim | Status |
|---|---|---|
| 1 | "External listeners have high false-positive risk" | Not verified against source — candidate was deferred, claim accepted without verification |
| 2 | "Temperature activation needs per-chip parsing" | Not verified against `_filter_invalid_temperatures()` — function exists at line 470 but format parsing is minimal |
| 3 | "Candidate B fits 3-8 files" | Approximate count — no exact file path breakdown verified |

---

## 4. Candidate A source trace

### Payload trace per diagnostic

| Diagnostic | Current collected facts | Current payload | Data lost | Downstream impact | Smallest safe payload |
|---|---|---|---|---|---|
| **BTRFS-ERR-001** (line 2045) | Each iteration line contains `_errs` counter name and value (e.g., `write_errs 5`) | `payload={}` | All error counter names and values; counter line is parsed only for `_errs` presence, value discarded | EvidenceBuilder falls to "Btrfs device state observation recorded" (line 939) instead of detailed counter summary (lines 929-935) | `{"device_error_counters": {"write_errs": 5}}` — parse the line being iterated |
| **BTRFS-SCRUB-001** (line 2060) | `scrub_status = "no_scrub"` from `_classify_btrfs_status()` (line 2058) | `payload={}` | scrub_status classification result | `data_complete = "scrub_status" in payload` → evaluates to False (line 2824), correctly marking partial; Evidence summary is generic "Btrfs scrub status" | `{"scrub_status": "no_scrub"}` |
| **SEGFAULT-WP-001** (line 2213) | `unique_segfault_count` (line 2197), `all_wireplumber = True` (line 2200-2208) | `payload={}` | count, segfault_type = "wireplumber" | **CRITICAL** — WirePlumberSegfaultRule.evaluate() at line 1182 checks `details.get("segfault_type") != "wireplumber"` → with empty payload, this is True → **returns empty DiagnosticRuleResult, Finding is silently lost**; GeneralSegfaultRule captures it with wrong severity P1 instead of P2 | `{"segfault_type": "wireplumber", "count": unique_segfault_count}` |
| **SEGFAULT-SYS-001** (line 2220) | `unique_segfault_count`, `all_wireplumber = False` | `payload={}` | count, segfault_type = "system_wide" | **CRITICAL** — `_raw_to_observation` at line 2839 defaults segfault_type to "unknown" → obs_id becomes "SEGFAULT-MIN-001" (wrong!); Finding title shows "(?)"; GeneralSegfaultRule still fires but with corrupted obs_id and unknown count | `{"segfault_type": "system_wide", "count": unique_segfault_count}` |
| **SEGFAULT-MIN-001** (line 2226) | `unique_segfault_count` (0 < count < 3) | `payload={}` | count | EvidenceBuilder defaults count to 0 (line 864), summary says "Limited segfault events observed (0)" — self-contradictory | `{"count": unique_segfault_count}` |
| **KERNEL-TAINT-001** (line 2237) | `"taint" in kernel_errors_result.stdout.lower()` (boolean only) | `payload={}` | "tainted": True | EvidenceBuilder falls to "The running kernel is marked as tainted" (line 974) — factual but generic; taint value and flags are in journalctl output but not parsed at collection | `{"tainted": True}` (minimal); value+flags parsing would require new code |

### Critical findings from the trace

1. **WirePlumber segfault Finding is silently lost.** At line 1182, `observation.details.get("segfault_type")` returns `None` (not `"wireplumber"`) → empty `DiagnosticRuleResult`. The user sees NO WirePlumber finding even though the collector detected it. GeneralSegfaultRule catches it instead, producing a P1 "hardware failure" suspicion for a known WirePlumber/libcamera issue. This is a **real diagnostic correctness defect**.

2. **All segfault Observations have corrupted obs_id.** At line 2839, empty payload → `segfault_type = "unknown"` → obs_id forced to `"SEGFAULT-MIN-001"`. All three segfault RawDiagnostics produce Observations with the same obs_id, breaking traceability.

3. **SEGFAULT-MIN-001 Evidence says count=0 when count > 0.** Line 864: `d.get("count", 0)` defaults to 0. Summary becomes "Limited segfault events observed (0)" — logically contradictory.

4. **KERNEL-TAINT-001 is purely cosmetic.** The taint boolean is the only fact available at collection time. The Evidence statement "The running kernel is marked as tainted" is factually correct, just generic. No diagnostic correctness bug exists here.

### Overview

| Aspect | Assessment |
|---|---|
| Does factual data exist at collection time? | **Yes** for all 6 — count, type, status are all computed or available before RawDiagnostic creation |
| Is information discarded? | **Yes** for all 6 — payload is `{}` even though data is in scope |
| Is Evidence materially weakened? | **Yes** for 5 of 6 (all except KERNEL-TAINT, where Evidence text is still factually correct) |
| Is the issue cosmetic or contractually important? | **Contractually important** for segfault (wrong diagnostic output); **important** for btrfs_error/scrub (lost detail); **cosmetic** for taint |
| Smallest structured payload feasible? | See table above — each is a simple dict with 1-2 fields |
| Domain contract change required? | **No** — all payload fields already supported by existing Observation/Evidence/rule contracts |
| Existing IDs, severities, classifications must change? | **No** — payload fields are additive, not changing existing IDs or severities |

---

## 5. Candidate B source trace

### Firewall backend verification

| Backend | Command/source | Success/active state | Inactive state | Unknown/error state | Reliability |
|---|---|---|---|---|---|
| **firewalld** | `systemctl is-active firewalld.service` (line 2688) | `is_ok()` AND `stdout.strip() == "active"` (line 2689) | stdout contains `"inactive"` (not "active") | Not ok status (error/timeout) | **High** — systemctl is deterministic |
| **ufw** | `ufw status` (line 2694, optional dependency) | `is_ok()` AND `"Status: active" in stdout` (line 2695) | stdout contains `"Status: inactive"` | `execution_status == "not_found"` (line 2698) | **High** — ufw output is stable |
| **nftables** | `nft list ruleset` (line 2670, standalone cmd, optional_dependency=True) | `is_ok()` AND `stdout.strip()` is truthy (line 2677) | Not ok OR stdout is empty/falsy | `execution_status == "permission_denied"` (line 2673), `"not_found"` | **Medium** — `bool(stdout.strip())` does not prove effective filtering |

### False-assurance risk analysis for nftables

Line 2677:
```python
elif nft_result.is_ok() and nft_result.stdout.strip():
    firewall_found = True
    firewall_details.append("nftables (aktywny)")
```

This treats **any non-empty nftables ruleset output** as an active firewall. This is **not source-backed justification** for an effective firewall:

- A bare `nft list ruleset` returns the combined kernel ruleset. On a system where nftables was once enabled and then disabled, residual rules may remain that don't filter traffic.
- On systems with `nftables.service` enabled but configured with a default-accept policy and no restrictive rules, the ruleset is non-empty but does not provide meaningful protection.
- The code does not inspect the ruleset content to check for actual filtering rules (e.g., drop/reject policies, established connection tracking, input chain restrictions).

### Safe diagnostic boundary

| Condition | Can a safe Finding be produced? | Risk |
|---|---|---|
| All three backends confirmed inactive: firewalld=inactive, ufw=inactive/not_found, nft=empty/not_found | **Yes** — "No active firewall detected" is factually correct | Low FP risk |
| Some backends unknown (permission denied) but none active | **Cautious yes** — qualify with "checked: firewalld (unknown, requires sudo), ufw (inactive), nftables (inactive)" | Low FP risk |
| nftables has non-empty ruleset but firewalld and ufw inactive | **Ambiguous** — nftables might be effective or might have residual non-filtering rules | **Medium false-assurance risk** |
| Only some backends checked (others failed) | **No** — insufficient evidence for either finding | Unknown state should not produce a finding |

### Product-fit assessment

| Criterion | Assessment |
|---|---|
| Does this belong in workstation diagnostics? | **Borderline** — firewall status is a security concern. The product defines itself as "not a security scanner." However, detecting a completely absent firewall on a workstation with network services is a legitimate operational concern, not security auditing. |
| Does it drift toward security auditing? | **Slight risk** for the "no firewall" finding (reasonable). **Higher risk** if expanded to policy analysis (checking rules, ports, etc.) |
| Is remediation safe and distribution-neutral? | **Yes** — `sudo systemctl enable --now firewalld` or `sudo ufw enable` are safe and work on all three supported distro families. |
| Would false assurance cause user harm? | **Yes** — if nftables has non-filtering rules, the user is told "firewall detected" and takes no action. The nftables ambiguity must be resolved before implementation. |

---

## 6. Comparative scorecard

| # | Criterion | A (Evidence Payload) | B (Firewall Activation) | Notes |
|---|---|---|---|---|
| 1 | **Evidence-first alignment** | **5** — directly fixes existing Evidence that is missing factual data | **3** — adds new Evidence but with unresolved nftables false-assurance risk | A addresses an existing contract violation; B has an unresolved evidence quality question |
| 2 | **Diagnostic correctness** | **5** — fixes 3 correctness bugs (WirePlumber lost, obs_id corruption, count=0) | **3** — adds a correct finding for "no firewall" but has false-assurance risk for "firewall found" | A fixes existing wrong output; B adds correct output alongside ambiguous output |
| 3 | **Explainability/traceability** | **4** — fixes obs_id corruption, making provenance traceable again | **3** — Evidence would show backend states but nftables ambiguity reduces explainability | A directly improves traceability; B's traceability depends on resolving nftables |
| 4 | **User value** | **3** — users see correct segfault counts and types; btrfs detail is niche | **3** — users learn about missing firewall; moderate value for workstation security | Roughly equal |
| 5 | **False-positive risk** | **5** — zero FP risk; hardening adds data, never triggers incorrectly | **4** — "no firewall" finding has low FP risk; nftables inactive state is reliable | A has no FP risk; B has low FP risk |
| 6 | **False-assurance risk** | **5** — none; hardening never claims something absent | **2** — nftables `bool(stdout.strip())` can give false assurance; user trusts "firewall detected" when filtering may be absent | **A is significantly better** — B's nftables check is not source-backed for effective firewall |
| 7 | **Cross-distro reliability** | **5** — all hardened payload fields are distro-independent | **3** — firewall backends vary by distro; nftables output format is consistent but semantic differs | A has no distro concerns; B varies |
| 8 | **Implementation size** | **4** — 6 payload fixes touching 3 code sections (collector, _raw_to_observation, EvidenceBuilder) | **5** — 1 new diagnostic, ~5 files | B is smaller, but prompt says correctness > ease |
| 9 | **Testability** | **4** — existing test patterns work; need to add payload assertions to existing tests | **4** — straightforward boolean test | Equal |
| 10 | **Architectural impact** | **5** — none; payloads are additive, all contracts unchanged | **4** — new FindingKind (FIREWALL_STATUS), new domain usage (SECURITY) | A involves zero new types; B requires one new enum value |
| 11 | **Scope discipline** | **5** — fixes existing diagnostics without expanding product scope | **2** — adds a new diagnostic domain (SECURITY) before existing domains are correct | **A aligns with "first make existing Evidence correct"** |
| 12 | **Risk of product drift** | **5** — no drift risk; hardening is strictly corrective | **3** — moderate drift risk; firewall detection tends to invite policy analysis, port scanning, etc. | A is contained; B opens a new area |

### Total scores

| Candidate | Total (max 60) | Notes |
|---|---|---|
| **A (Evidence Payload)** | **55** | Loses points only for moderate user value and slightly larger implementation |
| **B (Firewall Activation)** | **39** | Loses points primarily on false-assurance risk (6), scope discipline (11), product drift (12) |

### Decisive factors

1. **False-assurance risk (A=5 vs B=2):** The nftables check at line 2677 does not have source-backed justification for treating non-empty output as an effective firewall. This makes B not implementation-ready without additional analysis.

2. **Diagnostic correctness (A=5 vs B=3):** A fixes three demonstrable bugs (WirePlumber lost, obs_id corruption, count=0). B adds a new correct finding alongside a potentially misleading one.

3. **Product identity (A=5 vs B=3):** SysCheck's core identity is "evidence-first." Having 6 diagnostics with empty payloads that discard available evidence contradicts this identity more than missing a firewall diagnostic.

---

## 7. Selected milestone — Evidence Payload Integrity Hardening

### Exact scope

Harden the 6 empty-payload RawDiagnostics listed in Candidate A so that the factual data already available at collection time is preserved through the pipeline.

### Exact diagnostics affected

| Diagnostic | Current payload | Target payload | Downstream impact |
|---|---|---|---|
| BTRFS-ERR-001 | `{}` | `{"device_error_counters": {...}}` | EvidenceBuilder.detail shows counters; no longer falls to fallback text |
| BTRFS-SCRUB-001 | `{}` | `{"scrub_status": "no_scrub"}` | `data_complete` correctly evaluates; Evidence summary could show status |
| SEGFAULT-WP-001 | `{}` | `{"segfault_type": "wireplumber", "count": N}` | WirePlumberSegfaultRule correctly fires; Evidence shows actual count |
| SEGFAULT-SYS-001 | `{}` | `{"segfault_type": "system_wide", "count": N}` | GeneralSegfaultRule fires with correct obs_id and count |
| SEGFAULT-MIN-001 | `{}` | `{"count": N}` | Evidence shows actual count instead of 0 |
| KERNEL-TAINT-001 | `{}` | `{"tainted": True}` | Minimal — Evidence text unchanged but data dict now contains the fact |

### What changes

1. **syscheck.py** — `collect_storage()` lines 2042-2051: parse error counter values and store in payload
2. **syscheck.py** — `collect_storage()` lines 2058-2063: store scrub_status in payload
3. **syscheck.py** — `collect_kernel_hw()` lines 2213-2230: store segfault_type and count in all 3 segfault payloads
4. **syscheck.py** — `collect_kernel_hw()` lines 2237-2241: store `{"tainted": True}` in payload

### What explicitly does not change

- No new collector methods
- No new shell commands
- No changes to `_raw_to_observation()` — already handles all expected payload fields via `{**payload}`
- No changes to `EvidenceBuilder.build()` — already handles `segfault_type`, `count`, `device_error_counters`, `scrub_status`, `tainted`
- No changes to any `DiagnosticRule` — rules already check for these fields
- No changes to `FindingClassificationPolicy` — classifications unchanged
- No changes to `FindingKind`, `DiagnosticDomain`, `EvidenceType`, `Actionability`, `RecommendationIntent`
- No changes to Finding IDs, severities, titles, remediations, verifications, or risk levels
- No changes to CLI or report rendering
- No changes to snapshot schema or serialization
- No changes to `constants.py`

### Expected file count

- **Production files**: 1 (`syscheck.py`)
- **Test files**: 1 (`test_syscheck.py` — add assertions to existing tests; add new tests for payload content)
- **Total**: ~2 files

### Architecture change required

**No.** The current architecture supports all needed payload fields. No contract changes, no pipeline changes, no model changes.

---

## 8. File-by-file implementation plan

### Required files

| # | File | Purpose | Symbols affected | Lines |
|---|---|---|---|---|
| 1 | `syscheck.py` | **BTRFS-ERR-001**: Parse error counter values from each line and store as dict in payload | `SysCheckEngine.collect_storage` | ~2042-2051 |
| 2 | `syscheck.py` | **BTRFS-SCRUB-001**: Store `scrub_status` in payload | `SysCheckEngine.collect_storage` | ~2058-2063 |
| 3 | `syscheck.py` | **SEGFAULT-WP-001**: Store `{"segfault_type": "wireplumber", "count": N}` | `SysCheckEngine.collect_kernel_hw` | ~2213-2217 |
| 4 | `syscheck.py` | **SEGFAULT-SYS-001**: Store `{"segfault_type": "system_wide", "count": N}` | `SysCheckEngine.collect_kernel_hw` | ~2220-2224 |
| 5 | `syscheck.py` | **SEGFAULT-MIN-001**: Store `{"count": N}` | `SysCheckEngine.collect_kernel_hw` | ~2226-2230 |
| 6 | `syscheck.py` | **KERNEL-TAINT-001**: Store `{"tainted": True}` | `SysCheckEngine.collect_kernel_hw` | ~2237-2241 |
| 7 | `test_syscheck.py` | Add payload content assertions to existing rule+evidence tests | `TestBtrfsDeviceErrorRuleEvidence`, `TestBtrfsScrubStatusRuleEvidence`, `TestWirePlumberSegfaultRuleEvidence`, `TestGeneralSegfaultRuleEvidence`, `TestMinorSegfaultRuleEvidence`, `TestKernelTaintRuleEvidence` | Various |
| 8 | `test_syscheck.py` | Update bootstrap/golden data tests that reference empty payloads | `TestCompleteNativeRuntime` (if affected) | ~4843+ |

### Conditional files

| # | File | Condition | Purpose |
|---|---|---|---|
| 9 | `.agent-work/reviews/iteration-24-evidence-payload-hardening.md` | Standard practice | Review document |

### Out-of-scope files

| File | Reason |
|---|---|
| `constants.py` | No new thresholds or configuration needed |
| `syscheck.py` — `EvidenceBuilder` | Already handles all payload fields; no changes needed |
| `syscheck.py` — `_raw_to_observation` | Already preserves payload via `{**payload}`; no changes needed |
| `syscheck.py` — DiagnosticRule classes | Already check for payload fields with `.get()` defaults; adding payload does not change rule behavior |
| `syscheck.py` — `FindingClassificationPolicy` | No new categories |

---

## 9. Test plan

### Positive cases

| # | Test | Diagnostic | Verification |
|---|---|---|---|
| 1 | `btrfs_error_payload_contains_counters` | BTRFS-ERR-001 | RawDiagnostic payload has `device_error_counters` with at least one non-zero counter |
| 2 | `btrfs_scrub_payload_contains_status` | BTRFS-SCRUB-001 | RawDiagnostic payload has `scrub_status` = "no_scrub" |
| 3 | `segfault_wp_payload_contains_type_and_count` | SEGFAULT-WP-001 | RawDiagnostic payload has `segfault_type="wireplumber"` and `count` > 0 |
| 4 | `segfault_sys_payload_contains_type_and_count` | SEGFAULT-SYS-001 | RawDiagnostic payload has `segfault_type="system_wide"` and `count` > 0 |
| 5 | `segfault_min_payload_contains_count` | SEGFAULT-MIN-001 | RawDiagnostic payload has `count` > 0 |
| 6 | `taint_payload_contains_tainted` | KERNEL-TAINT-001 | RawDiagnostic payload has `tainted=True` |

### Negative cases

| # | Test | Diagnostic | Verification |
|---|---|---|---|
| 7 | `no_btrfs_errors_still_empty_error_list` | BTRFS-ERR-001 | When no errors exist, no RawDiagnostic created (existing behavior) |
| 8 | `scrub_permission_denied_no_payload_change` | BTRFS-SCRUB-001 | When scrub status is permission_denied, no RawDiagnostic created (existing behavior) |
| 9 | `no_segfaults_no_payload` | All segfault | When no segfaults, no RawDiagnostic created (existing behavior) |
| 10 | `no_taint_no_payload` | KERNEL-TAINT-001 | When no taint, no RawDiagnostic created (existing behavior) |

### Partial/malformed data

| # | Test | Diagnostic | Verification |
|---|---|---|---|
| 11 | `btrfs_error_line_format_variation` | BTRFS-ERR-001 | Error lines without expected format don't crash parser; line skipped or default counter value |
| 12 | `segfault_zero_count_not_emitted` | SEGFAULT-MIN-001 | unique_segfault_count = 0 → no RawDiagnostic (existing behavior; count > 0 is the trigger) |

### Deterministic repeatability

| # | Test | Verification |
|---|---|---|
| 13 | Same collector input produces identical payload | Two calls with same mock data produce identical RawDiagnostic payload dicts |
| 14 | Evidence ID stable after payload change | Adding payload does not change `EVIDENCE-{OID}-001` pattern |

### Provenance preservation

| # | Test | Verification |
|---|---|---|
| 15 | source_raw_ids unchanged | Hardened payload does not alter provenance chain |
| 16 | source_observation_ids unchanged | Hardened payload does not alter provenance chain |

### No orphan Evidence

| # | Test | Verification |
|---|---|---|
| 17 | Every hardened RawDiagnostic still produces paired Evidence+Finding | Existing test coverage (each rule test verifies finding and evidence) |

### Regression

| # | Test | Verification |
|---|---|---|
| 18 | All existing 340 tests pass | Unchanged by payload additions |
| 19 | WirePlumberSegfaultRule fires after payload hardening | Now correctly: `details.get("segfault_type") == "wireplumber"` → True |
| 20 | GeneralSegfaultRule does NOT fire for WirePlumber observations | Now correctly: `details.get("segfault_type") != "wireplumber"` → False |

### Existing test locations to update

| Test class | Location (test_syscheck.py) | Change |
|---|---|---|
| `TestBtrfsDeviceErrorRuleEvidence` | ~line 2660+ | Add payload content assertion |
| `TestBtrfsScrubStatusRuleEvidence` | ~line 2610+ | Add payload content assertion |
| `TestWirePlumberSegfaultRuleEvidence` | ~line 3274+ | Add payload content assertion; verify Finding now fires |
| `TestGeneralSegfaultRuleEvidence` | ~line 3540+ | Add payload content assertion; verify obs_id is correct |
| `TestMinorSegfaultRuleEvidence` | ~line 3680+ | Add payload content assertion |
| `TestKernelTaintRuleEvidence` | ~line 4140+ | Add payload content assertion |
| `TestCompleteNativeRuntime` | ~line 4843+ | Verify WirePlumber finding count is correct after fix |

---

## 10. Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | BTRFS-ERR-001 RawDiagnostic payload contains `device_error_counters` with at least one non-zero entry | Test: `btrfs_error_payload_contains_counters` |
| 2 | BTRFS-SCRUB-001 RawDiagnostic payload contains `scrub_status` | Test: `btrfs_scrub_payload_contains_status` |
| 3 | SEGFAULT-WP-001 RawDiagnostic payload contains `segfault_type="wireplumber"` and `count` > 0 | Test: `segfault_wp_payload_contains_type_and_count` |
| 4 | SEGFAULT-SYS-001 RawDiagnostic payload contains `segfault_type="system_wide"` and `count` > 0 | Test: `segfault_sys_payload_contains_type_and_count` |
| 5 | SEGFAULT-MIN-001 RawDiagnostic payload contains `count` > 0 | Test: `segfault_min_payload_contains_count` |
| 6 | KERNEL-TAINT-001 RawDiagnostic payload contains `tainted=True` | Test: `taint_payload_contains_tainted` |
| 7 | WirePlumberSegfaultRule produces a Finding when payload has segfault_type="wireplumber" | Existing test: `WirePlumberSegfaultRuleEvidence` (currently passes with empty payload? **verify**) |
| 8 | WirePlumberSegfaultRule does NOT produce a Finding when segfault_type is not "wireplumber" | Existing test (unchanged behavior) |
| 9 | GeneralSegfaultRule does NOT capture WirePlumber observations | New assertion in regression test |
| 10 | All 340 existing tests pass | `python3 -m pytest -q` |
| 11 | No new shell commands added | Source grep for subprocess/cmd calls |
| 12 | No new collector methods added | Source grep for `def collect_` |
| 13 | No changes to Finding IDs, severities, classifications | Source diff review |
| 14 | No changes to EvidenceBuilder | Source diff review |
| 15 | No changes to DiagnosticRule classes | Source diff review |

---

## 11. Validation commands

Derived from project configuration (no `pyproject.toml` exists; tools use defaults):

```bash
# Formatting
ruff format --check .

# Lint
ruff check .

# Full test suite
python3 -m pytest -q

# Focused tests (after implementation)
python3 -m pytest -v -k "TestBtrfsDeviceErrorRuleEvidence or TestBtrfsScrubStatusRuleEvidence or \
  TestWirePlumberSegfaultRuleEvidence or TestGeneralSegfaultRuleEvidence or \
  TestMinorSegfaultRuleEvidence or TestKernelTaintRuleEvidence or \
  TestCompleteNativeRuntime"

# Type checking (known unavailable)
mypy . || echo "mypy not installed — no type checking available"
```

Expected baseline:

| Command | Current result |
|---|---|
| `ruff format --check .` | 3 files already formatted |
| `ruff check .` | All checks passed |
| `python3 -m pytest -q` | 340 passed in 0.15s |

---

## 12. Blocking decisions

### None required.

All 6 payload hardening changes are pure additions of factual data that already exists at collection time. No contract decisions, no security policies, no domain expansions, no naming decisions need human approval.

The exact format for `device_error_counters` in BTRFS-ERR-001 should follow the btrfs device stats output format (`{counter_name: int_value}`), which is deterministic and documented in the Linux kernel's btrfs documentation.

---

## 13. Follow-up coding task

### For a coding agent after plan approval

**Task: Implement Evidence Payload Integrity Hardening in SysCheck**

1. In `syscheck.py` — `collect_storage()` around line 2042:
   - Parse each error line in the format `"device_name counter_name counter_value"` or similar
   - Build a dict of non-zero counters
   - Store as `payload={"device_error_counters": parsed_counters}` in the BTRFS-ERR-001 RawDiagnostic
   - Handle malformed lines gracefully (skip or default to empty counter list)

2. In `syscheck.py` — `collect_storage()` around line 2060:
   - Change `payload={}` to `payload={"scrub_status": scrub_status}` in the BTRFS-SCRUB-001 RawDiagnostic

3. In `syscheck.py` — `collect_kernel_hw()` around lines 2213-2230:
   - SEGFAULT-WP-001: `payload={"segfault_type": "wireplumber", "count": unique_segfault_count}`
   - SEGFAULT-SYS-001: `payload={"segfault_type": "system_wide", "count": unique_segfault_count}`
   - SEGFAULT-MIN-001: `payload={"count": unique_segfault_count}`

4. In `syscheck.py` — `collect_kernel_hw()` around line 2237:
   - KERNEL-TAINT-001: `payload={"tainted": True}`

5. In `test_syscheck.py`:
   - For each affected diagnostic's existing test class, add one test verifying payload content
   - For WirePlumber segfault, add a test that verifies the Finding now fires correctly with populated payload (currently it may not, depending on how the test constructs the Observation directly)
   - Add regression tests for the 3 segfault types ensuring correct obs_id assignment

6. Run validation:
   ```bash
   ruff format --check .
   ruff check .
   python3 -m pytest -q
   ```

7. Do NOT stage, commit, push, create branches, or rename any project artifacts.
