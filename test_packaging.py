"""Focused packaging contract tests for the flat-module LDE distribution."""

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent


def _manifest_text() -> str:
    return (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")


class TestPackagingContract:
    def test_manifest_declares_supported_project_and_empty_runtime_dependencies(self):
        manifest = _manifest_text()

        assert 'name = "linux-diagnostic-engine"' in manifest
        assert 'version = "0.5.0"' in manifest
        assert 'requires-python = ">=3.10"' in manifest
        assert "dependencies = []" in manifest

    def test_manifest_declares_mit_license_and_repository_contains_license(self):
        manifest = _manifest_text()

        assert 'license = "MIT"' in manifest
        assert 'license-files = ["LICENSE"]' in manifest
        assert (PROJECT_ROOT / "LICENSE").is_file()

    def test_manifest_uses_flat_modules_without_source_relocation(self):
        manifest = _manifest_text()
        modules = ["constants", "diagnostic_rules", "syscheck"]

        assert 'py-modules = ["constants", "diagnostic_rules", "syscheck"]' in manifest
        for module in modules:
            assert (PROJECT_ROOT / f"{module}.py").is_file()

    def test_manifest_exposes_canonical_lde_console_script(self):
        assert 'lde = "syscheck:main"' in _manifest_text()

    def test_direct_execution_guard_remains_available(self):
        source = (PROJECT_ROOT / "syscheck.py").read_text(encoding="utf-8")

        assert 'if __name__ == "__main__":' in source
        assert "main()" in source

    def test_installation_docs_cover_installed_and_direct_cli_paths(self):
        documentation = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        assert "uv build --wheel" in documentation
        assert "/linux_diagnostic_engine-0.5.0-py3-none-any.whl" in documentation
        assert "/tmp/lde-venv/bin/lde --version" in documentation
        assert "/tmp/lde-venv/bin/lde --help" in documentation
        assert "python3 syscheck.py --help" in documentation
        assert "./install.sh" in documentation
        assert "$XDG_DATA_HOME/lde/reports" in documentation

    def test_public_cli_version_and_help_use_current_identity(self):
        version = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "syscheck.py"), "--version"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        help_output = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "syscheck.py"), "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert version.returncode == 0
        assert version.stdout.strip() == "Linux Diagnostic Engine 0.5.0"
        assert version.stderr == ""
        assert help_output.returncode == 0
        assert "Linux Diagnostic Engine (LDE)" in help_output.stdout
        assert "syscheck —" not in help_output.stdout
        assert "read-only Linux system diagnostics" in help_output.stdout
        assert "tylko do odczytu" not in help_output.stdout

        run_help = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "syscheck.py"), "run", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert run_help.returncode == 0
        assert "--print-report" in run_help.stdout
        assert "--verbose" in run_help.stdout
        assert "Wycisz" not in run_help.stdout

    def test_public_and_legacy_compatibility_versions_are_explicit(self):
        import constants
        import syscheck

        assert constants.PRODUCT_VERSION == "0.5.0"
        assert constants.REPORT_COMPATIBILITY_VERSION == "2.1.0"
        assert syscheck.SNAPSHOT_SCHEMA_VERSION == 3

    def test_supported_installer_is_local_no_sudo_and_no_system_mutation(self):
        installer = PROJECT_ROOT / "install.sh"
        source = installer.read_text(encoding="utf-8")

        assert installer.is_file()
        assert installer.stat().st_mode & 0o111
        assert "uv tool install" in source
        assert 'mkdir -p "$reports_dir"' in source
        assert "XDG_DATA_HOME" in source
        assert "lde --version" in source
        assert "sudo" not in source
        assert "systemctl" not in source
        assert ".codex" not in source
        assert "git " not in source
