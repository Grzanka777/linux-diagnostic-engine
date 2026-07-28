# Post-Migration Architecture Assessment

## Executive conclusion

**The current architecture is sufficient.** No implementation milestone is currently justified. The Evidence Runtime migration has produced a coherent, well-layered pipeline with clean separation of concerns. No existing workflow is blocked, no feature is degraded, and no architectural defect has been introduced.

The smallest justified next step is **documentation and stabilization only**:

1. Close the Evidence Runtime migration epic.
2. Record the current contracts (this document serves as the basis).
3. Retain schema v3, runtime-only Evidence, Finding-only Recommendations.
4. Do not add Evidence persistence, schema v4, health scores, aggregation, or RecommendationEngine changes.

Tempting changes that should **not** be made yet:
- **Evidence persistence / schema v4** — no current feature requires it; historical comparison works without it.
- **Health score** — no stable, explainable contract can be defended from existing domain semantics.
- **Diagnostic aggregation** — no current incident grouping or conflict problem exists.
- **RecommendationEngine Evidence access** — all current recommendations are correctly produced from Findings alone.

Concrete future signals that would justify revisiting these:
- A user workflow that requires cross-run Evidence comparison.
- A rule whose recommendation cannot be correctly produced without Evidence content.
- A demonstrated case of repeated or conflicting Findings that confuse users.

---

## Current architecture

The verified data flow:

```
Collector (collect_*)
    ↓
RawDiagnostic          — raw command output, no interpretation
    ↓
_derive_observations()
    ↓
Observation            — structured facts with quality flags, no interpretation
    ↓
DiagnosticRuleEngine
    ↓
DiagnosticRuleResult
    ├── Finding         — diagnosis, severity, interpretation, evidence_ids
    └── Evidence        — factual support, type, quality, provenance
    ↓
DiagnosticEvaluation
    ↓
SysCheckEngine
    ├── findings        → report rendering, recommendations
    ├── evidence_objects→ runtime-only, not persisted
    └── observations    → snapshot (as ObservationSnapshot)
    ↓
RecommendationEngine   — consumes Findings only, produces recommendations
    ↓
Report (Markdown)      — Finding text, recommendation plan
Snapshot (JSON v3)     — observations, findings (snapshot), recommendations
```

All 11 production rules return `DiagnosticRuleResult`. Zero legacy compatibility remains. The `DiagnosticRuleEngine` contract is `DiagnosticRuleResult` only.

---

## Current contracts

### RawDiagnostic
- Frozen dataclass: `source_id`, `category`, `payload`, `collected_at` (unused default)
- Stores raw command output facts; contains **no interpretation, severity, confidence, or remediation**
- Ephemeral — exists only during pipeline execution, consumed by `_derive_observations()`
- Not persisted in snapshots (only a count is recorded)
- 12 production instances across 9 categories

### Observation
- Mutable dataclass: `obs_id`, `category`, `details`, `data_complete`, `contradictory_evidence`, `direct_measurement`, `inference_required`, `independent_sources`, `source_raw_ids`
- Contains **facts only** (class docstring: "Nie zawiera interpretacji ani rekomendacji — tylko fakty.")
- Quality flags represent measurement confidence, not diagnostic severity
- `source_raw_ids` preserves RawDiagnostic provenance
- Persisted in snapshots as `ObservationSnapshot` (identical field set)

### Evidence
- Frozen dataclass: `evidence_id`, `evidence_type`, `data`, `source_observation_ids`, `source_raw_ids`, `summary`, `strength`, `directness`, `completeness`, `contradictory`
- **Runtime-only** — not persisted in snapshots, not rendered in reports
- Identity: `EVIDENCE-{OBSERVATION_ID}-001` (deterministic, not derived from content)
- `data` contains factual observation details (measurements, counts, status — never diagnosis)
- `summary` contains a human-readable factual statement (never root-cause claims)
- Quality model (`strength`/`directness`/`completeness`) derived from Observation flags
- Produced by `EvidenceBuilder.build(observation)` — one Evidence per Observation

