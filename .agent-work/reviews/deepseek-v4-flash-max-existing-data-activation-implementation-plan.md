# DeepSeek V4 Flash Max — Existing Data Activation Implementation Plan

## 1. Executive decision

### Recommended implementation slice

**Activate firewall status as a diagnostic.**

The `collect_network()` method already:

1. Checks three firewall backends (`firewalld`, `ufw`, `nftables`).
2. Computes a `firewall_found` boolean and `firewall_details` list.
3. Produces a display-only report warning when no firewall is detected.

The recommended slice converts this display-only analysis into a structured diagnostic:

- **One new Rule**: `FirewallStatusRule`
- **One new Finding**: `NET-FW-001` ("No active firewall detected")
- **Zero new shell commands** — every needed command already runs
- **Zero new collectors** — data is collected and partially analyzed in `collect_network()`

### Why this is the best next product increment

| Criterion | Assessment |
|---|---|
| Existing data | Fully collected and already partially analyzed (`firewall_found` boolean, `firewall_details` list) |
| Implementation cost | Lowest possible — add a RawDiagnostic creation at the point where analysis is already complete |
| User value | Medium — workstation security awareness |
| False-positive risk | Near zero — each backend check is deterministic |
| Cross-distro stability | Excellent — checks nftables, firewalld, and ufw independently |
| Architectural impact | None — fits existing `Observation → Evidence → Finding → Recommendation` pipeline |
| Testability | High — simple boolean condition |

### Why broader work is deferred

The Product Coverage Assessment (`.agent-work/reviews/syscheck-product-coverage-assessment.md`) identified 22 candidate domains and 6 epics. The firewall slice is deliberately the smallest safe increment:

- Temperature/sensor activation would require new parsing of sensor output (per-chip format varies), adding complexity and cross-distribution risk.
- Memory/swap/zram diagnostics would require new parsing of `free -h` and `zramctl` output and new Observation categories.
- Graphics/GPU diagnostics have higher false-positive risk from transient driver messages.

The firewall slice proves the activation pattern with minimal risk before tackling larger slices.

---

## 2. Repository checkpoint

| Property | Value |
|---|---|
| **Repository root** | `<REDACTED-PATH>` |
| **Product** | SysCheck — diagnostic tool for Arch Linux / CachyOS / Debian / RHEL |
| **Branch** | `master` |
| **HEAD** | No commits (working tree only) |
| **Working tree status** | Modified (staged `syscheck.py`, `test_syscheck.py`, `constants.py` from prior iterations; unstaged review documents) |
| **Unrelated changes** | None that affect this analysis — all prior iterations are complete and stable |
| **Key directories** | `.agent-work/prompts/`, `.agent-work/reviews/`, `__pycache__/` |
| **Python** | 3.14.6 |
| **Ruff** | 0.15.19 |
| **pytest** | 9.1.1 |
| **mypy** | Not installed |

### Files inspected

| Path | Purpose |
|---|---|
| `syscheck.py` (4273 lines) | All collectors, models, rules, pipeline, rendering |
| `test_syscheck.py` (4984+ lines) | All existing tests |
| `constants.py` (86 lines) | Configuration constants |
| `.agent-work/prompts/deepseek-v4-flash-max-existing-data-activation-implementation-plan.md` | This prompt |
| `.agent-work/reviews/syscheck-product-coverage-assessment.md` | Prior coverage assessment |
| `.agent-work/reviews/post-migration-architecture-assessment.md` | Prior architecture assessment |
| `.agent-work/reviews/iteration-23-boot-time-collector-payload.md` | Prior iteration review |

### Project configuration

No `pyproject.toml`, `setup.cfg`, `ruff.toml`, or `pytest.ini` exists. All tools use defaults:

- **`ruff format --check .`** — default formatting rules
- **`ruff check .`** — default lint rules
- **`python3 -m pytest -q`** — default test discovery
- **`mypy .`** — not installed (confirmed unavailable)

---

## 3. Current pipeline map

```
Collector (9 methods, ~50 commands)
    │
    ▼
RawDiagnostic (12 instances across 9 categories)
    │  source_id, category, payload
    │
    ▼
_raw_to_observation()  (12 branches)
    │
    ▼
Observation  (12 instances)
    │  obs_id, category, details, quality flags, source_raw_ids
    │
    ▼
DiagnosticRuleEngine.evaluate()
    │
    ├── FindingClassificationPolicy.classify()
    │       └── domain, kind, actionability, intent
    │
    ├── DiagnosticRuleRegistry → DiagnosticRule (11 rules)
    │       └── evaluate(observation, classification)
    │           ├── EvidenceBuilder.build(observation)
    │           │       └── Evidence (type, data, summary, quality, provenance)
    │           └── DiagnosticRuleResult(finding, evidence)
    │
    └── _normalize() → DiagnosticEvaluation(findings, evidence)
    │
    ▼
SysCheckEngine
    ├── findings → build_summary() → Report
    ├── evidence_objects → runtime-only, not persisted
    ├── observations → EnvironmentSnapshot (as ObservationSnapshot)
    │
    ▼
RecommendationEngine.generate(findings, restrictions)
    │
    ▼
RecommendationPlan → Report
```

Key symbols and paths:
- `RawDiagnostic`: lines 205-216
- `Observation`: lines 227-266
- `Evidence`: lines 752-763
- `EvidenceBuilder`: lines 780-1036
- `EvidenceType`: lines 719-730
- `DiagnosticRule`: lines 1044-1050 (ABC)
- `DiagnosticRuleEngine`: lines 1557-1632
- `FindingClassificationPolicy`: lines 625-713
- `SysCheckEngine.collect_*`: lines 1825-2731
- `SysCheckEngine._raw_to_observation`: lines 2800-2937
- `SysCheckEngine._interpret`: lines 2940-2953
- `RecommendationEngine`: lines 3151-3244
- `build_default_rule_engine`: lines 1635-1651

