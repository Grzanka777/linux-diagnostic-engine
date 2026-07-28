# SysCheck Product Coverage Assessment

## Executive summary

SysCheck is a mature, CLI-only Linux workstation diagnostic tool with 11 production rules spanning 7 domains (BOOT, SYSTEMD, KERNEL, FILESYSTEM, STORAGE, PACKAGES, AUDIO). It collects system data across 17 subsystems via ~50 shell commands, but only ~60% of collected data is consumed by the diagnostic pipeline — the remainder is rendered directly in the Markdown report without structured analysis.

The architecture is a three-stage pipeline (RAW → OBS → Evidence + Finding → Recommendation) with clean separation of concerns, deterministic rules, and no external dependencies. It is well-suited for expansion.

**This assessment identifies 22 candidate diagnostic domains, evaluates all of them, and recommends a 6-epic roadmap covering approximately 25 new rules over the next product phase.**

The highest-priority gap is **Memory and OOM diagnostics** — this is the most impactful Linux workstation failure mode not currently addressed. The second priority is **Filesystem health (ext4/XFS)** , followed by **Thermal and power management** and **GPU reliability**.

The current architecture is sufficient for the entire proposed roadmap without redesign. Only minor collector additions and model extensions are needed.

---

## Current diagnostic coverage

### Rule inventory (11 rules)

| # | Finding ID | Rule | Category | Severity | Domain | Kind | Actionability | Intent | What it detects |
|---|---|---|---|---|---|---|---|---|---|
| 1 | BOOT-SLOW-001 | BootDelayRule | boot_time | P3 | BOOT | BOOT_DELAY | CONDITIONAL | MONITOR | Userspace boot > 30s |
| 2 | SYSD-SYS-FAIL-001 | FailedSystemUnitRule | systemd_failed | P2 | SYSTEMD | FAILED_UNIT | ACTIONABLE | INVESTIGATE | Failed system units |
| 3 | SYSD-USR-FAIL-001 | FailedUserUnitRule | systemd_failed | P3 | SYSTEMD | FAILED_UNIT | ACTIONABLE | INVESTIGATE | Failed user units |
| 4 | STORAGE-USAGE-WARNING | StorageUsageRule | storage_usage | P3 | STORAGE | STORAGE_USAGE | ACTIONABLE | REMEDIATE | Disk usage ≥ 75% |
| 5 | STORAGE-USAGE-CRITICAL | StorageUsageRule | storage_usage | P2 | STORAGE | STORAGE_USAGE | ACTIONABLE | REMEDIATE | Disk usage ≥ 90% |
| 6 | BTRFS-ERR-001 | BtrfsDeviceErrorRule | btrfs_error | P2 | FILESYSTEM | DEVICE_ERROR | ACTIONABLE | VERIFY | Btrfs device errors |
| 7 | BTRFS-SCRUB-001 | BtrfsScrubStatusRule | btrfs_scrub | P3 | FILESYSTEM | SCRUB_STATUS | ACTIONABLE | REMEDIATE | Btrfs scrub never run |
| 8 | SEGFAULT-SYS-001 | GeneralSegfaultRule | segfault | P2 | KERNEL | SEGFAULT | ACTIONABLE | INVESTIGATE | ≥3 system segfaults |
| 9 | SEGFAULT-WP-001 | WirePlumberSegfaultRule | segfault | P2 | AUDIO | SEGFAULT | ACTIONABLE | INVESTIGATE | ≥3 WirePlumber segfaults |
| 10 | SEGFAULT-MIN-001 | MinorSegfaultRule | segfault_minor | P3 | KERNEL | SEGFAULT | ACTIONABLE | MONITOR | 1-2 segfaults |
| 11 | KERNEL-TAINT-001 | KernelTaintRule | tainted | P2 | KERNEL | KERNEL_TAINT | CONDITIONAL | MONITOR | Kernel tainted |
| 12 | KRNL-INFO-001 | KernelCountRule | kernel_count | Info | PACKAGES | KERNEL_COUNT | INFORMATIONAL | INFORMATIONAL | >2 bootable kernels |

### Collector inventory (9 collectors, ~50 commands)

