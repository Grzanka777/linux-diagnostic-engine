# DeepSeek V4 Flash Max — OOM Evidence Diagnostic Feasibility Assessment (Corrected)

## 1. Repository Checkpoint

```
Branch:         master
Working tree:   clean (2 untracked files — assessment documents)
Recent commits (git log -5 --oneline):
  6804f70 fix: remove misleading temperature warning
  e7ee372 fix: detect kernel taint precisely
  db1b3b9 chore: ignore superseded review artifacts
  1a81959 docs: record diagnostic engine assessments
  55049c2 feat: establish SysCheck diagnostic engine
```

Only the assessment documents are untracked. No production files were modified.

---

## 2. Exact Current Data Path

### 2.1 Display-Oriented Kernel Error Collector

The sole kernel journal path is `collect_kernel_hw()` at `syscheck.py:2111`.

**Task entry (line 2123–2131):**
```python
"kernel_errors": (
    [
        "bash",
        "-c",
        f"journalctl -b -k --no-pager 2>/dev/null | grep -iE '{RE_KERNEL_ERROR}' | tail -50 || true",
    ],
    TIMEOUT_LONG,
    False,
),
```

**Regex constant** (`constants.py:22`):
```python
RE_KERNEL_ERROR = r"error|fail|BUG|lockup|hung|oom|taint|Call Trace"
```

### 2.2 Data Flow

1. `_parallel_cmd()` executes all kernel-hw tasks concurrently, returns
   `Dict[str, CmdResult]` (`syscheck.py:2153`).
2. `kernel_errors_result = r["kernel_errors"]` — a `CmdResult` with stdout
   containing up to 50 lines of journalctl output filtered by the broad
   display regex.
3. `kernel_errors_result.to_fallback_text()` → `_filter_own_journal_entries()`
   → displayed in report as a codeblock (`syscheck.py:2164–2169`).
4. A sideband check reads `kernel_errors_result.stdout` directly (before
   filtering) for `r"\bTainted:\s"` (`syscheck.py:2257`).

### 2.3 What `oom` Substring Actually Captures

Because `RE_KERNEL_ERROR` contains a bare `oom` (no word boundaries), the
current display grep matches **any kernel journal line** containing the
three-character sequence `oom` as a substring:

| Pattern | Matches | Misses |
|---|---|---|
| `oom-killer:` | ✅ `kernel: oom-killer:` | — |
| `invoked oom-killer` | ✅ `... invoked oom-killer: gfp_mask=...` | — |
| `OOM killer` | ✅ (case-insensitive `-i`) | — |
| `oom_reaper` | ✅ `kernel: oom_reaper ...` | — |
| `Out of memory: Killed process` | ❌ no `oom` substring | **FN** |
| `Memory cgroup out of memory` | ❌ no `oom` substring | **FN** |
| `bloom` | ✅ **FP** (incidental) | — |
| `doom` | ✅ **FP** (incidental) | — |
| `room` | ✅ **FP** (incidental) | — |

### 2.4 Existing Segfault and Taint Matching (Reference Patterns)

**Segfault** — dedicated grep:
```python
f"journalctl -b --no-pager 2>/dev/null | grep -i '{RE_SEGFAULT}' || true"
```
Separate collector, literal string match, no `tail` cap, separate from the
display kernel-error collector. Post-processing via
`_count_unique_segfaults()` and `_deduplicate_journal_lines()`.

**Taint** — sideband regex on existing kernel_errors stdout:
```python
re.search(r"\bTainted:\s", kernel_errors_result.stdout, re.IGNORECASE)
```
No new collector. Exact marker with word boundary. Produces a single
`RawDiagnostic` when found.

### 2.5 Key Difference Between Display and Diagnostic Paths

The display grep is designed for **report readability** (broad coverage,
truncated to 50 lines). The diagnostic pipeline consumes
`self.raw_diagnostics` which is populated by sideband checks — currently
only for taint. OOM is not checked anywhere as a standalone diagnostic.

### 2.6 Collected-But-Unused OOM-Related Data

The `kernel_errors_result.stdout` (pre-filtering) is available at line 2257
but only consumed for taint. OOM-relevant lines that happen to contain `oom`
substring are present in this `stdout`, but:
- truncated by `tail -50`,
- competing with unrelated errors for the 50-line budget,
- not parsed or routed to `raw_diagnostics`.

---

## 3. OOM Classes Matrix

### 3.1 Global Kernel OOM Invocation

**Markers:** `oom-killer:`, `invoked oom-killer`

**Kernel format examples:**
```
kernel: mysqld invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, oom_score_adj=0
kernel: oom-killer: constraining constraint at zone Normal
kernel: OOM killer enabled.
```

**In Scope:** YES — definitive OOM invocation markers.

### 3.2 Global OOM Outcome

**Marker:** `Out of memory: Killed process`

**Kernel format example:**
```
kernel: Out of memory: Killed process 1234 (mysqld) total-vm:1234567kB, anon-rss:123456kB, file-rss:0kB, shmem-rss:0kB, UID:0, ...
```

**In Scope:** YES — confirms an OOM kill occurred. This line does **not**
contain the substring `oom` and is thus a **false negative** in the current
grep. This is the strongest argument for a dedicated query.

### 3.3 Memcg / Cgroup OOM

**Markers:** `Memory cgroup out of memory`, `memory: usage ... limit ...`

**Kernel format example:**
```
kernel: Memory cgroup out of memory: Killed process 5678 (java) ...
kernel: memory: usage 524288kB, limit 524288kB, failcnt 256
```

**In Scope:** NO — separate cause (cgroup limit), different remediation
(adjust cgroup limits vs. add system RAM). Excluding this removes the
primary FN risk for the initial scope. Could be added as a separate
diagnostic in the future.

**Rationale for exclusion:** A cgroup OOM is a container/application limit
exhaustion, not necessarily system-wide memory pressure. Combining both
under one diagnostic would conflate different root causes.

