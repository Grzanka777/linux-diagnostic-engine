# Post-v0.1.5 Session and Service Reliability Pack

## 1. Checkpoint

- Repository: `/run/media/<USER>/<VOLUME>/projekty/linux-diagnostic-engine`.
- Baseline release: `5c6951756e4edd0e1888028b57b2cff799c784d3`.
- `HEAD`, `origin/master`, and tag `v0.1.5` pointed to the same commit before and after this task.
- Initial worktree had no tracked or staged changes. Existing untracked paths were preserved: the two prior release reviews, `.codex/`, `build/`, and `linux_diagnostic_engine.egg-info/`.
- `neural status`: Brain `Initialized`, trust `TRUSTED_CURRENT`; no Brain write was performed. The relevant historical search returned no matching LDE session-reliability record.
- No commit, push, tag, version bump, network call, sudo/root operation, or system mutation was performed.

## 2. Source inventory

The inventory was completed before implementation. It records both active sources and intentionally absent pipeline routes.

| Source | Collection command | Success contract | Failure contract | RAW / OBS category | Current rule / presentation | Authority and limits |
|---|---|---|---|---|---|---|
| User failed units | `systemctl --user --failed --no-pager` | `rc=0` plus a parseable result; `0 loaded units listed` is authoritative zero | Preserve status, rc, stdout, stderr; failure is not a failed unit | `systemd_failed` for positive; `systemd_user_source_failure` for unavailable, malformed, or truncated output | `FailedUserUnitRule`; systemd report section and restrictions | Requires a reachable user systemd bus; no root-cause inference |
| User timers | `systemctl --user list-timers --no-pager` | Report-only command capture | Display fallback text only | None | Report-only | Same user-bus limitation; not part of the implemented failed-unit contract |
| User journal | No current `journalctl --user` collection exists | Not applicable | Not applicable | None | No rule; no report section | Explicit inventory gap, not silently treated as clean |
| Graphical/session journal | Bounded `journalctl -b` filtered for `niri`, `dms`, `wayland`, `greetd`, `i915`, `drm`, then `error|fail|warn`, tail 30 | Captured lines are supporting report data | `CmdResult` fallback and truncation restriction | None | Report-only | Bounded and component-filtered; a warning alone is not authoritative user impact |
| Niri outputs | `niri msg outputs` | Successful output inventory | Fallback text | None | Report-only | Confirms output query only; does not prove compositor health |
| DMS / Quickshell / udisks | Covered by the bounded graphical/session journal | Exact line is retained as report evidence | Fallback and possible truncation restriction | None | No dedicated rule | Ownership may be visible in the line, but impact and actionability were not established |
| PipeWire / WirePlumber | Kernel/current-boot journal segfault query | Exact kernel segfault signature and bounded capture | Fallback and truncation restriction | Existing `segfault` / `SEGFAULT-WP-001` | `WirePlumberSegfaultRule`; finding and recommendation already existed | Exact WirePlumber/libcamera signature is already owned; no new session rule added |
| Pipeline accounting | `RawDiagnostic` → `_raw_to_observation()` → rule engine → `_refresh_pipeline_accounting()` | Every emitted Observation ends in a Finding or stable rejection | Source failure remains rejected with explicit reason | Runtime-only accounting | Existing internal projection | Snapshot schema remains unchanged; accounting is not a new public schema field |

## 3. Real-machine baseline

Command:

```text
env -u PYTEST_ADDOPTS TMPDIR=/tmp TMP=/tmp TEMP=/tmp PYTHONDONTWRITEBYTECODE=1 python3 syscheck.py run --output-dir <temporary>/reports --snapshot <temporary>/snapshot.json --quiet
```

Baseline evidence: `/tmp/lde-v015-session-baseline-rerun.sXfsBz`.

- Real workstation: `<HOST>`, CachyOS, kernel `7.2.2-1-cachyos`, niri / Wayland.
- Return code: `0`.
- Commands: `69`.
- RAW: `5`; OBS: `5`; Evidence: `4`; Findings: `4`; recommendations: `4`; restrictions: `6`.
- Existing findings were `SEGFAULT-WP-001`, `KERNEL-TAINT-001`, `PLATFORM-ACPI-FIRMWARE-ERROR-001`, and informational `KRNL-INFO-001`.
- `systemctl --user --failed` returned rc `1` with `Failed to connect to user scope bus via local transport: No data available`. The baseline displayed this in the report but emitted no structured RAW/OBS/restriction for it.
- Observed event classifications:
  - user-systemd bus error: `SOURCE_COLLECTION_FAILURE`;
  - repeated Quickshell invalid desktop-entry line: `BENIGN_INFORMATIONAL`;
  - repeated DMS/udisks monitor runtime-check line: `INCOMPLETE_EVIDENCE`;
  - DMS destroyed-notification error: `TRANSIENT_NON_ACTIONABLE`;
  - ten WirePlumber/libcamera kernel segfaults: `CONFIRMED_FAILURE`, already owned by the existing rule;
  - successful `niri msg outputs`: `BENIGN_INFORMATIONAL`.

## 4. User-systemd evidence contract