| Collector | Commands | Data collected | Used by rules | Display-only data |
|---|---|---|---|---|
| collect_base_info | cat /etc/os-release, uname, hostname, uptime, /proc/cmdline, ls /boot/, ls /usr/lib/modules/, niri --version | Distro info, kernel version, hostname, uptime, cmdline, boot/modules listings, niri version | KernelCountRule (via _get_bootable_kernels_*) | Distro, uptime, session type, Wayland display, desktop env, kernel count comparison |
| collect_resources | lscpu, free -h, zramctl, /proc/loadavg, cpufreq governor, ps aux, sensors | CPU info, RAM/swap, zram, load, governor, top processes, temperatures | None | All data is display-only |
| collect_storage | lsblk, df -h, df -i, btrfs filesystem show, btrfs filesystem df, btrfs device stats, btrfs scrub status, nvme list | Block devices, disk usage, inode usage, btrfs status, btrfs errors, btrfs scrub, NVMe list | StorageUsageRule, BtrfsDeviceErrorRule, BtrfsScrubStatusRule | lsblk, df, btrfs show/df, nvme list |
| collect_kernel_hw | dmesg_restrict, journalctl kernel errors, journalctl segfaults, journalctl firmware, lspci -k, lsusb | Kernel logs, segfaults, firmware messages, PCI/USB devices | Segfault rules, KernelTaintRule | Kernel errors, firmware msgs, lspci, lsusb |
| collect_systemd | systemctl --failed (sys+usr), systemd-analyze, systemd-analyze blame, systemd-analyze critical-chain, systemctl list-timers (sys+usr), systemctl list-units auto-restart/restarting | Failed units, boot time, blame, critical chain, timers, auto-restart/restarting units | FailedSystemUnitRule, FailedUserUnitRule, BootDelayRule | All systemd output is display-only beyond rules |
| collect_packages | pacman -Qdt / apt / dnf, pacman -Qm / apt / dnf, pacman -Q linux* / dpkg / rpm | Orphan packages, foreign/AUR packages, kernel packages | KernelCountRule | Orphan/foreign package listings |
| collect_graphics | /sys/class/drm vendor/device, ls /sys/class/drm/, niri msg outputs, journalctl gfx errors | DRM vendor/device, DRM nodes, niri outputs, graphics errors | None | All data is display-only |
| collect_network | ip addr, ss -tlnp, resolvectl status, systemctl status NetworkManager, journalctl auth fails, systemctl is-active firewalld, ufw status, nft list ruleset | Network addresses, listening services, DNS, NetworkManager, auth failures, firewall status | None | All data is display-only |
| collect_userenv | fish --version, env vars (SHELL, TERM, LANG, EDITOR, BROWSER) | Shell config, environment | None | All data is display-only |

### Architectural observations