### 3.4 oom_reaper

**Marker:** `oom_reaper` (substring)

**Kernel format example:**
```
kernel: oom_reaper: reaped process 1234 (mysqld), now anon-rss:0kB
```

**In Scope:** SUPPORTING EVIDENCE ONLY. The `oom_reaper` follows a
successful OOM kill. It is not independently diagnostic — if `oom_reaper`
appears without a prior `oom-killer:` or `Out of memory:` line, it may be
a stale/partial log. The diagnostic should not trigger on `oom_reaper`
alone.

### 3.5 systemd-oomd

**Markers:** `systemd-oomd`, `oomd` in userspace journal

**In Scope:** NO — `systemd-oomd` is a userspace daemon with its own
policy (managed OOM, not kernel OOM). Its cause (memory pressure) and
remediation (swap, limits, cgroup adjustment) differ from kernel OOM.
`systemd-oomd` events do not appear in `journalctl -b -k` (kernel journal)
— they appear in `journalctl -b` (system journal). Excluding this is
straightforward because the dedicated query uses `-k` (kernel messages
only).

### 3.6 Userspace Application Text Containing `oom`

**Context:** Userspace applications may write "room", "doom", "bloom",
"oom" in their logs. These appear in `journalctl -b` but not in
`journalctl -b -k`.

**In Scope:** NO — the dedicated query uses `-k` (kernel journal only),
so userspace text is automatically excluded.

### 3.7 Incidental Substring Matches

**Context:** The kernel journal itself could contain `bloom_filter`,
`room_for_grow`, `doom_ring` in driver or filesystem messages.

**In Scope:** EXCLUDED — the exact markers `oom-killer:`, `invoked
oom-killer`, and `Out of memory: Killed process` are sufficiently specific
that incidental overlap is improbable. However, this is not proven zero;
a kernel driver or module could in theory print a string matching one of
these exact phrases without an actual OOM event. The exact-phrase approach
substantially reduces false-positive risk but does not eliminate it
categorically.

### 3.8 Prior Boot Events

**In Scope:** EXCLUDED — `journalctl -b` (with `-b` and no argument) means
current boot only. The dedicated query uses `-b` (same as existing
kernel_errors collector), so prior boots are excluded by construction.

### 3.9 Current-Boot Events Already Resolved

**Context:** An OOM event that happened earlier in the same boot but has
since been resolved (more swap configured, extra RAM, etc.) is still a
real historical event in the current boot.

**In Scope:** YES (with caveat). The diagnostic detects "OOM evidence
present in current boot journal" — it does not claim ongoing pressure.
This is factually correct. The journal entry exists; it happened. Whether
the condition persists is a separate question that the diagnostic does
not answer. The recommendation should guide the user to assess current
state.

### 3.10 Summary Matrix

| OOM Class | Scope | Rationale |
|---|---|---|
| Global kernel invocation (`oom-killer:`, `invoked oom-killer`) | ✅ IN SCOPE | Definitive markers |
| Global OOM outcome (`Out of memory: Killed process`) | ✅ IN SCOPE | Confirms kill; currently missed by display grep (FN) |
| Memcg/cgroup OOM | ❌ EXCLUDED | Separate cause, separate remediation |
| `oom_reaper` | 🔶 SUPPORTING ONLY | Not independently diagnostic |
| `systemd-oomd` | ❌ EXCLUDED | Userspace, different mechanism; auto-excluded by `-k` |
| Userspace `oom` text | ❌ EXCLUDED | Auto-excluded by `-k` |
| Incidental substrings | ❌ EXCLUDED | Exact markers make overlap improbable but not proven impossible |
| Prior boots | ❌ EXCLUDED | `-b` scopes to current boot |
| Resolved same-boot events | ✅ IN SCOPE | Factually correct; recommendation guides current-state check |

---

## 4. Path A / B / C Comparison

### 4.1 Path A — Parse Existing Filtered Kernel-Error Output

| Factor | Assessment |
|---|---|
| **Data availability** | `kernel_errors_result.stdout` is available at `syscheck.py:2257` |
| **Marker coverage** | `Out of memory: Killed process` is **not** captured (FN) |
| **Competition** | Existing `tail -50` means OOM lines compete with all other kernel errors |
| **Substring risk** | Bare `oom` matches `bloom`, `doom`, `room` in kernel drivers |
| **Sideband pattern** | This is how taint works — but taint uses exact `\bTainted:\s`, not substring `taint` |
| **Minimum change** | Could add a sideband `re.search` on `kernel_errors_result.stdout` for OOM markers |

**Verdict: REJECTED.**

Three fatal flaws:
1. **`Out of memory: Killed process` is a FN** in the display grep —
   parsing the filtered output would still miss it.
2. **Competing with `tail -50`** — if there are 50+ other kernel errors,
   OOM lines never reach the diagnostic.
3. **Maintenance coupling** — the display regex is tuned for readability,
   not diagnostic completeness. Changing it for one diagnostic could affect
   the report.

Even adding a sideband `re.search` on the pre-filtered stdout would only
see lines that survived the display grep AND the `tail -50` truncation.
This is not reliable.

### 4.2 Path B — Dedicated Current-Boot Kernel OOM Query

| Factor | Assessment |
|---|---|
| **New collector** | Yes — one additional `_parallel_cmd` task in `collect_kernel_hw()` |
| **Command pattern** | Same pattern as existing segfault collector |
| **Marker accuracy** | Exact phrases, no substring risk |
| **Truncation** | No `tail -50`; the query targets a tiny set of expected lines |
| **`Out of memory`** | Captured (exact marker) |
| **Independence** | Not affected by display grep changes |
| **Cost** | One additional `journalctl -b -k` call (same journal cached by systemd) |
| **Optional dependency** | Same as kernel_errors — False (not optional) |