---

## 4. Collector utilization matrix

### Legend

| Status | Meaning |
|---|---|
| **Active** | Collector output is consumed by at least one diagnostic rule with populated payload |
| **Partial** | Collector output is consumed but with empty payload, or only partially analyzed |
| **Report-only** | Collector output is displayed in the report but never enters the structured pipeline |
| **Empty-risk** | RawDiagnostic created with `payload={}`, limiting downstream Evidence quality |
| **Unused** | No consumer found in any code path (rules, rendering, serialization, tests) |

### Matrix

| Collector | Output / payload | Source location | Consumer(s) | Diagnostic(s) | Current status | User problem | Product value | FP risk | Recommended disposition | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| `collect_base_info` — os-release | `osr` string, `os_info` dict | lines 1828-1854 | `self.report_lines` (display) | None | **Report-only** | Other | Low | — | Keep report-only | No RawDiagnostic created |
| `collect_base_info` — kernel version | `self.active_kernel` | line 1841 | kernel count report display | None | **Report-only** | Other | Low | — | Keep report-only | Used for report text, not pipeline |
| `collect_base_info` — /proc/cmdline | `cmdline` string | line 1844 | `self.report_lines` (display) | None | **Report-only** | Boot | Low | — | Keep report-only | No RawDiagnostic created |
| `collect_base_info` — ls /boot/ | `boot_list` | line 1845 | `self.report_lines` (display) | None | **Report-only** | Boot | Low | — | Keep report-only | No RawDiagnostic created |
| `collect_base_info` — ls /usr/lib/modules/ | `modules_list` | line 1846 | `self.report_lines` (display) | None | **Report-only** | Boot | Low | — | Keep report-only | No RawDiagnostic created |
| `collect_resources` — lscpu | `lscpu` string | line 1935 | display (truncated) | None | **Report-only** | Performance | Low | — | Keep report-only | No RawDiagnostic created |
| `collect_resources` — free -h | `free_h` string | line 1944 | display | None | **Report-only** | Performance | Medium | — | **Activation candidate** | Has user value for memory pressure; needs parsing |
| `collect_resources` — zramctl | `zramctl` string | line 1947 | display | None | **Report-only** | Performance | Medium | — | **Activation candidate** | Has user value for swap config |
| `collect_resources` — loadavg | `loadavg` string | line 1938 | display | None | **Report-only** | Performance | Low | — | Keep report-only | Transient metric; high FP risk |
| `collect_resources` — cpu governor | `governor` string | line 1941 | display | None | **Report-only** | Performance | Low | — | Keep report-only | Informational; no actionable diagnosis |
| `collect_resources` — ps aux | `ps_cpu`, `ps_mem` strings | lines 1950-1957 | display (truncated) | None | **Report-only** | Performance | Low | — | Keep report-only | Transient snapshot; high FP risk |
| `collect_resources` — sensors | `sensors_raw`, `sensors_filtered` | lines 1960-1974 | display; `"crit="` check | None | **Report-only** | Thermal | Medium | Medium | **Activation candidate** | Needs parsing per-chip; `"crit="` check exists but is weak |
| `collect_storage` — lsblk | `lsblk` string | line 1998 | display | None | **Report-only** | Storage | Low | — | Keep report-only | Informational listing |
| `collect_storage` — df -h | parsed `usage` list of `(mount, pct)` | lines 2071-2099 | `StorageUsageRule` | `STORAGE-USAGE-WARNING`, `STORAGE-USAGE-CRITICAL` | **Active** | Storage | High | Low | Keep active | Full payload: mountpoint, usage_percent, threshold_state |
| `collect_storage` — df -i | `df_i` string | line 2002 | display | None | **Report-only** | Storage | Low | — | Keep report-only | Inode exhaustion is rare on workstations |
| `collect_storage` — btrfs filesystem show | `btrfs_show` string | line 2004 | display | None | **Report-only** | Storage | Low | — | Keep report-only | No diagnostic value without parsing |
| `collect_storage` — btrfs filesystem df | `btrfs_df` string | line 2006 | display | None | **Report-only** | Storage | Low | — | Keep report-only | No diagnostic value without parsing |
| `collect_storage` — btrfs device stats | parsed `_errs` lines | lines 2039-2055 | `BtrfsDeviceErrorRule` | `BTRFS-ERR-001` | **Empty-risk** | Storage | High | Low | **Harden** (populate payload) | Payload is `{}`; should contain error details |
| `collect_storage` — btrfs scrub status | `_classify_btrfs_status()` result | lines 2057-2069 | `BtrfsScrubStatusRule` | `BTRFS-SCRUB-001` | **Empty-risk** | Storage | Medium | Low | **Harden** (populate payload) | Payload is `{}`; should contain scrub_status detail |
| `collect_storage` — nvme list | `nvme_result` | lines 2012-2019 | display | None | **Report-only** | Storage | Medium | — | **Activation candidate** | Optional dependency; has strategic value |
| `collect_kernel_hw` — kernel errors | `kernel_errors_out` (filtered) | lines 2154-2160 | display; taint check | `KERNEL-TAINT-001` | **Partial** | Kernel | High | Low | Keep (partially active) | Taint uses payload={}; kernel errors display-only |
| `collect_kernel_hw` — segfaults | `segfaults_dedup`, `unique_segfault_count` | lines 2161-2230 | Segfault rules | `SEGFAULT-*` | **Empty-risk** | Stability | High | Low | **Harden** (populate payload with count/type) | All 3 segfault payloads are `{}` |
| `collect_kernel_hw` — firmware | `firmware_filtered` | lines 2169-2175 | display | None | **Report-only** | Firmware | Low | — | Keep report-only | Informational only |
| `collect_kernel_hw` — dmesg_restrict | `dmesg_restrict` stdout | lines 2176-2186 | restriction note | None | **Report-only** | Security | Low | — | Keep report-only | Used for restriction, not diagnostic |
| `collect_kernel_hw` — lspci | `lspci_result` | lines 2187-2192 | display (truncated) | None | **Report-only** | Hardware | Low | — | Keep report-only | Format too variable for parsing |
| `collect_kernel_hw` — lsusb | `lsusb_result` | line 2194 | display | None | **Report-only** | Hardware | Low | — | Keep report-only | Format too variable for parsing |
| `collect_systemd` — sys failed | `_sys_units` list | lines 2307-2316 | `FailedSystemUnitRule` | `SYSD-SYS-FAIL-001` | **Active** | Systemd | High | Low | Keep active | Full payload: scope, units |
| `collect_systemd` — usr failed | `_usr_units` list | lines 2319-2328 | `FailedUserUnitRule` | `SYSD-USR-FAIL-001` | **Active** | Systemd | High | Low | Keep active | Full payload: scope, units |
| `collect_systemd` — analyze | `userspace_time`, `total_time` | lines 2330-2389 | `BootDelayRule` | `BOOT-SLOW-001` | **Active** | Boot | High | Low | Keep active | Populated in Iteration 23 |
| `collect_systemd` — blame | `blame_out` string | lines 2331, 2344-2371 | display (top 20); fstrim analysis | `BOOT-SLOW-001` (indirect, fstrim) | **Partial** | Boot | Medium | Low | Keep partial | Only fstrim is parsed; rest is display |
| `collect_systemd` — critical-chain | `critical_out` string | line 2332 | display; fstrim check | `BOOT-SLOW-001` (indirect, fstrim) | **Partial** | Boot | Medium | Low | Keep partial | Only fstrim membership checked |
| `collect_systemd` — timers (sys+usr) | `timers`, `usr_timers` | lines 2295-2296 | display | None | **Report-only** | Boot | Low | — | Keep report-only | Informational listing |
| `collect_systemd` — auto-restart | `auto_restart` | line 2297 | display | None | **Report-only** | Systemd | Low | — | Keep report-only | Informational |
| `collect_systemd` — restarting | `restarting` | line 2298 | display | None | **Report-only** | Systemd | Low | — | Keep report-only | Informational |
| `collect_packages` — orphans | `orphans_result` | lines 2428-2439 | display | None | **Report-only** | Packages | Medium | — | **Activation candidate** | Could flag orphan count > threshold |
| `collect_packages` — foreign/AUR | `foreign_result` (aur_count) | lines 2441-2455 | display (truncated) | None | **Report-only** | Packages | Medium | — | Keep report-only | Informational count |
| `collect_packages` — kernels | `bootable_count` | lines 2458-2514 | `KernelCountRule` | `KRNL-INFO-001` | **Active** | Packages | Medium | Low | Keep active | Full payload: count |
| `collect_graphics` — DRM vendor/device | `drm_vendor`, `drm_device` | lines 2549-2562 | display | None | **Report-only** | Graphics | Low | — | Keep report-only | Identification data |
| `collect_graphics` — DRM nodes | `drm_ls` | line 2562 | display | None | **Report-only** | Graphics | Low | — | Keep report-only | Informational |
| `collect_graphics` — niri outputs | `niri_out` | line 2565 | display | None | **Report-only** | Graphics | Low | — | Keep report-only | Compositor-specific |
| `collect_graphics` — gfx logs | `gfx_logs_filtered` | lines 2567-2572 | display | None | **Report-only** | Graphics | Medium | High | Keep report-only | High FP risk; transient messages |
| `collect_network` — ip addr | `ip_addr` | lines 2607-2613 | display (truncated) | None | **Report-only** | Network | Low | — | Keep report-only | Display only |
| `collect_network` — ss -tlnp | `ss_output` parsed for listeners | lines 2615, 2636-2663 | display; local/external analysis | None | **Report-only** | Network | Medium | Medium | **Activation candidate** | External listener detection exists but is display-only |
| `collect_network` — resolvectl | `resolvectl` | lines 2617-2625 | display (truncated) | None | **Report-only** | Network | Low | — | Keep report-only | Display only |
| `collect_network` — NetworkManager | `nm_status` | lines 2627-2629 | display (first 15 lines) | None | **Report-only** | Network | Low | — | Keep report-only | Display only |
| `collect_network` — auth fails | `auth_fails` count | lines 2631-2633 | display (count text) | None | **Report-only** | Security | Medium | Low | **Activation candidate** | Count already computed; could flag threshold |
| `collect_network` — firewalld | `firewalld_result` | lines 2687-2691 | display; `firewall_found` | None | **Report-only** | Security | Medium | Low | **→ PRIMARY SLICE** | Already analyzed as `firewall_found` boolean; just needs activation |
| `collect_network` — ufw | `ufw_result` | lines 2694-2699 | display; `firewall_found` | None | **Report-only** | Security | Medium | Low | **→ PRIMARY SLICE** | Already analyzed as `firewall_found` boolean |
| `collect_network` — nftables | `nft_result` | lines 2670-2683 | display; `firewall_found` | None | **Report-only** | Security | Medium | Low | **→ PRIMARY SLICE** | Already analyzed as `firewall_found` boolean |
| `collect_userenv` — shell, term, lang, etc. | env var strings | lines 2717-2731 | display | None | **Report-only** | Other | Low | — | Keep report-only | Low value; no diagnostic potential |
| `collect_userenv` — fish version | `fish_ver` | line 2717 | display | None | **Report-only** | Other | Low | — | Keep report-only | Low value |

