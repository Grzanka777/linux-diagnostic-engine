# Iteration 43 — Platform, Firmware & Device Reliability Pack Review

## Verdict

PASS — Implemented four deterministic current-boot kernel diagnostics:
1. `PLATFORM-ACPI-FIRMWARE-ERROR-001` (category `platform_acpi_firmware_error`, `FindingKind.PLATFORM_ACPI_FIRMWARE_ERROR`, severity P2) detects explicit ACPI BIOS and ACPI interpreter error events.
2. `KERNEL-FIRMWARE-LOAD-FAIL-001` (category `kernel_firmware_load_fail`, `FindingKind.KERNEL_FIRMWARE_LOAD_FAIL`, severity P2) detects explicit kernel firmware-loader failures.
3. `USB-ENUMERATION-FAIL-001` (category `usb_enumeration_fail`, `FindingKind.USB_ENUMERATION_FAIL`, severity P2) detects explicit USB descriptor, address, and enumeration failures.
4. `IOMMU-FAULT-001` (category `iommu_fault`, `FindingKind.IOMMU_FAULT`, severity P1) detects explicit AMD-Vi, Intel DMAR, and IOMMU DMA translation faults.

A single shared bounded, status-aware current-boot kernel journal capture (`platform_device_reliability`) queries events for all four families simultaneously while strictly preserving truncation, completeness, and security semantics. The pack strictly rejects generic ACPI/firmware/USB/IOMMU/fault text, userspace messages, normal boot device and table announcements, and unrelated existing LDE diagnostics. At most one RawDiagnostic and one DiagnosticRule is emitted per family per pass, while independent valid families coexist cleanly without mutual interference. All diagnostics adhere to strict non-causal language without root-cause attribution or automatic remediation.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Baseline supplied for this iteration: 770 tests passing (`HEAD == origin/master == 546283c`).
- Final suite: 826 tests collected; 826 tests passing (56 new focused test cases collected; within +45..+65 target range).
- No staging, committing, pushing, resetting, restoring, stashing, checking out, branching, rebasing, merging, tagging, or cleaning operation was performed. Unstaged changes preserved; `.codex/` untouched.

## Contract Audit

| Contract item | Evidence | Result |
| --- | --- | --- |
| Diagnostic IDs | `PLATFORM-ACPI-FIRMWARE-ERROR-001`, `KERNEL-FIRMWARE-LOAD-FAIL-001`, `USB-ENUMERATION-FAIL-001`, `IOMMU-FAULT-001` | PASS |
| Categories & FindingKinds | `platform_acpi_firmware_error` (`PLATFORM_ACPI_FIRMWARE_ERROR`), `kernel_firmware_load_fail` (`KERNEL_FIRMWARE_LOAD_FAIL`), `usb_enumeration_fail` (`USB_ENUMERATION_FAIL`), `iommu_fault` (`IOMMU_FAULT`) | PASS |
| Explicit triggers | ACPI BIOS / interpreter errors, direct/request firmware loader failures, USB descriptor/address/enumeration failures, AMD-Vi/Intel DMAR/IOMMU translation faults | PASS |
| False positive rejection | Strictly rejects generic ACPI/firmware/USB/IOMMU/error text, userspace logs, normal boot initialization/detection lines, and existing LDE diagnostics | PASS |
| Severity mapping | ACPI firmware error (P2), Firmware load fail (P2), USB enumeration fail (P2), IOMMU fault (P1) | PASS |
| Shared status-aware journal collector | One shared task `"platform_device_reliability"` via bounded `_oom_collector_command("journalctl -b -k --no-pager 2>/dev/null", RE_PLATFORM_DEVICE_RELIABILITY)` | PASS |
| Truncation / completeness | Propagates `capture_truncated` → `data_complete=False` → `completeness=PARTIAL` across all 4 families | PASS |
| Non-causal wording | All findings report recorded journal events without attributing root cause to specific hardware, faulty modules, or userspace workloads | PASS |
| Architecture & runtime seam | Registered in `DiagnosticRuleRegistry`, re-exported via `syscheck`, typed classification policy (`Actionability.ACTIONABLE`, `RecommendationIntent.INVESTIGATE`) | PASS |
| Coexistence | Independent valid families coexist cleanly within the same collection pass | PASS |

## Changed Paths

- `constants.py` — Added `RE_PLATFORM_ACPI_FIRMWARE_ERROR`, `RE_KERNEL_FIRMWARE_LOAD_FAIL`, `RE_USB_ENUMERATION_FAIL`, `RE_IOMMU_FAULT`, and unified shared regex `RE_PLATFORM_DEVICE_RELIABILITY`.
- `syscheck.py` — Added `FindingKind` members, classification policies, `EvidenceBuilder` branches, shared capture task in `collect_kernel_hw`, RawDiagnostic extractions, Observation mappings, and rule re-exports.
- `diagnostic_rules.py` — Implemented `PlatformAcpiFirmwareErrorRule`, `KernelFirmwareLoadFailRule`, `UsbEnumerationFailRule`, and `IommuFaultRule`; registered all four in `build_default_rule_engine()`.
- `test_syscheck.py` — Added 56 new test cases (4 in `TestCaptureCompleteness`, 1 in re-exports test assertion list, 51 in `TestPlatformFirmwareDeviceReliabilityPack`).
- `.agent-work/reviews/iteration-43-platform-firmware-device-reliability-pack.md` — this review.