The contract is deterministic and fail-closed:

| Input state | RAW / OBS / Evidence | Finding / recommendation | Public result |
|---|---|---|---|
| Bus available, authoritative zero | None | None | No failed-user-service Finding |
| Bus available, one or more parseable failed units | `systemd_failed` → `systemd_failed`; `SERVICE_STATE` | Existing `SYSD-USR-FAIL-001` and its existing recommendation | Failed units are reported |
| Query execution failure, including bus unavailable | `systemd_user_source_failure` → same category; `COMMAND_RESULT`, partial, direct | No service Finding and no service recommendation | Restriction identifies unknown user-service state; rc/status/stderr are preserved |
| Timeout | Same source-failure path | No service Finding | Timeout is not evidence of a failed service |
| Successful malformed, empty, or truncated output | Same source-failure path with `failure_kind=malformed_output` | No service Finding | Non-authoritative result is visible and cannot prove zero |

The new RAW payload preserves scope, exact query, failure kind, authority flag, execution status, return code, stdout, and stderr. Provenance separately preserves command, status, rc, collection time, and truncation. The source-failure rule emits Evidence only; it intentionally emits no Finding.

## 5. Session / graphics evidence contract

The current graphical journal is a bounded supporting source, not a generic warning detector. The implementation keeps DMS/Quickshell/udisks/niri lines report-only because the real capture provided no defensible user-impact proof, stable remediation boundary, or benign-near-miss contract for a new Finding. The existing WirePlumber/libcamera segfault path remains the sole applicable session-adjacent rule and was not duplicated.

## 6. Implemented high-confidence fixes

Exactly one high-confidence product defect was fixed: an unavailable user-systemd failed-unit query is now distinguished from an authoritative zero and from a real failed-unit result.

Changed paths and hunk summary:

- `syscheck.py`: added source-failure classification, payload-preserving Evidence, source-failure Observation and rejection reasons, strict user failed-unit state parsing, report/restriction propagation, and `SOURCE_FAILURE` internal classification.
- `diagnostic_rules.py`: added and registered `SystemdUserSourceFailureRule`, which emits command-result Evidence without a Finding.
- `test_syscheck.py`: added the real-world state corpus and converted four old empty user-systemd fixtures to explicit authoritative zero output.
- `.agent-work/reviews/post-v0.1.5-session-service-reliability-pack.md`: this local review artifact.

Tracked source diff stat before adding this review artifact: `296 insertions(+), 6 deletions(-)` across the three source/test files. Full tracked diff SHA-256: `58eb2a432d28b95cc9489f43ddcd6f8b539631363b9383737087a4ee963974ab`.

## 7. Explicitly rejected / deferred signatures

| Exact signature or bounded candidate | Frequency in baseline | Impact evidence | Ownership / actionability | Decision |
|---|---:|---|---|---|
| `quickshell.desktopentry: Encountered invalid line in desktop entry (no =) "[Desktop Entry]\r"` | At least 12 visible bounded lines | No reported user impact | Component ownership likely DMS/Quickshell; remediation boundary not proven | Deferred; report-only |
| `monitor_on_interface_proxy_properties_changed: runtime check failed: (g_strv_length ((gchar **) invalidated_properties) == 0)` | 12 visible lines in three bursts | No mount, USB, or session failure correlated | DMS invokes udisksctl; ownership/actionability incomplete | Deferred; incomplete evidence |
| `ERROR: Cannot close destroyed notification` | 1 | No persistent notification or session impact shown | DMS ownership likely; transient semantics | Rejected as non-actionable transient |
| Kernel `wireplumber[...] segfault ... in libspa-libcamera.so` | 10 | Direct kernel-reported process failures; existing Finding present | Existing rule has ownership and bounded recommendation | Kept under existing rule; no new diagnostic |
| `cups.service unavailable` / CUPS query failure | Not observed | No exact baseline line | No current evidence | Deferred; no diagnostic |
| `wl-mirror: command not found` or equivalent missing helper | Not observed | No exact baseline line | No current evidence | Deferred; no diagnostic |
| `evdev ... disappeared` | Not observed | No exact baseline line | No current evidence | Deferred; no diagnostic |
| PipeWire stream connection failure | Not observed in bounded capture | No exact baseline line or impact | No current evidence | Deferred; no diagnostic |

`NEW_SESSION_DIAGNOSTICS_ADDED = 0`. The deferred backlog is one bundled future decision covering first-class contracts for the report-only session sources; it is not a speculative implementation.

## 8. False-positive contracts

The focused corpus covers all required states:

- available bus plus zero failed units: no user-service Finding;
- available bus plus a failed unit: existing Finding remains;
- unavailable/error bus: source failure only;
- timeout: source failure only;
- malformed, empty, or truncated output: non-authoritative source failure only.

No state above emits `SYSD-USR-FAIL-001` unless a parseable failed-unit marker is present in an authoritative successful result.

## 9. Exact-command recommendation tests

No recommendation command string or shell pipeline was changed. The new source-failure path emits no recommendation. Existing exact command execution coverage remains applicable, and the focused recommendation/command run passed `77` tests. This satisfies the command standard without adding a string-only assertion for an untouched recommendation.

