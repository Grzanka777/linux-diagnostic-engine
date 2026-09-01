"""Focused tests for the v0.6 Finding lifecycle and verification workflow."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import syscheck  # noqa: E402
from syscheck import (  # noqa: E402
    EnvironmentSnapshot,
    ExecutionSnapshot,
    FindingLifecycleComparator,
    FindingSnapshot,
    ObservationSnapshot,
    RawDiagnosticSnapshot,
    SnapshotComparison,
    SnapshotComparator,
    SnapshotMetadata,
    SystemSnapshot,
    compare_finding_lifecycle,
    format_verification_cli,
)


COMPATIBILITY = syscheck.REPORT_COMPATIBILITY_VERSION


def _metadata(*, timestamp: str = "2026-09-01T10:00:00+00:00", version=COMPATIBILITY):
    return SnapshotMetadata(
        hostname="test-host",
        kernel="6.18.0-test",
        distro="test-linux",
        syscheck_version=version,
        timestamp_utc=timestamp,
        timestamp_local=timestamp,
    )


def _finding(
    finding_id: str,
    *,
    query: str = "kernel_errors",
    evidence: str = "evidence",
    recommended_diagnostics: str = "diagnostic",
    source: bool = True,
):
    if not source:
        return FindingSnapshot(
            finding_id=finding_id,
            title=f"Title {finding_id}",
            severity="P2",
            confidence="Certain",
            evidence=evidence,
            recommended_diagnostics=recommended_diagnostics,
        )
    return FindingSnapshot(
        finding_id=finding_id,
        title=f"Title {finding_id}",
        severity="P2",
        confidence="Certain",
        evidence=evidence,
        recommended_diagnostics=recommended_diagnostics,
        source_observation_ids=(f"OBS-{finding_id}",),
    )


def _snapshot(
    findings=(),
    *,
    restrictions=(),
    timestamp="2026-09-01T10:00:00+00:00",
    raw_queries=None,
    source=True,
    version=COMPATIBILITY,
):
    findings = tuple(findings)
    raw_queries = raw_queries or {}
    observations = []
    raw_diagnostics = []
    for finding in findings:
        if not finding.source_observation_ids:
            continue
        observation_id = finding.source_observation_ids[0]
        query = raw_queries.get(finding.finding_id, "kernel_errors")
        raw_id = f"RAW-{finding.finding_id}"
        observations.append(
            ObservationSnapshot(
                obs_id=observation_id,
                category="kernel_event",
                source_raw_ids=(raw_id,),
            )
        )
        raw_diagnostics.append(
            RawDiagnosticSnapshot(
                source_id=raw_id,
                category="kernel_event",
                payload={"source_query": query},
                provenance={
                    "command": f"journalctl query {query}",
                    "execution_status": "ok",
                    "truncated": False,
                },
            )
        )
    return SystemSnapshot(
        metadata=_metadata(timestamp=timestamp, version=version),
        environment=EnvironmentSnapshot(),
        observations=tuple(observations),
        raw_diagnostics=tuple(raw_diagnostics),
        findings=findings,
        restrictions=tuple(restrictions),
        execution=ExecutionSnapshot(),
    )


def _write_snapshot(path: Path, snapshot: SystemSnapshot):
    snapshot.to_json(str(path))
    return path


class TestFindingLifecycleComparator:
    def test_simultaneous_new_persistent_and_resolved(self):
        baseline = _snapshot(
            [_finding("B-RESOLVED"), _finding("A-PERSISTENT")],
            raw_queries={"B-RESOLVED": "resolved_query"},
        )
        current = _snapshot(
            [_finding("A-PERSISTENT"), _finding("C-NEW")],
            raw_queries={"A-PERSISTENT": "persistent_query"},
        )

        result = compare_finding_lifecycle(baseline, current)

        assert result.new_finding_ids == ("C-NEW",)
        assert result.persistent_finding_ids == ("A-PERSISTENT",)
        assert result.resolved_finding_ids == ("B-RESOLVED",)
        assert result.unverified_finding_ids == ()

    def test_persistent_identity_ignores_evidence_text(self):
        baseline = _snapshot([_finding("F1", evidence="old evidence")])
        current = _snapshot([_finding("F1", evidence="new evidence")])

        result = FindingLifecycleComparator.compare(baseline, current)

        assert result.persistent_finding_ids == ("F1",)
        assert result.new_finding_ids == ()
        assert result.resolved_finding_ids == ()

    def test_persistent_identity_ignores_recommendation_text(self):
        baseline = _snapshot(
            [_finding("F1", recommended_diagnostics="old recommendation")]
        )
        current = _snapshot(
            [_finding("F1", recommended_diagnostics="new recommendation")]
        )

        result = FindingLifecycleComparator.compare(baseline, current)

        assert result.persistent_finding_ids == ("F1",)

    @pytest.mark.parametrize(
        ("baseline_timestamp", "current_timestamp"),
        [
            ("2026-09-01T10:00:00+00:00", "2026-09-01T10:01:00+00:00"),
            ("old-local", "new-local"),
            ("", "2026-09-01T10:01:00+00:00"),
        ],
    )
    def test_persistent_identity_ignores_volatile_timestamps(
        self, baseline_timestamp, current_timestamp
    ):
        baseline = _snapshot([_finding("F1")], timestamp=baseline_timestamp)
        current = _snapshot([_finding("F1")], timestamp=current_timestamp)

        assert compare_finding_lifecycle(baseline, current).persistent_finding_ids == (
            "F1",
        )

    @pytest.mark.parametrize(
        "order",
        [
            ["F3", "F1", "F2"],
            ["F2", "F3", "F1"],
            ["F1", "F2", "F3"],
        ],
    )
    def test_lifecycle_order_is_sorted_independently_of_snapshot_order(self, order):
        baseline = _snapshot([_finding(finding_id) for finding_id in order])
        current = _snapshot([_finding(finding_id) for finding_id in reversed(order)])

        result = compare_finding_lifecycle(baseline, current)

        assert result.persistent_finding_ids == ("F1", "F2", "F3")

    def test_empty_baseline_reports_all_current_findings_as_new(self):
        result = compare_finding_lifecycle(
            _snapshot([]), _snapshot([_finding("F2"), _finding("F1")])
        )

        assert result.new_finding_ids == ("F1", "F2")
        assert result.resolved_finding_ids == ()

    def test_empty_current_with_authoritative_snapshot_reports_resolved(self):
        result = compare_finding_lifecycle(_snapshot([_finding("F1")]), _snapshot([]))

        assert result.resolved_finding_ids == ("F1",)
        assert result.unverified_finding_ids == ()

    @pytest.mark.parametrize(
        "restriction",
        [
            "Source current-boot journal query kernel_errors cannot establish an authoritative state (status=FAILED_EXECUTION, rc=1).",
            "Source current-boot journal query kernel_errors cannot establish an authoritative state (status=TIMEOUT, rc=-2).",
            "Source current-boot journal query kernel_errors cannot establish an authoritative state (status=PERMISSION_DENIED, rc=-3).",
            "Source current-boot query kernel_errors (status=TRUNCATED_OUTPUT); absence of matching data is not authoritative.",
            "Source current-boot journal query kernel_errors returned non-authoritative output (status=MALFORMED_OUTPUT).",
            "Source current-boot journal query kernel_errors unavailable; state is unknown.",
        ],
    )
    def test_relevant_source_limitation_prevents_false_resolution(self, restriction):
        baseline = _snapshot([_finding("F1")], raw_queries={"F1": "kernel_errors"})
        current = _snapshot([], restrictions=(restriction,))

        result = compare_finding_lifecycle(baseline, current)

        assert result.resolved_finding_ids == ()
        assert result.unverified_finding_ids == ("F1",)
        assert restriction in result.source_limitations

    def test_unrelated_source_limitation_does_not_block_resolution(self):
        baseline = _snapshot([_finding("F1")], raw_queries={"F1": "kernel_errors"})
        current = _snapshot(
            [],
            restrictions=(
                "Source UPower power-source query cannot establish an authoritative state (status=PERMISSION_DENIED, rc=-3).",
            ),
        )

        result = compare_finding_lifecycle(baseline, current)

        assert result.resolved_finding_ids == ("F1",)
        assert result.unverified_finding_ids == ()

    @pytest.mark.parametrize(
        "raw_provenance",
        [
            {"execution_status": "timeout", "truncated": False},
            {"execution_status": "permission_denied", "truncated": False},
            {"execution_status": "ok", "truncated": True},
        ],
    )
    def test_non_authoritative_current_raw_prevents_resolution(self, raw_provenance):
        baseline = _snapshot([_finding("F1")])
        current = _snapshot([])
        current = SystemSnapshot(
            metadata=current.metadata,
            observations=current.observations,
            raw_diagnostics=(
                RawDiagnosticSnapshot(
                    source_id="RAW-F1",
                    category="kernel_event",
                    payload={"source_query": "kernel_errors"},
                    provenance=raw_provenance,
                ),
            ),
            findings=(),
            execution=current.execution,
        )

        result = compare_finding_lifecycle(baseline, current)

        assert result.unverified_finding_ids == ("F1",)
        assert result.resolved_finding_ids == ()

    def test_missing_baseline_lineage_is_unverified_not_resolved(self):
        baseline = _snapshot([_finding("F1", source=False)])

        result = compare_finding_lifecycle(baseline, _snapshot([]))

        assert result.unverified_finding_ids == ("F1",)
        assert result.resolved_finding_ids == ()
        assert any(
            "no persisted source lineage" in reason
            for reason in result.source_limitations
        )

    def test_missing_raw_lineage_is_unverified_not_resolved(self):
        baseline = SystemSnapshot(
            metadata=_metadata(),
            observations=(
                ObservationSnapshot(
                    obs_id="OBS-F1",
                    category="kernel_event",
                    source_raw_ids=("MISSING",),
                ),
            ),
            findings=(_finding("F1"),),
        )

        result = compare_finding_lifecycle(baseline, _snapshot([]))

        assert result.unverified_finding_ids == ("F1",)
        assert "missing raw diagnostic" in result.source_limitations[0]

    def test_duplicate_finding_ids_are_rejected_before_comparison(self):
        baseline = _snapshot([_finding("F1"), _finding("F1")])

        with pytest.raises(ValueError, match="Duplicate finding IDs"):
            compare_finding_lifecycle(baseline, _snapshot([]))

    @pytest.mark.parametrize("bad_schema", [2, 4, "3"])
    def test_incompatible_schema_is_rejected(self, bad_schema):
        baseline = _snapshot([_finding("F1")])
        current = _snapshot([])
        current = SystemSnapshot(
            schema_version=bad_schema,
            metadata=current.metadata,
            findings=current.findings,
        )

        with pytest.raises(syscheck.UnsupportedSnapshotSchemaError):
            compare_finding_lifecycle(baseline, current)

    def test_incompatible_report_compatibility_is_rejected(self):
        baseline = _snapshot([_finding("F1")], version="1.0.0")

        with pytest.raises(ValueError, match="compatibility"):
            compare_finding_lifecycle(baseline, _snapshot([]))

    def test_result_exposes_snapshot_identities_and_json_fields(self):
        result = compare_finding_lifecycle(_snapshot([_finding("F1")]), _snapshot([]))

        payload = result.to_dict()

        assert payload["baseline_identity"]["hostname"] == "test-host"
        assert payload["current_identity"]["schema_version"] == 3
        assert payload["resolved_finding_ids"] == ["F1"]
        assert set(payload) == {
            "baseline_identity",
            "current_identity",
            "new_finding_ids",
            "persistent_finding_ids",
            "resolved_finding_ids",
            "unverified_finding_ids",
            "source_limitations",
        }

    def test_comparison_does_not_mutate_baseline(self):
        baseline = _snapshot([_finding("F1")])
        before = baseline.to_dict()

        compare_finding_lifecycle(baseline, _snapshot([]))

        assert baseline.to_dict() == before

    def test_generic_snapshot_compare_keeps_structural_resolved_behavior(self):
        baseline = _snapshot([_finding("F1")])

        generic = SnapshotComparator.compare(baseline, _snapshot([]))

        assert generic.resolved_findings[0]["finding_id"] == "F1"
        assert isinstance(generic, SnapshotComparison)


class TestVerificationCli:
    @staticmethod
    def _patch_pipeline(monkeypatch, current_snapshot):
        monkeypatch.setattr(
            syscheck,
            "_run_cli_diagnostics",
            lambda **_kwargs: (object(), Path("/tmp/unused-report.md")),
        )
        monkeypatch.setattr(
            syscheck, "build_snapshot", lambda _engine: current_snapshot
        )

    def test_human_output_has_stable_sections_and_no_markdown(self):
        result = compare_finding_lifecycle(
            _snapshot([_finding("F-RESOLVED"), _finding("F-PERSISTENT")]),
            _snapshot([_finding("F-PERSISTENT"), _finding("F-NEW", source=False)]),
        )

        output = format_verification_cli(result)

        assert output == (
            "LDE Verification\n\n"
            "Resolved\n"
            "  F-RESOLVED\n\n"
            "Persistent\n"
            "  F-PERSISTENT\n\n"
            "New\n"
            "  F-NEW\n"
        )
        assert "#" not in output
        assert "Unverified" not in output

    def test_human_output_includes_unverified_only_when_needed(self):
        baseline = _snapshot([_finding("F1")], raw_queries={"F1": "kernel_errors"})
        current = _snapshot(
            [],
            restrictions=(
                "Source current-boot journal query kernel_errors unavailable; state is unknown.",
            ),
        )

        output = format_verification_cli(compare_finding_lifecycle(baseline, current))

        assert "Unverified\n  F1" in output

    def test_verify_cli_human_output_is_compact_and_read_only(
        self, monkeypatch, tmp_path, capsys
    ):
        baseline_path = _write_snapshot(
            tmp_path / "baseline.json", _snapshot([_finding("F1")])
        )
        current = _snapshot([_finding("F1"), _finding("F2", source=False)])
        self._patch_pipeline(monkeypatch, current)
        monkeypatch.setattr(
            syscheck.sys,
            "argv",
            ["lde", "verify", str(baseline_path), "--output-dir", str(tmp_path)],
        )
        before = baseline_path.read_bytes()

        syscheck.main()

        captured = capsys.readouterr()
        assert captured.err == ""
        assert "LDE Verification" in captured.out
        assert "Persistent\n  F1" in captured.out
        assert "New\n  F2" in captured.out
        assert "#" not in captured.out
        assert baseline_path.read_bytes() == before

    def test_verify_cli_json_exposes_lifecycle_and_source_limitations(
        self, monkeypatch, tmp_path, capsys
    ):
        baseline_path = _write_snapshot(
            tmp_path / "baseline.json", _snapshot([_finding("F1")])
        )
        current = _snapshot(
            [],
            restrictions=(
                "Source current-boot journal query kernel_errors unavailable; state is unknown.",
            ),
        )
        self._patch_pipeline(monkeypatch, current)
        monkeypatch.setattr(
            syscheck.sys,
            "argv",
            ["lde", "verify", str(baseline_path), "--json"],
        )

        syscheck.main()

        payload = json.loads(capsys.readouterr().out)
        assert payload["unverified_finding_ids"] == ["F1"]
        assert payload["resolved_finding_ids"] == []
        assert payload["baseline_identity"]["schema_version"] == 3
        assert payload["source_limitations"]

    @pytest.mark.parametrize(
        ("argv_tail", "needle"),
        [
            (["/missing-baseline.json"], "Baseline snapshot not found"),
            (["/missing-baseline.json", "--json"], "Baseline snapshot not found"),
        ],
    )
    def test_verify_missing_baseline_is_controlled_cli_error(
        self, monkeypatch, capsys, argv_tail, needle
    ):
        monkeypatch.setattr(syscheck.sys, "argv", ["lde", "verify", *argv_tail])

        with pytest.raises(SystemExit) as exc_info:
            syscheck.main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert needle in captured.err
        assert "Traceback" not in captured.err

    @pytest.mark.parametrize(
        "payload",
        [
            "{not-json\n",
            "[]\n",
            json.dumps({"schema_version": 999}),
            json.dumps(
                {
                    "schema_version": 3,
                    "metadata": {
                        "hostname": "h",
                        "kernel": "k",
                        "syscheck_version": "1.0.0",
                    },
                }
            ),
        ],
    )
    def test_verify_malformed_or_incompatible_baseline_is_controlled_error(
        self, monkeypatch, tmp_path, capsys, payload
    ):
        baseline_path = tmp_path / "invalid.json"
        baseline_path.write_text(payload, encoding="utf-8")
        monkeypatch.setattr(syscheck.sys, "argv", ["lde", "verify", str(baseline_path)])

        with pytest.raises(SystemExit) as exc_info:
            syscheck.main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert "Invalid baseline snapshot" in captured.err
        assert "Traceback" not in captured.err

    def test_verify_output_is_identical_with_no_color_environment(
        self, monkeypatch, tmp_path, capsys
    ):
        baseline_path = _write_snapshot(tmp_path / "baseline.json", _snapshot([]))
        current = _snapshot([_finding("F1", source=False)])
        self._patch_pipeline(monkeypatch, current)
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr(
            syscheck.sys,
            "argv",
            ["lde", "verify", str(baseline_path)],
        )

        syscheck.main()

        output = capsys.readouterr().out
        assert "\033[" not in output
        assert "New\n  F1" in output

    def test_snapshot_create_writes_explicit_new_baseline(
        self, monkeypatch, tmp_path, capsys
    ):
        current = _snapshot([_finding("F1")])
        self._patch_pipeline(monkeypatch, current)
        output_path = tmp_path / "baseline.json"
        monkeypatch.setattr(
            syscheck.sys,
            "argv",
            [
                "lde",
                "snapshot",
                "create",
                "--output",
                str(output_path),
                "--quiet",
            ],
        )

        syscheck.main()

        assert SystemSnapshot.from_json(output_path).findings[0].finding_id == "F1"
        assert f"Snapshot saved to: {output_path.resolve()}" in capsys.readouterr().out

    def test_snapshot_create_does_not_overwrite_existing_baseline(
        self, monkeypatch, tmp_path, capsys
    ):
        current = _snapshot([])
        self._patch_pipeline(monkeypatch, current)
        output_path = tmp_path / "baseline.json"
        output_path.write_text("keep\n", encoding="utf-8")
        monkeypatch.setattr(
            syscheck.sys,
            "argv",
            ["lde", "snapshot", "create", "--output", str(output_path)],
        )

        with pytest.raises(SystemExit) as exc_info:
            syscheck.main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert output_path.read_text(encoding="utf-8") == "keep\n"
        assert "Destination" in captured.err
