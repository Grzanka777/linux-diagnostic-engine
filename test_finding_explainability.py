"""Focused tests for v0.6 Finding explanation and actionability integration."""

import json
import os
import shlex
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import syscheck  # noqa: E402
from syscheck import (  # noqa: E402
    Actionability,
    EvidenceSnapshot,
    FindingExplanation,
    FindingSnapshot,
    ObservationSnapshot,
    RawDiagnosticSnapshot,
    SnapshotMetadata,
    SystemSnapshot,
    ExplainStep,
    explain_finding,
    find_finding_explanation_definition,
    format_finding_explanation,
    validate_finding_explanation_registry,
)


EXPLAIN_PATTERNS = tuple(syscheck.FINDING_EXPLANATION_REGISTRY)
DIRECT_COMMANDS = (
    "btrfs filesystem show /",
    "btrfs scrub status /",
    "systemctl --failed",
    "systemctl --user --failed",
    "df -h",
    "free -h",
    "lspci -nnk",
    "lsusb",
    "systemd-analyze critical-chain",
    "upower -d",
    "nmcli device status",
    "ip -details link",
    "findmnt -o SOURCE,FSTYPE,TARGET",
)


def _metadata() -> SnapshotMetadata:
    return SnapshotMetadata(
        hostname="explain-host",
        kernel="6.18.0-explain",
        distro="test-linux",
        syscheck_version=syscheck.REPORT_COMPATIBILITY_VERSION,
        timestamp_utc="2026-09-01T10:00:00+00:00",
        timestamp_local="2026-09-01T10:00:00+00:00",
    )


def _snapshot(*, finding=None, restrictions=(), authoritative=True):
    if finding is None:
        observations = ()
        evidence = ()
        raw = ()
        findings = ()
    else:
        obs_id = finding.source_observation_ids[0]
        evidence_id = finding.evidence_ids[0]
        raw_id = f"RAW-{finding.finding_id}"
        observations = (
            ObservationSnapshot(
                obs_id=obs_id,
                category="btrfs_error",
                details={},
                source_raw_ids=(raw_id,),
            ),
        )
        evidence = (
            EvidenceSnapshot(
                evidence_id=evidence_id,
                evidence_type="device_error",
                source_observation_ids=(obs_id,),
                source_raw_ids=(raw_id,),
                summary="persisted evidence summary",
                completeness="complete",
            ),
        )
        raw = (
            RawDiagnosticSnapshot(
                source_id=raw_id,
                category="btrfs_error",
                payload={"source_query": "btrfs_error"},
                provenance={
                    "command": "btrfs filesystem show /",
                    "execution_status": "ok" if authoritative else "FAILED_EXECUTION",
                },
            ),
        )
        findings = (finding,)
    return SystemSnapshot(
        metadata=_metadata(),
        observations=observations,
        evidence=evidence,
        raw_diagnostics=raw,
        findings=findings,
        restrictions=tuple(restrictions),
    )


def _persisted_finding(**overrides):
    values = {
        "finding_id": "BTRFS-ERR-001",
        "title": "Runtime Btrfs title",
        "severity": "P1",
        "confidence": "Certain",
        "actionability": Actionability.ACTIONABLE.value,
        "source_observation_ids": ("OBS-BTRFS",),
        "evidence_ids": ("EVID-BTRFS",),
    }
    values.update(overrides)
    return FindingSnapshot(**values)


def _step_for_command(command: str) -> ExplainStep:
    for definition in syscheck.FINDING_EXPLANATION_REGISTRY.values():
        for step in definition.investigation + definition.verification:
            if step.command == command:
                return step
    raise AssertionError(f"Command not found in registry: {command}")


def test_registry_matches_default_detector_inventory():
    assert validate_finding_explanation_registry() == ()


@pytest.mark.parametrize("pattern", EXPLAIN_PATTERNS)
def test_every_current_finding_family_has_bounded_metadata(pattern):
    definition = syscheck.FINDING_EXPLANATION_REGISTRY[pattern]

    assert definition.finding_id_pattern == pattern
    assert definition.summary
    assert definition.why_reported
    assert definition.possible_impact
    assert definition.severity in syscheck.VALID_SEVERITIES | {"RULE_DERIVED"}
    assert definition.confidence in syscheck.VALID_CONFIDENCES | {"RULE_DERIVED"}
    assert definition.actionability in {item.value for item in Actionability}
    assert definition.investigation
    assert definition.verification
    assert definition.sources
    assert all(step.instruction for step in definition.investigation)
    assert all(step.instruction for step in definition.verification)


@pytest.mark.parametrize(
    "pattern",
    [pattern for pattern in EXPLAIN_PATTERNS if not pattern.endswith("*")],
)
def test_static_explain_has_required_public_fields(pattern):
    explanation = explain_finding(pattern)
    payload = explanation.to_dict()

    assert isinstance(explanation, FindingExplanation)
    assert payload["finding_id"] == pattern
    assert payload["severity"] == "RULE_DERIVED"
    assert payload["confidence"] == "RULE_DERIVED"
    assert payload["present"] is None
    assert payload["source_status"] == "STATIC_DEFINITION"
    assert payload["investigation"]
    assert payload["verification"]


