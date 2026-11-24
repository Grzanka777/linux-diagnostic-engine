"""Synthetic and captured, privacy-safe portability regression coverage."""

import json
import shutil
from pathlib import Path

import pytest

import syscheck
from constants import DISTRO_CONFIG
from syscheck import CmdResult, SysCheckEngine

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "lde_v0_7_multi_distro_portability.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _result(
    command: str,
    *,
    stdout: str = "",
    stderr: str = "",
    return_code: int = 0,
    status: str = "ok",
    truncated: bool = False,
) -> CmdResult:
    return CmdResult(
        command=command,
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        execution_status=status,
        truncated=truncated,
    )


def test_portability_fixture_declares_evidence_scope_for_each_family():
    records = FIXTURE["records"]
    assert {record["family"] for record in records} == {
        "arch",
        "fedora",
        "debian_ubuntu",
    }
    assert {record["evidence_type"] for record in records} == {
        "REAL_MACHINE",
        "CONTAINER",
    }
    assert all(record["proves"] and record["cannot_prove"] for record in records)
    assert FIXTURE["privacy"] == {
        "raw_real_reports_included": False,
        "host_personal_identifiers_included": False,
        "environment_values_limited_to_statuses_and_counts": True,
    }


@pytest.mark.parametrize(
    ("case", "profile"),
    [(case, case["profile"]) for case in FIXTURE["distro_detection_cases"]],
)
def test_os_release_selects_only_known_package_families(case, profile):
    os_release = f'ID="{case["id"]}"\nID_LIKE="{case["id_like"]}"\n'
    os_info = syscheck._parse_os_release(os_release)
    assert syscheck._distro_profile_from_os_release(os_info) == (
        case["id"],
        profile,
    )


def test_os_release_parser_handles_quoted_values_without_shell_evaluation():
    parsed = syscheck._parse_os_release(
        'NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n'
    )
    assert parsed == {
        "NAME": "CachyOS Linux",
        "ID": "cachyos",
        "ID_LIKE": "arch",
    }
    assert syscheck._parse_os_release('ID="unterminated\n') is None
    assert syscheck._distro_profile_from_os_release(None) == ("unknown", "generic")
    assert syscheck._distro_profile_from_os_release({}) == ("unknown", "generic")
    assert syscheck._distro_profile_from_os_release(
        {"ID": "$(touch /tmp/lde-os-release-must-not-run)"}
    ) == ("$(touch /tmp/lde-os-release-must-not-run)", "generic")


@pytest.mark.parametrize(
    ("result", "expected_id", "expected_profile"),
    [
        (
            _result("cat os-release", stdout="ID=cachyos\nID_LIKE=arch"),
            "cachyos",
            "arch",
        ),
        (
            _result("cat os-release", stdout="ID=some-new-distro"),
            "some-new-distro",
            "generic",
        ),
        (
            _result("cat os-release", status="not_found", return_code=-1),
            "unknown",
            "generic",
        ),
        (
            _result(
                "cat os-release",
                stdout='ID="bad',
            ),
            "unknown",
            "generic",
        ),
    ],
)
def test_detect_distro_degrades_to_generic_for_unknown_or_unusable_release(
    tmp_path, monkeypatch, result, expected_id, expected_profile
):
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    monkeypatch.setattr(engine, "cmd", lambda *args, **kwargs: result)
    engine.detect_distro()
    assert engine.distro_id == expected_id
    assert engine.distro_config is DISTRO_CONFIG[expected_profile]
    if expected_profile == "generic":
        assert engine.restrictions


def test_package_commands_are_native_and_unsupported_classifications_stay_unknown():
    assert DISTRO_CONFIG["arch"]["pkg_query_installed"] == ["pacman", "-Q"]
    assert DISTRO_CONFIG["debian"]["pkg_query_installed"][0] == "dpkg-query"
    assert DISTRO_CONFIG["debian"]["pkg_query_kernels"][-1] == "linux-image-*"
    assert DISTRO_CONFIG["rhel"]["pkg_query_installed"][:3] == [
        "rpm",
        "-qa",
        "--qf",
    ]
    for profile in ("debian", "rhel", "generic"):
        assert DISTRO_CONFIG[profile]["pkg_list_orphans"] is None
        assert DISTRO_CONFIG[profile]["pkg_list_foreign"] is None
    for key in (
        "pkg_list_orphans",
        "pkg_list_foreign",
        "pkg_query_installed",
        "pkg_query_kernels",
    ):
        assert DISTRO_CONFIG["generic"][key] is None


