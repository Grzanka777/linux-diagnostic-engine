"""Minimal sanitized regression evidence from a real LDE 0.6.1 run."""

import json
import re
from pathlib import Path

import syscheck
from syscheck import (
    CmdResult,
    EnvironmentSnapshot,
    ExecutionSnapshot,
    FindingLifecycleComparator,
    FindingSnapshot,
    ObservationSnapshot,
    RawDiagnosticSnapshot,
    SnapshotMetadata,
    SystemSnapshot,
)

FIXTURE_PATH = (
    Path(__file__).parent / "tests" / "fixtures" / "lde_v0_6_1_real_world_minimal.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_lspci(*, card0="1002:f00d", card1="8086:beef"):
    return (
        "0000:01:00.0 VGA compatible controller [0300]: Synthetic GPU A "
        f"[{card0}]\n\tKernel driver in use: amdgpu\n"
        "0000:02:00.0 3D controller [0302]: Synthetic GPU B "
        f"[{card1}]\n\tKernel driver in use: i915\n"
    )


def test_real_world_fixture_is_minimal_synthetic_and_preserves_authority():
    assert FIXTURE_PATH.stat().st_size < 5_000
    assert set(FIXTURE) == {
        "provenance",
        "boot",
        "kernel_inventory",
        "gpu",
        "kernel_event",
        "btrfs",
        "privacy_sample",
    }
    assert FIXTURE["provenance"]["sanitized_before_repository_admission"] is True
    assert len(FIXTURE["provenance"]["scope"]) == 5
    assert FIXTURE["boot"] == {
        "enumeration_status": "permission_denied",
        "module_tree_count": 3,
        "boot_images": None,
    }
    kernel_inventory = FIXTURE["kernel_inventory"]
    assert syscheck._count_kernel_packages("\n".join(kernel_inventory["packages"])) == (
        2,
        2,
        kernel_inventory["packages"],
    )
    assert len(kernel_inventory["module_trees"]) == 3
    assert "7.2.8-2-cachyos" in kernel_inventory["module_trees"]
    assert FIXTURE["btrfs"]["expected_authoritative"] is False
    assert FIXTURE["btrfs"]["expected_finding"] is False


def test_gpu_complete_drm_identity_does_not_use_fallback():
    records = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\t0x1002\t0xf00d\n",
        _fixture_lspci(),
    )

    assert len(records) == 1
    assert records[0].reconciliation_status == "drm_complete"
    assert records[0].vendor_id == "1002"
    assert records[0].device_id == "f00d"
    assert records[0].vendor_source == "DRM"
    assert records[0].device_source == "DRM"


def test_real_world_gpu_gap_uses_matching_lspci_identity_with_provenance():
    records = syscheck._reconcile_gpu_inventory(
        FIXTURE["gpu"]["drm_tsv"],
        FIXTURE["gpu"]["lspci_nnk"],
    )

    assert len(records) == 1
    record = records[0]
    assert record.reconciliation_status == "lspci_fallback"
    assert record.pci_address == "0000:03:00.0"
    assert record.vendor_id == "1002"
    assert record.device_id == "f00d"
    assert record.vendor_source == "DRM"
    assert record.device_source == "lspci -nnk"


def test_gpu_multiple_devices_are_associated_by_pci_address():
    drm = "card0\t0000:01:00.0\t0x1002\tunknown\ncard1\t0000:02:00.0\t0x8086\tunknown\n"
    records = syscheck._reconcile_gpu_inventory(drm, _fixture_lspci())

    assert [record.device_id for record in records] == ["f00d", "beef"]
    assert [record.pci_address for record in records] == [
        "0000:01:00.0",
        "0000:02:00.0",
    ]
    assert all(record.reconciliation_status == "lspci_fallback" for record in records)


def test_gpu_unknown_is_preserved_when_lspci_is_unavailable():
    records = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\t0x1002\tunknown\n",
        "",
        lspci_available=False,
    )

    assert len(records) == 1
    assert records[0].device_id is None
    assert records[0].reconciliation_status == "unknown"
    assert records[0].device_source == "unknown"


def test_gpu_contradiction_keeps_drm_values_and_does_not_merge():
    records = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\t0x1002\t0x9999\n",
        _fixture_lspci(),
    )

    assert len(records) == 1
    assert records[0].device_id == "9999"
    assert records[0].device_source == "DRM"
    assert records[0].reconciliation_status == "conflict"


def test_gpu_malformed_lspci_does_not_crash_or_fill_unknown_identity():
    records = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\t0x1002\tunknown\n",
        "not a PCI inventory record\n0000:01:00.0 VGA compatible controller [1002:nope]\n",
    )

    assert len(records) == 1
    assert records[0].device_id is None
    assert records[0].reconciliation_status == "unknown"


def test_graphics_collector_renders_reconciled_per_card_identity(monkeypatch):
    engine = syscheck.SysCheckEngine(
        output_dir="/tmp/lde-gpu-reconcile-test", quiet=True
    )

    def fake_parallel_cmd(self, tasks):
        return {
            name: CmdResult(
                command=name,
                stdout=(
                    FIXTURE["gpu"]["drm_tsv"]
                    if name == "drm_inventory"
                    else FIXTURE["gpu"]["lspci_nnk"]
                    if name == "lspci"
                    else ""
                ),
                stderr="",
                return_code=0,
                execution_status="ok",
            )
            for name in tasks
        }

    monkeypatch.setattr(syscheck.SysCheckEngine, "_parallel_cmd", fake_parallel_cmd)
    engine.collect_graphics()
    report = "".join(engine.report_lines)

    assert "device `0xf00d` (lspci -nnk" in report
    assert "0000:03:00.0" in report