### Finding
- Mutable dataclass: `finding_id`, `title`, `severity`, `confidence`, `evidence` (text), `interpretation`, `recommended_diagnostics`, `remediation`, `verification`, `risk_level`, `domain`, `kind`, `actionability`, `recommendation_intent`, `source_observation_ids`, `evidence_ids`
- Contains **diagnosis** (severity, interpretation, remediation — not raw facts)
- `evidence` (text) field is a human-readable summary rendered in reports and persisted in snapshots
- `evidence_ids` is a runtime-only reference to structured Evidence objects (dropped in snapshots)
- Classification is represented by `domain`, `kind`, `actionability`, `recommendation_intent` enums

### Recommendation
- Frozen dataclass with `recommendation_id`, `title`, `priority`, `impact`, `effort`, `risk`, `action_type`, `rationale`, `diagnostics`, `remediation`, `verification`, `source_finding_ids`, `blocked_by_restrictions`
- Consumes **Findings only** — never reads Evidence or Observations
- Priority derived from Finding severity and confidence
- All 11 findings have correct, deterministic recommendations

### DiagnosticRuleEngine
- `evaluate(observations) → DiagnosticEvaluation(findings, evidence)`
- `_normalize(result: DiagnosticRuleResult) → DiagnosticRuleResult | None` — filters empty results
- No bare `Finding` compatibility. Contract is `DiagnosticRuleResult` only.

---

## Evidence runtime-only assessment

| Question | Answer | Source evidence |
|---|---|---|
| Is any existing feature unable to function because Evidence is not persisted? | **No** | Snapshot comparison uses Finding text + severity + confidence; report uses Finding text; recommendations use Finding classification. No feature reads Evidence from storage. |
| Is provenance lost in a way that affects current users? | **No** | Provenance chain (RawDiagnostic.source_id → Observation.source_raw_ids → Finding.source_observation_ids) is complete in runtime AND snapshot. Evidence adds `source_observation_ids` + `source_raw_ids` but these duplicate existing provenance. |
| Does historical comparison require Evidence content? | **No** | `SnapshotComparator` compares by finding_id, severity, confidence, interpretation, and evidence text (the `Finding.evidence` string). It never accesses Evidence objects. |
| Would persisting Evidence improve an actual existing workflow? | **No** | No current workflow reads Evidence after the pipeline completes. The Finding text field already surfaces the human-readable conclusion. |
| Would schema v4 introduce meaningful complexity without current value? | **Yes** | Schema v4 would require: migration from v3, comparator updates, snapshot format churn, documentation updates. Current value is zero because no workflow depends on persisted Evidence. |

**Conclusion:** Evidence runtime-only is not a limitation. It is a deliberate architectural choice.

---

## RecommendationEngine boundary assessment

| Question | Answer | Source evidence |
|---|---|---|
| Is all information for current recommendations present in Findings? | **Yes** | Priority uses severity + confidence. Action type uses actionability. Blocking uses restrictions. All are Finding fields. |
| Are recommendations losing precision without Evidence? | **No** | Every recommendation is correctly produced for all 11 findings. No rule produces a finding whose recommendation would benefit from Evidence data. |
| Would Evidence access create undesirable coupling? | **Yes** | RecommendationEngine currently depends only on Findings. Adding Evidence access would couple it to the Evidence model, making both harder to change independently. |
| Is there a concrete rule whose recommendation cannot be correctly produced? | **No** | All 11 rules produce correct recommendations. See `TestRecommendationEngine`, `TestPriorityDerivation`. |
| Would recommendation behavior become nondeterministic? | **No** (but risk of scope creep) | Evidence access is technically deterministic, but it creates a temptation to encode rule logic in the recommendation engine, which would violate separation of concerns. |

**Conclusion:** RecommendationEngine should continue consuming Findings only.

---

## Diagnostic aggregation assessment