---

## 5. Diagnostic coverage metrics

### Measured values

| Metric | Value | Derivation |
|---|---|---|
| **Total collector methods** | 9 | `collect_base_info`, `collect_resources`, `collect_storage`, `collect_kernel_hw`, `collect_systemd`, `collect_packages`, `collect_graphics`, `collect_network`, `collect_userenv` |
| **Collectors actively used by ≥1 diagnostic** | 4 | `collect_storage` (StorageUsageRule, BtrfsDeviceErrorRule, BtrfsScrubStatusRule), `collect_kernel_hw` (Segfault rules, KernelTaintRule), `collect_systemd` (FailedUnit rules, BootDelayRule), `collect_packages` (KernelCountRule) |
| **Collectors partially consumed** | 2 | `collect_systemd` (blame/critical-chain used only for fstrim), `collect_kernel_hw` (kernel errors used for taint only; rest display-only) |
| **Report-only collectors** | 4 | `collect_base_info`, `collect_resources`, `collect_graphics`, `collect_userenv` |
| **Collectors with no consumer** | 0 | Every collector's output appears in the report at minimum |
| **RawDiagnostics with empty payload** | 6 | BTRFS-ERR-001, BTRFS-SCRUB-001, SEGFAULT-WP-001, SEGFAULT-SYS-001, SEGFAULT-MIN-001, KERNEL-TAINT-001 |
| **Computed shell commands** | ~48 | Across all 9 collectors (some vary by distro) |
| **Diagonstic rules** | 11 | `build_default_rule_engine()` line 1638-1650 |