## 10. Pipeline accounting

Final real-machine accounting run:

| RAW source | Observation | Outcome | Finding | Reason |
|---|---|---|---|---|
| `BTRFS-MISSING-INCOMPLETE-001` | `BTRFS-ERR-001` | rejected | — | `privilege_limited_btrfs_missing` |
| `SEGFAULT-WP-001` | `SEGFAULT-WP-001` | finding | `SEGFAULT-WP-001` | — |
| `KERNEL-TAINT-001` | `KERNEL-TAINT-001` | finding | `KERNEL-TAINT-001` | — |
| `PLATFORM-ACPI-FIRMWARE-ERROR-001` | same | finding | `PLATFORM-ACPI-FIRMWARE-ERROR-001` | — |
| `SYSD-USR-SOURCE-FAIL-001` | `SYSD-USR-SOURCE-FAIL-001` | rejected | — | `user_systemd_query_unavailable` |
| `KRNL-INFO-001` | `KRNL-INFO-001` | finding | `KRNL-INFO-001` | — |

The final run had `69` commands, `6` RAW, `6` OBS, `5` Evidence, and `4` Findings. Every Observation had either a Finding or a stable rejection reason.

## 11. Real-world replay corpus

The corpus is deterministic and sanitized from the real workstation contract:

- explicit `0 loaded units listed` success;
- exact real bus-error text with rc `1` and preserved stderr;
- timeout, not-found, and permission-denied execution states;
- parseable failed-user-unit positive case;
- successful malformed output;
- truncated zero output, which is rejected as non-authoritative;
- exact real DMS/Quickshell/udisks/WirePlumber signatures evaluated for implementation or rejection;
- existing exact recommendation-command tests.

## 12. Focused tests

- Test-first pre-fix run: the five new failure/malformed cases failed because no source RAW existed; the two unchanged zero/positive checks passed.
- Final user-systemd contract run: `8 passed, 893 deselected`.
- Final recommendation/command run: `77 passed, 824 deselected`.

## 13. Full validation

- `env -u PYTEST_ADDOPTS TMPDIR=/tmp TMP=/tmp TEMP=/tmp PYTHONDONTWRITEBYTECODE=1 python -m pytest -q`: `910 passed`.
- `ruff format --check .`: pass.
- `ruff check .`: pass.
- `git diff --check`: pass.

The release baseline was `902` tests. The final suite increased to `910`; the increase is attributable to the added contract coverage and not to a version or compatibility change.

## 14. Real-machine before / after proof

| Metric | v0.1.5 baseline | Post-fix | Interpretation |
|---|---:|---:|---|
| Return code | 0 | 0 | Run remained successful |
| Commands | 69 | 69 | Collection surface unchanged |
| RAW | 5 | 6 | One explicit user-systemd source-failure RAW added |
| OBS | 5 | 6 | One incomplete source-failure Observation added |
| Evidence | 4 | 5 | One partial direct command-result Evidence added |
| Findings | 4 | 4 | No new finding |
| Recommendations | 4 | 4 | No new recommendation |
| Restrictions | 6 | 7 | One user-systemd availability restriction added |

Post-fix evidence: `/tmp/lde-v015-session-final.2PAjFA`, RC `0`. Finding IDs and recommendation IDs are identical to baseline. The only new pipeline item is the expected rejected user-systemd source failure. The post-fix report explicitly states that the unavailable source is not treated as a failed service.

## 15. Compatibility / version proof

- `PRODUCT_VERSION = 0.1.5`.
- `REPORT_COMPATIBILITY_VERSION = 2.1.0`.
- `SNAPSHOT_SCHEMA_VERSION = 3`.
- `python3 syscheck.py --version` printed `Linux Diagnostic Engine 0.1.5`.
- No public CLI redesign, schema migration, compatibility bump, or persisted-field contract change was made.

## 16. Git verification

- `HEAD`: `5c6951756e4edd0e1888028b57b2cff799c784d3`.
- `origin/master`: `5c6951756e4edd0e1888028b57b2cff799c784d3`.
- Tag at `HEAD`: `v0.1.5`.
- Branch: `master`, tracking `origin/master`.
- Reflog tip remains the v0.1.5 release commit; no history rewrite occurred.
- Final tracked changes are limited to `diagnostic_rules.py`, `syscheck.py`, and `test_syscheck.py`; this review and the pre-existing local artifacts remain untracked.
- `git diff --check`: pass. No staging, commit, push, or tag operation was performed.

## 17. Deferred backlog

One bounded backlog item remains: decide whether user timers and a future user-journal source should receive their own first-class source-failure contracts. That decision requires a separate scope and evidence review. It is not needed to prevent false failed-user-service Findings in the current `systemctl --user --failed` path.

## 18. Verdict

`POST_V0_1_5_SESSION_SERVICE_RELIABILITY_PACK = PASS`

The high-confidence ambiguity is closed, the false-positive contract is covered, session signatures are evaluated without speculative diagnostics, real-machine before/after evidence is consistent, and the repository is ready for the next product decision with one explicitly bounded deferred backlog item.