## Per-File Summary

- `constants.py`:
  - `RE_PLATFORM_ACPI_FIRMWARE_ERROR`: matches `ACPI [BIOS] Error:` and `ACPI [BIOS] Exception: AE_...`.
  - `RE_KERNEL_FIRMWARE_LOAD_FAIL`: matches `Direct firmware load for <file> failed with error <err>`, `firmware: failed to load`, `Failed to load firmware`, `request_firmware failed`.
  - `RE_USB_ENUMERATION_FAIL`: matches `device descriptor read/(64|8|all), error <err>`, `unable to enumerate USB device`, `device not accepting address <addr>, error <err>`, `can't set address`, `can't read configurations`.
  - `RE_IOMMU_FAULT`: matches `AMD-Vi: Event logged [...]`, `AMD-Vi: Completion-Wait loop timed out`, `DMAR: [DMA Read/Write] Request device`, `DMAR: DRHD: handling fault status`, `DMAR: [INTR-REMAP] Request device`, `arm-smmu: Unhandled context fault`, `IOMMU: DMA translation fault`.
  - `RE_PLATFORM_DEVICE_RELIABILITY`: combines all 4 patterns into a single expression for shared bounded journal capture.
- `syscheck.py`:
  - Defined `FindingKind.PLATFORM_ACPI_FIRMWARE_ERROR`, `KERNEL_FIRMWARE_LOAD_FAIL`, `USB_ENUMERATION_FAIL`, and `IOMMU_FAULT`.
  - Added classification policy mappings for all 4 categories: `platform_acpi_firmware_error` (`HARDWARE`), `kernel_firmware_load_fail` (`KERNEL`), `usb_enumeration_fail` (`HARDWARE`), `iommu_fault` (`HARDWARE`), all with `Actionability.ACTIONABLE`, `RecommendationIntent.INVESTIGATE`.
  - Implemented `EvidenceBuilder` branches emitting `EvidenceType.JOURNAL_EVENT` with completeness propagation.
  - Added shared task `"platform_device_reliability"` to `tasks_cmd` in `collect_kernel_hw()`.
  - Extracted individual RawDiagnostics guarded by `is_ok()` and stdout content.
  - Mapped raw entries to Observations in `_raw_to_observation()`.
  - Re-exported the four rule classes from `diagnostic_rules`.
- `diagnostic_rules.py`:
  - Implemented `PlatformAcpiFirmwareErrorRule` (`RULE-PLATFORM-ACPI-FIRMWARE-ERROR`, P2).
  - Implemented `KernelFirmwareLoadFailRule` (`RULE-KERNEL-FIRMWARE-LOAD-FAIL`, P2).
  - Implemented `UsbEnumerationFailRule` (`RULE-USB-ENUMERATION-FAIL`, P2).
  - Implemented `IommuFaultRule` (`RULE-IOMMU-FAULT`, P1).
  - Registered all four rules in `build_default_rule_engine()`.
- `test_syscheck.py`:
  - Extended `TestCaptureCompleteness` with the four new categories.
  - Added `TestPlatformFirmwareDeviceReliabilityPack` covering positive detection, generic/userspace rejection, normal boot message rejection, unrelated diagnostic rejection, individual collector runs, coexistence in shared capture, failure/empty handling, observation/evidence/finding contracts, and isolation from other diagnostic domains.

## Validation Commands and Results

- `ruff check .` — PASS (`All checks passed!`).
- `ruff format --check .` — PASS (`4 files already formatted`).
- `python3 -m pytest --collect-only -q` — PASS (`826 tests collected`).
- `pytest` — PASS (`826 passed in 4.25s`).
- `git diff --check` — PASS (clean, no whitespace or formatting errors).
- `git diff --cached --quiet` — PASS (no staged changes).

## Scope Audit

- In scope: Four deterministic current-boot kernel platform, firmware, USB, and IOMMU reliability diagnostics, single shared journal collection pass, complete runtime integration, comprehensive test suite (56 new collected tests).
- Excluded: No root cause attribution, no invasive system actions, no Git publication, staging, or committing.

## Conclusion & Freeze Status

```text
FEATURE_EXPANSION_FREEZE_FOR_V0_1_0 = YES
```

With the completion of Iteration 43, feature expansion for `v0.1.0` is officially frozen.

### Next Phase Roadmap

The engine now transitions from new feature expansion to release stabilization:
1. `coverage/overlap/false-positive audit` — comprehensive matrix review across all implemented diagnostic rules.
2. `real-machine E2E` — execution validation against diverse physical hardware and Linux configurations.
3. `CLI/output stabilization` — finalization of terminal output, reporting formats, and flag contracts.
4. `packaging/install` — packaging, system dependencies, distribution manifests, and installer scripts.
5. `release readiness` — documentation verification, changelog generation, and pre-release smoke checks.
6. `//SHIP v0.1.0` — final tag and release publication.

## NeuralEngine Usage

- `neural status`:
  Initialized Brain resolved through `NEURAL_HOME` at `<REDACTED-PATH>`; command exited 0.
- NeuralEngine search used: YES (searched "firmware", "usb", "iommu", "acpi"; no historical records found).
- Outcome: Current repository authority and explicit user specification were controlling.
- Brain writes: NONE.