### Inferred values

| Metric | Value | Rationale |
|---|---|---|
| **Collector utilization rate** | ~44% (4/9) actively used | 4 collectors produce diagnostics; 5 produce only display data |
| **Data consumption rate** | ~40% of collected data enters pipeline | Most commands output is display-only; only ~20 of ~48 command outputs are parsed for diagnostics |
| **Empty payload rate** | 50% (6/12) | Half of all RawDiagnostic instances carry no structured data |

### Values that cannot yet be measured reliably

- **Lines of collector code vs. rule code** — Not counted; the file is a single module without breakdown.
- **Test coverage per collector** — Not measured; the existing test suite uses synthetic Observations, not collector-level integration tests.
- **CPU/memory cost per collector** — Not measured; no profiling infrastructure exists.

### Critical limitation

The 6 empty-payload RawDiagnostics (`btrfs_error`, `btrfs_scrub`, `segfault` ×3, `tainted`) represent a significant quality gap. The downstream Evidence and Finding for these diagnostics contain no structured data — only category and source_id. The EvidenceBuilder for these categories handles missing data with fallback summary text (e.g., "Btrfs device state observation recorded", "Segfault events detected in kernel journal (0)"), but the `details={}` Observation means the rule engine and recommendation engine receive no factual payload.

---

## 6. Candidate activation slices

### Candidate A: Firewall status diagnostic (PRIMARY)

| Property | Detail |
|---|---|
| **User problem** | User may not know their workstation has no active firewall |
| **Source collector** | `collect_network()` lines 2665-2711 |
| **Existing analysis** | `firewall_found` boolean, `firewall_details` list, `firewall_found` display warning |
| **Proposed diagnostic** | "No active firewall detected" — P3, SECURITY domain, ACTIONABLE |
| **Evidence chain** | Service state check for firewalld + ufw + nftables → Observation → SERVICE_STATE Evidence |
| **Recommendation** | "Install and enable a firewall" |
| **Value** | Medium |
| **FP risk** | Low |
| **Files** | ~5 (production + test) |
| **Decision** | **ACCEPT — primary slice** |

### Candidate B: Temperature threshold diagnostic (DEFERRED)

| Property | Detail |
|---|---|
| **User problem** | Overheating causes performance loss or hardware damage |
| **Source collector** | `collect_resources()` lines 1959-1974 |
| **Existing analysis** | `_filter_invalid_temperatures()` removes < -100°C readings; `"crit=" in sensors_raw` check exists but only detects threshold definition, not exceedance |
| **Proposed diagnostic** | "CPU/GPU temperature exceeds safe threshold" |
| **Evidence chain** | sensor output → parse numeric readings → HARDWARE_STATE Evidence |
| **Value** | Medium-High |
| **FP risk** | Medium (transient load spikes, laptop vs desktop differences) |
| **Files** | ~7 (new parsing utility + production + test) |
| **Decision** | **DEFER** — requires per-chip sensor parsing; higher complexity than firewall slice |

### Candidate C: External network listeners diagnostic (DEFERRED)

| Property | Detail |
|---|---|
| **User problem** | Unintended external network exposure |
| **Source collector** | `collect_network()` lines 2636-2663 |
| **Existing analysis** | `external_listeners` list already computed; display warning already generated |
| **Proposed diagnostic** | "External network services detected" |
| **Evidence chain** | ss -tlnp output → parsed addresses → SERVICE_STATE Evidence |
| **Value** | Medium |
| **FP risk** | Medium (many legitimate services listen externally: Docker, KDE Connect, etc.) |
| **Files** | ~5 |
| **Decision** | **DEFER** — higher FP risk; needs allowlist of known-good services |