**Command (following existing convention at `syscheck.py:2127` and `:2136`):**
```
bash -c "journalctl -b -k --no-pager 2>/dev/null | grep -iE 'invoked oom-killer|oom-killer:|Out of memory: Killed process' || true"
```

This follows the exact pattern of:
- `syscheck.py:2127`: `kernel_errors` — bash -c, journalctl, grep -iE, `|| true`
- `syscheck.py:2136`: `segfaults` — bash -c, journalctl, grep -i, `|| true`

**Timeout:** `TIMEOUT_LONG` (60s) — same as kernel_errors and segfaults.

**Output cap:** Not needed — exact markers produce <<10 lines on any real
system.

**`|| true` masking caveat:** The shell `|| true` suffix causes the
pipeline to exit 0 even when `journalctl` fails or produces no output.
This means a failed `journalctl` invocation (e.g., journald unavailable)
is indistinguishable from "no OOM events found" — both produce empty
stdout with rc=0. The diagnostic is therefore **presence-only**: a
positive match is authoritative, but absence of a match does not
constitute proof that no OOM event occurred. The sideband check
(`oom_result.is_ok() and oom_result.stdout.strip() and matched lines`)
correctly produces no diagnostic on empty/failed output, but it cannot
distinguish the two cases. This is an accepted limitation shared with the
existing segfault collector.

**Verdict: RECOMMENDED.**

### 4.3 Path C — Reuse Raw Unfiltered Kernel Journal

| Factor | Assessment |
|---|---|
| **Does raw journal exist in memory?** | **No.** The `journalctl -b -k` output is piped directly to `grep`; only grep-filtered stdout reaches Python. |
| **Can we collect raw journal cheaply?** | That would require a new collector anyway (contradicting the "reuse" premise) |
| **Is truncation-free raw data available?** | No — even if we stored the full output, it could be large (1000s of lines) |

**Verdict: REJECTED.** The unfiltered kernel journal is not available in
memory.

### 4.4 Path Selection

**Chosen: Path B — Dedicated Current-Boot Kernel OOM Query.**

This is the only path that provides:
- exact marker matching (corrects the FN on `Out of memory`, avoids
  incidental substring FP),
- no competition with display grep,
- no `tail -50` truncation,
- clean separation of concerns from the display collector,
- alignment with existing segfault collector pattern.

---

## 5. Selected Path Detail

### 5.1 Command Contract

```
Task name:     "oom_events"
Command:       ["bash", "-c",
                "journalctl -b -k --no-pager 2>/dev/null | "
                "grep -iE 'invoked oom-killer|oom-killer:|Out of memory: Killed process' "
                "|| true"]
Timeout:       TIMEOUT_LONG (60)
Optional:      False (like kernel_errors, segfaults)
Execution:     Via existing _parallel_cmd in collect_kernel_hw()
```

### 5.2 Diagnostic Presence-Only Semantics

| Collector outcome | Sideband action | Diagnostic produced |
|---|---|---|
| rc=0, stdout has matching lines | Emit RawDiagnostic | ✅ Yes |
| rc=0, stdout empty (no matches) | No action | ❌ No — absence of match is not proof |
| rc=0, stdout has non-matching lines only | No action | ❌ No |
| rc != 0 / permission denied / timeout | No action (CmdResult status != "ok") | ❌ No — failure is not "no OOM" |

The `|| true` suffix masks journalctl failures (rc → 0), so a failed
journalctl with empty stdout is indistinguishable from "no OOM events".
The diagnostic does not claim absence. This limitation is shared with all
existing journal-based collectors in the repository.

### 5.3 Coexistence with Display Collector

The existing `kernel_errors` display collector remains unchanged. The
dedicated OOM query is a new key in the same `tasks_cmd` dict. Both run
concurrently via `ThreadPoolExecutor`.

### 5.4 Report Display

The OOM query result is consumed **only** by the `raw_diagnostics`
pipeline, analogous to how the taint check reads
`kernel_errors_result.stdout` but does not add a separate report section.
The report continues to show any OOM-related lines incidentally captured
by the display grep, but the authoritative diagnostic is the pipeline.

---

## 6. Exact Matching Policy

### 6.1 Markers

| Marker | Case | Type |
|---|---|---|
| `invoked oom-killer` | Case-insensitive | Literal phrase |
| `oom-killer:` | Case-insensitive | Literal with trailing colon (avoids matching unrelated terms that happen to begin with `oom-killer`) |
| `Out of memory: Killed process` | Case-insensitive | Full phrase |

### 6.2 Combined Regex (case-insensitive)

```
invoked oom-killer|oom-killer:|Out of memory: Killed process
```

No word boundaries needed — the phrases are self-bounding. The colon after
`oom-killer:` prevents a match on hypothetical `oom-killer-foo`.

### 6.3 Exclusions

- `oom_reaper` alone does **not** trigger.
- `Memory cgroup out of memory` does **not** trigger (separate future
  diagnostic).
- `systemd-oomd` does **not** trigger (automatically excluded by `-k`).
- Lines from prior boots do **not** trigger (automatically excluded by
  `-b`).

### 6.4 Behavior When Multiple Matching Lines Belong to One Event

A single OOM event produces multiple journal lines:

```
kernel: mysqld invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0, oom_score_adj=0
kernel: oom-killer: constraining constraint at zone Normal
kernel: Out of memory: Killed process 1234 (mysqld) total-vm:1234567kB, ...
```

All matching lines are collected and preserved in the payload. One
`RawDiagnostic` is emitted regardless of how many lines match. No event
counting or grouping is attempted.

### 6.5 Behavior When Only `oom_reaper` Is Present

No `RawDiagnostic` is produced. The `oom_reaper` marker is not in the
matching set.

---

## 7. False-Positive and False-Negative Analysis

### 7.1 False Positives