def test_installed_package_counter_uses_provider_status_and_machine_rows():
    debian_rows = (
        "ii \tlinux-image-6.12.0-1-amd64\t6.12.12-1\n"
        "rc \told-package\t1.0\n"
        "iH \thalf-package\t2.0\n"
    )
    assert syscheck._count_installed_packages(debian_rows, "debian") == 1
    assert (
        syscheck._count_installed_packages("kernel-core\nlinux-firmware\n", "rhel") == 2
    )
    assert syscheck._count_installed_packages("", "arch") == 0


def test_kernel_package_parser_normalizes_arch_fedora_and_debian_formats():
    arch = """linux-cachyos 6.15.1-1
linux-lts 6.12.4-1
linux-headers 6.15.1-1
linux-firmware 2025.01-1
bash 5.2.0-1"""
    assert syscheck._count_kernel_packages(arch) == (
        2,
        4,
        ["linux-cachyos 6.15.1-1", "linux-lts 6.12.4-1"],
    )

    fedora = """kernel-core-6.15.1-300.fc44.x86_64
kernel-modules-6.15.1-300.fc44.x86_64
kernel-modules-extra-6.15.1-300.fc44.x86_64"""
    assert syscheck._count_kernel_packages(fedora) == (
        1,
        3,
        ["kernel-core-6.15.1-300.fc44.x86_64"],
    )

    debian = (
        "ii \tlinux-image-6.12.0-1-amd64\t6.12.12-1\n"
        "ii \tlinux-image-amd64\t6.12.12-1\n"
        "rc \tlinux-image-6.1.0-old-amd64\t6.1.0-1\n"
    )
    assert syscheck._count_kernel_packages(debian) == (
        1,
        2,
        ["linux-image-6.12.0-1-amd64 6.12.12-1"],
    )


def test_module_roots_union_versions_and_deduplicate_merged_usr_alias(tmp_path):
    canonical = tmp_path / "usr" / "lib" / "modules"
    canonical.mkdir(parents=True)
    (canonical / "6.15.1-arch").mkdir()
    (canonical / "6.12.4-lts").mkdir()
    alias = tmp_path / "lib" / "modules"
    alias.parent.mkdir()
    alias.symlink_to(canonical, target_is_directory=True)

    assert syscheck._get_bootable_kernels_from_module_roots((canonical, alias)) == [
        "6.12.4-lts",
        "6.15.1-arch",
    ]
    assert (
        syscheck._get_bootable_kernels_from_module_roots(
            (tmp_path / "missing-a", tmp_path / "missing-b")
        )
        is None
    )


def test_module_inventory_unreadable_root_remains_unknown(tmp_path, monkeypatch):
    modules = tmp_path / "modules"
    modules.mkdir()

    def denied(self):
        raise PermissionError("protected module directory")

    monkeypatch.setattr(Path, "iterdir", denied)
    assert syscheck._get_bootable_kernels_from_module_roots((modules,)) is None


def test_boot_efi_sources_keep_visible_counts_separate_from_unknown_paths(tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "vmlinuz-6.15.1").touch()
    (boot / "initramfs-6.15.1.img").touch()

    boot_efi = tmp_path / "boot-efi"
    (boot_efi / "EFI" / "Linux").mkdir(parents=True)
    (boot_efi / "EFI" / "Linux" / "synthetic-linux.efi").touch()

    efi = tmp_path / "efi"
    (efi / "EFI" / "BOOT").mkdir(parents=True)
    (efi / "EFI" / "BOOT" / "BOOTX64.EFI").touch()

    boot_inventory, boot_efi_inventory, efi_inventory = syscheck._inspect_boot_sources(
        boot_dir=boot,
        boot_efi_dir=boot_efi,
        efi_dir=efi,
    )
    assert boot_inventory.status == "available"
    assert boot_inventory.kernel_images == ("vmlinuz-6.15.1",)
    assert boot_inventory.initramfs_images == ("initramfs-6.15.1.img",)
    assert syscheck._get_bootable_kernels_from_boot(boot) == ["6.15.1"]
    assert boot_efi_inventory.efi_artifacts == ("synthetic-linux.efi",)
    assert boot_efi_inventory.unified_kernel_images == ("synthetic-linux.efi",)
    assert efi_inventory.efi_artifacts == ("BOOTX64.EFI",)