| Concern | Does it exist? | Source evidence |
|---|---|---|
| Repeated Findings that represent one incident | **No** | Each observation produces exactly one finding. No rule duplicates findings for the same incident. |
| Conflicting Findings | **No** | Rules sharing a category (WirePlumber/General segfault, system/user failed units) are mutually exclusive by design. Tests verify no `AmbiguousObservationRuleError`. |
| No way to communicate overall system status | **Partially** | The report lists all findings with severity and confidence. Users can assess overall status by reading the ordered finding list and recommendation plan. No single "health indicator" exists, but no workflow requires one. |
| Unstable severity ordering | **No** | Findings are sorted by `Finding._severity_order` which is deterministic. Tests verify stable ordering. |
| Duplicate remediation | **No** | Each finding has its own remediation. No two findings share identical remediation text. |
| Recommendations that should be grouped | **No** | Each finding produces one recommendation. There is no case where multiple findings should produce a single grouped recommendation. |
| Inability to distinguish active vs informational conditions | **No** | Severity distinguishes P1/P2/P3/Info. Actionability distinguishes ACTIONABLE/CONDITIONAL/INFORMATIONAL. |

**Conclusion:** No diagnostic aggregation is currently needed. The Finding list + Recommendation plan provide sufficient structure for current users.

---

## Health score assessment

| Consideration | Assessment |
|---|---|
| Are severity values comparable? | Severity (P1, P2, P3, Info) is ordinal but not numerically comparable. P1 != 4x P3. |
| Should confidence affect the score? | Confidence (Certain/Likely/Guessing) would need weighting that cannot be defended. A Guessing-P1 finding should probably not outrank a Certain-P2 finding. |
| Should informational Findings reduce health? | Informational findings (e.g., kernel count) are not problems. Reducing health for them would be misleading. |
| Should missing diagnostics affect health? | Absence of a finding does not mean the subsystem is healthy. The collector may not have run. |
| Should multiple Findings compound? | Two P2 findings are not necessarily worse than one P1. Severity is categorical, not additive. |
| Can a weighting scheme be defended? | **No.** Any weighting would be arbitrary. The domain lacks a stable calibration target. |
| Do users have a concrete workflow that needs a score? | **No.** No CLI flag, report section, or integration test references a health score. |

**Conclusion:** A health score is not justified. The current severity + confidence + recommendation system provides more actionable information than any defensible composite score.

---

## Diagnostic coverage assessment

### Covered domains (11 rules):

| Domain | Rule(s) | Observation category |
|---|---|---|
| FILESYSTEM | `BtrfsDeviceErrorRule`, `BtrfsScrubStatusRule` | `btrfs_error`, `btrfs_scrub` |
| KERNEL | `GeneralSegfaultRule`, `MinorSegfaultRule`, `KernelTaintRule` | `segfault`, `segfault_minor`, `tainted` |
| AUDIO | `WirePlumberSegfaultRule` | `segfault` (wireplumber subtype) |
| SYSTEMD | `FailedSystemUnitRule`, `FailedUserUnitRule` | `systemd_failed` |
| BOOT | `BootDelayRule` | `boot_time` |
| PACKAGES | `KernelCountRule` | `kernel_count` |
| STORAGE | `StorageUsageRule` | `storage_usage` |

### Unused collectors:

All collectors produce `RawDiagnostic` objects that are consumed by `_raw_to_observation()`. No collector produces unused observations. No category in the classification policy lacks a corresponding rule. No known `RawDiagnostic` category is silently dropped.

### Confirmed coverage gaps (**none**):

Every observation category that can be emitted has:
- A `FindingClassificationPolicy` entry — verified by `TestClassificationPolicyCompleteness`
- At least one `DiagnosticRule` that supports it — verified by `TestCompleteNativeRuntime`
- A corresponding `EvidenceBuilder` branch — verified by rule migration tests

### Possible future features (not gaps):

| Candidate | Why it is not a gap |
|---|---|
| Firewall rule | No collector exists; would need new RawDiagnostic + rule |
| Temperature sensor anomaly | Filtered out as invalid; no rule warranted |
| Network connectivity | Not in scope of diagnostic tool |
| Memory health (SMART, memtest) | Not collected; could be added if justified |