| Source | Assessment |
|---|---|
| Kernel driver printing "oom" substring | ✅ **Eliminated** by exact phrases — `oom` substring alone no longer triggers |
| Custom kernel module printing a matched phrase verbatim | ⚠️ **Theoretically possible** — a module could print any string, including these exact phrases, without actual OOM. This is improbable but not proven impossible. The exact-phrase approach substantially reduces FP risk compared to substring matching. |
| Userspace process in kernel journal | ✅ **Eliminated** by `-k` — only kernel messages are queried |
| Prior boot | ✅ **Eliminated** by `-b` flag |

**FP risk: Low.** The exact markers make incidental false-positive matches
improbable. A kernel module or driver would need to deliberately or
accidentally print one of these specific phrases without an actual OOM
event — no known kernel code does this.

### 7.2 False Negatives

| Source | Assessment |
|---|---|
| `Out of memory: Killed process` | ✅ **Eliminated** by dedicated query (was FN in display grep) |
| Memcg cgroup OOM | 🔶 **Known deliberate exclusion** — may be added as a separate diagnostic later |
| `systemd-oomd` | ✅ **Known deliberate exclusion** — different mechanism; userspace journal |
| Journal rotation / message loss before collection | ⚠️ Possible — same risk as all journal-dependent diagnostics. An OOM event that occurred but was rotated out before the diagnostic runs would be missed. |
| Kernel message ratelimiting by journald | ⚠️ Possible — affects all journal-based diagnostics equally |
| `journalctl` command failure masked by `\|\| true` | ⚠️ The diagnostic is presence-only; a masked failure produces no diagnostic but cannot be distinguished from "no OOM" |

**FN risk: Moderate for completeness (some OOM events could be missed),
low for the specific diagnostic claim (when a match is found, it is
authoritative).** The diagnostic claims "OOM evidence was found in the
current-boot journal" — not "no OOM events occurred." The limitation is
explicitly documented in the Finding interpretation.

---

## 8. Deduplication Policy

### 8.1 Rule

One `RawDiagnostic` per `collect_kernel_hw()` call when **any** qualifying
marker is present.

### 8.2 Behavior

- Single `RawDiagnostic` with `source_id = "KERNEL-OOM-001"`.
- Payload preserves all matched lines up to a safety cap of 20 (single
  events typically produce 1–5 lines).
- No PID-based grouping.
- No timestamp parsing or event reconstruction.
- No deduplication of identical lines within one collection.

### 8.3 Rationale

One RawDiagnostic per collection with bounded matched lines is minimal,
deterministic, and reversible. Any aggregation (event counting, kill
counting) adds inference without reliability.

---

## 9. Severity and Confidence Decision

### 9.1 Severity: P2

**Comparison with existing severity assignments:**

| Diagnostic | Severity | Rationale |
|---|---|---|
| Btrfs device errors | P1 | Hardware-level I/O errors detected |
| System-wide segfault storm | P1 | Multiple processes affected; may indicate hardware failure |
| Kernel taint | P2 | Informational — not an emergency, but worth knowing |
| Failed system units | P2 | Service failure detected |
| Minor segfaults (1–2) | P3 | Incidental, low impact |
| **OOM evidence (proposed)** | **P2** | **Real event, process was killed, but system is stable now** |

**Why P2, not P1:**
- An OOM event is a **historical fact** in the journal, not necessarily an
  ongoing emergency. The system recovered (a process was killed to free
  memory).
- P1 is reserved for active hardware errors (btrfs counters, persistent
  segfault storms across many processes) that suggest immediate action.
- P2 signals "this should be investigated" — between kernel taint (P2,
  informational) and failed units (P2, actionable).

**Why P2, not P3:**
- A process was killed by the kernel. This is more significant than
  incidental segfaults (P3) or informational taint.
- OOM events can be precursors to system instability if the underlying
  cause is not addressed.

### 9.2 Confidence: Certain

The Observation uses `data_complete=True`. The meaning of `data_complete`
in this context is: the dedicated journal query executed successfully and
its output was fully processed. The query itself is not truncated (no
`tail`). The flag does not assert that the systemd journal contains every
kernel message from the entire boot — journal rate-limiting, rotation, and
prior journald state are not checked. However, confidence that the
**matched lines are real OOM events** is Certain because:

- `direct_measurement = True` — journal lines are a direct observation.
- `data_complete = True` — the query completed and all output was examined.
- `contradictory_evidence = False` — exact markers; no reasonable
  contradiction.
- `inference_required = False` — exact marker match requires no inference.
- `independent_sources = 1` — single source, sufficient for presence.

Calling `derive_confidence()` with these values returns `"Certain"`.

**Caveat:** `data_complete=True` reflects query-level completeness, not
journal-level omniscience. An OOM event that was rotated out of the
journal before this diagnostic runs would be missed (a FN), but that does
not reduce confidence in events that **were** captured. The Finding
interpretation acknowledges this limitation.

---

## 10. Architecture Compatibility

### 10.1 Required New Enum Values

**FindingKind** (`syscheck.py:129`):
```python
OOM_EVENT = "oom_event"
```

New value, distinct from `KERNEL_TAINT` and `SEGFAULT`. Semantically
justified: OOM is a distinct kernel event class that does not fit under
existing kinds.

**No new DiagnosticDomain or EvidenceType needed:**
- Domain: `KERNEL` (existing, line 116, used by taint and system-wide
  segfaults)
- EvidenceType: `JOURNAL_EVENT` (existing, line 722, used by segfaults)

### 10.2 Verified Enum Values

All values proposed in this contract have been verified against source:

| Enum | Member | Source Line | Status |
|---|---|---|---|
| `Actionability` | `ACTIONABLE` | 143 | ✅ Exists |
| `RecommendationIntent` | `INVESTIGATE` | 150 | ✅ Exists |
| `DiagnosticDomain` | `KERNEL` | 116 | ✅ Exists |
| `EvidenceType` | `JOURNAL_EVENT` | 722 | ✅ Exists |
| `FindingKind` | `OOM_EVENT` | **New** | To be added |