def test_boot_kernel_counter_accepts_image_and_bzimage_names(tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "Image").touch()
    (boot / "bzImage-6.12.4").touch()
    assert syscheck._get_bootable_kernels_from_boot(boot) == [
        "Image",
        "bzImage-6.12.4",
    ]


def test_readable_empty_boot_is_zero_within_source_but_missing_source_is_unknown(
    tmp_path,
):
    empty = tmp_path / "visible-empty-boot"
    empty.mkdir()
    empty_inventory = syscheck._inspect_boot_source(empty, label="/boot")
    missing_inventory = syscheck._inspect_boot_source(
        tmp_path / "not-visible", label="/efi"
    )
    assert empty_inventory.status == "available"
    assert empty_inventory.kernel_images == ()
    assert missing_inventory.status == "unavailable"
    assert missing_inventory.kernel_images == ()
    assert "unknown" in missing_inventory.limitation


def test_protected_boot_directory_is_unavailable_not_zero(tmp_path, monkeypatch):
    boot = tmp_path / "boot"
    boot.mkdir()

    def denied(self):
        raise PermissionError("protected boot")

    monkeypatch.setattr(Path, "iterdir", denied)
    inventory = syscheck._inspect_boot_source(boot, label="/boot")
    assert inventory.status == "unavailable"
    assert syscheck._get_bootable_kernels_from_boot(boot) is None


def test_unreadable_nested_efi_directory_makes_boot_inventory_partial(
    tmp_path, monkeypatch
):
    boot = tmp_path / "boot"
    linux_efi = boot / "EFI" / "Linux"
    linux_efi.mkdir(parents=True)
    (boot / "vmlinuz-6.15.1").touch()
    (linux_efi / "synthetic.efi").touch()
    original_iterdir = Path.iterdir

    def deny_linux_efi(self):
        if self == linux_efi:
            raise PermissionError("protected EFI directory")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", deny_linux_efi)
    inventory = syscheck._inspect_boot_source(boot, label="/boot")
    assert inventory.status == "partial"
    assert inventory.kernel_images == ("vmlinuz-6.15.1",)
    assert syscheck._get_bootable_kernels_from_boot(boot) is None


@pytest.mark.parametrize(
    ("vendor_id", "device_id"),
    [("1002", "f00d"), ("8086", "beef"), ("10de", "d00d")],
)
def test_gpu_vendor_identity_fallback_keeps_exact_bdf_and_provenance(
    vendor_id, device_id
):
    drm = "card0\t0000:01:00.0\tunknown\tunknown\n"
    lspci = (
        "0000:01:00.0 VGA compatible controller [0300]: "
        f"Synthetic adapter [{vendor_id}:{device_id}]\n"
    )
    record = syscheck._reconcile_gpu_inventory(drm, lspci)[0]
    assert record.pci_address == "0000:01:00.0"
    assert record.vendor_id == vendor_id
    assert record.device_id == device_id
    assert record.vendor_source == "lspci -nnk"
    assert record.device_source == "lspci -nnk"


@pytest.mark.parametrize(
    ("first_vendor", "second_vendor"),
    [("1002", "10de"), ("8086", "10de"), ("1002", "1002")],
)
def test_gpu_hybrid_and_same_vendor_devices_match_by_bdf(first_vendor, second_vendor):
    drm = (
        "card0\t0000:01:00.0\tunknown\tunknown\ncard1\t0000:02:00.0\tunknown\tunknown\n"
    )
    lspci = (
        "0000:01:00.0 VGA compatible controller [0300]: "
        f"First [{first_vendor}:f001]\n"
        "0000:02:00.0 3D controller [0302]: "
        f"Second [{second_vendor}:f002]\n"
    )
    records = syscheck._reconcile_gpu_inventory(drm, lspci)
    assert [(record.vendor_id, record.device_id) for record in records] == [
        (first_vendor, "f001"),
        (second_vendor, "f002"),
    ]
    assert all(record.reconciliation_status == "lspci_fallback" for record in records)


def test_non_display_pci_device_cannot_fill_gpu_identity():
    record = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\tunknown\tunknown\n",
        "0000:01:00.0 Ethernet controller [0200]: Synthetic network device "
        "[1002:f00d]\n",
    )[0]
    assert record.vendor_id is None
    assert record.device_id is None
    assert record.reconciliation_status == "unknown"