### Candidate D: Memory pressure / zram diagnostic (DEFERRED)

| Property | Detail |
|---|---|
| **User problem** | Low memory or misconfigured swap causes thrashing |
| **Source collector** | `collect_resources()` lines 1943-1947 |
| **Existing analysis** | None (display-only) |
| **Proposed diagnostic** | "Low memory available" or "No swap configured" |
| **Evidence chain** | free -h output → parse percentages → DERIVED_MEASUREMENT Evidence |
| **Value** | Medium |
| **FP risk** | Medium (threshold-dependent) |
| **Files** | ~7 (new parsing + production + test) |
| **Decision** | **DEFER** — requires new parsing of free -h output |

---

## 7. Selected implementation slice: Firewall status diagnostic

### Diagnostic identifier

Following current naming conventions:

| Element | Value | Convention source |
|---|---|---|
| **source_id** | `NET-FW-001` | Pattern: `{AREA}-{TOPIC}-{NUM}` (e.g., `BOOT-SLOW-001`, `SYSD-SYS-FAIL-001`, `KRNL-INFO-001`) |
| **category** | `firewall_status` | Descriptive snake_case (e.g., `boot_time`, `systemd_failed`, `kernel_count`) |
| **obs_id** | `NET-FW-001` | Matches source_id (existing pattern) |
| **evidence_id** | `EVIDENCE-NET-FW-001-001` | `EVIDENCE-{OBS_ID}-001` pattern (line 785) |
| **finding_id** | `NET-FW-001` | Matches obs_id (existing pattern) |
| **rec_id** | `REC-NET-FW-001` | `REC-{FINDING_ID}` pattern (line 3174) |
| **domain** | `DiagnosticDomain.SECURITY` | Fits security context; add to enum if needed, or use existing `SYSTEMD` (firewall is a system service) |
| **kind** | `FindingKind.FIREWALL_STATUS` | New FindingKind; follow existing pattern |
| **actionability** | `Actionability.ACTIONABLE` | User can act on this |
| **intent** | `RecommendationIntent.INVESTIGATE` | User should investigate firewall configuration |

### Current naming conventions confirmed

From source code (syscheck.py):
- `DiagnosticDomain` enum at lines 111-124: values like `SYSTEMD`, `STORAGE`, `KERNEL`, `BOOT`, `AUDIO`, `HARDWARE`, `NETWORK`, `SECURITY`, `PACKAGES`, `ENVIRONMENT`, `OTHER`. Add `SECURITY` (already exists) or use `NETWORK`.
- `FindingKind` enum at lines 129+: values like `FAILED_UNIT`, `KERNEL_COUNT`, `KERNEL_TAINT`, `DEVICE_ERROR`, `SCRUB_STATUS`, `STORAGE_USAGE`, `BOOT_DELAY`, `SEGFAULT`. Add `FIREWALL_STATUS` following this pattern.
- `Actionability` at lines ~140: `ACTIONABLE`, `CONDITIONAL`, `INFORMATIONAL`.
- `RecommendationIntent` at lines ~148: `INVESTIGATE`, `VERIFY`, `REMEDIATE`, `MONITOR`, `INFORMATIONAL`.

### User problem

A Linux workstation user may not be aware that their system has no active firewall. While Linux desktop systems are generally not exposed to the internet directly, firewall protection matters for:

- Laptops on public/untrusted networks
- Systems with network services enabled (SSH, Samba, KDE Connect, etc.)
- Docker/Podman setups that expose ports
- Defense-in-depth against local network threats

### Diagnostic behavior

#### Triggering condition

After `collect_network()` completes the firewall check (lines 2665-2711), if `firewall_found` is `False` AND at least one firewall backend was checked (i.e., `firewall_details` is non-empty):

- `firewall_found = False` with `firewall_details` containing checked backends → emit NET-FW-001
- `firewall_found = True` → no diagnostic
- `firewall_details` is empty (all commands failed/not found) → no diagnostic (unknown state)

#### Evidence construction

```python
Evidence(
    evidence_id="EVIDENCE-NET-FW-001-001",
    evidence_type=EvidenceType.SERVICE_STATE,
    source_observation_ids=("NET-FW-001",),
    source_raw_ids=("NET-FW-001",),
    summary="No active firewall detected. Checked: firewalld (inactive), ufw (not found), nftables (active but no ruleset).",
    data={
        "firewall_found": False,
        "firewall_details": firewall_details,
        "firewalld_active": firewalld_active,
        "ufw_active": ufw_active,
        "nftables_active": nftables_active,
    },
    strength=EvidenceStrength.STRONG,
    directness=EvidenceDirectness.DIRECT,
    completeness=EvidenceCompleteness.COMPLETE,
)
```

#### Finding

```python
Finding(
    finding_id="NET-FW-001",
    title="No active firewall detected",
    severity="P3",
    confidence="Certain",
    evidence="No active firewall was detected. Checked: firewalld (inactive), ufw (not found), nftables (active but no ruleset).",
    interpretation="The system has no active firewall protecting network services on local networks.",
    recommended_diagnostics="`systemctl status firewalld`; `ufw status`; `nft list ruleset`",
    remediation="Enable a firewall: `sudo systemctl enable --now firewalld` or `sudo ufw enable`",
    verification="`sudo systemctl is-active firewalld` or `sudo ufw status`",
    risk_level="Niskie - standard dla Linux desktop, ale zalecane w sieciach publicznych.",
    domain=DiagnosticDomain.SECURITY,
    kind=FindingKind.FIREWALL_STATUS,
    actionability=Actionability.ACTIONABLE,
    recommendation_intent=RecommendationIntent.INVESTIGATE,
    source_observation_ids=("NET-FW-001",),
    evidence_ids=("EVIDENCE-NET-FW-001-001",),
)
```