### 10.3 FindingClassificationPolicy

New entry in `_BY_CATEGORY` (`syscheck.py:631`):
```python
"oom_event": FindingClassification(
    DiagnosticDomain.KERNEL,
    FindingKind.OOM_EVENT,
    Actionability.ACTIONABLE,
    RecommendationIntent.INVESTIGATE,
),
```

`Actionability.ACTIONABLE` — the user can review swap, memory usage, and
processes.
`RecommendationIntent.INVESTIGATE` — the primary action is investigation,
not immediate remediation.

### 10.4 Diagnostic ID: `KERNEL-OOM-001`

**Chosen namespace justification:**

| Component | Rationale |
|---|---|
| `KERNEL` | The authoritative source is the kernel journal (`journalctl -b -k`) |
| `OOM` | The diagnosed phenomenon is Out-Of-Memory exhaustion |
| `001` | Single diagnostic per category (no sub-types in initial scope) |

This ID is used consistently for:
- `RawDiagnostic.source_id`
- Observation `obs_id`
- Finding `finding_id`

### 10.5 RawDiagnostic (Stage 1, Collect)

New sideband check in `collect_kernel_hw()`, after the taint check,
following the same pattern:

```python
# Check OOM events — dedicated collector path
oom_result = r.get("oom_events")
if oom_result and oom_result.is_ok() and oom_result.stdout.strip():
    lines = oom_result.stdout.split("\n")
    matching = [
        l for l in lines
        if re.search(
            r"(?i)invoked oom-killer|oom-killer:|Out of memory: Killed process",
            l,
        )
    ]
    if matching:
        # Classify each matched line
        match_classes = []
        for ml in matching:
            ml_lower = ml.lower()
            if "invoked oom-killer" in ml_lower:
                match_classes.append("oom_invocation")
            if "oom-killer:" in ml_lower:
                match_classes.append("oom_killer_marker")
            if "out of memory: killed process" in ml_lower:
                match_classes.append("oom_kill_outcome")
        # Deduplicate classes while preserving order
        seen_classes = set()
        unique_classes = []
        for cls in match_classes:
            if cls not in seen_classes:
                seen_classes.add(cls)
                unique_classes.append(cls)

        self.raw_diagnostics.append(
            RawDiagnostic(
                source_id="KERNEL-OOM-001",
                category="oom_event",
                payload={
                    "oom_detected": True,
                    "matched_lines": matching[:20],
                    "match_count": len(matching),
                    "match_classes": unique_classes,
                    "journal_scope": "current_boot_kernel",
                    "source_query": "oom_events",
                },
            )
        )
```

**Payload provenance:**

| Field | Value | Determined by |
|---|---|---|
| `oom_detected` | `True` | Any match of the exact markers |
| `matched_lines` | List of matching journal lines (max 20) | Direct from collector stdout |
| `match_count` | Integer count | `len(matched_lines)` |
| `match_classes` | List of class labels | Classification of each line against the three markers |
| `journal_scope` | `"current_boot_kernel"` | Command uses `journalctl -b -k` |
| `source_query` | `"oom_events"` | Task name in `_parallel_cmd` dict |

### 10.6 Observation (Stage 2, _raw_to_observation)

New branch in `_raw_to_observation()` (`syscheck.py:2825`):

```python
elif cat == "oom_event":
    return Observation(
        obs_id="KERNEL-OOM-001",
        category="oom_event",
        details={**payload},
        direct_measurement=True,
        data_complete=True,
        contradictory_evidence=False,
        inference_required=False,
        independent_sources=1,
        source_raw_ids=(src_id,),
    )
```

`direct_measurement=True` — journal lines are a direct observation.
`data_complete=True` — the query completed and all output was processed.
Journal-level limitations (rate-limiting, rotation) are acknowledged in
the Finding interpretation, not in this flag.
`inference_required=False` — exact markers require no inference.

### 10.7 Evidence (Stage 3, EvidenceBuilder)

New branch in `EvidenceBuilder.build()` (`syscheck.py:781`):

```python
if cat == "oom_event":
    strength = EvidenceStrength.STRONG
    directness = EvidenceDirectness.DIRECT
    completeness = EvidenceCompleteness.COMPLETE
    if not observation.data_complete:
        completeness = EvidenceCompleteness.PARTIAL
    if observation.inference_required:
        directness = EvidenceDirectness.INFERRED
    if observation.contradictory_evidence:
        strength = EvidenceStrength.MODERATE

    count = d.get("match_count", 0)
    summary = (
        f"OOM killer invoked during current boot "
        f"({count} matching journal line(s))"
    )

    return Evidence(
        evidence_id=eid,
        evidence_type=EvidenceType.JOURNAL_EVENT,
        source_observation_ids=(oid,),
        source_raw_ids=observation.source_raw_ids,
        summary=summary,
        data={
            "oom_detected": d.get("oom_detected", False),
            "match_count": count,
            "matched_lines": d.get("matched_lines", []),
            "match_classes": d.get("match_classes", []),
            "journal_scope": d.get("journal_scope", "current_boot_kernel"),
            "source_query": d.get("source_query", "oom_events"),
        },
        strength=strength,
        directness=directness,
        completeness=completeness,
    )
```

### 10.8 Rule (New DiagnosticRule)

New class following the `KernelTaintRule` pattern (`syscheck.py:1302`):