def test_gpu_display_class_uses_locale_stable_pci_class_code():
    record = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\tunknown\tunknown\n",
        "0000:01:00.0 Adaptador de visualización [0300]: "
        "Synthetic adapter [1002:f00d]\n",
    )[0]
    assert record.vendor_id == "1002"
    assert record.device_id == "f00d"
    assert record.reconciliation_status == "lspci_fallback"


def test_gpu_contradiction_and_missing_lspci_preserve_unknown_or_conflict():
    drm = "card0\t0000:01:00.0\t0x1002\t0xf00d\n"
    lspci = (
        "0000:01:00.0 VGA compatible controller [0300]: Synthetic adapter [10de:d00d]\n"
    )
    conflict = syscheck._reconcile_gpu_inventory(drm, lspci)[0]
    unavailable = syscheck._reconcile_gpu_inventory(
        "card0\t0000:01:00.0\t0x1002\tunknown\n",
        "",
        lspci_available=False,
    )[0]
    assert conflict.reconciliation_status == "conflict"
    assert conflict.vendor_id == "1002"
    assert unavailable.device_id is None
    assert unavailable.reconciliation_status == "unknown"


@pytest.mark.parametrize(
    "tool",
    ["lspci", "btrfs", "nvme", "sensors", "upower", "resolvectl", "systemd-analyze"],
)
def test_optional_command_missing_records_degraded_source_not_health(tmp_path, tool):
    result = syscheck.run_cmd([tool], env={"PATH": str(tmp_path)})
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine._record_source_status(result, f"optional tool {tool}")
    assert result.execution_status == "not_found"
    assert result.return_code == -1
    assert "COMMAND_NOT_FOUND" in " ".join(engine.restrictions)
    assert engine.findings == []


def test_journal_pipeline_missing_bash_or_grep_is_failure_not_empty_evidence(
    tmp_path,
):
    command = syscheck._journal_filter_command(
        "printf 'Synthetic event\\n'",
        ["Synthetic event"],
    )
    no_tools = syscheck.run_cmd(command, env={"PATH": str(tmp_path)})
    assert no_tools.execution_status == "not_found"
    assert no_tools.return_code == -1

    bash_path = shutil.which("bash")
    assert bash_path is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "bash").symlink_to(bash_path)
    missing_grep = syscheck.run_cmd(command, env={"PATH": str(bin_dir)})
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine._record_source_status(missing_grep, "journal filter pipeline")
    assert missing_grep.execution_status == "error"
    assert missing_grep.return_code == 127
    assert "FAILED_EXECUTION" in " ".join(engine.restrictions)
    assert engine.findings == []


def test_generic_package_collection_runs_no_manager_and_never_claims_zero(
    tmp_path, monkeypatch
):
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine.distro_config = DISTRO_CONFIG["generic"]
    monkeypatch.setattr(
        engine,
        "_parallel_cmd",
        lambda tasks: pytest.fail(
            f"generic profile unexpectedly ran commands: {tasks}"
        ),
    )
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_module_roots", list)
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_boot", list)

    engine.collect_packages()
    rendered = "".join(engine.report_lines)
    assert "installed package count is unknown" in rendered
    assert "Kernel package inventory provider is not configured" in rendered
    assert "Bootable kernel package records:** 0" not in rendered
    assert "not reported as empty" in " ".join(engine.restrictions)


def test_boot_and_module_evidence_survive_kernel_package_query_failure(
    tmp_path, monkeypatch
):
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine.distro_config = DISTRO_CONFIG["rhel"]
    engine.distro_id = "fedora"

    def package_results(tasks):
        assert set(tasks) == {"installed", "kernels"}
        return {
            "installed": _result("rpm -qa", stdout="bash\n"),
            "kernels": _result(
                "rpm -qa kernel*",
                stdout="",
                stderr="rpm database unavailable",
                return_code=1,
                status="error",
            ),
        }

    monkeypatch.setattr(engine, "_parallel_cmd", package_results)
    monkeypatch.setattr(
        syscheck, "_get_bootable_kernels_from_module_roots", lambda: ["6.15.1"]
    )
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_boot", lambda: ["6.15.1"])
    engine.collect_packages()
    rendered = "".join(engine.report_lines)
    assert "Visible module-tree versions:** 1" in rendered
    assert "Visible /boot kernel images:** 1" in rendered
    assert "rpm database unavailable" in rendered
    assert "Bootable kernel package records:** 0" not in rendered
    assert any(
        "kernel package query" in restriction for restriction in engine.restrictions
    )


