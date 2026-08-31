# v0.3 storage and memory reliability replay corpus

All files in this directory are sanitized, deterministic fixtures. They contain
no hostnames, UUIDs, usernames, device serial numbers, or live command output.

| Fixture | Contract case | Expected result |
| --- | --- | --- |
| `btrfs-show-healthy.txt` | Complete device record plus negative MISSING text | No Btrfs error; authoritative healthy capture |
| `btrfs-show-authoritative-missing.txt` | Complete successful device record marked `MISSING` | `BTRFS-DEVICE-MISSING-001` and `BTRFS-ERR-001` Finding |
| `btrfs-show-limited-missing.txt` | MISSING line with permission failure | Preserved raw; non-authoritative rejection |
| `btrfs-stats-healthy.txt` | All error counters zero | No Btrfs error |
| `btrfs-stats-errors.txt` | Nonzero read/corruption counters | One Btrfs device-error Finding |
| `btrfs-scrub-healthy.txt` | Scrub currently inactive | No scrub-history Finding |
| `btrfs-scrub-no-history.txt` | No scrub history | `BTRFS-SCRUB-001` Finding |
| `btrfs-show-malformed.txt` | Successful but unrecognizable show output | Non-authoritative source status |
| `btrfs-show-truncated.txt` | Truncated MISSING capture | Preserved raw; non-authoritative rejection |
| `nvme-kernel-failure.txt` | Explicit timeout/reset event | `NVME-CONTROLLER-RESET-001` Finding |
| `nvme-kernel-near-miss.txt` | Initialization/configuration text | No NVMe Finding |
| `filesystem-block-error.txt` | Buffer I/O error | `FS-IO-ERROR-001`, family `block_io` |
| `filesystem-near-miss.txt` | Successful I/O text | No filesystem-I/O Finding |
| `filesystem-read-only.txt` | Explicit filesystem read-only remount | `FS-IO-ERROR-001`, family `filesystem_read_only` |
| `oom-kernel-failure.txt` | Kernel OOM-killer event | `KERNEL-OOM-001` Finding |
| `oom-kernel-near-miss.txt` | Pressure/oomd text without kernel OOM marker | No OOM Finding |
| `overlap-kernel-events.txt` | PCIe AER plus NVMe recovery | Two independent Findings |
| `nvme-smart-healthy.txt` | Sanitized healthy SMART/NVMe candidate | Deferred; no SMART Finding |
| `nvme-smart-positive.txt` | Sanitized SMART warning/counter candidate | Deferred; no SMART Finding |
| `nvme-smart-deferred-source.txt` | SMART source unavailable | Deferred; no SMART Finding |
| `psi-normal.txt` | PSI zero-value baseline | Deferred; no PSI Finding |
| `psi-nonzero-candidate.txt` | PSI non-zero values without persistence contract | Deferred; no PSI Finding |
| `system-service-failure.txt` | Structured failed system unit | `SYSD-SYS-FAIL-001` Finding |
| `user-service-source-failure.txt` | User systemd source transport failure | Source rejection; no user-service Finding |
| `segfault-wireplumber-only.txt` | Three same-owner WirePlumber events | `SEGFAULT-WP-001` Finding |
| `segfault-wireplumber-mixed.txt` | WirePlumber plus unrelated process | `SEGFAULT-SYS-001` Finding |
| `source-timeout.txt` | Journal source timeout | `TIMEOUT` restriction |
| `source-command-not-found.txt` | Journal command missing | `COMMAND_NOT_FOUND` restriction |
| `source-permission-denied.txt` | Journal permission failure | `PERMISSION_DENIED` restriction |
| `source-malformed.txt` | Unrecognized source output | `MALFORMED_OUTPUT` restriction |
| `source-truncated.txt` | Positive journal result with truncation marker | Partial evidence; no absence claim |
| `overlap-oom-oomd.txt` | Kernel OOM plus oomd near-miss text | One kernel OOM Finding |
| `overlap-service-segfault.txt` | Failed service plus unrelated segfault | Two independent Findings |
| `overlap-nvme-smart-healthy.txt` | NVMe event plus healthy SMART candidate | One NVMe Finding |
| `overlap-nvme-smart-issue-filesystem.txt` | NVMe/SMART candidate plus filesystem I/O | Two independent Findings; no SMART Finding |
| `overlap-memory-pressure-no-kill.txt` | PSI pressure plus monitoring-only oomd text | Deferred; no memory Finding |

The corpus deliberately does not claim NVMe SMART/health-counter, PSI, or
systemd-oomd Finding coverage. Those sources are not collected by the current
product and remain deferred until command availability, source authority,
interpretation, and actionability contracts are established.