```python
class KernelOomRule(DiagnosticRule):
    rule_id = "RULE-KERNEL-OOM"
    supported_categories = frozenset({"oom_event"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=Finding(
                finding_id=obs_id,
                title="Wykryto zdarzenie OOM (Out of Memory) w bieżącym bocie",
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Jądro zgłosiło brak pamięci i uruchomiło OOM killer. "
                    "Proces(y) zostały zabite w celu odzyskania pamięci. "
                    "Diagnostyka nie określa przyczyny — może to być "
                    "niewystarczająca ilość RAM-u, brak/zbyt mały swap, "
                    "wyciek pamięci aplikacji, ograniczenie cgroup, "
                    "anormalne obciążenie lub konfiguracja.\n\n"
                    "Uwaga: diagnostyka wykrywa obecność zdarzenia OOM "
                    "w dzienniku bieżącego bota. Nie potwierdza ani nie "
                    "zaprzecza trwającej presji pamięci. Zdarzenia OOM "
                    "mogły zostać pominięte jeśli zostały usunięte z "
                    "dziennika przed uruchomieniem diagnostyki."
                ),
                recommended_diagnostics=(
                    "Sprawdź bieżące użycie pamięci: `free -h`\n"
                    "Sprawdź swap: `swapon --show`\n"
                    "Sprawdź procesy według zużycia pamięci: "
                    "`ps aux --sort=-%mem | head -20`"
                ),
                remediation=(
                    "Jeśli problem jest powtarzalny: zwiększ swap, "
                    "dodaj więcej RAM, zidentyfikuj wyciek pamięci, "
                    "dostosuj limity cgroup lub ogranicz obciążenie."
                ),
                verification=(
                    "Sprawdź bieżące użycie pamięci komendą `free -h` — "
                    "czy dostępna pamięć nie jest zbyt niska.\n"
                    "Sprawdź swap: `swapon --show` — czy swap jest "
                    "włączony i ma odpowiedni rozmiar.\n"
                    "Po podjęciu działań naprawczych monitoruj dziennik "
                    "w kolejnym bocie: `journalctl -b -k --grep='oom'`."
                ),
                risk_level=(
                    "Umiarkowane. OOM wskazuje na wyczerpanie pamięci; "
                    "nieleczona przyczyna może prowadzić do dalszych "
                    "problemów stabilności."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )
```

**Key semantic choices:**
- `interpretation` states: OOM detected, process was killed, cause not
  determined. Includes an explicit caveat that the diagnostic is
  presence-only and some OOM events could have been missed.
- `recommended_diagnostics` does **not** recommend adjusting cgroup limits
  (memcg is out of scope).
- `verification` checks **current state** (`free -h`, `swapon --show`),
  not a re-run of the journal query. A journal entry from this boot cannot
  disappear after remediation, so "no results from journal query" would be
  invalid verification. Instead, verification checks whether current
  memory/swap state is healthy and monitors the **next** boot for
  recurrence.

### 10.9 Rule Registration

Register `KernelOomRule(eb)` in `build_default_rule_engine()` (`syscheck.py:1635`):

```python
def build_default_rule_engine() -> DiagnosticRuleEngine:
    policy = FindingClassificationPolicy()
    eb = EvidenceBuilder()
    rules = (
        BtrfsDeviceErrorRule(eb),
        BtrfsScrubStatusRule(eb),
        WirePlumberSegfaultRule(eb),
        GeneralSegfaultRule(eb),
        MinorSegfaultRule(eb),
        KernelTaintRule(eb),
        KernelOomRule(eb),           # ← ADD
        FailedSystemUnitRule(eb),
        FailedUserUnitRule(eb),
        KernelCountRule(eb),
        BootDelayRule(eb),
        StorageUsageRule(eb),
    )
    return DiagnosticRuleEngine(DiagnosticRuleRegistry(rules), policy)
```

### 10.10 Architecture Summary

| Stage | Element | Value |
|---|---|---|
| RAW | `source_id` | `KERNEL-OOM-001` |
| RAW | `category` | `oom_event` |
| RAW | `payload` | `oom_detected`, `matched_lines` (≤20), `match_count`, `match_classes`, `journal_scope`, `source_query` |
| OBS | `obs_id` | `KERNEL-OOM-001` |
| OBS | `direct_measurement` | `True` |
| OBS | `inference_required` | `False` |
| OBS | `data_complete` | `True` (query-level; journal-level limits documented in Finding) |
| INT | `rule_id` | `RULE-KERNEL-OOM` |
| INT | `EvidenceType` | `JOURNAL_EVENT` |
| INT | `severity` | `P2` |
| INT | `confidence` | `"Certain"` |
| INT | `FindingKind` | `OOM_EVENT` (new) |
| INT | `DiagnosticDomain` | `KERNEL` |
| INT | `actionability` | `ACTIONABLE` |
| INT | `recommendation_intent` | `INVESTIGATE` |

---

## 11. Proposed Contract

### 11.1 Decision: Implement Minimal OOM Evidence Diagnostic

**Decision A.** The dedicated query and full pipeline should be introduced
in one atomic milestone. There is no engineering reason to split the
collector from pipeline activation — the collector alone produces no
diagnostic value without the pipeline, and the pipeline cannot function
without the collector. Adding both atomically is the smallest testable
increment.

### 11.2 Exact Contract

| Property | Value |
|---|---|
| Diagnostic ID | `KERNEL-OOM-001` |
| Category | `oom_event` |
| FindingKind | `OOM_EVENT` (new) |
| Domain | `DiagnosticDomain.KERNEL` |
| Severity | `P2` |
| Confidence | `Certain` |
| Actionability | `Actionability.ACTIONABLE` |
| Recommendation intent | `RecommendationIntent.INVESTIGATE` |
| EvidenceType | `EvidenceType.JOURNAL_EVENT` |

### 11.3 Query / Collector Behavior

- Task name: `oom_events`
- Command: `bash -c "journalctl -b -k --no-pager 2>/dev/null | grep -iE 'invoked oom-killer|oom-killer:|Out of memory: Killed process' \|\| true"`
- Timeout: `TIMEOUT_LONG` (60s)
- Optional: `False`
- Execution: Via `_parallel_cmd` in `collect_kernel_hw()`
- Sideband check: After taint check, reads `oom_result.stdout`, applies
  exact regex, emits `RawDiagnostic` only on positive match.