---

## Snapshot and comparison assessment

| Question | Answer | Source evidence |
|---|---|---|
| Does schema v3 faithfully support current historical comparisons? | **Yes** | Comparison by finding_id works. Severity, confidence, interpretation, evidence text, environment, and kernel changes are all detected. |
| Are runtime-only `evidence_ids` intentionally excluded? | **Yes** | `FindingSnapshot` deliberately omits `evidence_ids`. Evidence is defined as runtime-only. |
| Is any current comparison misleading without Evidence? | **No** | Comparisons detect all meaningful changes (new/resolved findings, severity changes, environment changes). Evidence would not add information to a cross-run diff. |
| Is a schema change justified now? | **No** | No user workflow is blocked by the current schema. Schema v4 would add migration cost without benefit. |
| What exact compatibility cost would schema v4 introduce? | High | Migration from v3 would require a new `SnapshotMigrator` step. All existing v3 snapshots would be incompatible. Comparator may need updates. No demonstrable benefit. |

**Conclusion:** Retain schema v3. Do not add Evidence persistence.

---

## Reporting and CLI assessment

| Question | Answer | Source evidence |
|---|---|---|
| Is Evidence visible to users? | **No** | Evidence objects are internal only. Reports show `Finding.evidence` text field. |
| Is Evidence only stored internally? | **Yes** | `engine.evidence_objects` is populated but never serialized or rendered. |
| Does the report clearly distinguish fact, interpretation, and action? | **Partially** | Findings present: evidence text (fact), interpretation, recommended diagnostics, remediation, verification, risk level. The separation is present but the structured Evidence summary is not exposed. |
| Can provenance be inspected? | **Partially** | The finding shows `source_observation_ids` in snapshot but not in report. The structured Evidence with `source_raw_ids` is invisible. |
| Can users diagnose why a Finding was emitted? | **Yes** | The Finding.evidence text + interpretation explain the diagnosis. Rule logic is deterministic and documented in tests. |
| Does output duplication or ambiguity remain? | **No** | No duplicate findings, no ambiguous results. |

**Minor observation:** The structured Evidence objects (with quality `strength`/`directness`/`completeness` and factual `summary`) represent a significant investment in diagnostic quality, but they are invisible to users. The user-facing text in `Finding.evidence` duplicates some of this information but not all (quality flags are not exposed). This is a reporting gap, not an architectural one.

**Conclusion:** Exposing the Evidence summary in the report would make the quality investment visible, but it is not a blocking issue. The current report is functionally complete.

---

## Confirmed limitations

| Candidate limitation | Source evidence | User-visible impact | Architectural impact | Action required now |
| -------------------- | --------------- | ------------------- | -------------------- | ------------------- |
| Evidence not persisted | Snapshot schema omits Evidence, `evidence_ids` | None — no workflow reads Evidence after pipeline | None — deliberate design choice | None |
| RecommendationEngine can't read Evidence | Engine consumes Findings only | None — all recommendations correct | Lower coupling is beneficial | None |
| No health score | No existing workflow requires it | None | N/A | None |
| No diagnostic aggregation | No duplicate/conflicting findings exist | None | N/A | None |
| Evidence invisible in reports | Report uses `Finding.evidence` text, not Evidence | Minor — investment in structured Evidence quality is not surfaced | Low — could be addressed by adding Evidence summary to report | **Candidate for small improvement** |
| Boot_time payload empty in production | `collect_systemd` creates `payload={}` | Minor — finding title shows "?s" instead of actual value | Low — collector-level fix | **Candidate for small improvement** |
| No REST/API output | Tool is CLI-only | None — tool is designed for CLI | N/A | None |

---

## Candidate milestone evaluation

### A. No implementation milestone