1. **Payload quality gap**: 6 of 12 RawDiagnostics (`btrfs_error`, `btrfs_scrub`, `segfault` variants, `tainted`) carry empty `payload={}`, meaning downstream Evidence has no structured data to work with. These are legacy migration artifacts that should be completed (similar to Iteration 23's boot_time fix).
2. **Wasted collector data**: `collect_resources`, `collect_graphics`, `collect_network`, and `collect_userenv` produce zero RawDiagnostics. Their data is displayed but never enters the structured pipeline.
3. **No cross-collector correlation**: Each collector operates independently. No rule combines data from multiple collectors (e.g., correlating storage errors with kernel messages).
4. **Deterministic-only**: All rules are deterministic string/pattern matching. No probabilistic or ML-based diagnosis exists. This is a deliberate and correct constraint.
5. **Report-only domains**: Graphics (DRM, niri), network (IP, DNS, firewall), and resources (CPU, memory, temperatures) are documented but not diagnosed.

---

## Missing diagnostic domains

### Domains currently covered (7 of ~20 relevant):

| Domain | Covered | Missing aspects |
|---|---|---|
| BOOT | ✅ Boot delay | Boot firmware/loader issues, bootloader config |
| SYSTEMD | ✅ Failed units, boot analysis | Service timing degradation, dependency loops |
| KERNEL | ✅ Segfaults, taint | Panic history, watchdog, module failures |
| FILESYSTEM | ✅ Btrfs errors, scrub status | Ext4/XFS health, fsck required, readonly remount |
| STORAGE | ✅ Disk usage (df) | SMART health, NVMe errors, discard failures, RAID |
| PACKAGES | ✅ Kernel count | Orphan packages (display only), repo issues, AUR |
| AUDIO | ✅ WirePlumber segfaults | PipeWire status, ALSA issues |
| MEMORY | ❌ Not covered | OOM, swap pressure, zram, memory exhaustion |
| CPU | ❌ Not covered | Throttling, frequency scaling, overheating |
| GPU | ❌ Not covered | Driver hangs, resets, firmware failures, VRAM |
| THERMAL | ❌ Not covered | Critical temperatures, throttling events, fan failure |
| NETWORK | ❌ Not covered | DNS resolution, connectivity, Wi-Fi disconnects |
| FIREWALL | ❌ Not covered (display only) | Firewall down, exposed services |
| POWER | ❌ Not covered | Suspend/resume failures, sleep issues |
| BATTERY | ❌ Not covered | Battery health, charge thresholds, wear |
| FIRMWARE | ❌ Not covered (display only) | Microcode updates, UEFI issues |
| SECURE BOOT | ❌ Not covered | Secure Boot status, key enrollment |
| TPM | ❌ Not covered | TPM availability, PCR measurements |
| JOURNAL | ❌ Not covered | Journal corruption, log overflow, rate limiting |
| TIME SYNC | ❌ Not covered | NTP status, clock drift |
| CONTAINERS | ❌ Not covered | Docker/Podman runtime issues |
| SECURITY | ❌ Not covered | Firewall down, SSH exposed, apparmor/selinux |

---

## Domain evaluation

### Evaluation criteria

Each candidate domain is scored on:

- **User value** (1-5): How much does this matter to a Linux workstation user?
- **Frequency** (1-5): How often does this problem occur in practice?
- **Confidence** (1-5): Can a deterministic rule reliably detect this?
- **Complexity** (1-5): How hard is the collector + rule implementation? (Higher = easier)
- **FP risk** (1-5): How likely are false positives? (Higher = safer)
- **Maintenance** (1-5): How stable are the diagnostic surfaces? (Higher = more stable)

### Detailed evaluation

#### A. Memory / OOM

| Criterion | Score | Rationale |
|---|---|---|
| User value | 5 | OOM kills and swap thrashing are top workstation complaints |
| Frequency | 4 | Common with memory-intensive workflows (browsers, containers, VMs, IDEs) |
| Confidence | 4 | journalctl clearly records OOM kills; swap pressure is measurable via /proc |
| Complexity | 4 | Simple collector (journalctl OOM filter, /proc/meminfo, /proc/zoneinfo); deterministic rule |
| FP risk | 4 | OOM events are unambiguous; swap pressure thresholds are configurable |
| Maintenance | 5 | Journalctl output format is stable; /proc interface is ABI-stable |

**Verdict: HIGH PRIORITY**

#### B. Filesystem health (ext4/XFS)

| Criterion | Score | Rationale |
|---|---|---|
| User value | 5 | Filesystem corruption is catastrophic; silent degradation is dangerous |
| Frequency | 2 | Rare on healthy systems, but critical when it occurs |
| Confidence | 5 | fsck required flag, readonly remount, journal errors are unambiguous |
| Complexity | 4 | Collectors: journalctl for filesystem errors, /proc/mounts for ro, tune2fs/xfs_info optional |
| FP risk | 5 | Filesystem errors are objective |
| Maintenance | 4 | Filesystem error messages are stable but kernel-version dependent |

**Verdict: HIGH PRIORITY (despite low frequency, the severity justifies coverage)**

#### C. GPU reliability

| Criterion | Score | Rationale |
|---|---|---|
| User value | 4 | GPU hangs and driver resets cause visible workflow disruption |
| Frequency | 3 | Common with newer hardware/kernel combos, especially on laptops with hybrid graphics |
| Confidence | 3 | journalctl GPU errors are indicative but can be noisy; some resets are transient |
| Complexity | 3 | Journalctl grep for GPU errors (i915, amdgpu, nvidia) already partially collected but not analyzed |
| FP risk | 3 | Some GPU errors are non-fatal (e.g., "GPU HANG" that self-recovers) |
| Maintenance | 3 | GPU driver error messages vary by kernel version and driver |

**Verdict: HIGH PRIORITY**

#### D. Thermal throttling

| Criterion | Score | Rationale |
|---|---|---|
| User value | 4 | Throttling causes performance loss; overheating can damage hardware |
| Frequency | 3 | Common on laptops under sustained load, especially in warm environments |
| Confidence | 4 | sensors + journalctl thermal events are reliable indicators |
| Complexity | 4 | Collector already runs sensors; just needs parsing and a rule |
| FP risk | 4 | Critical temperature crossings are unambiguous |
| Maintenance | 4 | sensor output format is stable; thermal zones via /sys are ABI-stable |

**Verdict: HIGH PRIORITY**

#### E. CPU throttling / frequency scaling

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Informative — explains performance issues, but rarely an actionable problem |
| Frequency | 3 | Common on laptops; users wonder about governor settings |
| Confidence | 4 | Governor state is deterministic; /sys interface is reliable |
| Complexity | 4 | Governor data already collected but not parsed |
| FP risk | 5 | Governor is just a string read — no false positives possible |
| Maintenance | 5 | /sys cpufreq interface is ABI-stable |

**Verdict: MEDIUM PRIORITY**

#### F. NVMe / SMART health

| Criterion | Score | Rationale |
|---|---|---|
| User value | 5 | NVMe media errors predict failure; SMART degradation is actionable |
| Frequency | 2 | Rare on consumer hardware, but critical when present |
| Confidence | 4 | NVMe errors from nvme list + nvme smart-log are reliable; SMART data is objective |
| Complexity | 2 | Requires nvme-cli smart-log parsing; optional dependency (already marked optional in collector) |
| FP risk | 5 | NVMe error counters and SMART attributes are unambiguous |
| Maintenance | 3 | nvme-cli output format is stable but not all systems have it installed |

**Verdict: HIGH PRIORITY (strategic value for proactive failure detection)**

#### G. PCIe errors (AER)

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | PCIe errors indicate hardware issues; AER events appear in dmesg |
| Frequency | 2 | Uncommon on healthy workstations; more common with TB4/docking |
| Confidence | 3 | AER events are clear but some are non-fatal correctable errors |
| Complexity | 3 | Journalctl/dmesg grep for PCIe errors |
| FP risk | 3 | Correctable vs uncorrectable distinction matters; some errors are transient |
| Maintenance | 4 | PCIe AER format is stable in dmesg |

**Verdict: MEDIUM PRIORITY**

#### H. Firmware / UEFI

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Firmware update announcements are useful; UEFI misconfiguration can block boot |
| Frequency | 3 | Common (fwuupd announcements, microcode updates) |
| Confidence | 3 | fwupd status is clear; microcode versions are comparable |
| Complexity | 3 | New collector (fwupdmgr), /sys/firmware/ paths |
| FP risk | 4 | Firmware version comparison is deterministic |
| Maintenance | 3 | fwupd interface is stable but optional |

**Verdict: MEDIUM PRIORITY**

#### I. Secure Boot

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Important for dual-boot and kernel module loading; users often don't know their status |
| Frequency | 2 | Configuration is static; only relevant on change or for diagnosis |
| Confidence | 5 | `bootctl status`, `mokutil` output is unambiguous |
| Complexity | 5 | Simple collector (bootctl status, mokutil --sb-state) |
| FP risk | 5 | No false positive possible |
| Maintenance | 4 | systemd-bootctl interface is stable |

**Verdict: MEDIUM PRIORITY**

#### J. Suspend / resume (power management)

| Criterion | Score | Rationale |
|---|---|---|
| User value | 4 | Suspend/resume failures are a top Linux workstation complaint |
| Frequency | 3 | Common on laptops, especially with newer kernels or NVidia GPUs |
| Confidence | 3 | journalctl identifies suspend/resume errors but can be noisy |
| Complexity | 3 | Journalctl grep for PM events; regression detection via timestamps |
| FP risk | 3 | Some "failed" suspend messages are non-fatal |
| Maintenance | 3 | PM error format varies by kernel version and hardware |

**Verdict: HIGH PRIORITY**

#### K. Battery health

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Laptop users benefit from wear-level awareness |
| Frequency | 2 | Battery degradation is slow; relevant for older systems |
| Confidence | 4 | /sys/class/power_supply/*/charge_full vs charge_full_design is reliable |
| Complexity | 5 | Simple sysfs read |
| FP risk | 5 | No false positive possible |
| Maintenance | 5 | Power supply sysfs interface is ABI-stable |

**Verdict: LOW PRIORITY**

#### L. Journal health

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Journal corruption can cause data loss of historical diagnostics |
| Frequency | 1 | Rare on healthy systems |
| Confidence | 4 | journalctl --verify output is clear; empty/repeating logs indicate problems |
| Complexity | 4 | Simple collector (journalctl --verify, check disk usage) |
| FP risk | 4 | Journal verification is reliable |
| Maintenance | 4 | systemd-journald interface is stable |

**Verdict: LOW PRIORITY**

#### M. DNS / Network connectivity

| Criterion | Score | Rationale |
|---|---|---|
| User value | 4 | Network connectivity issues are frequent workstation problems |
| Frequency | 4 | Common — DNS misconfiguration, Wi-Fi disconnects, VPN issues |
| Confidence | 2 | Connectivity is environment-dependent; "is this a problem" often requires external probes |
| Complexity | 2 | Deterministic rules limited to config validation, not actual connectivity testing |
| FP risk | 2 | Many false positives from transient network conditions |
| Maintenance | 3 | resolvctl/systemd-resolved interface is stable |

**Verdict: LOW PRIORITY for deterministic rules. Proactive network diagnosis is better suited to dedicated tools.**

#### N. Wi-Fi

| Criterion | Score | Rationale |
|---|---|---|
| User value | 4 | Wi-Fi disconnects are a top laptop complaint |
| Frequency | 4 | Common across all Linux desktop users |
| Confidence | 2 | journalctl wpa_supplicant logs are noisy; many disconnects are intentional |
| Complexity | 2 | Requires iwconfig/iw dev link quality; transient conditions make rules unreliable |
| FP risk | 1 | High risk of false positives from routine reconnects and power saving |
| Maintenance | 2 | Wi-Fi stack error format varies significantly |

**Verdict: LOW PRIORITY — better suited to iterative improvement than a first-pass deterministic rule.**

#### O. Bluetooth

| Criterion | Score | Rationale |
|---|---|---|
| User value | 2 | Bluetooth issues are less frequent on workstations |
| Frequency | 2 | Moderate for users who use BT peripherals |
| Confidence | 3 | bluetoothctl show, journalctl BT errors are reasonable |
| Complexity | 3 | Simple collector (bluetoothctl show, dmesg BT errors) |
| FP risk | 3 | Some errors are transient or non-fatal |
| Maintenance | 3 | BlueZ interface is reasonably stable |

**Verdict: LOW PRIORITY**

#### P. USB

| Criterion | Score | Rationale |
|---|---|---|
| User value | 2 | USB errors are uncommon on workstations with adequate power |
| Frequency | 2 | Uncommon |
| Confidence | 3 | dmesg USB errors are clear |
| Complexity | 3 | Simple collector (dmesg USB grep) |
| FP risk | 4 | USB error counters are reliable |
| Maintenance | 4 | USB subsystem messages are stable |

**Verdict: LOW PRIORITY**

#### Q. PipeWire / Audio

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Audio failure is disruptive |
| Frequency | 3 | Common — PipeWire upgrades, ALSA config issues, JACK conflicts |
| Confidence | 3 | journalctl PipeWire errors are indicative but not always definitive |
| Complexity | 3 | Journalctl grep for PW errors; pw-cli list-objects is available |
| FP risk | 2 | Some PW errors are non-fatal |
| Maintenance | 2 | PipeWire error format changes across versions |

**Verdict: LOW PRIORITY (WirePlumber segfaults already covered; full PW health is too volatile)**

#### R. Time synchronization / clock drift

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Clock drift causes TLS failures, git confusion, log inconsistency |
| Frequency | 2 | Uncommon on systems with NTP; more common on dual-boot with Windows |
| Confidence | 4 | timedatectl output is clear; drift via adjtimex is measurable |
| Complexity | 4 | Simple collector (timedatectl, chronyc tracking or similar) |
| FP risk | 4 | NTP sync status is deterministic |
| Maintenance | 4 | systemd-timesyncd/timedatectl interface is stable |

**Verdict: MEDIUM PRIORITY**

#### S. Entropy starvation

| Criterion | Score | Rationale |
|---|---|---|
| User value | 2 | Historically relevant (lack of /dev/random blocking); modern kernels have getrandom() |
| Frequency | 1 | Rare with kernel 5.4+ — entropy starvation is largely solved |
| Confidence | 4 | /proc/sys/kernel/random/entropy_avail is measurable |
| Complexity | 4 | Simple sysfs read |
| FP risk | 5 | Objective measurement |
| Maintenance | 5 | /proc interface is ABI-stable |

**Verdict: LOW PRIORITY (mostly historical)**

#### T. TPM

| Criterion | Score | Rationale |
|---|---|---|
| User value | 2 | TPM matters for disk encryption users; most users never interact with it |
| Frequency | 1 | Static configuration; only relevant when it breaks |
| Confidence | 4 | tpm2_pcrread, /sys/class/tpm are reliable |
| Complexity | 3 | Simple collector |
| FP risk | 5 | No false positive |
| Maintenance | 4 | TPM sysfs interface is stable |

**Verdict: LOW PRIORITY**

#### U. Security hardening

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Relevant for security-conscious users |
| Frequency | 1 | Static configuration; rarely changes |
| Confidence | 4 | Firewall status, SSH port, apparmor/selinux status are unambiguous |
| Complexity | 4 | Commands partially already collected (firewalld, ufw, nft) |
| FP risk | 4 | Objective state checks |
| Maintenance | 4 | Security interfaces are stable |

**Verdict: MEDIUM PRIORITY**

#### V. Swap / zram

| Criterion | Score | Rationale |
|---|---|---|
| User value | 3 | Swap configuration affects memory pressure handling |
| Frequency | 3 | Common — many Arch users configure zram manually; misconfiguration causes issues |
| Confidence | 4 | swapon, zramctl output is deterministic |
| Complexity | 4 | Data already collected (free -h, zramctl) but not parsed for diagnostics |
| FP risk | 4 | Swap/zram state is objective |
| Maintenance | 5 | Swap/zram interface is stable |

**Verdict: MEDIUM PRIORITY**

---

## Product priorities

### High priority (should be implemented)

| Rank | Domain | Rationale |
|---|---|---|
| 1 | **Memory / OOM** | Most impactful gap; frequent real-world problem; deterministic detection; high confidence |
| 2 | **Filesystem health (ext4/XFS)** | Catastrophic when it occurs; unambiguous detection; complements existing btrfs coverage |
| 3 | **Thermal throttling** | Common on laptops; data already partially collected; deterministic thresholds |
| 4 | **GPU reliability** | Frequent workstation issue; journalctl data already partially collected |
| 5 | **NVMe / SMART health** | Strategic failure prediction; complements storage coverage |
| 6 | **Suspend / resume** | Top laptop complaint; journalctl-based detection |

### Medium priority

| Rank | Domain | Rationale |
|---|---|---|
| 7 | CPU frequency scaling / governor | Data already collected; useful context for performance issues |
| 8 | Time synchronization / clock drift | Deterministic; useful for dual-boot users |
| 9 | PCIe errors (AER) | Hardware failure indicator; complements GPU/Storage |
| 10 | Firmware / UEFI | Useful for update announcements |
| 11 | Secure Boot | Deterministic; important for module loading diagnosis |
| 12 | Swap / zram | Data already collected; useful memory pressure context |
| 13 | Security hardening | Deterministic; complements existing firewall display data |

### Low priority

| Rank | Domain | Rationale |
|---|---|---|
| 14 | Battery health | Simple but low frequency; useful for laptop fleet |
| 15 | Journal health | Low frequency; catastrophic when it occurs but rare |
| 16 | DNS / Network | Low confidence; better served by dedicated tools |
| 17 | Wi-Fi | High FP risk; error format volatility |
| 18 | PipeWire / Audio | Volatile interface; WirePlumber segfaults already covered |
| 19 | Bluetooth | Low user value for workstation use case |
| 20 | USB | Low frequency; low impact |
| 21 | Entropy starvation | Mostly historical; modern kernels handle this |
| 22 | TPM | Low frequency; niche user base |

### Out of scope (not recommended for SysCheck)

| Domain | Rationale |
|---|---|
| **Intrusion detection** | Better served by dedicated tools (AIDE, tripwire, rkhunter) |
| **Malware scanning** | Out of scope for a diagnostic-only tool |
| **Performance benchmarking** | SysCheck is a snapshot diagnostic, not a benchmark |
| **Cloud service monitoring** | SysCheck is offline/local by design |
| **Container orchestration** | Out of scope for workstation diagnostics |
| **Database health** | Not a workstation concern |
| **VPN status** | Too environment-specific; no deterministic rules possible |

---

## Proposed epics

### Epic 1: Memory Reliability (high priority, ~5 rules)

**Scope**: Detect memory pressure, OOM events, swap health, and zram configuration.

**New collectors**:
- `journalctl -b -k --grep="oom-killer\|Out of memory\|oom_reaper"` — OOM events (already available via kernel_errors collector but not specifically parsed)
- `/proc/meminfo` — memory pressure (SwapTotal, SwapFree, MemAvailable)
- `swapon --show` — swap device status
- `zramctl` — already collected but not parsed for diagnostics

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| OOMKillRule | OOM killer events in current boot ≥ 1 | P1 | JOURNAL_EVENT |
| MemoryPressureRule | MemAvailable < 10% of total RAM | P2 | DERIVED_MEASUREMENT |
| SwapExhaustionRule | Swap usage > 90% | P2 | STORAGE_MEASUREMENT |
| ZramMisconfigRule | Zram configured but no swap on zram (or vice versa) | P3 | HARDWARE_STATE |
| NoSwapRule | No swap configured at all | Info | HARDWARE_STATE |

**Architecture fit**: YES — minor collector additions for OOM parsing

---

### Epic 2: Filesystem Health Expansion (high priority, ~4 rules)

**Scope**: Detect ext4/XFS errors, readonly remounts, fsck requirements, and discard/fstrim issues.

**New collectors**:
- `journalctl -b -k --grep="ext4\|xfs\|filesystem\|READ ONLY\|I/O error"` — filesystem errors (partially collected in kernel_errors)
- `/proc/mounts` — detect ro remounts
- `findmnt` — structured mount info
- `systemctl status fstrim.timer` — fstrim service status
- `journalctl -u fstrim.service` — fstrim errors

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| FsReadonlyRule | Filesystem remounted readonly (ext4/XFS) | P1 | FILESYSTEM_STATE |
| FsJournalErrorRule | Filesystem journal errors in kernel log | P2 | JOURNAL_EVENT |
| FsckRequiredRule | fsck required countdown or manual flag | P2 | FILESYSTEM_STATE |
| FstrimFailureRule | fstrim.service failures | P3 | SERVICE_STATE |

**Architecture fit**: YES — minor collector additions

---

### Epic 3: Thermal and Power Management (high priority, ~4 rules)

**Scope**: Detect overheating, throttling, suspend/resume failures, battery health.

**New collectors**:
- Parse sensors for temperature thresholds (± already collected)
- `journalctl -b -k --grep="thermal\|throttl\|critical temperature\|TjMax"` — thermal events
- `journalctl -b --grep="PM\|suspend\|resume\|hibernate\|wake"` — PM events
- `/sys/class/power_supply/*/` — battery stats (new)

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| ThermalThrottleRule | Thermal throttling or critical temperature events | P2 | HARDWARE_STATE |
| HighTemperatureRule | Sensor temperature > 85°C sustained | P3 | HARDWARE_STATE |
| SuspendResumeFailRule | Suspend/resume failures in journal | P2 | JOURNAL_EVENT |
| BatteryHealthRule | Battery wear > 30% or capacity < 50% of design | P3 | HARDWARE_STATE |

**Architecture fit**: YES — sensors and journalctl commands already exist; temperature parsing needs to be upgraded from display-only to diagnostic

---

### Epic 4: GPU Reliability (high priority, ~3 rules)

**Scope**: Detect GPU driver hangs, resets, firmware issues.

**New collectors**:
- `journalctl -b -k --grep="GPU HANG\|gpu reset\|amdgpu\|i915\|nvidia"` — already partially collected in gfx_logs but focused on niri/drm/Wayland keywords
- `/sys/class/drm/card*/device/` — already collected

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| GpuResetRule | GPU reset events in kernel log | P2 | JOURNAL_EVENT |
| GpuDriverFailRule | GPU driver load failure or probe error | P2 | JOURNAL_EVENT |
| GpuFirmwareRule | GPU firmware loading errors | P3 | JOURNAL_EVENT |

**Architecture fit**: YES — journalctl data source already exists; no new system commands needed

---

### Epic 5: Storage Reliability (medium priority, ~4 rules)

**Scope**: Detect NVMe media errors, SMART degradation, discard failures, PCIe AER.

**New collectors**:
- `sudo nvme smart-log /dev/nvme0n1` (optional, requires sudo or already-marked optional)
- `journalctl -b -k --grep="nvme.*error\|media.*error\|ata.*error\|discard"` — storage errors
- `journalctl -b -k --grep="PCIe.*error\|aer"` — PCIe errors
- `/sys/block/*/device/model` — device identification

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| NvmeMediaErrorRule | NVMe media errors in kernel log | P1 | HARDWARE_STATE |
| NvmeSmartWarnRule | NVMe SMART critical warnings (nvme-cli output) | P2 | HARDWARE_STATE |
| DiscardFailRule | Discard/TRIM errors in journal | P3 | JOURNAL_EVENT |
| PcieAerRule | PCIe AER uncorrectable errors | P2 | JOURNAL_EVENT |

**Architecture fit**: YES — minor collector additions; nvme list command already collected (optional)

---

### Epic 6: Security and Configuration Baseline (medium priority, ~5 rules)

**Scope**: Detect firewall status, Secure Boot, time sync, security misconfiguration.

**New collectors**:
- `bootctl status` — Secure Boot, bootloader info
- `timedatectl show` — NTP status, clock synchronization
- `/sys/class/tpm/tpm*/` — TPM availability
- `lsblk --discard` — discard support detection (moving from nvme list optional)

**Proposed rules**:

| Rule | What it detects | Severity | Evidence |
|---|---|---|---|
| FirewallDownRule | No active firewall (nftables, firewalld, ufw all inactive) | P3 | SERVICE_STATE |
| SecureBootDisabledRule | Secure Boot disabled | Info | SYSTEM_STATE |
| TimeSyncFailRule | System clock not synchronized | P3 | SYSTEM_STATE |
| NoBackupRule | No recent btrfs snapshot or known backup indicator | P3 | SYSTEM_STATE |
| NoDiscardRule | SSD with no discard configured | P3 | HARDWARE_STATE |

**Architecture fit**: YES — firewall data already partially collected; minor additions for Secure Boot and time sync

---

## Architecture fitness

| Epic | Architecture fit | Required changes | Justification |
|---|---|---|---|
| Epic 1: Memory | **YES** | Minor collector additions | journalctl + /proc parsing fits existing pattern; new Observation categories needed |
| Epic 2: Filesystem | **YES** | Minor collector additions | Follows existing btrfs pattern; ext4/XFS error parsing needs new regex collectors |
| Epic 3: Thermal/Power | **YES** | Minor collector additions | Sensors data already collected; journalctl PM parsing is a new filter |
| Epic 4: GPU | **YES** | Minor collector additions | GFX logs already collected; broader journalctl GPU grep needed |
| Epic 5: Storage | **YES** | Minor collector additions | NVMe data partially collected; needs SMART parsing and PCIe grep |
| Epic 6: Security | **YES** | Minor collector additions | Firewall data already collected; Secure Boot and time sync are new collectors |

**Overall verdict: The current architecture is sufficient for the entire proposed roadmap without redesign.**

No epics require:
- Architectural redesign
- Changes to the pipeline (RAW → OBS → Evidence + Finding → Recommendation)
- New model types
- Schema version changes
- Evidence persistence
- Health scoring
- Diagnostic aggregation
- RecommendationEngine changes

The only changes needed are:
- New collector methods (following existing `collect_*` pattern)
- New `_raw_to_observation()` branches (following existing `cat == "..."` pattern)
- New `EvidenceBuilder.build()` branches (following existing `if cat == "..."` pattern)
- New `DiagnosticRule` subclasses (following existing rule pattern)
- New `FindingClassificationPolicy` entries
- New test classes (following existing test pattern)

---

## Long-term roadmap

### Phase 1 — Immediate (Epic 1: Memory Reliability)
**Estimated: 4-6 weeks, ~5 rules, ~15 tests**

The highest-value gap. OOM events and memory pressure are the most common severe Linux workstation issues not currently diagnosed. The implementation is low-risk because:
- journalctl OOM entries are unambiguous
- /proc/meminfo parsing is trivial
- Swap/zram state is deterministic

### Phase 2 — Foundation (Epic 2: Filesystem Health Expansion)
**Estimated: 3-4 weeks, ~4 rules, ~12 tests**

Complements existing btrfs coverage with ext4/XFS health. High severity when triggered. Low false-positive risk.

### Phase 3 — Hardware Health (Epics 3 + 4: Thermal, Power, GPU)
**Estimated: 6-8 weeks, ~7 rules, ~20 tests**

Thermal and GPU issues are common workstation problems. The sensors and journalctl data sources already exist; the work is largely in writing rules and tests.

### Phase 4 — Storage Depth (Epic 5: NVMe, PCIe, Discard)
**Estimated: 4-6 weeks, ~4 rules, ~12 tests**

NVMe health is strategic for proactive failure detection. PCIe AER errors complement GPU and storage diagnostics.

### Phase 5 — Configuration Baseline (Epic 6: Security, Time, Sync)
**Estimated: 3-4 weeks, ~5 rules, ~15 tests**

Lower urgency but high determinism. Firewall status already partially collected.

### Phase 6 — Payload Quality Complete (ongoing)
**Estimated: 1-2 weeks, 6 payload migrations**

Complete the remaining 6 empty-payload RawDiagnostics (`btrfs_error`, `btrfs_scrub`, `segfault` variants, `tainted`) following the pattern established in Iteration 23's boot_time fix. This is not a new epic but a quality improvement. It should be interleaved with Phase 1.

### Total estimated scope
- **~25 new rules** across 6 epics
- **~75 new tests** (baseline + edge cases)
- **~6 new collector methods**
- **~15 new shell commands** (mostly optional dependencies)
- **0 architecture changes**

### What should intentionally wait
- Evidence persistence / schema v4 — no workflow requires it
- Health score — no defensible weighting scheme
- Diagnostic aggregation — no incident grouping problem
- RecommendationEngine Evidence access — no recommendation needs it
- Wi-Fi diagnostics — too many false positives
- DNS/Network connectivity — better served by dedicated tools
- PipeWire/Audio (beyond existing segfault coverage) — interface too volatile
- ML/AI diagnosis — out of scope

---

## Explicit non-goals

1. **AI/ML diagnosis** — Not suitable for a deterministic diagnostic tool. Every rule must be explainable and testable.
2. **Health scores** — No defensible weighting scheme exists. Severity + confidence provide better information.
3. **Probabilistic diagnosis** — "Likely" confidence is acceptable for deterministic rules; Bayesian/probabilistic models are out of scope.
4. **Cloud services** — SysCheck runs locally with no telemetry, no API calls, no cloud dependencies.
5. **Telemetry** — No data leaves the workstation.
6. **Automatic repair** — SysCheck diagnoses and recommends; it never modifies system state.
7. **Background daemons** — SysCheck is a CLI tool, not a service. It runs on demand.
8. **Remote agents** — No network listening, no remote API, no agent deployment.
9. **Performance benchmarking** — SysCheck measures state, not speed.
10. **Intrusion detection** — Out of scope; dedicated tools exist.
11. **Malware scanning** — Out of scope.
12. **Database/webserver diagnostics** — Not workstation-relevant.
13. **Container orchestration health** — Not workstation-relevant (single-node Docker/Podman issues could be added later if warranted).
14. **Continuous monitoring** — SysCheck is a snapshot tool. Trend detection is a future-architecture consideration.

---

## Final recommendation

### What SysCheck should become

SysCheck should be the first tool an experienced Linux administrator runs on a workstation to answer: **"Is this system healthy, and if not, what should I investigate?"**

It should cover:
- All common Linux workstation failure modes with deterministic, low-FP rules
- The complete pipeline from data collection to actionable recommendations
- A stable, predictable diagnostic contract that does not change between runs
- Every collected datum should eventually enter the structured pipeline (no more "display-only" data)

Target: ~35 rules across 12-15 diagnostic domains, covering the top 95% of Linux workstation problems.

### Which epic should be implemented next

**Epic 1: Memory Reliability**

Rationale:
- OOM kills and memory pressure are the #1 workstation issue not currently diagnosed
- Implementation complexity is low
- Data sources already partially exist
- False positive rate is near zero for OOM detection
- User value is immediate and high

### Which epics should intentionally wait

- **Wi-Fi** (wait): Too many false positives from transient disconnects. The signal-to-noise ratio in wpa_supplicant logs is too low for deterministic rules.
- **DNS/Network** (wait): Meaningful network diagnosis requires external probes or active testing, which conflicts with SysCheck's read-only design.
- **PipeWire/Audio** (wait): The error interface is version-dependent and frequently changes. WirePlumber segfault coverage is sufficient for now.
- **Bluetooth, USB, TPM, Entropy** (indefinite wait): Low user value for the workstation diagnostic use case.

### Which ideas should never become part of SysCheck

- **AI/ML diagnosis** — Incompatible with the deterministic, testable, explainable rule philosophy
- **Cloud/telemetry** — Violates the offline/local design constraint
- **Automatic repair** — Violates the read-only diagnostic principle
- **Health scores** — Cannot be defensibly weighted; severity + confidence is more useful
- **Background daemon** — Would fundamentally change the tool's architecture and failure mode

### Is the current architecture sufficient for the proposed roadmap?

**YES.**

The three-stage pipeline (RAW → OBS → Evidence + Finding → Recommendation) is well-suited for all 22 candidate domains evaluated in this assessment. No architectural redesign is required. The following concrete additions are needed:

- **New collectors**: ~6 additional `collect_*` methods following the existing pattern
- **New Observation categories**: ~25 new branches in `_raw_to_observation()` and `_classification_policy`
- **New Evidence types**: No new `EvidenceType` values needed (existing `JOURNAL_EVENT`, `HARDWARE_STATE`, `SYSTEM_STATE`, `STORAGE_MEASUREMENT`, `FILESYSTEM_STATE`, `SERVICE_STATE`, `DERIVED_MEASUREMENT` cover all proposed domains)
- **New rules**: ~25 new `DiagnosticRule` subclasses following the existing pattern
- **New tests**: ~75 test methods following the existing pattern

The architecture's separation of concerns, deterministic contracts, and clean pipeline (RAW → OBS → Evidence + Finding → Recommendation) are validated for the proposed scope.

**No schema version changes. No Evidence persistence. No pipeline redesign.**