def test_btrfs_incomplete_missing_evidence_remains_non_authoritative():
    capture = FIXTURE["btrfs"]
    result = CmdResult(
        command="btrfs filesystem show /",
        stdout=capture["show_stdout"],
        stderr=capture["show_stderr"],
        return_code=capture["return_code"],
        execution_status=capture["execution_status"],
        privilege_required=capture["privilege_required"],
    )

    status = syscheck._classify_btrfs_status(result, command_kind="show")
    assert syscheck._btrfs_missing_device_lines(result.stdout)
    assert status == "permission_denied"
    assert not syscheck._btrfs_missing_capture_is_authoritative(result, status)


def test_incomplete_btrfs_source_cannot_turn_a_prior_finding_into_resolved():
    finding_id = "BTRFS-ERR-001"
    raw_id = "RAW-BTRFS-001"
    observation_id = "OBS-BTRFS-001"
    evidence_id = "EVID-BTRFS-001"
    timestamp = "2026-10-05T00:00:00+00:00"
    metadata = SnapshotMetadata(
        hostname="fixture-host",
        kernel="6.18.0-fixture",
        distro="fixture-linux",
        syscheck_version=syscheck.REPORT_COMPATIBILITY_VERSION,
        timestamp_utc=timestamp,
        timestamp_local=timestamp,
    )
    baseline = SystemSnapshot(
        metadata=metadata,
        environment=EnvironmentSnapshot(),
        observations=(
            ObservationSnapshot(
                obs_id=observation_id,
                category="btrfs_error",
                source_raw_ids=(raw_id,),
            ),
        ),
        raw_diagnostics=(
            RawDiagnosticSnapshot(
                source_id=raw_id,
                category="btrfs_error",
                payload={"source_query": "btrfs_show"},
                provenance={"execution_status": "ok", "truncated": False},
            ),
        ),
        findings=(
            FindingSnapshot(
                finding_id=finding_id,
                title="Fixture Btrfs state",
                severity="P1",
                confidence="Certain",
                source_observation_ids=(observation_id,),
            ),
        ),
        evidence=(
            syscheck.EvidenceSnapshot(
                evidence_id=evidence_id,
                evidence_type="journal_event",
                source_observation_ids=(observation_id,),
                source_raw_ids=(raw_id,),
            ),
        ),
        restrictions=(),
        execution=ExecutionSnapshot(),
    )
    current = SystemSnapshot(
        metadata=metadata,
        environment=EnvironmentSnapshot(),
        restrictions=(
            "btrfs_show permission denied; MISSING capture incomplete and non-authoritative",
        ),
        execution=ExecutionSnapshot(),
    )

    result = FindingLifecycleComparator.compare(baseline, current)

    assert result.resolved_finding_ids == ()
    assert result.unverified_finding_ids == (finding_id,)


def test_svm_event_is_captured_without_a_root_cause_finding(monkeypatch):
    event = FIXTURE["kernel_event"]["amdgpu_svm"]
    engine = syscheck.SysCheckEngine(
        output_dir="/tmp/lde-svm-evidence-test", quiet=True
    )
    requested_tasks = {}

    def fake_parallel_cmd(self, tasks):
        requested_tasks.update(tasks)
        return {
            name: CmdResult(
                command=name,
                stdout=event if name == "kernel_errors" else "",
                stderr="",
                return_code=0,
                execution_status="ok",
            )
            for name in tasks
        }

    monkeypatch.setattr(syscheck, "_get_script_pids", list)
    monkeypatch.setattr(syscheck.SysCheckEngine, "_parallel_cmd", fake_parallel_cmd)
    engine.collect_kernel_hw()
    engine._derive_observations()
    engine._interpret()

    assert re.search(syscheck.RE_KERNEL_ERROR, event, re.IGNORECASE)
    assert requested_tasks["lspci"][0] == ["lspci", "-nnk"]
    assert engine._lspci_result is not None
    assert event in "".join(engine.report_lines)
    assert engine.findings == []
    assert not any("svm" in raw.category.casefold() for raw in engine.raw_diagnostics)


def test_sanitizer_redacts_sensitive_synthetic_fields_but_keeps_diagnostic_value():
    original = FIXTURE["privacy_sample"]
    sanitized = syscheck._sanitize_markdown(original)

    assert sanitized == syscheck._sanitize_markdown(original)
    for sensitive in (
        "fixture-host",
        "testuser",
        "/run/user/4242",
        "02:00:00:00:00:01",
        "192.0.2.17",
        "fe80::1%test0",
        "123e4567-e89b-12d3-a456-426614174000",
        "TEST-SERIAL-0001",
        "TEST-SERIAL-0002",
        "TEST-SERIAL-0003",
        "TEST-SERIAL-0004",
        "/tmp/lde-fixture-run-0001/report.md",
    ):
        assert sensitive not in sanitized

    assert "<HOST>" in sanitized
    assert "<USER>" in sanitized
    assert "<HOME>/projects/lde" in sanitized
    assert "<TMP>" in sanitized
    assert "<INVOCATION_ID>" in sanitized
    assert "<SERIAL>" in sanitized
    assert "Opaque digest: 0123456789abcdef0123456789abcdef" in sanitized
    assert "Finding F-1" in sanitized
    assert "/dev/nvme0n1" in sanitized
    assert "Btrfs MISSING remains incomplete" in sanitized
    assert re.search(r"(?m)^> Sanitization note:", sanitized)
    invocation_id = "0123456789abcdef0123456789abcdef"
    assert (
        syscheck._sanitize_text(f"Invocation_ID={invocation_id}")
        == "Invocation_ID=<INVOCATION_ID>"
    )
    assert syscheck._sanitize_json_value({"invocation_id": invocation_id}) == {
        "invocation_id": "<INVOCATION_ID>"
    }