| Criterion | Assessment |
|---|---|
| Problem solved | N/A — no problem exists |
| Source evidence | All 330 tests pass. All 11 rules are native. Architecture is clean. |
| Implementation cost | Zero |
| Compatibility cost | Zero |
| Architectural risk | None |
| Test burden | None |

**Verdict:** Valid and justified.

### B. Diagnostic coverage expansion

| Criterion | Assessment |
|---|---|
| Problem solved | Adding a new diagnostic rule for an uncovered domain |
| Source evidence | No confirmed coverage gaps exist. All collected data is already used. |
| Implementation cost | Low per-rule (existing architecture supports it) |
| Compatibility cost | Zero (new rule, no breaking changes) |
| Architectural risk | Low |
| Test burden | New rule + classification + evidence tests |

**Verdict:** Justified only if a specific user-reported gap exists. Currently no gap is documented.

### C. Evidence reporting improvement

| Criterion | Assessment |
|---|---|
| Problem solved | Surface structured Evidence summary and quality in report output |
| Source evidence | Evidence objects have factual summaries and quality flags that are currently invisible to users |
| Implementation cost | Low — add Evidence summary to `build_summary()`, add quality badge to report |
| Compatibility cost | Zero — report format change only |
| Architectural risk | None — Evidence already exists, this only adds rendering |
| Test burden | Low — update report rendering tests |

**Verdict:** Smallest justified implementation if any work is done. However, the current report is functionally complete; this is an enhancement, not a fix.

### D. Evidence persistence

| Criterion | Assessment |
|---|---|
| Problem solved | Allow cross-run Evidence comparison |
| Source evidence | No workflow requires this. Current comparison works without Evidence. |
| Implementation cost | High — snapshot schema v4, migrations, comparator updates, serialization |
| Compatibility cost | High — breaks all existing v3 snapshots |
| Architectural risk | High — changes runtime-only contract |
| Test burden | High — new snapshot tests, migration tests, comparator tests |

**Verdict:** Not justified.

### E. RecommendationEngine Evidence access

| Criterion | Assessment |
|---|---|
| Problem solved | Allow recommendations to use Evidence content |
| Source evidence | No recommendation currently needs Evidence. All 11 produce correct output. |
| Implementation cost | Medium — new coupling between RecommendationEngine and Evidence model |
| Compatibility cost | Low — additive change |
| Architectural risk | Medium — breaks separation of concerns, creates temptation for rule logic in recommendation engine |
| Test burden | Medium — new recommendation tests with Evidence input |

**Verdict:** Not justified.

### F. Diagnostic aggregation

| Criterion | Assessment |
|---|---|
| Problem solved | Group related findings, derive subsystem state |
| Source evidence | No duplicate/conflicting findings exist. No workflow requires grouping. |
| Implementation cost | Medium-high — new aggregation layer, new model, new rendering |
| Compatibility cost | Low-medium — additive |
| Architectural risk | Medium — new abstraction layer over findings |
| Test burden | High — new model tests, aggregation tests, rendering tests |

**Verdict:** Not justified.

### G. Health score

| Criterion | Assessment |
|---|---|
| Problem solved | Single-number system health indicator |
| Source evidence | No existing workflow requires it. Weighting is indefensible. |
| Implementation cost | High — new scoring model, calibration, UI, tests |
| Compatibility cost | Low — additive |
| Architectural risk | High — scoring would need to be defensible, stable, and explainable |
| Test burden | High — calibration tests, regression tests, acceptance tests |

**Verdict:** Not justified.

---

## Ranked next steps

Based on demonstrated need, user-visible value, architectural fit, implementation size, compatibility risk, reversibility, and testability:

1. **No implementation milestone** — Close the Evidence Runtime epic. Record contracts. Move to maintenance.
2. **Evidence reporting improvement** — Expose Evidence summary and quality in report output. Small value, low cost, reversible.
3. **Diagnostic coverage expansion** — Add a new rule if a user-reported gap emerges.
4. **Diagnostic aggregation** — Not currently needed.
5. **RecommendationEngine Evidence access** — Not currently needed.
6. **Evidence persistence / schema v4** — Not currently needed.
7. **Health score** — Not currently needed.