def test_debian_kernel_query_no_match_is_not_treated_as_zero(tmp_path, monkeypatch):
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine.distro_config = DISTRO_CONFIG["debian"]
    engine.distro_id = "debian"

    def package_results(tasks):
        assert set(tasks) == {"installed", "kernels"}
        return {
            "installed": _result(
                "dpkg-query -W",
                stdout="ii \tbase-files\t13.8\n",
            ),
            "kernels": _result(
                "dpkg-query -W linux-image-*",
                stderr="dpkg-query: no packages found matching linux-image-*",
                return_code=1,
                status="error",
            ),
        }

    monkeypatch.setattr(engine, "_parallel_cmd", package_results)
    monkeypatch.setattr(
        syscheck, "_get_bootable_kernels_from_module_roots", lambda: None
    )
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_boot", lambda: None)
    engine.collect_packages()
    rendered = "".join(engine.report_lines)
    assert "dpkg-query: no packages found matching linux-image-*" in rendered
    assert "Bootable kernel package records:** 0" not in rendered
    assert any(
        "kernel package query" in restriction for restriction in engine.restrictions
    )


def test_fedora_successful_empty_kernel_query_is_scoped_zero(tmp_path, monkeypatch):
    engine = SysCheckEngine(output_dir=str(tmp_path), quiet=True)
    engine.distro_config = DISTRO_CONFIG["rhel"]
    engine.distro_id = "fedora"

    def package_results(tasks):
        assert set(tasks) == {"installed", "kernels"}
        return {
            "installed": _result("rpm -qa --qf", stdout="bash\n"),
            "kernels": _result("rpm -qa kernel*", stdout=""),
        }

    monkeypatch.setattr(engine, "_parallel_cmd", package_results)
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_module_roots", list)
    monkeypatch.setattr(syscheck, "_get_bootable_kernels_from_boot", list)
    engine.collect_packages()
    rendered = "".join(engine.report_lines)
    assert "no matching installed kernel packages" in rendered
    assert "Bootable kernel package records:** 0" in rendered


def test_cross_distro_sanitizer_redacts_private_boot_paths_and_keeps_evidence():
    private = (
        "Hostname: fixture-host\n"
        "Home: /home/fixtureuser/lde\n"
        "MAC: 02:00:00:00:00:01\n"
        "Address: 198.51.100.42\n"
        "UUID: 123e4567-e89b-12d3-a456-426614174000\n"
        "Serial Number: PRIVATE-SERIAL-9\n"
        "Temporary file: /tmp/lde-private-run/report.md\n"
        "EFI artifact: /boot/efi/EFI/Linux/fixture-host-build.efi\n"
        "Alternate ESP: /mnt/esp/EFI/Linux/private-machine.efi\n"
        "Command line: editor --profile /home/fixtureuser/profile\n"
        "Invocation ID: 0123456789abcdef0123456789abcdef\n"
        "Finding GPU-IDENTITY-001; safe diagnostic device /dev/nvme0n1\n"
    )
    sanitized = syscheck._sanitize_text(private, hostname="fixture-host")
    for secret in (
        "fixture-host",
        "fixtureuser",
        "02:00:00:00:00:01",
        "198.51.100.42",
        "123e4567-e89b-12d3-a456-426614174000",
        "PRIVATE-SERIAL-9",
        "/tmp/lde-private-run/report.md",
        "/boot/efi/EFI/Linux/fixture-host-build.efi",
        "/mnt/esp/EFI/Linux/private-machine.efi",
        "0123456789abcdef0123456789abcdef",
    ):
        assert secret not in sanitized
    assert "<EFI_ARTIFACT>" in sanitized
    assert "Finding GPU-IDENTITY-001" in sanitized
    assert "/dev/nvme0n1" in sanitized


def test_incomplete_btrfs_missing_evidence_cannot_resolve_finding():
    limited = _result(
        "btrfs filesystem show /",
        stdout="devid 1 path /dev/synthetic MISSING",
        stderr="Operation not permitted",
        return_code=1,
        status="error",
    )
    assert not syscheck._btrfs_missing_capture_is_authoritative(
        limited, "device_missing"
    )