#### Recommendation

```python
DiagnosticRecommendation(
    recommendation_id="REC-NET-FW-001",
    priority=3,  # P3 → derive_recommendation_priority
    title="No active firewall detected",
    impact="medium",
    effort="low",
    risk="low",
    action_type="investigate",
    rationale="The system has no active firewall. While typical for Linux desktops, this increases risk on untrusted networks.",
    recommended_diagnostics=("systemctl status firewalld", "ufw status", "nft list ruleset"),
    remediation=("sudo systemctl enable --now firewalld", "sudo ufw enable"),
    verification=("sudo systemctl is-active firewalld", "sudo ufw status"),
    source_finding_ids=("NET-FW-001",),
)
```

#### Non-trigger cases

- At least one firewall backend is active (`firewall_found = True`)
- All firewall commands failed (cannot determine status) — `firewall_details` is empty
- Firewall is active via an unlisted backend (custom iptables, etc.) — no diagnostic (cannot disprove)

#### Unavailable/unsupported behavior

- If `systemctl is-active firewalld` fails AND `ufw` is not found AND `nft` fails → unknown state → no diagnostic
- If `sudo` is required for some backends → the restriction is already tracked in `self.restrictions`; diagnostic proceeds with what is available

#### Cross-distribution considerations

- **Arch/CachyOS**: firewalld may be installed or not; ufw optional; nftables almost always present
- **Debian/Ubuntu**: ufw is common; firewalld optional
- **RHEL/Fedora**: firewalld is default; nftables is backend

The rule checks all three independently and succeeds as long as at least one backend can be meaningfully checked.

### Architecture integration

The firewall status is determined in `collect_network()` at lines 2701-2711. The existing code already computes `firewall_found` and `firewall_details`. The activation requires:

1. **In `collect_network()`**: After the existing firewall analysis, if `firewall_found` is `False` and at least one backend was checked, create a `RawDiagnostic(source_id="NET-FW-001", category="firewall_status", payload=...)`.

2. **In `_raw_to_observation()`**: New branch for `cat == "firewall_status"` that creates an `Observation` with the firewall details.

3. **In `EvidenceBuilder.build()`**: New branch for `cat == "firewall_status"` that creates `SERVICE_STATE` Evidence.

4. **In `FindingClassificationPolicy.classify()`**: New entry for `"firewall_status"` category.

5. **New `FirewallStatusRule`**: A `DiagnosticRule` that checks `observation.details.get("firewall_found")` is `False` and returns a `DiagnosticRuleResult` with the Finding.

6. **Register in `build_default_rule_engine()`**: Add `FirewallStatusRule(eb)` to the rules tuple.

---

## 8. File-by-file change plan

### Required files

| # | File | Purpose | Symbols affected | Type |
|---|---|---|---|---|
| 1 | `syscheck.py` | Add RawDiagnostic creation in `collect_network()` after firewall analysis (~line 2711) | `SysCheckEngine.collect_network` | Production |
| 2 | `syscheck.py` | Add `"firewall_status"` branch to `_raw_to_observation()` | `SysCheckEngine._raw_to_observation` | Production |
| 3 | `syscheck.py` | Add `"firewall_status"` branch to `EvidenceBuilder.build()` | `EvidenceBuilder.build` | Production |
| 4 | `syscheck.py` | Add `"firewall_status"` to `FindingClassificationPolicy._BY_CATEGORY` | `FindingClassificationPolicy._BY_CATEGORY` | Production |
| 5 | `syscheck.py` | Add new `FirewallStatusRule` class | `FirewallStatusRule` (new class) | Production |
| 6 | `syscheck.py` | Add `FIREWALL_STATUS` to `FindingKind` enum | `FindingKind.FIREWALL_STATUS` | Production |
| 7 | `syscheck.py` | Register `FirewallStatusRule` in `build_default_rule_engine()` | `build_default_rule_engine` | Production |
| 8 | `test_syscheck.py` | Add test class for FirewallStatusRule (rule, evidence, integration) | New test class | Test |
| 9 | `test_syscheck.py` | Update `TestClassificationPolicyCompleteness` to include new category | Existing test | Test |
| 10 | `test_syscheck.py` | Update `TestCompleteNativeRuntime` expected counts (11→12) | Existing test | Test |

### Conditional files

| # | File | Purpose | Condition |
|---|---|---|---|
| 11 | `.agent-work/reviews/iteration-24-firewall-status-activation.md` | Review document for this iteration | Standard practice |

### Explicitly out of scope

| File | Reason |
|---|---|
| `constants.py` | No new thresholds or configuration needed |
| `syscheck.py` — `DiagnosticDomain` | `SECURITY` already exists in the enum (line 120) |
| `syscheck.py` — `EvidenceType` | `SERVICE_STATE` already exists (line 725) |

---

## 9. Test plan

### Test class: `TestFirewallStatusRule`

Following the existing pattern in `TestBootDelayRuleEvidence` (line 4495) and `TestKernelTaintRuleEvidence` (line 4132).

### Test cases

