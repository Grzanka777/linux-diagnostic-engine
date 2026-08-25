"""
Stałe konfiguracyjne dla syscheck.
Wydzielone dla czytelności i łatwej modyfikacji.
"""

from pathlib import Path

# ── Metadane skryptu ─────────────────────────────────────────────
SCRIPT_VERSION = "2.1.0"
MODEL_NAME = "<REDACTED-PROVIDER>"
AGENT_NAME = "<REDACTED-ROLE>"

# ── Timeouty (sekundy) ──────────────────────────────────────────
TIMEOUT_SHORT = 10
TIMEOUT_MEDIUM = 30
TIMEOUT_LONG = 60

# ── Ścieżki domyślne ─────────────────────────────────────────────
OUTPUT_DIR_DEFAULT = str(Path.home() / "<REDACTED-USER>" / "raport")

# ── Wzorce regex do analizy logów ───────────────────────────────
RE_KERNEL_ERROR = r"error|fail|BUG|lockup|hung|oom|taint|Call Trace"
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