- Presence-only: No diagnostic emitted on empty/failed output.

### 11.4 RawDiagnostic Payload

```python
{
    "oom_detected": True,
    "matched_lines": [...],      # max 20
    "match_count": N,
    "match_classes": [...],      # deduplicated: "oom_invocation", "oom_killer_marker", "oom_kill_outcome"
    "journal_scope": "current_boot_kernel",
    "source_query": "oom_events",
}
```

### 11.5 Observation Mapping

```python
Observation(
    obs_id="KERNEL-OOM-001",
    category="oom_event",
    details=payload,
    direct_measurement=True,
    data_complete=True,
    contradictory_evidence=False,
    inference_required=False,
    independent_sources=1,
    source_raw_ids=(src_id,),
)
```

### 11.6 Evidence Payload

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

### 11.7 Finding Semantics

- **Title:** "Wykryto zdarzenie OOM (Out of Memory) w bieżącym bocie"
- **Severity:** P2
- **Confidence:** Certain
- **Interpretation:** States OOM occurred, process was killed, cause not
  determined. Explicitly notes: presence-only diagnostic, some OOM events
  could have been missed.
- **Verification:** Checks current memory/swap state (`free -h`,
  `swapon --show`), does **not** claim re-running the journal query proves
  resolution.
- **Remediation:** Suggests increasing swap, adding RAM, identifying leaks,
  adjusting limits, or reducing load — does not prescribe "add RAM" as sole
  remedy.
- **Does not recommend** adjusting cgroup limits (cgroup OOM is out of
  scope).

### 11.8 Deduplication

One RawDiagnostic per `collect_kernel_hw()` call when any qualifying
marker is present. Bounded matched lines (≤20). No event counting, no
PID grouping, no timestamp inference.

### 11.9 No-Go Boundaries

- Memcg/cgroup OOM — **excluded**
- `oom_reaper`-only — **excluded**
- `systemd-oomd` — **excluded**
- Prior boot — **excluded**
- Event counting / kill counting — **excluded**
- Ongoing-pressure assessment — **excluded**
- Swap-size threshold detection — **excluded**
- Automatic remediation — **excluded**
- Timestamp parsing — **excluded**

### 11.10 Files Modified

| File | Changes |
|---|---|
| `syscheck.py` | Add OOM_EVENT to FindingKind; add oom_events to collect_kernel_hw tasks; add sideband check; add _raw_to_observation branch; add EvidenceBuilder branch; add KernelOomRule class; register in FindingClassificationPolicy; register in build_default_rule_engine |
| `constants.py` | Optional: add RE_OOM constant (can be inline in command) |

### 11.11 Expected Tests

**12 test cases** in `TestOomCollectorPath`:

| # | Test | Type |
|---|---|---|
| 1 | `invoked oom-killer` marker triggers | Collector-path |
| 2 | `oom-killer:` marker triggers | Collector-path |
| 3 | `Out of memory: Killed process` marker triggers | Collector-path |
| 4 | Ordinary kernel errors (no OOM markers) do not trigger | Collector-path |
| 5 | Empty stdout (no OOM) does not trigger | Collector-path |
| 6 | Incidental `oom` substring (e.g., `bloom`, `doom`, `room`) does not trigger | Collector-path |
| 7 | `systemd-oomd` in output does not trigger | Collector-path |
| 8 | Memcg OOM (`Memory cgroup out of memory`) does not trigger | Collector-path |
| 9 | Multiple matching lines yield exactly one RawDiagnostic | Collector-path |
| 10 | oom_events command failure (rc≠0) does not trigger | Collector-path |
| 11 | Evidence and Finding mapping is complete | Pipeline |
| 12 | No regression: segfault and taint behavior unchanged | Regression |

All tests use mocked `_parallel_cmd` — no real journal, host state, sudo,
or network.

---

## 12. Recommendation Boundaries

### 12.1 What the Recommendation Must Not Claim

- **"Add more RAM"** as the sole remedy — the cause could be a leak,
  absent swap, or workload.
- **"Your system is unstable"** — the system stabilized (it killed a
  process and continued).
- **"Hardware failure"** — OOM is not primarily a hardware symptom.
- **"Reinstall"** — never appropriate for OOM.
- **"Adjust cgroup limits"** — cgroup OOM is out of scope.
- **"Re-run journalctl to verify"** — a historical journal entry remains
  present; its absence after remediation is not meaningful verification.

### 12.2 What the Recommendation Must Include

- **Verification-oriented steps** for current state:
  1. Check current memory usage: `free -h`
  2. Review swap status: `swapon --show`
  3. Identify memory-heavy processes: `ps aux --sort=-%mem | head -20`
- **Factual restatement:** "An OOM event occurred in this boot. A process
  was killed. The cause is not determined by this diagnostic."
- **Verification semantics:** Checking that current memory/swap state is
  healthy, and monitoring the next boot for recurrence. A journal query
  for current-boot OOM events will still return the historical match even
  after remediation — that is expected and does not indicate a continuing
  problem.

---

## 13. Required Tests

### 13.1 Test Infrastructure

Tests follow the existing `TestSegfaultAndTaintCollectorPath` pattern
(`test_syscheck.py:5559`):

- Class `TestOomCollectorPath` with `_cmd_ok()` and `_collect_with_mock()`
  that patches `SysCheckEngine._parallel_cmd`.
- Mock dictionary adds `"oom_events"` alongside existing keys.
- Helper `_make_oom_line()` for consistent test data.

### 13.2 Test Cases (12)