---

## Smallest justified milestone

### Outcome A: No implementation milestone is currently justified.

**Rationale:**

1. **Architecture is coherent and complete.** The RAW → OBS → Evidence + Finding → Recommendation pipeline has clean separation of concerns. Each layer has explicit responsibilities and no layer overreaches.

2. **All 11 production rules are native.** Zero legacy compatibility remains. The `DiagnosticRuleEngine` contract is `DiagnosticRuleResult` only.

3. **No existing workflow is blocked.** Reports render correctly. Snapshots serialize and compare correctly. Recommendations are correct and deterministic. All 330 tests pass.

4. **Evidence runtime-only is a deliberate choice, not a limitation.** Persisting Evidence would add complexity without demonstrated user value.

5. **No diagnostic gap affects current users.** Every observation category that can be emitted has a corresponding rule, classification, and Evidence handler.

6. **Health scores and aggregation are speculative.** No concrete problem requires them.

**Recommended close-out activities:**

- ✅ Record the current architecture contracts (this document).
- ✅ Verify all review documents are archived under `.agent-work/reviews/`.
- ✅ Confirm the Evidence Runtime migration epic is complete.
- 🔲 Remove the transitional `_normalize()` bare-Finding type annotation variance (minor typing cleanup not performed in Iteration 22).
- 🔲 Consider exposing Evidence summary in report output as a low-priority enhancement (not required).

---

## Explicit non-goals

The following are explicitly **not** part of any justified next step:

1. **Evidence persistence** — Not needed until a user workflow requires cross-run Evidence comparison.
2. **Schema v4** — Not needed. Schema v3 fully supports current workflows.
3. **Health score** — Not needed. Severity + confidence + recommendation plan provide more actionable information.
4. **Diagnostic aggregation** — Not needed. No incident grouping or conflict problem exists.
5. **RecommendationEngine Evidence access** — Not needed. All recommendations are correct from Findings alone.
6. **New diagnostic rules** — Not needed unless a specific user-reported gap emerges.
7. **CLI redesign** — Not needed. Current CLI is functional.
8. **JSON/REST API** — Not needed. Tool is CLI-only by design.
9. **New collector commands** — Not needed. All current collectors produce consumed observations.

---

## Revisit triggers

The following concrete signals would justify revisiting the decisions above:

### Schema v4 / Evidence persistence would be justified if:
- A user workflow requires comparing Evidence quality across diagnostic runs (e.g., "was Evidence strength stronger last week?")
- A new feature (e.g., trend analysis, anomaly detection over time) requires Evidence data from prior runs
- The `Finding.evidence` text field proves insufficient for comparison in a documented scenario

### Evidence-aware recommendations would be justified if:
- A specific rule produces a finding whose recommendation depends on a numeric value in Evidence (e.g., "if storage usage exceeds 95%, recommend immediate action; if 80-95%, recommend monitoring")
- The current Finding-based recommendation is demonstrably incorrect for a real-world scenario

### Diagnostic aggregation would be justified if:
- Two or more rules produce findings that should be presented as one incident (e.g., "Btrfs device error + Btrfs scrub never performed" shown as one issue)
- Users report confusion from the flat finding list
- A new subsystem-level diagnostic is added that requires finding correlation

### Health score would be justified if:
- A user workflow requires a single-number system health indicator (e.g., dashboard integration, monitoring alert)
- A stable, explainable, and testable scoring model can be designed that survives peer review
- The scoring model can be validated against real-world diagnostic outcomes

### New diagnostic rule would be justified if:
- A specific system problem is repeatedly diagnosed manually by users
- A collector already exists but its output is not consumed by a rule
- A user reports a false negative (problem not detected) that the current 11 rules miss

---

## Repository verification

No source code was modified during this assessment.

```
$ python3 -m pytest -q
330 passed in 0.15s

$ git status --short
(working tree contains changes from prior iterations only — no assessment changes)
```