| # | Test | Type | Description |
|---|---|---|---|
| 1 | `test_no_firewall_returns_native_result` | Positive | No active firewall → DiagnosticRuleResult with Finding and Evidence |
| 2 | `test_finding_id_unchanged` | Positive | Finding ID is NET-FW-001 |
| 3 | `test_severity_p3` | Positive | Severity is P3 |
| 4 | `test_classification_assigned` | Positive | Domain SECURITY, kind FIREWALL_STATUS, actionability ACTIONABLE |
| 5 | `test_evidence_is_service_state` | Positive | Evidence type is SERVICE_STATE |
| 6 | `test_evidence_contains_firewall_data` | Positive | Evidence data includes firewall_found, firewall_details |
| 7 | `test_finding_references_evidence` | Positive | Finding.evidence_ids matches Evidence |
| 8 | `test_evidence_references_observation` | Positive | Evidence.source_observation_ids contains Observation ID |
| 9 | `test_evidence_preserves_raw_ids` | Positive | Evidence.source_raw_ids preserved from RawDiagnostic |
| 10 | `test_evidence_id_stable` | Deterministic | Evidence ID is deterministic |
| 11 | `test_deterministic` | Deterministic | Multiple evaluations produce identical IDs |
| 12 | `test_finding_id_independent_of_evidence` | Deterministic | Finding ID ≠ Evidence ID |
| 13 | `test_summary_no_firewall` | Positive | Summary describes checked backends |
| 14 | `test_firewall_active_no_finding` | Negative | Active firewall → no diagnostic |
| 15 | `test_unknown_status_no_finding` | Negative | All backends failed → no diagnostic |
| 16 | `test_quality_flags_strong_by_default` | Boundary | Default quality is STRONG/DIRECT/COMPLETE |
| 17 | `test_no_orphan_evidence` | Regression | Evidence always paired with Finding |
| 18 | `test_interpret_stores_firewall_evidence` | Integration | Engine._interpret() stores SERVICE_STATE Evidence |

### Test style

Follow existing patterns:

```python
class TestFirewallStatusRule:
    """FirewallStatusRule returns DiagnosticRuleResult with SERVICE_STATE Evidence."""

    def test_no_firewall_returns_native_result(self):
        """No active firewall produces DiagnosticRuleResult with Finding and Evidence."""
        eb = EvidenceBuilder()
        rule = FirewallStatusRule(eb)
        obs = Observation(
            obs_id="NET-FW-001",
            category="firewall_status",
            details={"firewall_found": False, "firewall_details": ["firewalld (inactive)", "ufw (not found)"]},
        )
        policy = FindingClassificationPolicy()
        result = rule.evaluate(obs, policy.classify(obs))
        assert isinstance(result, DiagnosticRuleResult)
        assert result.finding is not None
        assert len(result.evidence) > 0

    def test_firewall_active_no_finding(self):
        """Active firewall produces no Finding."""
        eb = EvidenceBuilder()
        rule = FirewallStatusRule(eb)
        obs = Observation(
            obs_id="NET-FW-001",
            category="firewall_status",
            details={"firewall_found": True, "firewall_details": ["firewalld (active)"]},
        )
        policy = FindingClassificationPolicy()
        result = rule.evaluate(obs, policy.classify(obs))
        assert result.finding is None
```

### Collector-level test

Following the pattern from `TestBootTimeCollector` (Iteration 23), add one test for the collector path:

```python
class TestFirewallCollector:
    """Firewall status collector activation."""

    @staticmethod
    def _cmd_ok(stdout: str) -> CmdResult:
        return CmdResult(
            command="", stdout=stdout, stderr="",
            return_code=0, execution_status="ok",
        )

    def _collect_with_mock(self, engine, **overrides):
        from unittest.mock import patch
        results = {
            "ip_addr": self._cmd_ok(""),
            "ss_tlnp": self._cmd_ok(""),
            "resolvectl": self._cmd_ok(""),
            "nm_status": self._cmd_ok(""),
            "auth_fails": self._cmd_ok("0"),
            "firewalld": self._cmd_ok("inactive"),
            "ufw_status": CmdResult(... execution_status="not_found"),
        }
        results.update(overrides)
        with patch.object(SysCheckEngine, "_parallel_cmd", return_value=results):
            with patch.object(SysCheckEngine, "cmd", return_value=self._cmd_ok("")):
                engine.collect_network()
```

### CLI/report representation

No CLI changes. The existing report already formats findings with severity, interpretation, and remediation. The new Finding will appear in section "10. Problemy potwierdzone" and its Recommendation in section "11. Rekomendacje".

### Regression coverage

- Existing test counts: `TestCompleteNativeRuntime.test_all_rules_return_diagnostic_rule_result` expects 11 findings → must be updated to 12
- `TestClassificationPolicyCompleteness` must be updated to include `"firewall_status"`
- All other tests should pass unchanged

---

## 10. Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| 1 | Existing collector data (firewalld/ufw/nft status) is consumed by the new diagnostic | `collect_network()` creates `RawDiagnostic(category="firewall_status")` with `firewall_found` in payload |
| 2 | Evidence is traceable to the original observation | `Evidence.source_raw_ids` contains `("NET-FW-001",)` and `source_observation_ids` contains `("NET-FW-001",)` |
| 3 | Finding is deterministic | Same input → same Finding ID, severity, evidence text |
| 4 | Recommendation is actionable and non-speculative | Recommendation contains concrete commands (`systemctl enable firewalld`, `ufw enable`) |
| 5 | No new collector added | No new `def collect_*` method created |
| 6 | No new shell commands added | Only the existing firewalld/ufw/nft commands from `_parallel_cmd` are used |
| 7 | Existing diagnostics remain stable | All 340 existing tests pass unchanged (except count updates) |
| 8 | Missing/unknown firewall status does not trigger false finding | When no backend can be checked, no RawDiagnostic is created |
| 9 | Active firewall does not trigger finding | When any backend reports active, no RawDiagnostic is created |

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
python3 -m pytest -v -k "TestFirewallStatusRule or TestFirewallCollector or TestCompleteNativeRuntime or TestClassificationPolicyCompleteness"

