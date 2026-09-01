"""Product-maturity regression tests for the v0.5 readiness milestone."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import syscheck  # noqa: E402
from syscheck import (  # noqa: E402
    CAPABILITY_AVAILABLE,
    CAPABILITY_FAILED,
    CAPABILITY_LIMITED,
    CAPABILITY_NOT_APPLICABLE,
    CAPABILITY_UNAVAILABLE,
    CapabilityProbeSpec,
    CmdResult,
    EnvironmentSnapshot,
    EvidenceSnapshot,
    FindingSnapshot,
    ObservationSnapshot,
    RawDiagnosticSnapshot,
    RawDiagnostic,
    SnapshotMetadata,
    SourceCapability,
    SystemSnapshot,
    _capability_from_result,
    format_capabilities,
    probe_source_capabilities,
    sanitize_artifact,
)


FIXTURE_DIR = (
    Path(__file__).parent / ".agent-work" / "replay" / "v0.5-multi-workstation"
)


def _result(
    command: str = "fixture",
    *,
    stdout: str = "source output",
    stderr: str = "",
    return_code: int = 0,
    execution_status: str = "ok",
    truncated: bool = False,
) -> CmdResult:
    return CmdResult(
        command=command,
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        execution_status=execution_status,
        truncated=truncated,
    )


def test_capability_probe_surface_is_stable_and_non_diagnostic(monkeypatch):
    responses = {
        "journalctl -b --no-pager": _result(),
        "journalctl -b -k --no-pager": _result(),
        "cat /proc/sys/kernel/dmesg_restrict": _result(stdout="1"),
        "systemctl --failed --no-pager": _result(),
        "systemctl --user --failed --no-pager": _result(
            stderr="Failed to connect to bus: No medium found",
            return_code=1,
            execution_status="error",
        ),
        "systemctl status NetworkManager --no-pager": _result(),
        "upower -d": _result(),
        "btrfs filesystem show /": _result(),
        "nvme list": _result(execution_status="not_found", return_code=-1),
        "lspci -k": _result(),
        "lsusb": _result(),
        "sensors": _result(),
    }

    def fake_run(cmd, timeout=syscheck.TIMEOUT_SHORT, optional_dependency=False):
        del timeout, optional_dependency
        return responses[" ".join(cmd)]

    monkeypatch.setattr(syscheck, "run_cmd", fake_run)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")

    capabilities = probe_source_capabilities()

    assert [capability.family for capability in capabilities] == [
        spec.family for spec in syscheck.CAPABILITY_PROBES
    ] + ["session_display"]
    assert len({capability.family for capability in capabilities}) == len(capabilities)
    statuses = {capability.family: capability.status for capability in capabilities}
    assert statuses["systemd_user"] == CAPABILITY_LIMITED
    assert statuses["nvme"] == CAPABILITY_UNAVAILABLE
    assert statuses["session_display"] == CAPABILITY_AVAILABLE
    assert all(
        "healthy" not in capability.detail.lower() for capability in capabilities
    )


def test_capability_classifier_distinguishes_missing_limited_not_applicable_and_failed():
    assert (
        _capability_from_result(
            CapabilityProbeSpec("optional", ("optional",)),
            _result(execution_status="not_found", return_code=-1),
        ).status
        == CAPABILITY_UNAVAILABLE
    )
    assert (
        _capability_from_result(
            CapabilityProbeSpec("limited", ("limited",)),
            _result(
                stderr="Operation not permitted",
                return_code=1,
                execution_status="error",
            ),
        ).status
        == CAPABILITY_LIMITED
    )
    assert (
        _capability_from_result(
            CapabilityProbeSpec("fs", ("btrfs",), optional_dependency=True),
            _result(
                stderr="ERROR: not a btrfs filesystem",
                return_code=1,
                execution_status="error",
            ),
        ).status
        == CAPABILITY_NOT_APPLICABLE
    )
    assert (
        _capability_from_result(
            CapabilityProbeSpec("broken", ("broken",)),
            _result(
                stderr="unexpected source failure",
                return_code=7,
                execution_status="error",
            ),
        ).status
        == CAPABILITY_FAILED
    )
    assert (
        _capability_from_result(
            CapabilityProbeSpec("dmesg", ("cat",), mode="dmesg_restrict"),
            _result(stdout="1"),
        ).status
        == CAPABILITY_LIMITED
    )


def test_capabilities_json_and_plain_output_have_fixed_order_and_are_tty_independent():
    capabilities = (
        SourceCapability(
            "z_source", CAPABILITY_AVAILABLE, "authoritative source query succeeded"
        ),
        SourceCapability(
            "a_source",
            CAPABILITY_NOT_APPLICABLE,
            "source does not apply on this workstation",
        ),
    )
    plain = format_capabilities(capabilities)
    payload = json.loads(format_capabilities(capabilities, json_output=True))

    assert plain.index("z_source") < plain.index("a_source")
    assert "HEALTHY" not in plain
    assert payload["capabilities"] == [
        capability.to_dict() for capability in capabilities
    ]
    assert "ansi" not in format_capabilities(capabilities).lower()


def test_portability_fixtures_contain_only_source_contracts():
    fixtures = sorted(FIXTURE_DIR.glob("*.json"))
    assert len(fixtures) == 2
    for fixture in fixtures:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        assert payload["private_machine_identifiers"] == []
        assert set(payload["capabilities"]) == {
            "btrfs",
            "dmesg",
            "kernel_journal",
            "nvme",
            "optional_source",
            "systemd_user",
            "upower",
        }
        assert payload["diagnostic_semantics"] == {
            "unavailable_source_creates_finding": False,
            "limited_source_is_health": False,
            "limited_source_is_failure": False,
        }


def test_readme_documents_the_public_product_lifecycle_and_sharing_boundary():
    readme = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")
    for required_text in (
        "./install.sh",
        "uv tool uninstall linux-diagnostic-engine",
        "lde --version",
        "lde capabilities",
        "lde snapshot validate",
        "lde sanitize",
        "not a guarantee of anonymity",
    ):
        assert required_text in readme


def test_capability_limitations_do_not_change_diagnostic_truth():
    engine = syscheck.SysCheckEngine(output_dir="/tmp/lde-v05-semantics")
    engine.raw_diagnostics.extend(
        [
            RawDiagnostic(
                source_id="BTRFS-SOURCE-LIMITED",
                category="btrfs_error",
                payload={"status": "permission_denied"},
            ),
            RawDiagnostic(
                source_id="SYSTEMD-USER-BUS-LIMITED",
                category="systemd_user_source_failure",
                payload={
                    "scope": "user",
                    "authoritative": False,
                    "execution_status": "error",
                    "return_code": 1,
                },
            ),
        ]
    )
    engine._derive_observations()
    engine._interpret()

    assert engine.findings == []
    assert {obs.category for obs in engine.observations} == {
        "btrfs_error",
        "systemd_user_source_failure",
    }

    from unittest.mock import patch

    power_engine = syscheck.SysCheckEngine(output_dir="/tmp/lde-v05-power")
    with patch.object(
        power_engine,
        "cmd",
        return_value=_result(
            stdout=(
                "Device: /org/freedesktop/UPower/devices/battery_BAT0\n"
                "  power supply: yes\n"
                "  state: fully-charged\n"
                "  warning-level: none\n"
            )
        ),
    ):
        power_engine.collect_power()
    power_engine._derive_observations()
    power_engine._interpret()
    assert not any(
        finding.finding_id == "POWER-SOURCE-CRITICAL-001"
        for finding in power_engine.findings
    )


def test_sanitize_markdown_public_workflow_is_deterministic_and_preserves_meaning(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "private.md"
    output_one = tmp_path / "sanitized-one.md"
    output_two = tmp_path / "sanitized-two.md"
    original = (
        "# Report\n"
        "**Hostname:** `office-workstation`\n"
        "**Username:** `alice`\n"
        "**Serial:** `SN-123`\n"
        "**Filesystem label:** `work`\n"
        "Home: /home/alice/projects\n"
        "Network: 192.168.10.25 fe80::abcd:1234 aa:bb:cc:dd:ee:ff\n"
        "Volume UUID: 123e4567-e89b-12d3-a456-426614174000\n"
        "Device: /dev/nvme0n1, service my.service, Finding F-1, severity P2\n"
    )
    input_path.write_text(original, encoding="utf-8")

    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_one)],
    )
    syscheck.main()
    first_cli_output = capsys.readouterr().out

    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_two)],
    )
    syscheck.main()
    capsys.readouterr()

    sanitized = output_one.read_text(encoding="utf-8")
    assert output_one.read_bytes() == output_two.read_bytes()
    assert input_path.read_text(encoding="utf-8") == original
    assert "office-workstation" not in sanitized
    assert "alice" not in sanitized
    assert "SN-123" not in sanitized
    assert "`work`" not in sanitized
    assert "<HOST>" in sanitized
    assert "<USER>" in sanitized
    assert "<HOME>/projects" in sanitized
    assert "<IP>" in sanitized
    assert "<MAC>" in sanitized
    assert "<UUID>" in sanitized
    assert "/dev/nvme0n1" in sanitized
    assert "my.service" in sanitized
    assert "Finding F-1" in sanitized
    assert "severity P2" in sanitized
    assert "not guaranteed anonymous" in sanitized
    assert "not guaranteed anonymous" in first_cli_output
    assert sanitize_artifact(output_one) == sanitized


def test_sanitize_redacts_mount_paths_and_ps_user_columns():
    raw = (
        "USER         PID %CPU %MEM COMMAND\n"
        "alice         42  1.0  2.0 /run/media/alice/Private Backup\n"
    )

    sanitized = syscheck._sanitize_text(raw)

    assert "alice" not in sanitized
    assert "/run/media/" not in sanitized
    assert "Private Backup" not in sanitized
    assert "<MEDIA>" in sanitized
    assert "<USER>" in sanitized
    assert "42" in sanitized


def test_sanitize_snapshot_preserves_schema_ids_and_diagnostic_fields(tmp_path):
    snapshot = SystemSnapshot(
        metadata=SnapshotMetadata(
            hostname="home-workstation",
            kernel="6.1.1",
            distro="Test Linux",
            syscheck_version="2.1.0",
        ),
        environment=EnvironmentSnapshot(
            storage=({"mountpoint": "/home/alice", "usage_percent": 71},),
        ),
        observations=(
            ObservationSnapshot(
                obs_id="OBS-1",
                category="storage_usage",
                details={"username": "alice", "ip": "10.0.0.2"},
            ),
        ),
        evidence=(
            EvidenceSnapshot(
                evidence_id="EVIDENCE-1",
                evidence_type="measurement",
                data={"serial": "SERIAL-1", "device": "/dev/sda1"},
                source_observation_ids=("OBS-1",),
            ),
        ),
        raw_diagnostics=(
            RawDiagnosticSnapshot(
                source_id="RAW-1",
                category="storage_usage",
                payload={"uuid": "123e4567-e89b-12d3-a456-426614174000"},
            ),
        ),
        findings=(
            FindingSnapshot(
                finding_id="F-1",
                title="Storage usage",
                severity="P2",
                confidence="Certain",
                evidence_ids=("EVIDENCE-1",),
                source_observation_ids=("OBS-1",),
            ),
        ),
    )
    input_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "sanitized.json"
    snapshot.to_json(input_path)
    original = input_path.read_bytes()

    output = sanitize_artifact(input_path)
    output_path.write_text(output, encoding="utf-8")
    sanitized = json.loads(output_path.read_text(encoding="utf-8"))
    reloaded = SystemSnapshot.from_json(output_path)

    assert input_path.read_bytes() == original
    assert sanitized["schema_version"] == 3
    assert sanitized["metadata"]["hostname"] == "<HOST>"
    assert sanitized["environment"]["storage"][0]["mountpoint"] == "<HOME>"
    assert sanitized["observations"][0]["details"]["username"] == "<USER>"
    assert sanitized["evidence"][0]["data"]["serial"] == "<SERIAL>"
    assert sanitized["evidence"][0]["data"]["device"] == "/dev/sda1"
    assert sanitized["findings"][0]["finding_id"] == "F-1"
    assert sanitized["findings"][0]["severity"] == "P2"
    assert reloaded.schema_version == snapshot.schema_version
    assert reloaded.findings[0].evidence_ids == snapshot.findings[0].evidence_ids


@pytest.mark.parametrize(
    ("suffix", "content", "needle"),
    [
        (".txt", "not a supported report", "Unsupported input type"),
        (".json", "{not-json", "Invalid JSON input"),
        (
            ".json",
            '{"schema_version": 3, "metadata": []}',
            "Invalid snapshot input",
        ),
    ],
)
def test_sanitize_rejects_unsupported_or_malformed_input_cleanly(
    tmp_path, monkeypatch, capsys, suffix, content, needle
):
    input_path = tmp_path / f"input{suffix}"
    output_path = tmp_path / "output.md"
    input_path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        syscheck.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "Traceback" not in captured.err
    assert needle in captured.err
    assert not output_path.exists()


def test_sanitize_rejects_missing_input_cleanly(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "missing.md"
    output_path = tmp_path / "output.md"
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        syscheck.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "input or destination not found" in captured.err
    assert "Traceback" not in captured.err


def test_sanitize_rejects_input_output_alias_and_destination_collision(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "report.md"
    input_path.write_text("**Hostname:** `host`\n", encoding="utf-8")
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(input_path)],
    )
    with pytest.raises(SystemExit) as exc_info:
        syscheck.main()
    assert exc_info.value.code == 1
    assert "different from the input" in capsys.readouterr().err
    assert input_path.read_text(encoding="utf-8") == "**Hostname:** `host`\n"

    output_path = tmp_path / "output.md"
    output_path.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_path)],
    )
    with pytest.raises(SystemExit) as exc_info:
        syscheck.main()
    assert exc_info.value.code == 1
    assert "already exists" in capsys.readouterr().err
    assert output_path.read_text(encoding="utf-8") == "keep"


def test_sanitize_rejects_symlink_destination_without_touching_target(
    tmp_path, monkeypatch, capsys
):
    input_path = tmp_path / "report.md"
    input_path.write_text("**Hostname:** `host`\n", encoding="utf-8")
    target_path = tmp_path / "target.md"
    target_path.write_text("keep", encoding="utf-8")
    output_path = tmp_path / "output.md"
    output_path.symlink_to(target_path)
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "sanitize", str(input_path), "--output", str(output_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        syscheck.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "symlink" in captured.err
    assert output_path.is_symlink()
    assert target_path.read_text(encoding="utf-8") == "keep"