@pytest.mark.parametrize(
    ("finding_id", "pattern"),
    [
        ("STORAGE-USAGE-WARNING", "STORAGE-USAGE-WARNING*"),
        ("STORAGE-USAGE-WARNING-MOUNT-%2Fhome", "STORAGE-USAGE-WARNING*"),
        ("STORAGE-USAGE-CRITICAL-MOUNT-%2Fvar%2Flib", "STORAGE-USAGE-CRITICAL*"),
    ],
)
def test_dynamic_storage_ids_resolve_to_their_threshold_family(finding_id, pattern):
    assert find_finding_explanation_definition(finding_id).finding_id_pattern == pattern


@pytest.mark.parametrize("finding_id", ["", "   ", "NOT-A-FINDING-001"])
def test_unknown_or_empty_finding_id_is_controlled(finding_id):
    with pytest.raises(ValueError, match="Finding ID"):
        find_finding_explanation_definition(finding_id)


def test_static_explain_does_not_collect_or_run_the_engine(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("static explain must not collect diagnostics")

    monkeypatch.setattr(syscheck, "SysCheckEngine", fail)
    explanation = explain_finding("BTRFS-ERR-001")
    assert explanation.source_status == "STATIC_DEFINITION"


def test_snapshot_explain_uses_persisted_finding_and_lineage_only():
    snapshot = _snapshot(finding=_persisted_finding())

    explanation = explain_finding("BTRFS-ERR-001", snapshot=snapshot)
    payload = explanation.to_dict()

    assert payload["present"] is True
    assert payload["title"] == "Runtime Btrfs title"
    assert payload["severity"] == "P1"
    assert payload["confidence"] == "Certain"
    assert payload["source_status"] == "SNAPSHOT_LINEAGE"
    assert payload["source_observation_ids"] == ["OBS-BTRFS"]
    assert payload["evidence_ids"] == ["EVID-BTRFS"]
    assert payload["evidence"] == [
        {
            "evidence_id": "EVID-BTRFS",
            "evidence_type": "device_error",
            "summary": "persisted evidence summary",
            "source_observation_ids": ["OBS-BTRFS"],
            "source_raw_ids": ["RAW-BTRFS-ERR-001"],
            "completeness": "complete",
            "contradictory": False,
        }
    ]


def test_snapshot_explain_excludes_unlinked_evidence():
    snapshot = _snapshot(finding=_persisted_finding())
    unrelated = EvidenceSnapshot(
        evidence_id="EVID-UNRELATED",
        evidence_type="other",
        source_observation_ids=("OBS-OTHER",),
        source_raw_ids=("RAW-OTHER",),
        summary="must not cross the Finding lineage boundary",
    )
    unrelated_observation = ObservationSnapshot(
        obs_id="OBS-OTHER",
        category="other",
        source_raw_ids=("RAW-OTHER",),
    )
    unrelated_raw = RawDiagnosticSnapshot(
        source_id="RAW-OTHER",
        category="other",
        payload={"source_query": "other"},
        provenance={"command": "other", "execution_status": "ok"},
    )
    snapshot = SystemSnapshot(
        metadata=snapshot.metadata,
        observations=snapshot.observations + (unrelated_observation,),
        evidence=snapshot.evidence + (unrelated,),
        raw_diagnostics=snapshot.raw_diagnostics + (unrelated_raw,),
        findings=snapshot.findings,
    )

    explanation = explain_finding("BTRFS-ERR-001", snapshot=snapshot)

    assert explanation.evidence_ids == ("EVID-BTRFS",)
    assert tuple(item["evidence_id"] for item in explanation.evidence) == (
        "EVID-BTRFS",
    )


def test_snapshot_explain_missing_finding_is_truthful_and_nonfatal():
    explanation = explain_finding("BTRFS-ERR-001", snapshot=_snapshot())

    assert explanation.present is False
    assert explanation.source_status == "NOT_PRESENT_IN_SNAPSHOT"
    assert explanation.evidence == ()
    assert (
        explanation.runtime_status == "Finding is not present in the supplied snapshot."
    )


def test_snapshot_explain_source_limitation_downgrades_actionability():
    restriction = (
        "Source btrfs_error cannot establish an authoritative state "
        "(status=PERMISSION_DENIED, rc=-3)."
    )
    explanation = explain_finding(
        "BTRFS-ERR-001",
        snapshot=_snapshot(finding=_persisted_finding(), restrictions=(restriction,)),
    )

    assert explanation.actionability == "source_limited"
    assert explanation.source_status == "LIMITED"
    assert explanation.limitations == (restriction,)


def test_snapshot_explain_non_authoritative_lineage_is_limited():
    explanation = explain_finding(
        "BTRFS-ERR-001",
        snapshot=_snapshot(finding=_persisted_finding(), authoritative=False),
    )

    assert explanation.actionability == "source_limited"
    assert explanation.limitations == (
        "Current source 'RAW-BTRFS-ERR-001' is not authoritative",
    )


def test_snapshot_explain_normalizes_legacy_enum_actionability():
    explanation = explain_finding(
        "BTRFS-ERR-001",
        snapshot=_snapshot(
            finding=_persisted_finding(actionability="Actionability.ACTIONABLE")
        ),
    )

    assert explanation.actionability == "actionable"


def test_snapshot_explain_does_not_include_unrelated_restriction():
    unrelated = (
        "Source UPower power-source query cannot establish an authoritative state "
        "(status=PERMISSION_DENIED, rc=-3)."
    )
    explanation = explain_finding(
        "BTRFS-ERR-001",
        snapshot=_snapshot(finding=_persisted_finding(), restrictions=(unrelated,)),
    )

    assert explanation.limitations == ()
    assert explanation.actionability == "actionable"


def test_snapshot_explain_rejects_incompatible_snapshot():
    snapshot = _snapshot(finding=_persisted_finding())
    bad = SystemSnapshot(
        schema_version=snapshot.schema_version,
        metadata=SnapshotMetadata(
            hostname="host",
            kernel="kernel",
            distro="distro",
            syscheck_version="wrong",
            timestamp_utc="now",
            timestamp_local="now",
        ),
    )

    with pytest.raises(ValueError, match="compatibility"):
        explain_finding("BTRFS-ERR-001", snapshot=bad)


def test_json_format_contains_the_machine_contract():
    payload = json.loads(
        format_finding_explanation(explain_finding("BOOT-SLOW-001"), json_output=True)
    )

    assert {
        "finding_id",
        "summary",
        "severity",
        "confidence",
        "why_reported",
        "actionability",
        "investigation",
        "verification",
        "sources",
        "limitations",
        "evidence_ids",
        "source_status",
    } <= payload.keys()


def test_human_format_contains_required_sections():
    output = format_finding_explanation(explain_finding("KERNEL-OOM-001"))

    for section in (
        "Finding:",
        "Summary:",
        "Severity:",
        "Confidence:",
        "Why LDE reports it",
        "Possible impact",
        "Investigate",
        "Verify",
        "Sources",
        "Limitations",
    ):
        assert section in output


def test_explain_cli_static_json(monkeypatch, capsys):
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "explain", "KERNEL-OOM-001", "--json"],
    )

    syscheck.main()
    payload = json.loads(capsys.readouterr().out)

    assert payload["finding_id"] == "KERNEL-OOM-001"
    assert payload["source_status"] == "STATIC_DEFINITION"