# Type checking (known unavailable)
mypy .  || echo "mypy not installed — no type checking available"
```

Expected baseline before implementation:

- `ruff format --check .` → 3 files already formatted
- `ruff check .` → All checks passed
- `python3 -m pytest -q` → 340 passed

Expected after implementation:

- `ruff format --check .` → 3 files already formatted
- `ruff check .` → All checks passed
- `python3 -m pytest -q` → **~355 passed** (340 existing + ~15 new)

---

## 12. Risks and unresolved decisions

### Implementation risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Adding `FIREWALL_STATUS` to `FindingKind` breaks import order | Low | Low | Follow existing pattern at line 129+; add near `STORAGE_USAGE` |
| `DiagnosticDomain.SECURITY` exists but is unused | None | None | Already confirmed at line 120; just needs first consumer |
| `firewall_found` is a local variable in `collect_network()` | None | None | RawDiagnostic is created in the same method, so it has access |

### Product/false-positive risks

| Risk | Likelihood | Rationale |
|---|---|---|
| User has a custom firewall (iptables, not nft) | Low | The code checks nft ruleset, firewalld, and ufw; custom iptables would show as "no firewall found" — this is the only FP path |
| Docker exposes ports but user relies on cloud security groups | Low | This is a legitimate security concern; the finding is still valid as P3 |
| System on isolated network doesn't need firewall | Low | P3 severity is appropriate for this context; no false positive, just low urgency |

### Portability risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ufw is optional dependency | Low | Already handled by the `True` (optional) flag in `tasks_cmd`; `not_found` status is handled |
| firewalld may not be installed on Arch | Medium | Handled by `systemctl is-active` which returns "inactive" or error for non-existent services |
| nft requires sudo on some systems | Medium | Already handled: permission_denied → restriction tracked; `nft` runs as optional dependency |

### Questions requiring human decision

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Which `DiagnosticDomain` for firewall status? | `SECURITY` (exists, line 120) / `NETWORK` (exists, line 120) | **Use `SECURITY`** — firewall is a security control, not a network diagnostic |
| 2 | What should the FindingKind name be? | `FIREWALL_STATUS` / `FIREWALL_DOWN` / `NETWORK_FIREWALL` | **Use `FIREWALL_STATUS`** — follows `FAILED_UNIT`, `STORAGE_USAGE` pattern |
| 3 | Should external listeners be bundled in the same slice? | Yes / No | **No** — higher FP risk; better as a separate slice |
| 4 | Should the `nft` command remain as a standalone `self.cmd()` or move to `_parallel_cmd`? | Keep standalone / Move | **Keep standalone** — not part of this activation; change would be scope creep |

---

## 13. Recommended follow-up task

### For a coding agent after plan approval

**Task: Implement firewall status diagnostic activation in SysCheck**

1. In `syscheck.py`:
   - Add `FIREWALL_STATUS = "firewall_status"` to `FindingKind` enum (~line 135)
   - After line 2711 (firewall summary display), add:
     ```python
     if not firewall_found and firewall_details:
         self.raw_diagnostics.append(
             RawDiagnostic(
                 source_id="NET-FW-001",
                 category="firewall_status",
                 payload={
                     "firewall_found": False,
                     "firewall_details": list(firewall_details),
                     "firewalld_active": firewalld_result.is_ok() and firewalld_result.stdout.strip() == "active",
                     "ufw_active": ufw_result.is_ok() and "Status: active" in ufw_result.stdout,
                     "nftables_active": nft_result.is_ok() and bool(nft_result.stdout.strip()),
                 },
             )
         )
     ```
   - Add `"firewall_status"` to `FindingClassificationPolicy._BY_CATEGORY` with `SECURITY` domain, `FIREWALL_STATUS` kind, `ACTIONABLE` actionability, `INVESTIGATE` intent
   - Add `cat == "firewall_status"` branch to `_raw_to_observation()` following the pattern at line 2886 (boot_time)
   - Add `cat == "firewall_status"` branch to `EvidenceBuilder.build()` returning `SERVICE_STATE` Evidence
   - Add `FirewallStatusRule` class following `BootDelayRule` pattern (line 1467)
   - Register `FirewallStatusRule(eb)` in `build_default_rule_engine()` (line 1649)

2. In `test_syscheck.py`:
   - Add `from syscheck import FirewallStatusRule` (local import)
   - Add `TestFirewallStatusRule` class (~15 tests) following `TestBootDelayRuleEvidence` pattern
   - Add `TestFirewallCollector` class (~2 collector tests) following `TestBootTimeCollector` pattern
   - Update `TestCompleteNativeRuntime.test_all_rules_return_diagnostic_rule_result` expected count from 11 to 12
   - Update `TestCompleteNativeRuntime.test_no_bare_finding_returned` to include firewall observation or adjust count
   - Add `"firewall_status"` to `TestClassificationPolicyCompleteness` test data

3. Run validation:
   ```bash
   ruff format --check .
   ruff check .
   python3 -m pytest -q
   ```

4. Do NOT stage, commit, push, create branches, or rename any project artifacts.