| # | Test | Expected | Assertion |
|---|---|---|---|
| 1 | `invoked oom-killer` in stdout | ✅ Diagnostic | `len(raws) == 1`, `raws[0].source_id == "KERNEL-OOM-001"`, `"oom_invocation" in match_classes` |
| 2 | `oom-killer:` in stdout | ✅ Diagnostic | `"oom_killer_marker" in match_classes` |
| 3 | `Out of memory: Killed process` in stdout | ✅ Diagnostic | `"oom_kill_outcome" in match_classes` |
| 4 | Other kernel errors (e.g., `BUG`, `lockup`) | ❌ No diagnostic | `len(raws) == 0` |
| 5 | Empty stdout | ❌ No diagnostic | `len(raws) == 0` |
| 6 | Incidental substring (`bloom`, `doom`, `room`) | ❌ No diagnostic | `len(raws) == 0` |
| 7 | `systemd-oomd` text in `-k` output (regression guard) | ❌ No diagnostic | `len(raws) == 0` |
| 8 | `Memory cgroup out of memory` | ❌ No diagnostic | `len(raws) == 0` |
| 9 | Multiple matching lines (one event, 3 lines) | ✅ One diagnostic | `len(raws) == 1`, `match_count >= 3`, payload contains all lines |
| 10 | oom_events rc≠0, empty stdout (command failure) | ❌ No diagnostic | `len(raws) == 0` |
| 11 | Pipeline: `_interpret()` with oom_event observation | ✅ Evidence + Finding | `JOURNAL_EVENT` type, `P2` severity, `Certain` confidence |
| 12 | Existing segfault/taint tests pass with oom_events key added | ✅ No regression | Existing assertions unchanged |

### 13.3 Test Requirements

- **No real journal, host state, sudo, or network.**
- Each test creates a fresh `SysCheckEngine` instance.
- Collector-path tests call `engine.collect_kernel_hw()` with mocked
  results.
- Pipeline tests set `engine.observations` directly and call
  `engine._interpret()`.

### 13.4 Expected Test Count

**12 test cases** in one new test class `TestOomCollectorPath`.

---

## 14. Final Decision

### Decision A — Implement Minimal OOM Evidence Diagnostic

The dedicated query and full diagnostic pipeline should be introduced in
one atomic milestone.

**Why atomic:**
- The collector alone produces no diagnostic value.
- The pipeline alone cannot function without the collector.
- Adding both atomically is the smallest testable increment.
- No engineering reason exists to split them.

**Implementation scope:**
1. Add `FindingKind.OOM_EVENT`.
2. Add `oom_event` entry to `FindingClassificationPolicy._BY_CATEGORY`.
3. Add `oom_events` task to `collect_kernel_hw()`.
4. Add sideband check for RedDiagnostic after taint.
5. Add `oom_event` branch to `_raw_to_observation()`.
6. Add `oom_event` branch to `EvidenceBuilder.build()`.
7. Add `KernelOomRule` class.
8. Register in `build_default_rule_engine()`.
9. Add `RE_OOM` to `constants.py` (optional, can be inline).
10. Add 12 tests in `TestOomCollectorPath`.

**Atomic unlock:** A single `KERNEL-OOM-001` RawDiagnostic is collected,
routed through the full pipeline (Observation → Evidence → Finding → Rule),
and rendered as a P2/Certain Finding with investigation guidance. All 12
tests pass.

---

## 15. Exact Next Scope

### 15.1 Implementation Files

- `syscheck.py` — all pipeline changes
- `constants.py` — optional: add `RE_OOM`
- `test_syscheck.py` — 12 test cases in `TestOomCollectorPath`

### 15.2 Implementation Order

1. Add `OOM_EVENT = "oom_event"` to `FindingKind` enum.
2. Add `"oom_event": FindingClassification(...)` to `_BY_CATEGORY`.
3. Add `"oom_events"` task dict entry in `collect_kernel_hw()`.
4. Add sideband check after taint in `collect_kernel_hw()`.
5. Add `"oom_event"` branch in `_raw_to_observation()`.
6. Add `"oom_event"` branch in `EvidenceBuilder.build()`.
7. Add `KernelOomRule` class.
8. Register `KernelOomRule(eb)` in `build_default_rule_engine()`.
9. (Optional) Add `RE_OOM` in `constants.py`.
10. Add `TestOomCollectorPath` with 12 tests.

### 15.3 Future Phases (Deferred)

| Phase | Scope | Trigger |
|---|---|---|
| Follow-up A | Memcg/cgroup OOM detection as separate diagnostic | User feedback or cgroup-heavy environment |
| Follow-up B | `systemd-oomd` integration | Evidence that oomd events are confused with kernel OOM |
| Follow-up C | Dedicated `journalctl --grep` (remove `\|\| true` masking) | If `--grep` support is confirmed in project baseline and the masking limitation becomes problematic |

---

## 16. Unresolved Uncertainties

1. **`journalctl -k` completeness with `dmesg_restrict=1`:** `journalctl -k`
   should not be affected (it reads from the systemd journal, not `/dev/kmsg`
   directly), but this has not been tested on a system with
   `dmesg_restrict=1`.

2. **Journal rate-limiting edge cases:** If `journald` ratelimits kernel
   messages, OOM lines could be dropped before the diagnostic query runs.
   This is a shared limitation with all journal-based diagnostics.

3. **`|| true` masking of journalctl failures:** The diagnostic is
   presence-only. If `journalctl` fails silently (masked by `|| true`), the
   absence of a diagnostic is indistinguishable from "no OOM events." A
   future improvement could use `journalctl --grep` (if supported) to
   distinguish command failure from no matches.

4. **Match class classification accuracy:** The `match_classes` field is
   derived from simple substring checks on matched lines. A single line
   could match multiple classes (e.g., `oom-killer:` and `invoked
   oom-killer` on the same line). The deduplication preserves order but
   does not attempt to resolve semantic overlap — this is acceptable for an
   informational field.

---

## 17. Confirmation

- No production files (`syscheck.py`, `test_syscheck.py`, `constants.py`)
  were modified.
- No branches were created.
- No commits were made.
- Only this assessment document was overwritten.
