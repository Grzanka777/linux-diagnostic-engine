"""Focused packaging contract tests for the flat-module LDE distribution."""

from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parent


def _project_metadata() -> dict:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as manifest:
        return tomllib.load(manifest)


class TestPackagingContract:
    def test_manifest_declares_supported_project_and_empty_runtime_dependencies(self):
        project = _project_metadata()["project"]

        assert project["name"] == "linux-diagnostic-engine"
        assert project["version"] == "0.1.0"
        assert project["requires-python"] == ">=3.10"
        assert project["dependencies"] == []

    def test_manifest_uses_flat_modules_without_source_relocation(self):
        setuptools = _project_metadata()["tool"]["setuptools"]

        assert setuptools["py-modules"] == [
            "constants",
            "diagnostic_rules",
            "syscheck",
        ]
        for module in setuptools["py-modules"]:
            assert (PROJECT_ROOT / f"{module}.py").is_file()

    def test_manifest_exposes_canonical_lde_console_script(self):
        scripts = _project_metadata()["project"]["scripts"]

        assert scripts == {"lde": "syscheck:main"}

    def test_direct_execution_guard_remains_available(self):
        source = (PROJECT_ROOT / "syscheck.py").read_text(encoding="utf-8")

        assert 'if __name__ == "__main__":' in source
        assert "main()" in source

    def test_installation_docs_cover_installed_and_direct_cli_paths(self):
        documentation = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        assert "uv build --wheel" in documentation
        assert "/linux_diagnostic_engine-0.1.0-py3-none-any.whl" in documentation
        assert "/tmp/lde-venv/bin/lde --help" in documentation
        assert "python3 syscheck.py --help" in documentation