def test_explain_cli_snapshot_json(tmp_path, monkeypatch, capsys):
    snapshot_path = tmp_path / "snapshot.json"
    _snapshot(finding=_persisted_finding()).to_json(str(snapshot_path))
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        [
            "lde",
            "explain",
            "BTRFS-ERR-001",
            "--snapshot",
            str(snapshot_path),
            "--json",
        ],
    )

    syscheck.main()
    payload = json.loads(capsys.readouterr().out)

    assert payload["present"] is True
    assert payload["source_status"] == "SNAPSHOT_LINEAGE"
    assert payload["evidence_ids"] == ["EVID-BTRFS"]


def test_nested_snapshot_compare_forwards_to_generic_compare(
    tmp_path, monkeypatch, capsys
):
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    _snapshot().to_json(str(old_path))
    _snapshot().to_json(str(new_path))
    monkeypatch.setattr(
        syscheck.sys,
        "argv",
        ["lde", "snapshot", "compare", str(old_path), str(new_path)],
    )

    syscheck.main()

    assert "No significant changes detected." in capsys.readouterr().out


def test_direct_script_snapshot_keeps_canonical_classification_values(tmp_path):
    snapshot_path = tmp_path / "direct-script.json"
    result = subprocess.run(
        [
            sys.executable,
            "syscheck.py",
            "run",
            "--output-dir",
            str(tmp_path / "reports"),
            "--snapshot",
            str(snapshot_path),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    valid_actionability = {item.value for item in Actionability}
    assert all(
        finding["actionability"] in valid_actionability for finding in data["findings"]
    )


@pytest.mark.parametrize("command", DIRECT_COMMANDS)
def test_representative_registry_commands_execute_exactly_with_read_only_stubs(
    tmp_path, command
):
    executable = shlex.split(command)[0]
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / executable
    stub.write_text("#!/bin/sh\nprintf 'stub output\\n'\n", encoding="utf-8")
    stub.chmod(0o755)
    env = {"PATH": f"{stub_dir}:/usr/bin:/bin"}

    result = subprocess.run(
        ["bash", "-o", "pipefail", "-c", _step_for_command(command).command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_registry_commands_do_not_contain_mutation_markers():
    errors = validate_finding_explanation_registry()
    assert not [error for error in errors if "Mutation-like" in error]
