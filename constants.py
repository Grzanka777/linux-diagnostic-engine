"""
Stałe konfiguracyjne dla Linux Diagnostic Engine.
Wydzielone dla czytelności i łatwej modyfikacji.
"""

import os
from pathlib import Path

# ── Metadane produktu i kompatybilności ──────────────────────────
PRODUCT_NAME = "Linux Diagnostic Engine"
PRODUCT_SHORT_NAME = "LDE"
PRODUCT_VERSION = "0.2.0"

# Legacy report/snapshot compatibility metadata; this is not the product
# release version.  SCRIPT_VERSION remains as a compatibility alias for
# existing imports and for the schema-3 ``syscheck_version`` field.
REPORT_COMPATIBILITY_VERSION = "2.1.0"
SCRIPT_VERSION = REPORT_COMPATIBILITY_VERSION
# ── Timeouty (sekundy) ──────────────────────────────────────────
TIMEOUT_SHORT = 10
TIMEOUT_MEDIUM = 30
TIMEOUT_LONG = 60


# ── Ścieżki domyślne ─────────────────────────────────────────────
def get_default_reports_dir() -> Path:
    """Return the XDG data directory used for generated reports."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "lde" / "reports"
    return Path.home() / ".local" / "share" / "lde" / "reports"


# Compatibility export; callers needing environment-sensitive behavior should
# use get_default_reports_dir() at runtime.
OUTPUT_DIR_DEFAULT = str(get_default_reports_dir())

# ── Wzorce regex do analizy logów ───────────────────────────────
RE_KERNEL_ERROR = r"error|fail|BUG|lockup|hung|oom|taint|Call Trace"
RE_KERNEL_TAINT = r"(?:\bTainted:\s|\b(?:tainting|taints)\s+kernel\b)"
RE_SEGFAULT = r"segfault"
RE_FIRMWARE = r"firmware|microcode|ucode"
RE_AUTH_FAIL = r"authentication failure|Failed password"
RE_GFX_ERROR = r"niri|dms|wayland|greetd|i915|drm"
RE_OOM = r"invoked oom-killer|oom-killer:|Out of memory: Killed process"
RE_GPU_I915_HANG = r"i915.*GPU HANG:|GPU HANG:.*i915"
RE_AMDGPU_RESET_FAIL = r"amdgpu.*GPU reset failed|GPU reset failed.*amdgpu"
RE_NVIDIA_XID_79 = r"(NVRM|nvidia):\s*Xid\s*\(PCI:[^)]+\):\s*79\b"
RE_PCIE_AER = (
    r"PCIe Bus Error:\s*severity=(?:Corrected|Uncorrected \(Non-Fatal\)|"
    r"Uncorrected \(Fatal\))(?:\s|$)|AER:\s*(?:Corrected|"
    r"Uncorrected \(Non-Fatal\)|Uncorrected \(Fatal\))\s+error received\b"
)
RE_NVME_CONTROLLER_RELIABILITY = (
    r"\bnvme(?:\d+(?:n\d+)?)?\b.*(?:"
    r"I/O.*\btimeout\b,\s*(?:aborting|reset controller)\b|"
    r"\btimeout\b,\s*reset controller\b|"
    r"controller is down;\s*will reset\b|"
    r"Device not ready;\s*aborting reset\b"
    r")"
)
RE_HARDWARE_MCE_EDAC = (
    r"(?:"
    r"\bmce:\s*\[Hardware Error\]|"
    r"\[Hardware Error\]:.*?\bMachine Check\b|"
    r"\bMachine Check Exception\b|"
    r"\bMachine check events logged\b|"
    r"\bEDAC\b.*?(?:\b(?:CE|UE)\b|\b(?:[Cc]orrected|[Uu]ncorrected)\s+error\b)"
    r")"
)
RE_FILESYSTEM_IO_ERROR = (
    r"(?:"
    r"\bBuffer I/O error\b|"
    r"\bblk_update_request:\s*I/O error\b|"
    r"\bI/O error,\s*dev\b|"
    r"\bEXT4-fs\s+error\b|"
    r"\bEXT4-fs\s*(?:\([^)]+\))?:\s*(?:error\b|.*?error count\b|initial error\b|last error\b)|"
    r"\bXFS.*?\bmetadata I/O error\b|"
    r"\bBTRFS(?::\s*|\s+)(?:error|critical)\b|"
    r"\bcritical medium error\b"
    r")"
)
RE_HARDWARE_THERMAL_THROTTLE = (
    r"(?:"
    r"\b(?:Core|Package)\s+temperature\s+above\s+threshold,\s*cpu\s+clock\s+throttled\b|"
    r"\b(?:Core|Package)\s+temperature\s+above\s+threshold\b.*?\bthrottl\w*\b|"
    r"\b(?:temperature\s+above\s+(?:thermal\s+)?threshold|thermal\s+threshold\s+(?:exceeded|reached)|critical\s+temperature\s+threshold\s+reached)\b.*?\bthrottl\w*\b"
    r")"
)
RE_KERNEL_PANIC = r"\bKernel panic - not syncing\b"
RE_KERNEL_OOPS_BUG = (
    r"(?:"
    r"\bOops:\s*|"
    r"\bkernel BUG at\b|"
    r"\bBUG:\s*unable to handle kernel\b"
    r")"
)
RE_KERNEL_OOPS_PANIC = (
    r"(?:"
    r"\bKernel panic - not syncing\b|"
    r"\bOops:\s*|"
    r"\bkernel BUG at\b|"
    r"\bBUG:\s*unable to handle kernel\b"
    r")"
)
RE_KERNEL_SOFT_LOCKUP = (
    r"(?:\b(?:watchdog:\s+)?BUG:\s*soft lockup\s*-\s*CPU#\d+\s+stuck\s+for\s+\d+s!?\b)"
)
RE_KERNEL_HARD_LOCKUP = (
    r"(?:"
    r"\b(?:(?:NMI\s+)?watchdog:\s+)?(?:Watchdog detected\s+|BUG:\s*)hard\s+LOCKUP\b|"
    r"\bhard\s+LOCKUP\s+on\s+cpu\b"
    r")"
)
RE_KERNEL_HUNG_TASK = (
    r"(?:\b(?:INFO:\s+)?task\s+\S+?\s+blocked for more than\s+\d+\s+seconds\b)"
)
RE_KERNEL_RCU_STALL = (
    r"(?:"
    r"\b(?:rcu:\s+)?(?:INFO:\s+)?rcu(?:_[a-z_]+)?\s+(?:(?:self-)?detected\s+(?:expedited\s+)?stalls?|kthread\s+starved)\b|"
    r"\brcu(?:_[a-z_]+)?\s+(?:self-)?detected\s+(?:expedited\s+)?stalls?\b"
    r")"
)
RE_KERNEL_STALL_RELIABILITY = (
    r"(?:"
    r"\b(?:watchdog:\s+)?BUG:\s*soft lockup\s*-\s*CPU#\d+\s+stuck\s+for\s+\d+s!?\b|"
    r"\b(?:(?:NMI\s+)?watchdog:\s+)?(?:Watchdog detected\s+|BUG:\s*)hard\s+LOCKUP\b|"
    r"\bhard\s+LOCKUP\s+on\s+cpu\b|"
    r"\b(?:INFO:\s+)?task\s+\S+?\s+blocked for more than\s+\d+\s+seconds\b|"
    r"\b(?:rcu:\s+)?(?:INFO:\s+)?rcu(?:_[a-z_]+)?\s+(?:(?:self-)?detected\s+(?:expedited\s+)?stalls?|kthread\s+starved)\b|"
    r"\brcu(?:_[a-z_]+)?\s+(?:self-)?detected\s+(?:expedited\s+)?stalls?\b"
    r")"
)
RE_PLATFORM_ACPI_FIRMWARE_ERROR = (
    r"(?:"
    r"\bACPI\s+(?:BIOS\s+)?Error(?:\s*\([^)]+\))?:\s*\S+|"
    r"\bACPI\s+(?:BIOS\s+)?Exception:\s*AE_\w+"
    r")"
)
RE_KERNEL_FIRMWARE_LOAD_FAIL = (
    r"(?:"
    r"\bDirect firmware load for \S+ failed with error -?\d+\b|"
    r"\bfirmware:\s+failed to load \S+ \(-?\d+\)|"
    r"\b(?:failed|Failed) to load firmware ['\"]?\S+?['\"]?(?:\s|$)|"
    r"\brequest_firmware(?:_direct|_into_buf)?(?:\s+for\s+\S+)?\s+failed(?::|\s+with\s+error)?\s+-?\d+\b|"
    r"\brequest_firmware failed for \S+"
    r")"
)
RE_USB_ENUMERATION_FAIL = (
    r"(?:"
    r"\bdevice descriptor read\/(?:64|8|all),\s+error\s+-?\d+\b|"
    r"\bunable to enumerate USB device\b|"
    r"\bdevice not accepting address\s+\d+,\s+error\s+-?\d+\b|"
    r"\bcan't set address\s+\d+,\s+error\s+-?\d+\b|"
    r"\bcan't read configurations,\s+error\s+-?\d+\b"
    r")"
)
RE_IOMMU_FAULT = (
    r"(?:"
    r"\bAMD-Vi:\s+(?:Event logged\s+\[[A-Z_]+|Completion-Wait loop timed out)\b|"
    r"\bDMAR:\s+\[DMA (?:Read|Write)[^\]]*\]\s+Request device\b|"
    r"\bDMAR:\s+DRHD:\s+handling fault status\b|"
    r"\bDMAR:\s+\[INTR-REMAP\]\s+Request device\b|"
    r"\b(?:arm-smmu[0-9a-z.-]*:\s+)?Unhandled context fault\b|"
    r"\bIOMMU:\s+(?:DMA\s+)?translation fault\b"
    r")"
)
RE_PLATFORM_DEVICE_RELIABILITY = (
    r"(?:"
    r"\bACPI\s+(?:BIOS\s+)?Error(?:\s*\([^)]+\))?:\s*\S+|"
    r"\bACPI\s+(?:BIOS\s+)?Exception:\s*AE_\w+|"
    r"\bDirect firmware load for \S+ failed with error -?\d+\b|"
    r"\bfirmware:\s+failed to load \S+ \(-?\d+\)|"
    r"\b(?:failed|Failed) to load firmware ['\"]?\S+?['\"]?(?:\s|$)|"
    r"\brequest_firmware(?:_direct|_into_buf)?(?:\s+for\s+\S+)?\s+failed(?::|\s+with\s+error)?\s+-?\d+\b|"
    r"\brequest_firmware failed for \S+|"
    r"\bdevice descriptor read\/(?:64|8|all),\s+error\s+-?\d+\b|"
    r"\bunable to enumerate USB device\b|"
    r"\bdevice not accepting address\s+\d+,\s+error\s+-?\d+\b|"
    r"\bcan't set address\s+\d+,\s+error\s+-?\d+\b|"
    r"\bcan't read configurations,\s+error\s+-?\d+\b|"
    r"\bAMD-Vi:\s+(?:Event logged\s+\[[A-Z_]+|Completion-Wait loop timed out)\b|"
    r"\bDMAR:\s+\[DMA (?:Read|Write)[^\]]*\]\s+Request device\b|"
    r"\bDMAR:\s+DRHD:\s+handling fault status\b|"
    r"\bDMAR:\s+\[INTR-REMAP\]\s+Request device\b|"
    r"\b(?:arm-smmu[0-9a-z.-]*:\s+)?Unhandled context fault\b|"
    r"\bIOMMU:\s+(?:DMA\s+)?translation fault\b"
    r")"
)


# ── Maksymalna długość outputu w raporcie ────────────────────────
TRUNCATE_NORMAL = 5000
TRUNCATE_LSPCI = 5000
TRUNCATE_IP_ADDR = 3000
TRUNCATE_RESOLVECTL = 2000
TRUNCATE_FOREIGN_PKGS = 2000
TRUNCATE_FINDING_DETAIL = 800
TRUNCATE_SUSPICION_DETAIL = 500
TRUNCATE_NFT = 2000

# ── Progi analizy ────────────────────────────────────────────────
MAX_RECOMMENDED_KERNELS = 2
SEGFAULT_ALERT_THRESHOLD = 3

# ── Temperatury nieprawidłowe (poniżej tej wartości w °C) ────────
INVALID_TEMPERATURE_CELSIUS = -100.0

# ── Próg zajętości partycji do ostrzeżenia (procent) ────────────
STORAGE_WARNING_PERCENT = 75
STORAGE_CRITICAL_PERCENT = 90

# ── Prefixy pakietów które nie są bootowalnymi kernelami ────────
KERNEL_NON_BOOTABLE_PREFIXES = (
    "linux-api-",
    "linux-firmware",
    "linux-headers",
    # Każdy pakiet kończący się na -headers
)

# ── Sufiksy pakietów które nie są bootowalnymi kernelami ────────
KERNEL_NON_BOOTABLE_SUFFIXES = ("-headers",)

# ── Informacje o dystrybucji ─────────────────────────────────────
DISTRO_CONFIG: dict[str, dict] = {
    "arch": {
        "name": "Arch Linux / CachyOS",
        "pkg_list_orphans": ["pacman", "-Qdt"],
        "pkg_list_foreign": ["pacman", "-Qm"],
        "pkg_query_kernels": [
            "bash",
            "-c",
            "pacman -Q 2>/dev/null | grep -E '^linux'; "
            'statuses=("${PIPESTATUS[@]}"); '
            'if [ "${statuses[0]}" -ne 0 ]; then exit "${statuses[0]}"; '
            'elif [ "${statuses[1]}" -eq 1 ]; then exit 0; '
            'else exit "${statuses[1]}"; fi',
        ],
        "pkg_timeout": TIMEOUT_MEDIUM,
        "kernel_filter_prefixes": list(KERNEL_NON_BOOTABLE_PREFIXES),
    },
    "debian": {
        "name": "Debian / Ubuntu",
        "pkg_list_orphans": ["apt", "list", "?obsolete"],
        "pkg_list_foreign": ["apt", "list", "?installed", "?origin(Debian)"],
        "pkg_query_kernels": ["dpkg", "-l", "linux-image-*"],
        "pkg_timeout": TIMEOUT_MEDIUM,
        "kernel_filter_prefixes": [],
    },
    "rhel": {
        "name": "RHEL / Fedora",
        "pkg_list_orphans": ["dnf", "repoquery", "--unneeded"],
        "pkg_list_foreign": ["dnf", "list", "installed"],
        "pkg_query_kernels": ["rpm", "-qa", "kernel*"],
        "pkg_timeout": TIMEOUT_MEDIUM,
        "kernel_filter_prefixes": [],
    },
}
