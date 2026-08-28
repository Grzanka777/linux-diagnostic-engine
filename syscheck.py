#!/usr/bin/env python3
"""
syscheck — kompleksowa, tylko do odczytu diagnostyka systemu Linux.

Autor:      <REDACTED-ROLE>
Model:      <REDACTED-PROVIDER>
Licencja:   MIT
Wersja:     2.2.0

Architektura trójfazowego potoku diagnostycznego:
  Stage 1: RAW   — zbiór surowych wyników poleceń (CmdResult).
  Stage 2: OBS   — strukturalne obserwacje wyprowadzone z RAW (Observation).
  Stage 3: INT   — interpretacje + rekomendacje (Finding).

Interpretacje nigdy nie konsumują RAW bezpośrednio — zależą tylko od
Observation. To separacja upraszcza testowanie i redukuje false positives.

Zasady:
  - Wyłącznie operacje tylko do odczytu.
  - Bez sudo (chyba że odczyt jest niemożliwy – wtedy pomijane i oznaczane).
  - Bez modyfikacji konfiguracji, pakietów, usług.
  - Raport zapisywany do pliku .md i wyświetlany na konsoli.
  - Wspiera Arch/CachyOS, Debian/Ubuntu, RHEL/Fedora (pakiety).

Użycie:
  python syscheck.py [--output-dir KATALOG] [--quiet] [--full]
"""

from __future__ import annotations

import os
import subprocess
import argparse
import datetime
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple

# ── Stałe ────────────────────────────────────────────────────────
from constants import (  # type: ignore[import-untyped]
    AGENT_NAME,
    DISTRO_CONFIG,
    MAX_RECOMMENDED_KERNELS,
    MODEL_NAME,
    OUTPUT_DIR_DEFAULT,
    RE_AUTH_FAIL,
    RE_FIRMWARE,
    RE_GFX_ERROR,
    RE_KERNEL_ERROR,
    RE_AMDGPU_RESET_FAIL,
    RE_FILESYSTEM_IO_ERROR,
    RE_GPU_I915_HANG,
    RE_HARDWARE_MCE_EDAC,
    RE_NVIDIA_XID_79,
    RE_NVME_CONTROLLER_RELIABILITY,
    RE_OOM,
    RE_PCIE_AER,
    RE_SEGFAULT,
    SCRIPT_VERSION,
    SEGFAULT_ALERT_THRESHOLD,
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
    TIMEOUT_SHORT,
    TRUNCATE_FOREIGN_PKGS,
    TRUNCATE_IP_ADDR,
    TRUNCATE_LSPCI,
    TRUNCATE_NFT,
    TRUNCATE_NORMAL,
    TRUNCATE_RESOLVECTL,
    INVALID_TEMPERATURE_CELSIUS,
    STORAGE_WARNING_PERCENT,
    STORAGE_CRITICAL_PERCENT,
    KERNEL_NON_BOOTABLE_SUFFIXES,
)

# ──────────────────────────────────────────────────────────────────
# Narzędzia pomocnicze
# ──────────────────────────────────────────────────────────────────

MAX_WORKERS = 8  # maksymalna liczba równoległych wątków


@dataclass
class CmdResult:
    """Strukturalny wynik wykonania polecenia."""

    command: str
    stdout: str
    stderr: str
    return_code: int
    execution_status: str  # ok | not_found | timeout | permission_denied | error
    privilege_required: bool = False
    optional_dependency: bool = False
    collected_at: str = ""
    truncated: bool = False

    def is_ok(self) -> bool:
        return self.execution_status == "ok"

    def to_fallback_text(self) -> str:
        """Zwraca opis statusu do raportu."""

        def with_capture_marker(text: str) -> str:
            markers = []
            if self.truncated:
                markers.append("[... wynik polecenia obcięty ...]")
            if self.execution_status == "timeout" and (
                self.stdout or (self.stderr and not self.stderr.startswith("Timeout"))
            ):
                markers.append("[... wynik niepełny po timeout ...]")
            return text if not markers else f"{text}\n" + "\n".join(markers)

        if self.execution_status == "ok":
            return with_capture_marker(self.stdout)
        if self.execution_status == "not_found":
            return f"(nie znaleziono: {self.command})"
        if self.execution_status == "timeout":
            partial_stderr = (
                self.stderr if not self.stderr.startswith("Timeout") else ""
            )
            return with_capture_marker(self.stdout or partial_stderr or "(timeout)")
        if self.execution_status == "permission_denied":
            return "(wymaga sudo — pominięto)"
        if self.execution_status == "empty_ok":
            return with_capture_marker(self.stdout if self.stdout else "(brak wyników)")
        if self.truncated and (self.stdout or self.stderr):
            captured = "\n".join(part for part in (self.stdout, self.stderr) if part)
            return with_capture_marker(captured) + f"\n(błąd rc={self.return_code})"
        return f"(błąd rc={self.return_code})"


@dataclass
class DiagnosticDomain(str, Enum):
    SYSTEMD = "systemd"
    STORAGE = "storage"
    FILESYSTEM = "filesystem"
    KERNEL = "kernel"
    BOOT = "boot"
    AUDIO = "audio"
    HARDWARE = "hardware"
    NETWORK = "network"
    SECURITY = "security"
    PACKAGES = "packages"
    ENVIRONMENT = "environment"
    OTHER = "other"

    __hash__ = str.__hash__  # type: ignore[assignment]


class FindingKind(str, Enum):
    FAILED_UNIT = "failed_unit"
    STORAGE_USAGE = "storage_usage"
    SCRUB_STATUS = "scrub_status"
    DEVICE_ERROR = "device_error"
    SEGFAULT = "segfault"
    KERNEL_COUNT = "kernel_count"
    KERNEL_TAINT = "kernel_taint"
    OOM_EVENT = "oom_event"
    GPU_I915_HANG = "gpu_i915_hang"
    AMDGPU_RESET_FAIL = "amdgpu_reset_fail"
    GPU_NVIDIA_XID_79 = "gpu_nvidia_xid_79"
    PCIE_AER_ERROR = "pcie_aer_error"
    NVME_CONTROLLER_RELIABILITY = "nvme_controller_reliability"
    HARDWARE_MCE_EDAC_ERROR = "hardware_mce_edac_error"
    FILESYSTEM_IO_ERROR = "filesystem_io_error"
    BOOT_DELAY = "boot_delay"
    GENERAL = "general"
    __hash__ = str.__hash__  # type: ignore[assignment]


class Actionability(str, Enum):
    ACTIONABLE = "actionable"
    CONDITIONAL = "conditional"
    INFORMATIONAL = "informational"
    __hash__ = str.__hash__  # type: ignore[assignment]


class RecommendationIntent(str, Enum):
    INVESTIGATE = "investigate"
    VERIFY = "verify"
    REMEDIATE = "remediate"
    MONITOR = "monitor"
    INFORMATIONAL = "informational"


@dataclass
class Finding:
    """Pojedyncze ustalenie diagnostyczne ze strukturą (Stage 3: INT)."""

    finding_id: str
    title: str
    severity: str  # "P0" | "P1" | "P2" | "P3" | "Info"
    confidence: str  # "Certain" | "Likely" | "Guessing"
    evidence: str = ""
    interpretation: str = ""
    recommended_diagnostics: str = ""
    remediation: str = ""
    verification: str = ""
    risk_level: str = ""
    domain: DiagnosticDomain = field(default_factory=lambda: DiagnosticDomain.OTHER)
    kind: FindingKind = field(default_factory=lambda: FindingKind.GENERAL)
    actionability: Actionability = field(
        default_factory=lambda: Actionability.CONDITIONAL
    )
    recommendation_intent: RecommendationIntent = field(
        default_factory=lambda: RecommendationIntent.VERIFY
    )
    source_observation_ids: tuple = ()
    evidence_ids: tuple = ()

    # Klucz sortowania: P0=0, P1=1, P2=2, P3=3, Info=4
    _severity_order: ClassVar[dict] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Info": 4}


@dataclass
class Observation:
    """Pojedyncza obserwacja diagnostyczna (Stage 2: OBS).

    Wyprowadzana wyłącznie z danych RAW (RawDiagnostic).
    Nie zawiera interpretacji ani rekomendacji — tylko fakty.
    """

    obs_id: str
    category: str
    details: Dict[str, Any] = field(default_factory=dict)
    data_complete: bool = True
    contradictory_evidence: bool = False
    direct_measurement: bool = True
    inference_required: bool = False
    independent_sources: int = 1
    source_raw_ids: tuple = ()


@dataclass(frozen=True)
class RawDiagnostic:
    """Surowy rekord diagnostyczny (Stage 1: RAW output).

    Produkowany przez collect_*(), konsumowany przez _derive_observations().
    Nie zawiera interpretacji, severity, confidence, ani rekomendacji.
    """

    source_id: str
    category: str
    payload: dict
    collected_at: str = ""


# ── Confidence derivation ────────────────────────────────────────


def derive_confidence(
    *,
    direct_measurement: bool,
    data_complete: bool,
    contradictory_evidence: bool,
    inference_required: bool,
    independent_sources: int,
) -> str:
    """Deterministycznie wyznacza poziom pewności na podstawie metadanych."""
    if contradictory_evidence:
        return "Guessing"
    if not data_complete:
        return "Guessing"
    if independent_sources < 1:
        return "Guessing"
    if direct_measurement and not inference_required:
        return "Certain"
    if not direct_measurement and inference_required and independent_sources >= 1:
        return "Likely"
    return "Likely"


def run_cmd(
    cmd: List[str],
    timeout: int = TIMEOUT_SHORT,
    env: Optional[Dict[str, str]] = None,
    optional_dependency: bool = False,
) -> CmdResult:
    """
    Uruchamia polecenie. Zwraca CmdResult ze szczegółowym statusem.
    Bezpiecznie – bez powłoki, bez sudo.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    cmd_str = " ".join(cmd)
    collected_at = datetime.datetime.now().isoformat(timespec="seconds")

    def drain(stream: Any) -> Tuple[bytes, bool]:
        chunks: List[bytes] = []
        retained = 0
        truncated = False
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if retained < TRUNCATE_NORMAL:
                keep = chunk[: TRUNCATE_NORMAL - retained]
                chunks.append(keep)
                retained += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
        return b"".join(chunks), truncated

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            start_new_session=True,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None
        stdout_holder: List[Tuple[bytes, bool]] = []
        stderr_holder: List[Tuple[bytes, bool]] = []
        stdout_thread = threading.Thread(
            target=lambda: stdout_holder.append(drain(proc.stdout)), daemon=True
        )
        stderr_thread = threading.Thread(
            target=lambda: stderr_holder.append(drain(proc.stderr)), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            proc.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        stdout_bytes, stdout_truncated = (
            stdout_holder[0] if stdout_holder else (b"", True)
        )
        stderr_bytes, stderr_truncated = (
            stderr_holder[0] if stderr_holder else (b"", True)
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        truncated = stdout_truncated or stderr_truncated
        if timed_out:
            timeout_text = f"Timeout ({timeout}s): {cmd_str}"
            stderr = f"{stderr}\n{timeout_text}".strip()
            status = "timeout"
            return_code = -2
        else:
            return_code = proc.returncode
            status = "ok" if return_code == 0 else "error"
        return CmdResult(
            command=cmd_str,
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
            execution_status=status,
            optional_dependency=optional_dependency,
            collected_at=collected_at,
            truncated=truncated,
        )
    except FileNotFoundError:
        return CmdResult(
            command=cmd_str,
            stdout="",
            stderr=f"Polecenie nie znalezione: {cmd[0]}",
            return_code=-1,
            execution_status="not_found",
            optional_dependency=optional_dependency,
            collected_at=collected_at,
            truncated=False,
        )
    except PermissionError:
        return CmdResult(
            command=cmd_str,
            stdout="",
            stderr=f"Brak uprawnień (bez sudo): {cmd_str}",
            return_code=-3,
            execution_status="permission_denied",
            privilege_required=True,
            optional_dependency=optional_dependency,
            collected_at=collected_at,
            truncated=False,
        )
    except Exception as exc:
        return CmdResult(
            command=cmd_str,
            stdout="",
            stderr=str(exc),
            return_code=-4,
            execution_status="error",
            optional_dependency=optional_dependency,
            collected_at=collected_at,
            truncated=False,
        )


def safestr(text: str, max_len: int = TRUNCATE_NORMAL, *, full: bool = False) -> str:
    """Przycina długi string, chyba że full=True."""
    if full or len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n[... obcięto, pełna długość: {len(text)} znaków]"


def _capture_payload(result: CmdResult, payload: dict) -> dict:
    """Preserve bounded-capture metadata through the RAW diagnostic stage."""
    if result.truncated:
        payload["capture_truncated"] = True
    return payload


def _write_new_text(path: str | Path, text: str) -> None:
    """Create a new text file without following or replacing a destination."""
    destination = Path(path)
    if destination.is_symlink():
        raise FileExistsError(f"Destination {destination} is a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(destination, flags, 0o644)
    except FileExistsError:
        raise FileExistsError(f"Destination {destination} already exists") from None
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    try:
        handle.write(text)
    except BaseException:
        try:
            current = os.stat(destination, follow_symlinks=False)
            opened = os.fstat(fd)
            if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                destination.unlink()
        except OSError:
            pass
        raise
    finally:
        handle.close()


def heading(level: int, title: str) -> str:
    return f"{'#' * level} {title}\n"


def codeblock(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```\n"


def confidence_tag(level: str) -> str:
    tags = {"Certain": "[Certain]", "Likely": "[Likely]", "Guessing": "[Guessing]"}
    return tags.get(level, level)


def severity_tag(level: str) -> str:
    tags = {
        "P0": "P0 – krytyczny",
        "P1": "P1 – wysoki",
        "P2": "P2 – średni",
        "P3": "P3 – niski",
        "Info": "Info – informacja",
    }
    return tags.get(level, level)


def _get_script_pids() -> List[str]:
    """Zwraca listę PIDów procesów syscheck.py w bieżącej sesji."""
    try:
        import psutil  # type: ignore[import-untyped]

        pids = []
        current_pid = os.getpid()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                if any("syscheck.py" in part for part in cmdline):
                    pids.append(str(proc.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if str(current_pid) not in pids:
            pids.append(str(current_pid))
        return pids
    except ImportError:
        # Bez psutil: używamy tylko własnego PID
        return [str(os.getpid())]
    except Exception:
        return [str(os.getpid())]


def _filter_own_journal_entries(text: str) -> str:
    """Filtruje linie z dziennika które pochodzą z syscheck.py (własne wpisy)."""
    lines = text.split("\n")
    filtered = []
    for line in lines:
        # Pomijamy linie zawierające wpisy z syscheck.py[PID]
        if re.search(r"\bsyscheck\.py\[\d+\]", line):
            continue
        filtered.append(line)
    return "\n".join(filtered)


def _deduplicate_journal_lines(text: str) -> str:
    """
    Deduplikuje linie dziennika po treści (pomijając znacznik czasu).
    Linie są uznawane za duplikaty jeśli ich treść za znacznikiem czasu jest identyczna.
    """
    lines = text.split("\n")
    seen = set()
    unique_lines = []
    for line in lines:
        if not line.strip():
            continue
        # Usuń znacznik czasu (początek linii do drugiego pola)
        # Format: "month day HH:MM:SS hostname source[pid]: message"
        # Lub: "month day HH:MM:SS hostname kernel: ..."
        normalized = re.sub(r"^\w+\s+\d+\s+\d+:\d+:\d+\s+\S+\s+", "", line)
        if normalized not in seen:
            seen.add(normalized)
            unique_lines.append(line)
    return "\n".join(unique_lines)


def _count_unique_segfaults(text: str) -> int:
    """
    Zlicza unikalne segfaulty z jądra, pomijając duplikaty i wpisy z syscheck.py.
    Prawdziwy segfault to linia kernel: zawierająca 'segfault' i 'kernel:'.
    """
    lines = text.split("\n")
    seen = set()
    count = 0
    for line in lines:
        # Pomijamy puste linie
        if not line.strip():
            continue
        # Pomijamy linie z syscheck.py
        if re.search(r"\bsyscheck\.py\[\d+\]", line):
            continue
        # Pomijamy linie które nie są z kernel source
        if "kernel:" not in line:
            continue
        if "segfault" not in line.lower():
            continue
        # Normalizujemy linię dla deduplikacji (pomijamy PID i adres)
        # Wyciągamy: program[PID] oraz shared library
        match = re.match(r".*kernel:\s+(\S+)\[\d+\]:\s+segfault.*in\s+(\S+)", line)
        if match:
            key = f"{match.group(1)}:{match.group(2)}"
        else:
            # Fallback: cała linia poza timestampem i hostname
            normalized = re.sub(r"^\w+\s+\d+\s+\d+:\d+:\d+\s+\S+\s+", "", line)
            key = normalized
        if key not in seen:
            seen.add(key)
            count += 1
    return count


def _filter_invalid_temperatures(text: str) -> str:
    """
    Filtruje temperatury poniżej INVALID_TEMPERATURE_CELSIUS (np. -273.15°C).
    Takie wartości oznaczają niepodłączony lub nieobsługiwany czujnik.
    """
    lines = text.split("\n")
    filtered = []
    skip_next = False
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        # Szukamy linii z temperaturą: "temp1:       -273.3°C"
        match = re.match(r"^(\s*\w+\d*:\s+)([+-]?\d+[.,]\d+°[CF])(.*)", line)
        if match:
            try:
                temp_str = (
                    match.group(2).replace(",", ".").replace("°C", "").replace("°F", "")
                )
                temp = float(temp_str)
                if temp < INVALID_TEMPERATURE_CELSIUS:
                    # Pomijamy tę linię
                    continue
            except ValueError:
                pass
        filtered.append(line)
    return "\n".join(filtered)


def _classify_btrfs_status(cmd_result: CmdResult) -> str:
    """
    Klasyfikuje wynik polecenia btrfs.
    Zwraca: "ok", "no_scrub", "permission_denied", "command_not_found", "device_missing", "error"
    """
    if cmd_result.execution_status == "not_found":
        return "command_not_found"
    if cmd_result.execution_status == "permission_denied":
        return "permission_denied"

    stderr_lower = cmd_result.stderr.lower()
    stdout_lower = cmd_result.stdout.lower()

    # Sprawdź błędy uprawnień w stderr/stdout (mogą być przy rc=0 lub rc!=0)
    if (
        "permission denied" in stderr_lower
        or "not root" in stderr_lower
        or "operation not permitted" in stderr_lower
        or "wymaga sudo" in stderr_lower
    ):
        return "permission_denied"

    # Sprawdź status scrub (przy rc=0 też się pojawia)
    if "no scrub" in stdout_lower or "no scrub" in stderr_lower:
        return "no_scrub"

    # Sprawdź missing device
    if "missing" in stdout_lower:
        return "device_missing"

    # Jeśli wszystko OK
    if cmd_result.return_code == 0:
        return "ok"

    return "error"


def _get_bootable_kernels_from_modules() -> List[str]:
    """Zwraca listę wersji kernel z /usr/lib/modules/."""
    modules_dir = Path("/usr/lib/modules")
    if not modules_dir.is_dir():
        return []
    return sorted(
        [
            d.name
            for d in modules_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
    )


def _get_bootable_kernels_from_boot() -> List[str]:
    """Zwraca listę nazw kernel dla których istnieje vmlinuz w /boot."""
    boot_dir = Path("/boot")
    if not boot_dir.is_dir():
        return []
    kernels = []
    for f in boot_dir.iterdir():
        if f.name.startswith("vmlinuz-"):
            kernels.append(f.name[len("vmlinuz-") :])
    return sorted(kernels)


def _count_kernel_packages(pkg_list: str) -> Tuple[int, int, List[str]]:
    """
    Zlicza pakiety kernel vs non-bootable (headers, firmware).
    Zwraca: (bootable_kernel_count, total_linux_packages, list_of_bootable_kernels)

    Logika:
    - Zachowuje filtrowanie pakietów Arch/CachyOS `linux*`
    - Z tabeli `dpkg -l` wybiera zainstalowane, wersjonowane linux-image
    - Z `rpm -qa kernel*` wybiera unikalne wersje kernel/kernel-core
    """
    bootable = []
    rpm_bootable = {}
    total_packages = 0
    is_dpkg_output = any(
        re.match(r"^[a-z][a-z]\s+linux-", line.strip()) for line in pkg_list.split("\n")
    )
    for line in pkg_list.split("\n"):
        line = line.strip()
        if not line:
            continue

        dpkg_match = re.match(r"^(\S{2})\s+(\S+)\s+(\S+)", line)
        if dpkg_match:
            status, pkg_name, version = dpkg_match.groups()
            if status[1] != "i":
                continue
            total_packages += 1
            if re.match(r"^linux-image-(?:unsigned-)?\d", pkg_name):
                bootable.append(f"{pkg_name} {version}")
            continue

        if is_dpkg_output:
            continue

        if line.startswith("kernel"):
            total_packages += 1
            rpm_match = re.match(r"^(kernel(?:-core)?)-(\d.+)$", line)
            if rpm_match:
                package, version = rpm_match.groups()
                if version not in rpm_bootable or package == "kernel-core":
                    rpm_bootable[version] = line
            continue

        # Wyodrębnij nazwę pakietu (pierwsze słowo)
        pkg_name = line.split()[0] if " " in line else line
        total_packages += 1
        # Sprawdź prefiksy na nazwie pakietu
        filters = DISTRO_CONFIG.get("arch", {}).get("kernel_filter_prefixes", [])
        if any(pkg_name.startswith(prefix) for prefix in filters):
            continue
        # Sprawdź sufiksy na nazwie pakietu (np. -headers)
        if any(pkg_name.endswith(suffix) for suffix in KERNEL_NON_BOOTABLE_SUFFIXES):
            continue
        bootable.append(line)
    bootable.extend(rpm_bootable.values())
    return len(bootable), total_packages, bootable


def _parse_storage_usage(df_h_output: str) -> List[Tuple[str, int]]:
    """Parsuje df -h i zwraca listę (mountpoint, usage_percent)."""
    results = []
    for line in df_h_output.split("\n"):
        parts = line.split()
        if len(parts) >= 6 and parts[4].endswith("%"):
            try:
                pct = int(parts[4].rstrip("%"))
                mount = parts[5] if parts[5] else parts[0]
                results.append((mount, pct))
            except ValueError:
                pass
    return results


def _journal_filter_command(
    upstream_cmd: str, regexes: List[str], tail_lines: Optional[int] = None
) -> List[str]:
    """Build a status-aware journal filter with bounded pipeline semantics."""
    stages = [f"grep -iE '{regex}'" for regex in regexes]
    if tail_lines is not None:
        stages.append(f"tail -{tail_lines}")
    pipeline = f"{upstream_cmd} | " + " | ".join(stages)
    parts = [
        f"{pipeline};",
        'statuses=("${PIPESTATUS[@]}");',
        'if [ "${statuses[0]}" -ne 0 ]; then exit "${statuses[0]}"; fi;',
    ]
    for index in range(1, len(regexes) + 1):
        parts.append(
            f'if [ "${{statuses[{index}]}}" -ne 0 ] && '
            f'[ "${{statuses[{index}]}}" -ne 1 ]; then '
            f'exit "${{statuses[{index}]}}"; fi;'
        )
    if tail_lines is not None:
        tail_index = len(regexes) + 1
        parts.append(f'exit "${{statuses[{tail_index}]}}";')
    else:
        parts.append("exit 0;")
    return ["bash", "-c", " ".join(parts)]


def _journal_count_command(upstream_cmd: str, regex: str) -> List[str]:
    """Build a status-aware count command with explicit grep no-match handling."""
    return [
        "bash",
        "-c",
        f"{upstream_cmd} | grep -iE '{regex}' | wc -l; "
        'statuses=("${PIPESTATUS[@]}"); '
        'if [ "${statuses[0]}" -ne 0 ]; then exit "${statuses[0]}"; '
        'elif [ "${statuses[1]}" -ne 0 ] && [ "${statuses[1]}" -ne 1 ]; then '
        'exit "${statuses[1]}"; '
        'else exit "${statuses[2]}"; fi',
    ]


def _oom_collector_command(
    upstream_cmd: str, regex: str, tail_lines: Optional[int] = None
) -> List[str]:
    """Build the OOM collector bash command with safe PIPESTATUS handling.

    Args:
        upstream_cmd: The upstream command that produces journal output
                      (e.g. ``journalctl -b -k --no-pager 2>/dev/null``).
        regex: The grep -iE pattern to match against.

    Returns:
        A ``["bash", "-c", "..."]`` list suitable for ``_parallel_cmd``.

    The captured PIPESTATUS array is read atomically so that the
    ``journalctl`` exit status and ``grep`` exit status are both
    preserved regardless of bash version.
    """
    return _journal_filter_command(upstream_cmd, [regex], tail_lines=tail_lines)


def _pcie_aer_severity(line: str) -> Optional[str]:
    """Return the explicit AER severity encoded in a matched kernel line."""
    normalized = line.lower()
    if "uncorrected (fatal)" in normalized:
        return "fatal"
    if "uncorrected (non-fatal)" in normalized:
        return "non_fatal"
    if "corrected" in normalized:
        return "corrected"
    return None


def _nvme_controller_reliability_severity(line: str) -> Optional[str]:
    """Return the severity class encoded in a matched NVMe kernel line."""
    if "device not ready; aborting reset" in line.lower():
        return "reset_failure"
    if re.search(RE_NVME_CONTROLLER_RELIABILITY, line, re.IGNORECASE):
        return "timeout_or_reset"
    return None


def _hardware_mce_edac_severity(line: str) -> Optional[str]:
    """Return the severity class encoded in a matched MCE/EDAC kernel line."""
    normalized = line.lower()
    if (
        "machine check" in normalized
        or "uncorrected" in normalized
        or "mce:" in normalized
        or "[hardware error]" in normalized
        or re.search(r"\bUE\b", line)
    ):
        return "uncorrected"
    if "corrected" in normalized or re.search(r"\bCE\b", line):
        return "corrected"
    return None


def _filesystem_io_error_severity(line: str) -> Optional[str]:
    """Return the severity class encoded in a matched filesystem/block-I/O kernel line."""
    if not re.search(RE_FILESYSTEM_IO_ERROR, line, re.IGNORECASE):
        return None
    normalized = line.lower()
    if (
        "critical medium error" in normalized
        or "critical" in normalized
        or "fatal" in normalized
        or "corrupt" in normalized
        or "force_shutdown" in normalized
        or "forced shutdown" in normalized
        or "shut down due to" in normalized
        or "remount-ro" in normalized
    ):
        return "critical_or_fatal"
    return "io_error"


# ──────────────────────────────────────────────────────────────────
# Silnik diagnostyczny
# ──────────────────────────────────────────────────────────────────


# ── Classification policy ──────────────────────────────────────


@dataclass(frozen=True)
class FindingClassification:
    """Niezmienna wartość klasyfikacji diagnostycznej."""

    domain: DiagnosticDomain
    kind: FindingKind
    actionability: Actionability
    recommendation_intent: RecommendationIntent

    def __post_init__(self):
        if not isinstance(self.domain, DiagnosticDomain):
            raise ValueError(f"Invalid domain: {self.domain}")
        if not isinstance(self.kind, FindingKind):
            raise ValueError(f"Invalid kind: {self.kind}")


class UnsupportedObservationCategoryError(ValueError):
    """Rzucany gdy kategoria Observation nie jest obsługiwana."""

    pass


class FindingClassificationPolicy:
    """Deterministyczna polityka: Observation → FindingClassification.

    Nie zależy od finding_id, tytułów, Recommendation Engine.
    """

    _BY_CATEGORY: ClassVar[dict] = {
        "btrfs_error": FindingClassification(
            DiagnosticDomain.FILESYSTEM,
            FindingKind.DEVICE_ERROR,
            Actionability.ACTIONABLE,
            RecommendationIntent.VERIFY,
        ),
        "btrfs_scrub": FindingClassification(
            DiagnosticDomain.FILESYSTEM,
            FindingKind.SCRUB_STATUS,
            Actionability.ACTIONABLE,
            RecommendationIntent.REMEDIATE,
        ),
        "segfault_minor": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.SEGFAULT,
            Actionability.ACTIONABLE,
            RecommendationIntent.MONITOR,
        ),
        "tainted": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_TAINT,
            Actionability.CONDITIONAL,
            RecommendationIntent.MONITOR,
        ),
        "kernel_count": FindingClassification(
            DiagnosticDomain.PACKAGES,
            FindingKind.KERNEL_COUNT,
            Actionability.INFORMATIONAL,
            RecommendationIntent.INFORMATIONAL,
        ),
        "boot_time": FindingClassification(
            DiagnosticDomain.BOOT,
            FindingKind.BOOT_DELAY,
            Actionability.CONDITIONAL,
            RecommendationIntent.MONITOR,
        ),
        "oom_event": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.OOM_EVENT,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "gpu_i915_hang": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.GPU_I915_HANG,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "amdgpu_reset_fail": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.AMDGPU_RESET_FAIL,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "gpu_nvidia_xid_79": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.GPU_NVIDIA_XID_79,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "pcie_aer_error": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.PCIE_AER_ERROR,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "nvme_controller_reliability": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.NVME_CONTROLLER_RELIABILITY,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "hardware_mce_edac_error": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.HARDWARE_MCE_EDAC_ERROR,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "filesystem_io_error": FindingClassification(
            DiagnosticDomain.FILESYSTEM,
            FindingKind.FILESYSTEM_IO_ERROR,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
    }

    _SEGFAULT_WP = FindingClassification(
        DiagnosticDomain.AUDIO,
        FindingKind.SEGFAULT,
        Actionability.ACTIONABLE,
        RecommendationIntent.INVESTIGATE,
    )
    _SEGFAULT_SYS = FindingClassification(
        DiagnosticDomain.KERNEL,
        FindingKind.SEGFAULT,
        Actionability.ACTIONABLE,
        RecommendationIntent.INVESTIGATE,
    )

    def classify(self, observation: Observation) -> FindingClassification:
        cat = observation.category
        details = observation.details

        if cat in self._BY_CATEGORY:
            return self._BY_CATEGORY[cat]

        if cat == "segfault":
            if details.get("segfault_type") == "wireplumber":
                return self._SEGFAULT_WP
            return self._SEGFAULT_SYS

        if cat == "systemd_failed":
            return FindingClassification(
                DiagnosticDomain.SYSTEMD,
                FindingKind.FAILED_UNIT,
                Actionability.ACTIONABLE,
                RecommendationIntent.INVESTIGATE,
            )

        if cat == "storage_usage":
            return FindingClassification(
                DiagnosticDomain.STORAGE,
                FindingKind.STORAGE_USAGE,
                Actionability.ACTIONABLE,
                RecommendationIntent.REMEDIATE,
            )

        raise UnsupportedObservationCategoryError(
            f"Unknown observation category: {cat}"
        )


# ── Diagnostic Rule Engine ──────────────────────────────────────


class EvidenceType(str, Enum):
    COMMAND_RESULT = "command_result"
    SYSTEM_STATE = "system_state"
    JOURNAL_EVENT = "journal_event"
    FILESYSTEM_STATE = "filesystem_state"
    STORAGE_MEASUREMENT = "storage_measurement"
    SERVICE_STATE = "service_state"
    PACKAGE_STATE = "package_state"
    BOOT_MEASUREMENT = "boot_measurement"
    HARDWARE_STATE = "hardware_state"
    DERIVED_MEASUREMENT = "derived_measurement"
    __hash__ = str.__hash__


class EvidenceStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    __hash__ = str.__hash__


class EvidenceDirectness(str, Enum):
    DIRECT = "direct"
    INFERRED = "inferred"
    __hash__ = str.__hash__


class EvidenceCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    __hash__ = str.__hash__


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    evidence_type: EvidenceType
    data: dict = field(default_factory=dict)
    source_observation_ids: tuple = ()
    source_raw_ids: tuple = ()
    summary: str = ""
    strength: EvidenceStrength = EvidenceStrength.MODERATE
    directness: EvidenceDirectness = EvidenceDirectness.INFERRED
    completeness: EvidenceCompleteness = EvidenceCompleteness.PARTIAL
    contradictory: bool = False

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "source_observation_ids": list(self.source_observation_ids),
            "source_raw_ids": list(self.source_raw_ids),
            "summary": self.summary,
            "data": dict(self.data),
            "strength": self.strength.value,
            "directness": self.directness.value,
            "completeness": self.completeness.value,
            "contradictory": self.contradictory,
        }


class EvidenceBuilder:
    def build(self, observation: Observation) -> Evidence:
        cat = observation.category
        d = observation.details
        oid = observation.obs_id
        eid = f"EVIDENCE-{oid}-001"
        if cat == "systemd_failed":
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.SERVICE_STATE,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=f"Failed units: {d.get('units', [])}",
                data={"scope": d.get("scope", ""), "units": list(d.get("units", []))},
                strength=EvidenceStrength.STRONG,
                directness=EvidenceDirectness.DIRECT,
                completeness=EvidenceCompleteness.COMPLETE,
            )
        if cat == "storage_usage":
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.STORAGE_MEASUREMENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=f"{d.get('mountpoint', '/')}: {d.get('usage_percent', '?')}%",
                data={
                    "mountpoint": d.get("mountpoint", "/"),
                    "usage_percent": d.get("usage_percent", 0),
                },
                strength=EvidenceStrength.STRONG,
                directness=EvidenceDirectness.DIRECT,
                completeness=EvidenceCompleteness.COMPLETE,
            )
        if cat == "segfault":
            # Derive quality from observation flags
            strength = EvidenceStrength.MODERATE
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.WEAK

            # Factual summary based on segfault type
            stype = d.get("segfault_type", "unknown")
            count = d.get("count", 0)
            if stype == "wireplumber":
                summary = (
                    f"WirePlumber segfault events involving "
                    f"libspa-libcamera.so detected ({count})"
                )
            elif stype == "system_wide":
                summary = (
                    f"Kernel-reported segfault events "
                    f"affecting multiple processes ({count})"
                )
            else:
                summary = f"Segfault events detected in kernel journal ({count})"

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data=dict(d),
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "segfault_minor":
            # Derive quality from observation flags
            strength = EvidenceStrength.MODERATE
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.WEAK

            count = d.get("count", 0)
            summary = f"Limited segfault events observed ({count})"

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data=dict(d),
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_count":
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.PACKAGE_STATE,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=f"Kernel count: {d.get('count', '?')}",
                data={"count": d.get("count", 0)},
                strength=EvidenceStrength.STRONG,
                directness=EvidenceDirectness.DIRECT,
                completeness=EvidenceCompleteness.COMPLETE,
            )
        if cat == "btrfs_scrub":
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.FILESYSTEM_STATE,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary="Btrfs scrub status",
                data=dict(d),
                strength=EvidenceStrength.MODERATE,
                directness=EvidenceDirectness.DIRECT,
                completeness=EvidenceCompleteness.PARTIAL,
            )
        if cat == "btrfs_error":
            # Derive quality from observation flags
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            # Factual summary based on available details
            if "status" in d:
                if d["status"] == "device_missing":
                    summary = (
                        f"Btrfs reported device status MISSING for "
                        f"mountpoint {d.get('mountpoint', '?')}"
                    )
                elif d["status"] == "permission_denied":
                    summary = (
                        "Btrfs device state could not be read: "
                        "elevated privileges required"
                    )
                else:
                    summary = f"Btrfs device status: {d['status']}"
            elif d.get("device_error_counters"):
                counters = d["device_error_counters"]
                non_zero = {k: v for k, v in counters.items() if v != 0}
                if non_zero:
                    parts = [
                        f"{k.replace('_errors', '')}={v}" for k, v in non_zero.items()
                    ]
                    summary = f"Btrfs device statistics: {', '.join(parts)} errors"
                else:
                    summary = "Btrfs device error counters are all zero"
            else:
                summary = "Btrfs device state observation recorded"

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.FILESYSTEM_STATE,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data=dict(d),
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "tainted":
            # Derive quality from observation flags
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            # Factual summary
            taint_value = d.get("taint_value")
            taint_flags = d.get("taint_flags")
            if taint_value is not None:
                summary = f"Kernel reports non-zero taint value of {taint_value}"
                if taint_flags:
                    summary += f" (flags: {', '.join(taint_flags)})"
            elif taint_flags:
                summary = f"Kernel taint flags observed: {', '.join(taint_flags)}"
            else:
                summary = "The running kernel is marked as tainted"

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.SYSTEM_STATE,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data=dict(d),
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "boot_time":
            # Derive quality from observation flags
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            # Factual summary based on available measurements
            total = d.get("total_seconds")
            userspace = d.get("userspace_time")
            threshold = d.get("threshold", 30)
            fstrim_in_cc = d.get("fstrim_in_critical_chain")
            if total is not None:
                summary = f"Total measured boot time was {total} seconds"
                if threshold is not None and total > threshold:
                    summary += (
                        f", exceeding the configured threshold of {threshold} seconds"
                    )
                else:
                    summary += "."
            elif userspace is not None:
                summary = f"Userspace initialization took {userspace} seconds"
                if threshold is not None and userspace > threshold:
                    summary += (
                        f", exceeding the configured threshold of {threshold} seconds"
                    )
                else:
                    summary += "."
            else:
                summary = "Boot time measurement recorded."
            if fstrim_in_cc is False:
                summary += " fstrim.service was not present in the critical chain."

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.BOOT_MEASUREMENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data=dict(d),
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "oom_event":
            # Derive quality from observation flags
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            count = d.get("match_count", 0)
            summary = (
                f"OOM killer invoked during current boot "
                f"({count} matching journal line(s))"
            )

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data={
                    "oom_detected": d.get("oom_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "match_classes": d.get("match_classes", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "oom_events"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "gpu_i915_hang":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            count = d.get("match_count", 0)
            summary = (
                f"i915 GPU hang detected during current boot "
                f"({count} matching journal line(s))"
            )

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data={
                    "hang_detected": d.get("hang_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "driver": d.get("driver", "i915"),
                    "driver_attribution_source": d.get(
                        "driver_attribution_source", "in_message"
                    ),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "gpu_i915_hang"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "amdgpu_reset_fail":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            count = d.get("match_count", 0)
            summary = (
                f"AMDGPU reset failure detected during current boot "
                f"({count} matching journal line(s))"
            )

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data={
                    "reset_failure_detected": d.get("reset_failure_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "driver": d.get("driver", "amdgpu"),
                    "driver_attribution_source": d.get(
                        "driver_attribution_source", "in_message"
                    ),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "amdgpu_reset_fail"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "gpu_nvidia_xid_79":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL
            if observation.inference_required:
                directness = EvidenceDirectness.INFERRED
            if observation.contradictory_evidence:
                strength = EvidenceStrength.MODERATE

            count = d.get("match_count", 0)
            summary = (
                f"NVIDIA Xid 79 event detected during current boot "
                f"({count} matching journal line(s))"
            )

            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=summary,
                data={
                    "xid_detected": d.get("xid_detected", False),
                    "xid_code": d.get("xid_code", 0),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "driver": d.get("driver", "nvidia"),
                    "driver_attribution_source": d.get(
                        "driver_attribution_source", "in_message"
                    ),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "gpu_nvidia_xid_79"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "pcie_aer_error":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            severity = d.get("aer_severity", "unknown")
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"PCIe AER {severity} event detected during current boot "
                    f"({count} matching journal line(s))"
                ),
                data={
                    "aer_detected": d.get("aer_detected", False),
                    "aer_severity": severity,
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "pcie_aer"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "nvme_controller_reliability":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            severity = d.get("event_severity", "timeout_or_reset")
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"NVMe controller reliability {severity} event detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "nvme_detected": d.get("nvme_detected", False),
                    "event_severity": severity,
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "event_classes": d.get("event_classes", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "nvme_controller_reliability"
                    ),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "hardware_mce_edac_error":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            severity = d.get("event_severity", "uncorrected")
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Hardware MCE/EDAC {severity} error detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "mce_edac_detected": d.get("mce_edac_detected", False),
                    "event_severity": severity,
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "event_classes": d.get("event_classes", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "hardware_mce_edac"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "filesystem_io_error":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            severity = d.get("event_severity", "io_error")
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Filesystem/block-I/O {severity} error detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "fs_io_detected": d.get("fs_io_detected", False),
                    "event_severity": severity,
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "event_classes": d.get("event_classes", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "filesystem_io_error"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        raise ValueError(f"Unsupported evidence category: {cat}")


import diagnostic_rules as _diagnostic_rules  # noqa: E402

# Compatibility re-exports for existing syscheck imports.
AmdgpuResetFailRule = _diagnostic_rules.AmdgpuResetFailRule
AmbiguousObservationRuleError = _diagnostic_rules.AmbiguousObservationRuleError
BootDelayRule = _diagnostic_rules.BootDelayRule
BtrfsDeviceErrorRule = _diagnostic_rules.BtrfsDeviceErrorRule
BtrfsScrubStatusRule = _diagnostic_rules.BtrfsScrubStatusRule
DiagnosticEvaluation = _diagnostic_rules.DiagnosticEvaluation
DiagnosticRule = _diagnostic_rules.DiagnosticRule
DiagnosticRuleEngine = _diagnostic_rules.DiagnosticRuleEngine
DiagnosticRuleError = _diagnostic_rules.DiagnosticRuleError
DiagnosticRuleRegistry = _diagnostic_rules.DiagnosticRuleRegistry
DiagnosticRuleResult = _diagnostic_rules.DiagnosticRuleResult
DuplicateDiagnosticRuleError = _diagnostic_rules.DuplicateDiagnosticRuleError
DuplicateEvidenceError = _diagnostic_rules.DuplicateEvidenceError
DuplicateFindingError = _diagnostic_rules.DuplicateFindingError
FailedSystemUnitRule = _diagnostic_rules.FailedSystemUnitRule
FailedUserUnitRule = _diagnostic_rules.FailedUserUnitRule
FilesystemIoErrorRule = _diagnostic_rules.FilesystemIoErrorRule
GeneralSegfaultRule = _diagnostic_rules.GeneralSegfaultRule
GpuI915HangRule = _diagnostic_rules.GpuI915HangRule
GpuNvidiaXid79Rule = _diagnostic_rules.GpuNvidiaXid79Rule
HardwareMceEdacRule = _diagnostic_rules.HardwareMceEdacRule
KernelCountRule = _diagnostic_rules.KernelCountRule
KernelOomRule = _diagnostic_rules.KernelOomRule
KernelTaintRule = _diagnostic_rules.KernelTaintRule
MinorSegfaultRule = _diagnostic_rules.MinorSegfaultRule
PcieAerErrorRule = _diagnostic_rules.PcieAerErrorRule
NvmeControllerReliabilityRule = _diagnostic_rules.NvmeControllerReliabilityRule
StorageUsageRule = _diagnostic_rules.StorageUsageRule
UnsupportedObservationRuleError = _diagnostic_rules.UnsupportedObservationRuleError
WirePlumberSegfaultRule = _diagnostic_rules.WirePlumberSegfaultRule
build_default_rule_engine = _diagnostic_rules.build_default_rule_engine


class SysCheckEngine:
    """Główna klasa wykonująca diagnostykę i budująca raport."""

    def __init__(
        self,
        output_dir: str,
        quiet: bool = False,
        full: bool = False,
        classification_policy: FindingClassificationPolicy | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.quiet = quiet
        self.full = full
        self.classification_policy = (
            classification_policy or FindingClassificationPolicy()
        )
        self.start_time = datetime.datetime.now(datetime.timezone.utc)
        self.start_time_local = datetime.datetime.now()
        self.hostname: str = ""
        self.active_kernel: str = ""
        self.distro_id: str = "unknown"
        self.distro_config: dict = DISTRO_CONFIG.get("arch", DISTRO_CONFIG["arch"])
        self.report_lines: List[str] = []
        self.findings: List[Finding] = []
        self.observations: List[Observation] = []  # Stage 2: OBS
        self.recommendation_plan: Optional[RecommendationPlan] = None  # Stage 4: REC
        self.raw_diagnostics: List[RawDiagnostic] = []
        self.evidence_objects: List[Evidence] = []
        self.restrictions: List[str] = []
        self.commands_used: List[str] = []
        self._script_pids: List[str] = []

    # ── Logowanie ────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {msg}", file=sys.stderr, flush=True)

    def log_section(self, name: str) -> None:
        if not self.quiet:
            print(f"\n═══ {name} ═══", file=sys.stderr, flush=True)

    # ── Wykonanie komend ─────────────────────────────────────────
    def cmd(
        self,
        cmd: List[str],
        timeout: int = TIMEOUT_SHORT,
        env: Optional[Dict[str, str]] = None,
        optional_dependency: bool = False,
    ) -> CmdResult:
        self.commands_used.append(" ".join(cmd))
        return run_cmd(
            cmd, timeout=timeout, env=env, optional_dependency=optional_dependency
        )

    def cmd_ok(
        self,
        cmd: List[str],
        timeout: int = TIMEOUT_SHORT,
        env: Optional[Dict[str, str]] = None,
        fallback: str = "",
        optional_dependency: bool = False,
    ) -> str:
        result = self.cmd(
            cmd, timeout=timeout, env=env, optional_dependency=optional_dependency
        )
        if result.execution_status == "permission_denied":
            self.restrictions.append(f"Brak sudo: {cmd[0]}")
        return fallback if fallback else result.to_fallback_text()

    # ── Równoległe wykonanie grupy komend ────────────────────────
    def _parallel(self, tasks: Dict[str, Tuple[List[str], int]]) -> Dict[str, str]:
        """
        Uruchamia wiele komend równolegle. Zwraca słownik name->stdout.
        tasks: {nazwa: ([cmd, ...], timeout)}
        """
        results: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tasks))) as executor:
            future_map = {
                executor.submit(self.cmd_ok, cmd, timeout): name
                for name, (cmd, timeout) in tasks.items()
            }
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = f"(błąd równoległy: {exc})"
        return results

    # ── Równoległe wykonanie z CmdResult ─────────────────────────
    def _parallel_cmd(
        self, tasks: Dict[str, Tuple[List[str], int, bool]]
    ) -> Dict[str, CmdResult]:
        """
        Uruchamia wiele komend równolegle. Zwraca słownik name->CmdResult.
        tasks: {nazwa: ([cmd, ...], timeout, optional_dependency)}
        """
        results: Dict[str, CmdResult] = {}
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tasks))) as executor:
            future_map = {
                executor.submit(self.cmd, cmd, timeout, None, optional): name
                for name, (cmd, timeout, optional) in tasks.items()
            }
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    results[name] = future.result()
                except Exception as exc:
                    results[name] = CmdResult(
                        command="",
                        stdout="",
                        stderr=str(exc),
                        return_code=-4,
                        execution_status="error",
                    )
        return results

    # ── Detekcja dystrybucji ─────────────────────────────────────
    def detect_distro(self) -> None:
        """Wykrywa dystrybucję i wybiera odpowiednie komendy pakietów."""
        result = self.cmd(["cat", "/etc/os-release"])
        osr = result.stdout
        id_like = ""
        distro_id = ""

        if osr:
            for line in osr.split("\n"):
                if line.startswith("ID_LIKE="):
                    id_like = line.split("=", 1)[1].strip('"').lower()
                elif line.startswith("ID="):
                    distro_id = line.split("=", 1)[1].strip('"').lower()

        self.distro_id = distro_id or "unknown"

        if "arch" in id_like or distro_id in (
            "arch",
            "cachyos",
            "manjaro",
            "endeavouros",
        ):
            self.distro_config = DISTRO_CONFIG["arch"]
        elif "debian" in id_like or distro_id in (
            "debian",
            "ubuntu",
            "linuxmint",
            "pop",
        ):
            self.distro_config = DISTRO_CONFIG["debian"]
        elif (
            "rhel" in id_like
            or "fedora" in id_like
            or distro_id in ("fedora", "rhel", "centos", "almalinux", "rocky")
        ):
            self.distro_config = DISTRO_CONFIG["rhel"]
        else:
            self.distro_config = DISTRO_CONFIG["arch"]
            self.restrictions.append(
                f"Dystrybucja '{distro_id or 'unknown'}' nie została rozpoznana — "
                f"używam komend dla Arch Linux. Raport dotyczący pakietów może być niekompletny."
            )

    # ── Raport: podstawowe dane ──────────────────────────────────
    def collect_base_info(self) -> None:
        self.log_section("Identyfikacja środowiska")

        tasks = {
            "osr": (["cat", "/etc/os-release"], TIMEOUT_SHORT),
            "kernel": (["uname", "-r"], TIMEOUT_SHORT),
            "hostname": (["hostname"], TIMEOUT_SHORT),
            "uptime": (["uptime"], TIMEOUT_SHORT),
            "cmdline": (["cat", "/proc/cmdline"], TIMEOUT_SHORT),
            "boot_ls": (["ls", "-la", "/boot/"], TIMEOUT_SHORT),
            "mod_ls": (["ls", "-la", "/usr/lib/modules/"], TIMEOUT_SHORT),
            "niri_ver": (["niri", "--version"], TIMEOUT_SHORT),
        }
        r = self._parallel(tasks)

        osr = r["osr"]
        self.active_kernel = r["kernel"]
        self.hostname = r["hostname"] if r["hostname"] else "unknown"
        uptime = r["uptime"]
        cmdline = r["cmdline"]
        boot_list = r["boot_ls"]
        modules_list = r["mod_ls"]
        niri_ver = r["niri_ver"]

        os_info: Dict[str, str] = {}
        if osr:
            for line in osr.split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    os_info[k] = v.strip('"')
        pretty_name = os_info.get("PRETTY_NAME", "Linux (nieokreślony)")

        xdg_type = os.environ.get("XDG_SESSION_TYPE", "?")
        wayland_disp = os.environ.get("WAYLAND_DISPLAY", "?")
        xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "?")

        self.report_lines.append(heading(1, "Raport diagnostyczny syscheck"))
        self.report_lines.append(f"**Internal metadata:** `{AGENT_NAME}`  \n")
        self.report_lines.append(f"**Internal metadata:** `{MODEL_NAME}`  \n")
        self.report_lines.append(f"**Wersja skryptu:** `{SCRIPT_VERSION}`  \n")
        self.report_lines.append(
            f"**Data rozpoczęcia (UTC):** {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}  \n"
        )
        self.report_lines.append(
            f"**Data rozpoczęcia (lokalna):** {self.start_time_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  \n"
        )
        self.report_lines.append(f"**Aktywny kernel:** `{self.active_kernel}`  \n")
        self.report_lines.append(f"**Hostname:** `{self.hostname}`  \n")
        self.report_lines.append(
            f"**Dystrybucja:** {pretty_name} ({self.distro_config['name']})  \n"
        )
        self.report_lines.append(f"**Uptime:** {uptime}  \n")
        self.report_lines.append("\n---\n\n")

        self.report_lines.append(heading(2, "1. Identyfikacja środowiska"))
        self.report_lines.append(heading(3, "System operacyjny"))
        self.report_lines.append(codeblock(osr if osr else "(brak danych)"))
        self.report_lines.append(f"- **Dystrybucja:** {pretty_name}\n")
        self.report_lines.append(f"- **Wykryty typ:** {self.distro_config['name']}\n")
        self.report_lines.append(f"- **Kernel:** `{self.active_kernel}`\n")
        self.report_lines.append(f"- **Uptime:** {uptime}\n\n")

        self.report_lines.append(heading(3, "Parametry kernela"))
        self.report_lines.append(codeblock(cmdline))

        self.report_lines.append(heading(3, "Środowisko graficzne"))
        self.report_lines.append(f"- **Typ sesji:** `{xdg_type}`\n")
        self.report_lines.append(f"- **Wayland display:** `{wayland_disp}`\n")
        self.report_lines.append(f"- **Desktop:** `{xdg_desktop}`\n")
        self.report_lines.append(f"- **Niri:** {niri_ver}\n\n")

        # Zainstalowane kernele (z /usr/lib/modules i /boot)
        bootable_versions = _get_bootable_kernels_from_modules()
        bootable_kernels = _get_bootable_kernels_from_boot()
        self.report_lines.append(heading(3, "Zainstalowane moduły kernel (wersje)"))
        self.report_lines.append(codeblock(modules_list))
        self.report_lines.append(heading(3, "/boot (obrazy kernel)"))
        self.report_lines.append(codeblock(boot_list))

        # Dodaj podsumowanie kernel
        self.report_lines.append(
            f"**Wersje w /usr/lib/modules:** {len(bootable_versions)}\n"
        )
        self.report_lines.append(f"**Obrazy w /boot:** {len(bootable_kernels)}\n")

    # ── Raport: CPU, RAM, zram, procesy ──────────────────────────
    def collect_resources(self) -> None:
        self.log_section("Stan zasobów")

        tasks = {
            "lscpu": (["lscpu"], TIMEOUT_SHORT),
            "free_h": (["free", "-h"], TIMEOUT_SHORT),
            "zramctl": (["zramctl"], TIMEOUT_SHORT),
            "loadavg": (["cat", "/proc/loadavg"], TIMEOUT_SHORT),
            "governor": (
                [
                    "bash",
                    "-c",
                    "set -o pipefail; cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | sort | uniq -c",
                ],
                TIMEOUT_SHORT,
            ),
            "ps_cpu": (["ps", "aux", "--sort=-%cpu"], TIMEOUT_MEDIUM),
            "ps_mem": (["ps", "aux", "--sort=-%mem"], TIMEOUT_MEDIUM),
            "sensors": (["sensors"], TIMEOUT_MEDIUM),
        }
        r = self._parallel(tasks)

        self.report_lines.append(heading(2, "2. CPU, RAM, zram i procesy"))
        self.report_lines.append(heading(3, "CPU"))
        self.report_lines.append(codeblock(safestr(r["lscpu"][:3000], full=self.full)))

        self.report_lines.append(heading(3, "Load average"))
        self.report_lines.append(codeblock(r["loadavg"]))

        self.report_lines.append(heading(3, "CPU governor"))
        self.report_lines.append(codeblock(r["governor"]))

        self.report_lines.append(heading(3, "RAM i swap"))
        self.report_lines.append(codeblock(r["free_h"]))

        self.report_lines.append(heading(3, "ZRAM"))
        self.report_lines.append(codeblock(r["zramctl"]))

        self.report_lines.append(heading(3, "Top CPU (pierwsze 15)"))
        self.report_lines.append(
            codeblock(safestr("\n".join(r["ps_cpu"].split("\n")[:16]), full=self.full))
        )

        self.report_lines.append(heading(3, "Top MEM (pierwsze 15)"))
        self.report_lines.append(
            codeblock(safestr("\n".join(r["ps_mem"].split("\n")[:16]), full=self.full))
        )

        self.report_lines.append(heading(3, "Sensory / temperatury"))
        sensors_raw = r["sensors"]
        sensors_filtered = _filter_invalid_temperatures(sensors_raw)
        self.report_lines.append(codeblock(sensors_filtered))

        if sensors_raw != sensors_filtered:
            n_invalid = sensors_raw.count("\n") - sensors_filtered.count("\n")
            self.report_lines.append(
                f"ℹ️ Pominięto {n_invalid} nieprawidłowych odczytów czujników "
                f"(wartości poniżej {INVALID_TEMPERATURE_CELSIUS}°C - niepodłączone czujniki).\n\n"
            )

    # ── Raport: Dyski, NVMe, Btrfs ───────────────────────────────
    def collect_storage(self) -> None:
        self.log_section("Dyski, NVMe, Btrfs")

        tasks_cmd = {
            "lsblk": (
                ["lsblk", "-o", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,LABEL,MODEL"],
                TIMEOUT_SHORT,
                False,
            ),
            "df_h": (["df", "-h"], TIMEOUT_SHORT, False),
            "df_i": (["df", "-i"], TIMEOUT_SHORT, False),
            "btrfs_show": (["btrfs", "filesystem", "show", "/"], TIMEOUT_SHORT, False),
            "btrfs_df": (["btrfs", "filesystem", "df", "/"], TIMEOUT_SHORT, False),
            "btrfs_stats": (["btrfs", "device", "stats", "/"], TIMEOUT_SHORT, False),
            "btrfs_scrub": (["btrfs", "scrub", "status", "/"], TIMEOUT_SHORT, False),
            "nvme_list": (["nvme", "list"], TIMEOUT_SHORT, True),
        }
        r = self._parallel_cmd(tasks_cmd)

        self.report_lines.append(heading(2, "3. Dyski, NVMe i Btrfs"))
        self.report_lines.append(heading(3, "Urządzenia blokowe"))
        self.report_lines.append(codeblock(r["lsblk"].to_fallback_text()))
        self.report_lines.append(heading(3, "Systemy plików (df -h)"))
        self.report_lines.append(codeblock(r["df_h"].to_fallback_text()))
        self.report_lines.append(heading(3, "Inode (df -i)"))
        self.report_lines.append(codeblock(r["df_i"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — filesystem show"))
        self.report_lines.append(codeblock(r["btrfs_show"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — filesystem df"))
        self.report_lines.append(codeblock(r["btrfs_df"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — device stats"))
        self.report_lines.append(codeblock(r["btrfs_stats"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — scrub status"))
        self.report_lines.append(codeblock(r["btrfs_scrub"].to_fallback_text()))
        self.report_lines.append(heading(3, "NVMe list"))
        nvme_result = r["nvme_list"]
        if nvme_result.execution_status == "not_found":
            self.report_lines.append(
                "(diagnostyczne narzędzie NVMe nie jest zainstalowane – "
                "brak wpływu na działanie systemu)\n\n"
            )
        else:
            self.report_lines.append(codeblock(nvme_result.to_fallback_text()))

        # Analiza Btrfs
        btrfs_show = r["btrfs_show"]
        btrfs_stats = r["btrfs_stats"]
        btrfs_scrub = r["btrfs_scrub"]

        # Sprawdź czy Btrfs wymaga roota
        for name, result in [
            ("show", btrfs_show),
            ("stats", btrfs_stats),
            ("scrub", btrfs_scrub),
        ]:
            status = _classify_btrfs_status(result)
            if status == "permission_denied":
                self.restrictions.append(
                    f"Btrfs {name} — wymaga sudo. "
                    f"Nie można zweryfikować stanu filesystemu Btrfs bez podwyższonych uprawnień."
                )

        # Analiza Btrfs device stats (tylko jeśli mamy dane)
        if btrfs_stats.execution_status == "ok" and btrfs_stats.stdout:
            has_errors = False
            error_counters: Dict[str, int] = {}
            for line in btrfs_stats.stdout.split("\n"):
                if "_errs" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            value = int(parts[-1])
                            if value != 0:
                                has_errors = True
                                error_counters[parts[0]] = value
                        except (ValueError, IndexError):
                            pass
            if has_errors:
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="BTRFS-ERR-001",
                        category="btrfs_error",
                        payload={
                            "device_error_counters": dict(error_counters),
                        },
                    )
                )
            if not has_errors:
                self.report_lines.append(
                    "✅ Liczniki błędów Btrfs: wszystkie zerowe.\n\n"
                )

        # Analiza Btrfs scrub status
        scrub_status = _classify_btrfs_status(btrfs_scrub)
        if scrub_status == "no_scrub":
            self.raw_diagnostics.append(
                RawDiagnostic(
                    source_id="BTRFS-SCRUB-001",
                    category="btrfs_scrub",
                    payload={"scrub_status": scrub_status},
                )
            )
        elif scrub_status == "permission_denied":
            self.restrictions.append(
                "Btrfs scrub status — wymaga sudo. Nie można zweryfikować czy "
                "skrubowanie było kiedykolwiek wykonane."
            )

        # Analiza użycia storage
        if r["df_h"].is_ok():
            usage = _parse_storage_usage(r["df_h"].stdout)
            for mount, pct in usage:
                if mount == "/" or mount.startswith("/dev/"):
                    if pct >= STORAGE_CRITICAL_PERCENT:
                        self.raw_diagnostics.append(
                            RawDiagnostic(
                                source_id="STORAGE-USAGE-CRITICAL",
                                category="storage_usage",
                                payload={
                                    "mountpoint": mount,
                                    "usage_percent": pct,
                                    "threshold_state": "critical",
                                },
                            )
                        )
                    elif pct >= STORAGE_WARNING_PERCENT:
                        self.raw_diagnostics.append(
                            RawDiagnostic(
                                source_id="STORAGE-USAGE-WARNING",
                                category="storage_usage",
                                payload={
                                    "mountpoint": mount,
                                    "usage_percent": pct,
                                    "threshold_state": "warning",
                                },
                            )
                        )

    # ── Raport: Kernel i sprzęt ──────────────────────────────────
    def collect_kernel_hw(self) -> None:
        self.log_section("Kernel i sprzęt")

        # Zbierz PIDy skryptu przed rozpoczęciem logowania
        self._script_pids = _get_script_pids()

        tasks_cmd = {
            "dmesg_restrict": (
                ["cat", "/proc/sys/kernel/dmesg_restrict"],
                TIMEOUT_SHORT,
                False,
            ),
            "kernel_errors": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_KERNEL_ERROR,
                    tail_lines=50,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "segfaults": (
                _journal_filter_command(
                    "journalctl -b --no-pager 2>/dev/null", [RE_SEGFAULT]
                ),
                TIMEOUT_LONG,
                False,
            ),
            "firmware_msgs": (
                _oom_collector_command(
                    "journalctl -b --no-pager 2>/dev/null",
                    RE_FIRMWARE,
                    tail_lines=20,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "oom_events": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_OOM,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "gpu_i915_hang": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_GPU_I915_HANG,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "amdgpu_reset_fail": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_AMDGPU_RESET_FAIL,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "gpu_nvidia_xid_79": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_NVIDIA_XID_79,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "pcie_aer": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_PCIE_AER,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "nvme_controller_reliability": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_NVME_CONTROLLER_RELIABILITY,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "hardware_mce_edac": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_HARDWARE_MCE_EDAC,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "filesystem_io_error": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_FILESYSTEM_IO_ERROR,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "lspci": (["lspci", "-k"], TIMEOUT_SHORT, False),
            "lsusb": (["lsusb"], TIMEOUT_SHORT, False),
        }
        r = self._parallel_cmd(tasks_cmd)

        dmesg_restrict_result = r["dmesg_restrict"]
        kernel_errors_result = r["kernel_errors"]
        segfaults_result = r["segfaults"]
        firmware_msgs_result = r["firmware_msgs"]
        oom_events_result = r["oom_events"]
        gpu_i915_hang_result = r["gpu_i915_hang"]
        amdgpu_reset_fail_result = r["amdgpu_reset_fail"]
        gpu_nvidia_xid_79_result = r["gpu_nvidia_xid_79"]
        pcie_aer_result = r.get("pcie_aer")
        nvme_controller_reliability_result = r.get("nvme_controller_reliability")
        hardware_mce_edac_result = r.get("hardware_mce_edac")
        filesystem_io_error_result = r.get("filesystem_io_error")
        lspci_result = r["lspci"]
        lsusb_result = r["lsusb"]

        self.report_lines.append(heading(2, "4. Kernel, sprzęt i sterowniki"))
        self.report_lines.append(heading(3, "Kernel log (błędy/ostrzeżenia)"))
        kernel_errors_out = _filter_own_journal_entries(
            kernel_errors_result.to_fallback_text()
        )
        self.report_lines.append(
            codeblock(kernel_errors_out if kernel_errors_out else "(brak)")
        )
        self.report_lines.append(heading(3, "Segfaulty z bieżącego bootu"))
        segfaults_filtered = _filter_own_journal_entries(
            segfaults_result.to_fallback_text()
        )
        segfaults_dedup = _deduplicate_journal_lines(segfaults_filtered)
        self.report_lines.append(
            codeblock(segfaults_dedup if segfaults_dedup else "(brak)")
        )
        self.report_lines.append(heading(3, "Firmware / microcode"))
        firmware_filtered = _filter_own_journal_entries(
            firmware_msgs_result.to_fallback_text()
        )
        self.report_lines.append(
            codeblock(firmware_filtered if firmware_filtered else "(brak)")
        )
        self.report_lines.append(heading(3, "dmesg_restrict"))
        self.report_lines.append(
            f"`dmesg_restrict` = {dmesg_restrict_result.to_fallback_text()}\n"
        )
        if (
            dmesg_restrict_result.is_ok()
            and dmesg_restrict_result.stdout.strip() == "1"
        ):
            self.restrictions.append(
                "dmesg_restrict=1 — bezpośredni dmesg wymaga sudo."
            )
        self.report_lines.append(heading(3, "lspci -k"))
        self.report_lines.append(
            codeblock(
                safestr(lspci_result.to_fallback_text(), TRUNCATE_LSPCI, full=self.full)
            )
        )
        self.report_lines.append(heading(3, "lsusb"))
        self.report_lines.append(codeblock(lsusb_result.to_fallback_text()))

        # Analiza segfaultów — deduplikacja i poprawne zliczanie
        unique_segfault_count = _count_unique_segfaults(segfaults_result.stdout)
        if unique_segfault_count >= SEGFAULT_ALERT_THRESHOLD:
            # Sprawdź czy wszystkie segfaulty dotyczą jednego procesu/biblioteki
            all_wireplumber = True
            for line in segfaults_dedup.split("\n"):
                if (
                    "kernel:" in line
                    and "segfault" in line.lower()
                    and "wireplumber" not in line
                    and "libspa-libcamera" not in line
                ):
                    all_wireplumber = False
                    break

            if all_wireplumber and unique_segfault_count <= 10:
                # Wireplumber/libcamera segfault
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="SEGFAULT-WP-001",
                        category="segfault",
                        payload=_capture_payload(
                            segfaults_result,
                            {
                                "segfault_type": "wireplumber",
                                "count": unique_segfault_count,
                            },
                        ),
                    )
                )
            else:
                # Poważniejsze segfaulty — wiele procesów lub nieznana przyczyna
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="SEGFAULT-SYS-001",
                        category="segfault",
                        payload=_capture_payload(
                            segfaults_result,
                            {
                                "segfault_type": "system_wide",
                                "count": unique_segfault_count,
                            },
                        ),
                    )
                )
        elif unique_segfault_count > 0:
            self.raw_diagnostics.append(
                RawDiagnostic(
                    source_id="SEGFAULT-MIN-001",
                    category="segfault_minor",
                    payload=_capture_payload(
                        segfaults_result,
                        {
                            "count": unique_segfault_count,
                        },
                    ),
                )
            )

        # Sprawdź taint — używamy precyzyjnego wzorca 'Tainted:' zamiast
        # substring match by uniknąć false positives na 'Not tainted' itp.
        if kernel_errors_result.is_ok() and re.search(
            r"\bTainted:\s", kernel_errors_result.stdout, re.IGNORECASE
        ):
            self.raw_diagnostics.append(
                RawDiagnostic(
                    source_id="KERNEL-TAINT-001",
                    category="tainted",
                    payload=_capture_payload(kernel_errors_result, {"tainted": True}),
                )
            )

        # Sprawdź OOM — dedykowane zapytanie z dokładnymi markerami
        if oom_events_result.is_ok() and oom_events_result.stdout.strip():
            oom_lines = oom_events_result.stdout.split("\n")
            oom_matching = [
                line
                for line in oom_lines
                if re.search(RE_OOM, line, re.IGNORECASE)
                and "memory cgroup" not in line.lower()
            ]
            if oom_matching:
                # Klasyfikuj dopasowane linie
                all_classes = []
                for ml in oom_matching:
                    ml_lower = ml.lower()
                    if "invoked oom-killer" in ml_lower:
                        all_classes.append("oom_invocation")
                    if "oom-killer:" in ml_lower:
                        all_classes.append("oom_killer_marker")
                    if "out of memory: killed process" in ml_lower:
                        all_classes.append("oom_kill_outcome")
                # Deduplikuj klasy, zachowując kolejność pierwszego wystąpienia
                seen_classes = set()
                match_classes = []
                for cls in all_classes:
                    if cls not in seen_classes:
                        seen_classes.add(cls)
                        match_classes.append(cls)

                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="KERNEL-OOM-001",
                        category="oom_event",
                        payload=_capture_payload(
                            oom_events_result,
                            {
                                "oom_detected": True,
                                "matched_lines": oom_matching[:20],
                                "match_count": len(oom_matching),
                                "match_classes": match_classes,
                                "journal_scope": "current_boot_kernel",
                                "source_query": "oom_events",
                            },
                        ),
                    )
                )

        # Sprawdź i915 GPU HANG — dedykowane zapytanie z dokładnym markerem
        if gpu_i915_hang_result.is_ok() and gpu_i915_hang_result.stdout.strip():
            hang_lines = gpu_i915_hang_result.stdout.split("\n")
            hang_matching = [
                line
                for line in hang_lines
                if re.search(RE_GPU_I915_HANG, line, re.IGNORECASE)
            ]
            if hang_matching:
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="GPU-I915-HANG-001",
                        category="gpu_i915_hang",
                        payload=_capture_payload(
                            gpu_i915_hang_result,
                            {
                                "hang_detected": True,
                                "matched_lines": hang_matching[:20],
                                "match_count": len(hang_matching),
                                "driver": "i915",
                                "driver_attribution_source": "in_message",
                                "journal_scope": "current_boot_kernel",
                                "source_query": "gpu_i915_hang",
                            },
                        ),
                    )
                )

        # Sprawdź AMDGPU reset failed — dedykowane zapytanie z dokładnym markerem
        if amdgpu_reset_fail_result.is_ok() and amdgpu_reset_fail_result.stdout.strip():
            reset_lines = amdgpu_reset_fail_result.stdout.split("\n")
            reset_matching = [
                line
                for line in reset_lines
                if re.search(RE_AMDGPU_RESET_FAIL, line, re.IGNORECASE)
            ]
            if reset_matching:
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="AMDGPU-RESET-FAIL-001",
                        category="amdgpu_reset_fail",
                        payload=_capture_payload(
                            amdgpu_reset_fail_result,
                            {
                                "reset_failure_detected": True,
                                "matched_lines": reset_matching[:20],
                                "match_count": len(reset_matching),
                                "driver": "amdgpu",
                                "driver_attribution_source": "in_message",
                                "journal_scope": "current_boot_kernel",
                                "source_query": "amdgpu_reset_fail",
                            },
                        ),
                    )
                )

        # Sprawdź NVIDIA Xid 79 — dedykowane zapytanie z dokładnym kodem
        if gpu_nvidia_xid_79_result.is_ok() and gpu_nvidia_xid_79_result.stdout.strip():
            xid79_lines = gpu_nvidia_xid_79_result.stdout.split("\n")
            xid79_matching = [
                line
                for line in xid79_lines
                if re.search(RE_NVIDIA_XID_79, line, re.IGNORECASE)
            ]
            if xid79_matching:
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="GPU-NVIDIA-XID-79-001",
                        category="gpu_nvidia_xid_79",
                        payload=_capture_payload(
                            gpu_nvidia_xid_79_result,
                            {
                                "xid_detected": True,
                                "xid_code": 79,
                                "matched_lines": xid79_matching[:20],
                                "match_count": len(xid79_matching),
                                "driver": "nvidia",
                                "driver_attribution_source": "in_message",
                                "journal_scope": "current_boot_kernel",
                                "source_query": "gpu_nvidia_xid_79",
                            },
                        ),
                    )
                )

        # Sprawdź PCIe AER — tylko jawne komunikaty błędów z bieżącego bootu.
        if (
            pcie_aer_result
            and pcie_aer_result.is_ok()
            and pcie_aer_result.stdout.strip()
        ):
            aer_matching = [
                line
                for line in pcie_aer_result.stdout.split("\n")
                if re.search(RE_PCIE_AER, line, re.IGNORECASE)
            ]
            severities = [
                severity
                for line in aer_matching
                if (severity := _pcie_aer_severity(line)) is not None
            ]
            if severities:
                aer_severity = max(
                    severities,
                    key={"corrected": 1, "non_fatal": 2, "fatal": 3}.get,
                )
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="PCIE-AER-001",
                        category="pcie_aer_error",
                        payload=_capture_payload(
                            pcie_aer_result,
                            {
                                "aer_detected": True,
                                "aer_severity": aer_severity,
                                "matched_lines": aer_matching[:20],
                                "match_count": len(aer_matching),
                                "journal_scope": "current_boot_kernel",
                                "source_query": "pcie_aer",
                            },
                        ),
                    )
                )

        # Sprawdź niezawodność kontrolera NVMe — tylko jawne zdarzenia bieżącego bootu.
        if (
            nvme_controller_reliability_result
            and nvme_controller_reliability_result.is_ok()
            and nvme_controller_reliability_result.stdout.strip()
        ):
            nvme_matching = [
                line
                for line in nvme_controller_reliability_result.stdout.split("\n")
                if re.search(RE_NVME_CONTROLLER_RELIABILITY, line, re.IGNORECASE)
            ]
            severities = [
                severity
                for line in nvme_matching
                if (severity := _nvme_controller_reliability_severity(line)) is not None
            ]
            if severities:
                event_severity = max(
                    severities,
                    key={"timeout_or_reset": 1, "reset_failure": 2}.get,
                )
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="NVME-CONTROLLER-RESET-001",
                        category="nvme_controller_reliability",
                        payload=_capture_payload(
                            nvme_controller_reliability_result,
                            {
                                "nvme_detected": True,
                                "event_severity": event_severity,
                                "matched_lines": nvme_matching[:20],
                                "match_count": len(nvme_matching),
                                "event_classes": list(dict.fromkeys(severities)),
                                "journal_scope": "current_boot_kernel",
                                "source_query": "nvme_controller_reliability",
                            },
                        ),
                    )
                )

        # Sprawdź błędy sprzętowe MCE / EDAC — tylko jawne komunikaty z bieżącego bootu.
        if (
            hardware_mce_edac_result
            and hardware_mce_edac_result.is_ok()
            and hardware_mce_edac_result.stdout.strip()
        ):
            mce_edac_matching = [
                line
                for line in hardware_mce_edac_result.stdout.split("\n")
                if re.search(RE_HARDWARE_MCE_EDAC, line, re.IGNORECASE)
            ]
            severities = [
                severity
                for line in mce_edac_matching
                if (severity := _hardware_mce_edac_severity(line)) is not None
            ]
            if severities:
                event_severity = max(
                    severities,
                    key={"corrected": 1, "uncorrected": 2}.get,
                )
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="HW-MCE-EDAC-001",
                        category="hardware_mce_edac_error",
                        payload=_capture_payload(
                            hardware_mce_edac_result,
                            {
                                "mce_edac_detected": True,
                                "event_severity": event_severity,
                                "matched_lines": mce_edac_matching[:20],
                                "match_count": len(mce_edac_matching),
                                "event_classes": list(dict.fromkeys(severities)),
                                "journal_scope": "current_boot_kernel",
                                "source_query": "hardware_mce_edac",
                            },
                        ),
                    )
                )

        # Sprawdź błędy I/O systemu plików / podsystemu blokowego — tylko jawne komunikaty z bieżącego bootu.
        if (
            filesystem_io_error_result
            and filesystem_io_error_result.is_ok()
            and filesystem_io_error_result.stdout.strip()
        ):
            fs_io_matching = [
                line
                for line in filesystem_io_error_result.stdout.split("\n")
                if re.search(RE_FILESYSTEM_IO_ERROR, line, re.IGNORECASE)
            ]
            severities = [
                severity
                for line in fs_io_matching
                if (severity := _filesystem_io_error_severity(line)) is not None
            ]
            if severities:
                event_severity = max(
                    severities,
                    key={"io_error": 1, "critical_or_fatal": 2}.get,
                )
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="FS-IO-ERROR-001",
                        category="filesystem_io_error",
                        payload=_capture_payload(
                            filesystem_io_error_result,
                            {
                                "fs_io_detected": True,
                                "event_severity": event_severity,
                                "matched_lines": fs_io_matching[:20],
                                "match_count": len(fs_io_matching),
                                "event_classes": list(dict.fromkeys(severities)),
                                "journal_scope": "current_boot_kernel",
                                "source_query": "filesystem_io_error",
                            },
                        ),
                    )
                )

    # ── Raport: Systemd ──────────────────────────────────────────
    def collect_systemd(self) -> None:
        self.log_section("Systemd i usługi")

        tasks_cmd = {
            "sys_failed": (
                ["systemctl", "--failed", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "usr_failed": (
                ["systemctl", "--user", "--failed", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "analyze": (["systemd-analyze"], TIMEOUT_SHORT, False),
            "blame": (["systemd-analyze", "blame", "--no-pager"], TIMEOUT_SHORT, False),
            "critical": (
                ["systemd-analyze", "critical-chain", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "timers": (
                ["systemctl", "list-timers", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "usr_timers": (
                ["systemctl", "--user", "list-timers", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "auto_restart": (
                ["systemctl", "list-units", "--state=auto-restart", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "restarting": (
                ["systemctl", "list-units", "--state=restarting", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
        }
        r = self._parallel_cmd(tasks_cmd)

        self.report_lines.append(heading(2, "5. Systemd i proces uruchamiania"))
        for title, key in [
            ("systemctl --failed (system)", "sys_failed"),
            ("systemctl --user --failed", "usr_failed"),
            ("systemd-analyze (czas bootu)", "analyze"),
            ("systemd-analyze blame (top 20)", "blame"),
            ("systemd-analyze critical-chain", "critical"),
            ("Timery systemowe", "timers"),
            ("Timery użytkownika", "usr_timers"),
            ("Usługi auto-restart", "auto_restart"),
            ("Usługi restartujące się", "restarting"),
        ]:
            val = r[key].to_fallback_text()
            if key == "blame":
                val = "\n".join(val.split("\n")[:20])
            self.report_lines.append(heading(3, title))
            self.report_lines.append(codeblock(val))

        # Analiza system failed units (system)
        sys_failed = r["sys_failed"]
        if sys_failed.is_ok() and self._has_failed_units(sys_failed.stdout):
            _sys_units = self._extract_failed_unit_names(sys_failed.stdout)
            self.raw_diagnostics.append(
                RawDiagnostic(
                    source_id="SYSD-SYS-FAIL-001",
                    category="systemd_failed",
                    payload={"scope": "system", "units": _sys_units},
                )
            )

        # Analiza user failed units
        usr_failed = r["usr_failed"]
        if usr_failed.is_ok() and self._has_failed_units(usr_failed.stdout):
            _failed_units = self._extract_failed_unit_names(usr_failed.stdout)
            self.raw_diagnostics.append(
                RawDiagnostic(
                    source_id="SYSD-USR-FAIL-001",
                    category="systemd_failed",
                    payload={"scope": "user", "units": _failed_units},
                )
            )

        # Analiza boot time — korelacja blame z critical-chain
        blame_out = r["blame"].to_fallback_text()
        critical_out = r["critical"].to_fallback_text()
        analyze_out = r["analyze"].to_fallback_text()

        # Track fstrim critical-chain membership when available
        # None = unknown, True = in critical chain, False = outside critical chain
        fstrim_in_critical_chain = None

        if analyze_out:
            # Parsowanie czasu userspace i całkowitego czasu bootu
            # Format: "... X.XXXs (userspace) = Y.YYYs"
            userspace_match = re.search(r"([\d.]+)s\s*\(userspace\)", analyze_out)
            total_match = re.search(r"=\s*([\d.]+)s", analyze_out)
            blame_match = re.search(r"(\S+)\.service\s+([\d.]+)s", blame_out)

            if blame_match and userspace_match:
                # Sprawdź czy fstrim.service jest na liście blame ale nie w critical-chain
                fstrim_in_blame = False
                fstrim_time = 0.0
                for line in blame_out.split("\n"):
                    if "fstrim.service" in line:
                        fstrim_in_blame = True
                        try:
                            fstrim_time = float(line.split()[-1].rstrip("s"))
                        except (ValueError, IndexError):
                            pass

                # Determine fstrim critical-chain membership for structured payload
                if fstrim_in_blame:
                    fstrim_in_critical_chain = "fstrim" in critical_out

                if fstrim_in_blame and fstrim_time > 10:
                    if not fstrim_in_critical_chain:
                        self.report_lines.append(
                            "ℹ️ **fstrim.service** wykazuje długi czas ("
                            f"{fstrim_time}s) w `systemd-analyze blame`, "
                            "ale NIE znajduje się w ścieżce krytycznej bootu "
                            "(`systemd-analyze critical-chain`). "
                            "Jest to usługa wyzwalana timerem po uruchomieniu systemu "
                            "i nie wpływa na czas startu systemu.\n\n"
                        )

        # Analiza graficznego czasu bootu
        if userspace_match:
            userspace_time = float(userspace_match.group(1))
            if userspace_time > 30:
                payload = {
                    "userspace_time": userspace_time,
                    "threshold": 30.0,
                }
                if total_match:
                    payload["total_seconds"] = float(total_match.group(1))
                if fstrim_in_critical_chain is not None:
                    payload["fstrim_in_critical_chain"] = fstrim_in_critical_chain
                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="BOOT-SLOW-001", category="boot_time", payload=payload
                    )
                )

    # ── Pomocnicze do analizy jednostek systemd ──────────────────
    @staticmethod
    def _has_failed_units(output: str) -> bool:
        """Sprawdza czy są jakieś failed jednostki."""
        return "●" in output and "failed" in output.lower() and "0 loaded" not in output

    @staticmethod
    def _extract_failed_unit_names(output: str) -> List[str]:
        """Wyciąga nazwy jednostek z outputu systemctl --failed."""
        units = []
        for line in output.split("\n"):
            if line.strip().startswith("●"):
                parts = line.split()
                if len(parts) >= 2:
                    # Format: ● UNIT LOAD ACTIVE SUB DESCRIPTION
                    unit_name = parts[1]
                    units.append(unit_name)
        return units

    # ── Raport: Pakiety ──────────────────────────────────────────
    def collect_packages(self) -> None:
        self.log_section("Pakiety i spójność")

        cfg = self.distro_config
        tasks_cmd = {
            "orphans": (cfg["pkg_list_orphans"], cfg["pkg_timeout"], False),
            "foreign": (cfg["pkg_list_foreign"], cfg["pkg_timeout"], False),
            "kernels": (cfg["pkg_query_kernels"], cfg["pkg_timeout"], False),
        }
        r = self._parallel_cmd(tasks_cmd)

        orphans_result = r["orphans"]
        foreign_result = r["foreign"]
        kernels_result = r["kernels"]

        self.report_lines.append(heading(2, "6. Pakiety i spójność systemu"))
        self.report_lines.append(heading(3, "Pakiety osierocone"))

        # Obsługa pacman -Qdt: rc=1 z pustym stdout oznacza "brak pakietów osieroconych"
        if orphans_result.execution_status == "empty_ok" or (
            orphans_result.return_code == 1
            and not orphans_result.stdout
            and not orphans_result.stderr
        ):
            self.report_lines.append("(brak pakietów osieroconych)\n\n")
            self.restrictions.append(
                "Pacman -Qdt zwrócił rc=1 z pustym wyjściem — "
                "oznacza to brak pakietów osieroconych, nie błąd polecenia."
            )
        else:
            self.report_lines.append(codeblock(orphans_result.to_fallback_text()))

        self.report_lines.append(heading(3, "Pakiety AUR / obce"))
        if foreign_result.is_ok() or foreign_result.execution_status == "empty_ok":
            aur_count = len(
                [line for line in foreign_result.stdout.split("\n") if line.strip()]
            )
            self.report_lines.append(f"Liczba pakietów obcych: **{aur_count}**\n\n")
            self.report_lines.append(
                codeblock(
                    safestr(
                        foreign_result.stdout, TRUNCATE_FOREIGN_PKGS, full=self.full
                    )
                )
            )
        else:
            self.report_lines.append(codeblock(foreign_result.to_fallback_text()))

        self.report_lines.append(heading(3, "Zainstalowane kernele"))
        if kernels_result.is_ok():
            self.report_lines.append(codeblock(kernels_result.stdout))

            # Poprawne zliczanie kernel - bez nagłówków i firmware
            bootable_count, total_count, bootable_list = _count_kernel_packages(
                kernels_result.stdout
            )

            # Dodatkowa informacja z /usr/lib/modules i /boot
            modules_versions = _get_bootable_kernels_from_modules()
            boot_images = _get_bootable_kernels_from_boot()

            self.report_lines.append(
                f"**Bootowalne pakiety kernel:** {bootable_count}\n"
                f"**Rzeczywiste wersje w /usr/lib/modules:** {len(modules_versions)}\n"
                f"**Obrazy kernel w /boot:** {len(boot_images)}\n"
            )

            if len(bootable_list) > 0:
                self.report_lines.append(
                    f"**Zainstalowane:** {', '.join(bootable_list)}\n\n"
                )

            if bootable_count > MAX_RECOMMENDED_KERNELS:
                # Określ aktualny kernel
                current = self.active_kernel
                _removable = [
                    k
                    for k in bootable_list
                    if k.split(" ")[0] != current
                    and not current.startswith(k.split(" ")[0])
                ]

                _detail = (
                    f"Aktualnie uruchomiony kernel: {current}\n"
                    f"Zainstalowane pakiety kernel ({bootable_count}): "
                    f"{', '.join(bootable_list)}\n"
                    f"Zalecane jest zachowanie maksymalnie {MAX_RECOMMENDED_KERNELS} "
                    f"kernel (aktualny + jeden zapasowy)."
                )

                _remediation = (
                    "Aby usunąć nieużywane kernele, sprawdź najpierw który jest aktywny:\n"
                    "1. `uname -r` — sprawdź aktywny kernel\n"
                    "2. `pacman -Q linux-cachyos linux-lts` — lista kernel\n"
                    "3. Usuń nieużywane: `sudo pacman -Rs <nieużywany-kernel>`\n\n"
                    "UWAGA: Nie usuwaj kernela na którym aktualnie pracujesz! "
                    "Zawsze zostaw co najmniej jeden zapasowy kernel."
                )

                self.raw_diagnostics.append(
                    RawDiagnostic(
                        source_id="KRNL-INFO-001",
                        category="kernel_count",
                        payload={"count": bootable_count},
                    )
                )
        else:
            self.report_lines.append(codeblock(kernels_result.to_fallback_text()))

    # ── Raport: Grafika ──────────────────────────────────────────
    def collect_graphics(self) -> None:
        self.log_section("Warstwa graficzna")

        tasks_cmd = {
            "drm_vendor": (
                ["bash", "-c", "cat /sys/class/drm/card*/device/vendor 2>/dev/null"],
                TIMEOUT_SHORT,
                False,
            ),
            "drm_device": (
                ["bash", "-c", "cat /sys/class/drm/card*/device/device 2>/dev/null"],
                TIMEOUT_SHORT,
                False,
            ),
            "drm_ls": (["ls", "/sys/class/drm/"], TIMEOUT_SHORT, False),
            "niri_out": (["niri", "msg", "outputs"], TIMEOUT_SHORT, False),
            "gfx_logs": (
                _journal_filter_command(
                    "journalctl -b --no-pager 2>/dev/null",
                    [RE_GFX_ERROR, "error|fail|warn"],
                    tail_lines=30,
                ),
                TIMEOUT_LONG,
                False,
            ),
        }
        r = self._parallel_cmd(tasks_cmd)

        self.report_lines.append(heading(2, "7. Warstwa graficzna"))
        self.report_lines.append(heading(3, "DRM / GPU"))
        self.report_lines.append(f"- Vendor: `{r['drm_vendor'].to_fallback_text()}`\n")

        drm_device = r["drm_device"]
        if drm_device.execution_status == "error" and drm_device.return_code == 1:
            # rc=1 dla cat gdy plik nie istnieje lub brak dostępu
            self.report_lines.append(
                "- Device: `(brak dostępu lub nieznane urządzenie)`\n"
            )
        else:
            self.report_lines.append(f"- Device: `{drm_device.to_fallback_text()}`\n")

        self.report_lines.append(
            f"- DRM nodes:\n{codeblock(r['drm_ls'].to_fallback_text())}"
        )
        self.report_lines.append(heading(3, "Niri outputs (monitory)"))
        self.report_lines.append(codeblock(r["niri_out"].to_fallback_text()))
        self.report_lines.append(heading(3, "Logi graficzne (błędy/ostrzeżenia)"))
        gfx_logs_filtered = _filter_own_journal_entries(
            r["gfx_logs"].to_fallback_text()
        )
        self.report_lines.append(
            codeblock(gfx_logs_filtered if gfx_logs_filtered else "(brak)")
        )

    # ── Raport: Sieć ─────────────────────────────────────────────
    def collect_network(self) -> None:
        self.log_section("Sieć i bezpieczeństwo")

        tasks_cmd = {
            "ip_addr": (["ip", "addr", "show"], TIMEOUT_SHORT, False),
            "ss_tlnp": (["ss", "-tlnp"], TIMEOUT_MEDIUM, False),
            "resolvectl": (["resolvectl", "status"], TIMEOUT_SHORT, False),
            "nm_status": (
                ["systemctl", "status", "NetworkManager", "--no-pager"],
                TIMEOUT_SHORT,
                False,
            ),
            "auth_fails": (
                _journal_count_command(
                    "journalctl -b --no-pager 2>/dev/null", RE_AUTH_FAIL
                ),
                TIMEOUT_LONG,
                False,
            ),
            "firewalld": (
                ["systemctl", "is-active", "firewalld.service"],
                TIMEOUT_SHORT,
                False,
            ),
            "ufw_status": (["ufw", "status"], TIMEOUT_SHORT, True),
        }
        r = self._parallel_cmd(tasks_cmd)

        self.report_lines.append(heading(2, "8. Sieć i bezpieczeństwo operacyjne"))
        self.report_lines.append(heading(3, "Interfejsy sieciowe"))
        self.report_lines.append(
            codeblock(
                safestr(
                    r["ip_addr"].to_fallback_text(), TRUNCATE_IP_ADDR, full=self.full
                )
            )
        )
        self.report_lines.append(heading(3, "Nasłuchujące usługi (ss -tlnp)"))
        self.report_lines.append(codeblock(r["ss_tlnp"].to_fallback_text()))
        self.report_lines.append(heading(3, "DNS (resolvectl status)"))
        self.report_lines.append(
            codeblock(
                safestr(
                    r["resolvectl"].to_fallback_text(),
                    TRUNCATE_RESOLVECTL,
                    full=self.full,
                )
            )
        )
        self.report_lines.append(heading(3, "NetworkManager status"))
        self.report_lines.append(
            codeblock("\n".join(r["nm_status"].to_fallback_text().split("\n")[:15]))
        )
        self.report_lines.append(heading(3, "Nieudane logowania"))
        self.report_lines.append(
            f"Liczba nieudanych logowań: **{r['auth_fails'].to_fallback_text()}**\n\n"
        )

        # Analiza nasłuchujących usług — lokalne vs zewnętrzne
        ss_output = r["ss_tlnp"].stdout
        external_listeners = []
        local_listeners = []
        for line in ss_output.split("\n"):
            if "LISTEN" in line:
                addr_match = re.search(r"(\S+):(\d+)", line)
                if addr_match:
                    addr = addr_match.group(1)
                    port = addr_match.group(2)
                    if addr in ("127.0.0.1", "::1", "127.0.0.53", "127.0.0.54"):
                        local_listeners.append(f"{addr}:{port}")
                    elif addr == "0.0.0.0" or addr == "::":
                        # Może być zewnętrzne — sprawdź czy to znany port systemowy
                        if port not in ("631", "5355"):  # cups, llmnr
                            external_listeners.append(f"{addr}:{port}")
                    elif addr.startswith("192.168.") or addr.startswith("10."):
                        external_listeners.append(f"{addr}:{port}")

        if local_listeners:
            self.report_lines.append(
                f"ℹ️ Nasłuchiwanie lokalne: {len(local_listeners)} usług na "
                f"127.0.0.1/::1 (niedostępne z zewnątrz).\n\n"
            )
        if external_listeners:
            self.report_lines.append(
                f"⚠️ Nasłuchiwanie zewnętrzne: {len(external_listeners)} usług "
                f"na adresach niebędących localhost.\n\n"
            )

        # Firewall — sprawdź różne frontendy
        firewall_found = False
        firewall_details = []

        # 1. nftables
        nft_result = self.cmd(
            ["nft", "list", "ruleset"], timeout=TIMEOUT_SHORT, optional_dependency=True
        )
        if nft_result.execution_status == "permission_denied":
            self.restrictions.append(
                "Firewall (nft) — wymaga sudo, stan nie został zweryfikowany."
            )
        elif nft_result.is_ok() and nft_result.stdout.strip():
            firewall_found = True
            firewall_details.append("nftables (aktywny)")
            self.report_lines.append(heading(3, "Firewall (nft ruleset)"))
            self.report_lines.append(
                codeblock(safestr(nft_result.stdout, TRUNCATE_NFT, full=self.full))
            )
        elif nft_result.execution_status == "not_found":
            firewall_details.append("nftables (niedostępny)")

        # 2. firewalld
        firewalld_result = r["firewalld"]
        if firewalld_result.is_ok() and firewalld_result.stdout.strip() == "active":
            firewall_found = True
            firewall_details.append("firewalld (aktywny)")

        # 3. ufw
        ufw_result = r["ufw_status"]
        if ufw_result.is_ok() and "Status: active" in ufw_result.stdout:
            firewall_found = True
            firewall_details.append("ufw (aktywny)")
        elif ufw_result.execution_status == "not_found":
            firewall_details.append("ufw (niedostępny)")

        # Podsumowanie firewalla
        if firewall_found:
            self.report_lines.append(
                f"✅ Firewall wykryty: {', '.join(firewall_details)}\n\n"
            )
        else:
            self.report_lines.append(
                f"⚠️ Nie wykryto aktywnego firewalla. "
                f"Sprawdzone frontendy: {', '.join(firewall_details) if firewall_details else 'brak'}. "
                f"Możliwe że firewall jest skonfigurowany inaczej lub wymaga sudo do weryfikacji.\n\n"
            )

    # ── Raport: Środowisko użytkownika ───────────────────────────
    def collect_userenv(self) -> None:
        self.log_section("Środowisko użytkownika")

        fish_ver = self.cmd_ok(["fish", "--version"])
        shell = os.environ.get("SHELL", "?")
        term = os.environ.get("TERM", "?")
        lang = os.environ.get("LANG", "?")
        editor = os.environ.get("EDITOR", "(nie ustawiony)")
        browser = os.environ.get("BROWSER", "(nie ustawiony)")

        self.report_lines.append(heading(2, "9. Środowisko użytkownika"))
        self.report_lines.append(heading(3, "Zmienne środowiskowe"))
        self.report_lines.append(f"- **SHELL:** `{shell}`\n")
        self.report_lines.append(f"- **TERM:** `{term}`\n")
        self.report_lines.append(f"- **LANG:** `{lang}`\n")
        self.report_lines.append(f"- **EDITOR:** `{editor}`\n")
        self.report_lines.append(f"- **BROWSER:** `{browser}`\n")
        self.report_lines.append(f"- **Fish:** {fish_ver}\n\n")

    # ── Raport: Podsumowanie ─────────────────────────────────────
    def build_summary(self) -> None:
        self.log_section("Budowanie podsumowania")

        # Sortuj findings: P0 < P1 < P2 < P3 < Info
        self.findings.sort(key=lambda f: Finding._severity_order.get(f.severity, 99))

        self.report_lines.append(heading(2, "10. Problemy potwierdzone"))
        if self.findings:
            for f in self.findings:
                self.report_lines.append(
                    f"**{f.finding_id}.** {f.title}  \n"
                    f"**Priorytet:** {severity_tag(f.severity)}  \n"
                    f"**Pewność:** {confidence_tag(f.confidence)}  \n\n"
                )
                if f.evidence:
                    self.report_lines.append(f"{f.evidence}\n\n")
                if f.interpretation:
                    self.report_lines.append(
                        f"**Interpretacja:** {f.interpretation}\n\n"
                    )
                if f.recommended_diagnostics:
                    self.report_lines.append(
                        f"**Zalecana diagnostyka:**\n{f.recommended_diagnostics}\n\n"
                    )
                if f.remediation:
                    self.report_lines.append(
                        f"**Zalecana naprawa:**\n{f.remediation}\n\n"
                    )
                if f.verification:
                    self.report_lines.append(f"**Weryfikacja:** {f.verification}\n\n")
                if f.risk_level:
                    self.report_lines.append(f"**Poziom ryzyka:** {f.risk_level}\n\n")
        else:
            self.report_lines.append("Nie wykryto potwierdzonych problemów.\n\n")

        self.report_lines.append(heading(2, "11. Rekomendacje"))
        if hasattr(self, "recommendation_plan") and self.recommendation_plan:
            self.report_lines.append(
                format_recommendation_markdown(self.recommendation_plan)
            )
        else:
            self.report_lines.append("Brak rekomendacji.\n\n")

        self.report_lines.append(heading(2, "12. Ograniczenia analizy"))
        if self.restrictions:
            for i, r in enumerate(self.restrictions, 1):
                self.report_lines.append(f"{i}. {r}\n")
        else:
            self.report_lines.append("Brak ograniczeń.\n")
        self.report_lines.append("\n")

        self.report_lines.append(heading(2, "13. Lista wykonanych poleceń"))
        self.report_lines.append(codeblock("\n".join(self.commands_used), lang="bash"))

    # ── Stage 2: Derive observations ───────────────────────────
    def _derive_observations(self) -> None:
        """Stage 2 (OBS): wyprowadza Observation z RawDiagnostic (Stage 1).

        Konsumuje tylko self.raw_diagnostics. Nie czyta CmdResult, nie tworzy Finding.
        Produkuje deterministyczne Observation — identyczne RAW = identyczne OBS.
        """
        for raw in self.raw_diagnostics:
            obs = self._raw_to_observation(raw)
            if obs:
                self.observations.append(obs)

    def _raw_to_observation(self, raw: RawDiagnostic) -> Optional[Observation]:
        """Konwertuje jeden RawDiagnostic na Observation."""
        cat = raw.category
        payload = raw.payload
        src_id = raw.source_id
        capture_complete = not bool(payload.get("capture_truncated"))

        if cat == "btrfs_error":
            return Observation(
                obs_id="BTRFS-ERR-001",
                category="btrfs_error",
                details={**payload, "error_type": "device_stats"},
                direct_measurement=True,
                data_complete=True,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "btrfs_scrub":
            return Observation(
                obs_id="BTRFS-SCRUB-001",
                category="btrfs_scrub",
                details={**payload},
                direct_measurement=True,
                data_complete="scrub_status" in payload and capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "segfault":
            segfault_type = payload.get("segfault_type", "unknown")
            if segfault_type == "wireplumber":
                obs_id = "SEGFAULT-WP-001"
                inference = True  # root cause not directly observed
            elif segfault_type == "system_wide":
                obs_id = "SEGFAULT-SYS-001"
                inference = True
            else:
                obs_id = "SEGFAULT-MIN-001"
                inference = True

            return Observation(
                obs_id=obs_id,
                category="segfault",
                details={**payload},
                direct_measurement=False,  # segfaults are observed but cause is not
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=inference,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "segfault_minor":
            return Observation(
                obs_id="SEGFAULT-MIN-001",
                category="segfault_minor",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "tainted":
            return Observation(
                obs_id="KERNEL-TAINT-001",
                category="tainted",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "systemd_failed":
            scope = payload.get("scope", "system")
            obs_id = "SYSD-SYS-FAIL-001" if scope == "system" else "SYSD-USR-FAIL-001"
            return Observation(
                obs_id=obs_id,
                category="systemd_failed",
                details={**payload},
                direct_measurement=True,
                data_complete=True,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_count":
            return Observation(
                obs_id="KRNL-INFO-001",
                category="kernel_count",
                details={**payload},
                direct_measurement=True,
                data_complete=True,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "boot_time":
            return Observation(
                obs_id="BOOT-SLOW-001",
                category="boot_time",
                details={**payload},
                direct_measurement=True,
                data_complete=True,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "storage_usage":
            state = payload.get("threshold_state", "warning")
            obs_id = (
                "STORAGE-USAGE-CRITICAL"
                if state == "critical"
                else "STORAGE-USAGE-WARNING"
            )
            return Observation(
                obs_id=obs_id,
                category="storage_usage",
                details={
                    "mountpoint": payload.get("mountpoint", "/"),
                    "usage_percent": payload.get("usage_percent", 0),
                    "threshold_state": state,
                },
                direct_measurement=True,
                data_complete=True,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "oom_event":
            return Observation(
                obs_id="KERNEL-OOM-001",
                category="oom_event",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "gpu_i915_hang":
            return Observation(
                obs_id="GPU-I915-HANG-001",
                category="gpu_i915_hang",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "amdgpu_reset_fail":
            return Observation(
                obs_id="AMDGPU-RESET-FAIL-001",
                category="amdgpu_reset_fail",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "gpu_nvidia_xid_79":
            return Observation(
                obs_id="GPU-NVIDIA-XID-79-001",
                category="gpu_nvidia_xid_79",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "pcie_aer_error":
            return Observation(
                obs_id="PCIE-AER-001",
                category="pcie_aer_error",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "nvme_controller_reliability":
            return Observation(
                obs_id="NVME-CONTROLLER-RESET-001",
                category="nvme_controller_reliability",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "hardware_mce_edac_error":
            return Observation(
                obs_id="HW-MCE-EDAC-001",
                category="hardware_mce_edac_error",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "filesystem_io_error":
            return Observation(
                obs_id="FS-IO-ERROR-001",
                category="filesystem_io_error",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        return None

    # ── Stage 3: Interpret observations → findings ─────────────
    def _interpret(self) -> None:
        """Stage 3 (INT): deleguje do DiagnosticRuleEngine."""
        engine = build_default_rule_engine()
        evaluation = engine.evaluate(self.observations)
        self.findings = list(evaluation.findings)
        self.evidence_objects = list(evaluation.evidence)
        self.findings.sort(key=lambda f: Finding._severity_order.get(f.severity, 99))

        # Generate recommendations from findings
        engine_rec = RecommendationEngine()
        self.recommendation_plan = engine_rec.generate(
            findings=self.findings,
            restrictions=tuple(self.restrictions),
        )

    # ── Główna pętla diagnostyki (potok trójfazowy) ──────────────
    def run_all(self) -> str:
        """
        Trójfazowy potok diagnostyczny:
          Stage 1 (RAW): Zbierz surowe dane z poleceń.
          Stage 2 (OBS): Wyprowadź strukturalne obserwacje.
          Stage 3 (INT): Wygeneruj interpretacje z obserwacji.

        Żadna faza nie zależy od następnej. Interpretacja nie czyta RAW.
        """
        self.log("syscheck v" + SCRIPT_VERSION + " — rozpoczynanie diagnostyki...\n")

        # Stage 1: RAW data collection
        self.log("=== Stage 1: Zbieranie surowych danych (RAW) ===")
        self.detect_distro()
        self.collect_base_info()
        self.collect_resources()
        self.collect_storage()
        self.collect_kernel_hw()
        self.collect_systemd()
        self.collect_packages()
        self.collect_graphics()
        self.collect_network()
        self.collect_userenv()

        # Stage 2: Derive observations from RAW
        self.log("\n=== Stage 2: Wyprowadzanie obserwacji (OBS) ===")
        self._derive_observations()

        # Stage 3: Generate interpreted findings from observations
        self.log("\n=== Stage 3: Generowanie interpretacji (INT) ===")
        self._interpret()

        self.build_summary()

        self.report_lines.append("\n---\n")
        self.report_lines.append(
            f"*Raport wygenerowany {self.start_time_local.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"przez {AGENT_NAME} (skrypt v{SCRIPT_VERSION})*\n"
        )

        # Zapis
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self.start_time_local.strftime("%Y%m%d-%H%M%S")
        report_filename = f"syscheck-{self.hostname}-{timestamp}.md"
        report_path = self.output_dir / report_filename

        full_report = "".join(self.report_lines)
        _write_new_text(report_path, full_report)

        self.log(f"\nRaport zapisany do: {report_path}")
        return str(report_path)


# ── Recommendation models ──────────────────────────────────────

VALID_IMPACTS = frozenset({"critical", "high", "medium", "low", "informational"})
VALID_EFFORTS = frozenset({"trivial", "low", "medium", "high", "unknown"})
VALID_RISKS = frozenset({"none", "low", "medium", "high"})
VALID_ACTION_TYPES = frozenset(
    {"investigate", "verify", "remediate", "monitor", "informational"}
)


@dataclass(frozen=True)
class DiagnosticRecommendation:
    """Pojedyncza rekomendacja diagnostyczna — co zrobić, dlaczego, w jakiej kolejności."""

    recommendation_id: str
    priority: int
    title: str
    rationale: str
    source_finding_ids: tuple = ()
    impact: str = "medium"
    effort: str = "unknown"
    risk: str = "low"
    action_type: str = "investigate"
    recommended_diagnostics: tuple = ()
    remediation: tuple = ()
    verification: tuple = ()
    blocked_by_restrictions: tuple = ()

    def __post_init__(self):
        if not self.recommendation_id:
            raise ValueError("recommendation_id is required")
        if not (1 <= self.priority <= 5):
            raise ValueError(f"priority must be 1-5, got {self.priority}")
        if self.impact not in VALID_IMPACTS:
            raise ValueError(f"Invalid impact: {self.impact}")
        if self.effort not in VALID_EFFORTS:
            raise ValueError(f"Invalid effort: {self.effort}")
        if self.risk not in VALID_RISKS:
            raise ValueError(f"Invalid risk: {self.risk}")
        if self.action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action_type: {self.action_type}")

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "priority": self.priority,
            "title": self.title,
            "rationale": self.rationale,
            "source_finding_ids": list(self.source_finding_ids),
            "impact": self.impact,
            "effort": self.effort,
            "risk": self.risk,
            "action_type": self.action_type,
            "recommended_diagnostics": list(self.recommended_diagnostics),
            "remediation": list(self.remediation),
            "verification": list(self.verification),
            "blocked_by_restrictions": list(self.blocked_by_restrictions),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiagnosticRecommendation":
        return cls(
            recommendation_id=str(data.get("recommendation_id", "")),
            priority=int(data.get("priority", 5)),
            title=str(data.get("title", "")),
            rationale=str(data.get("rationale", "")),
            source_finding_ids=tuple(data.get("source_finding_ids", [])),
            impact=str(data.get("impact", "medium")),
            effort=str(data.get("effort", "unknown")),
            risk=str(data.get("risk", "low")),
            action_type=str(data.get("action_type", "informational")),
            recommended_diagnostics=tuple(data.get("recommended_diagnostics", [])),
            remediation=tuple(data.get("remediation", [])),
            verification=tuple(data.get("verification", [])),
            blocked_by_restrictions=tuple(data.get("blocked_by_restrictions", [])),
        )


def derive_recommendation_priority(
    *,
    severity: str,
    confidence: str,
    impact: str,
    action_type: str,
    blocked: bool,
) -> int:
    """Deterministycznie wyznacza priorytet rekomendacji (1-5).

    Zasady:
      - P0 Certain/Likely → 1 (natychmiastowa uwaga)
      - P1 Certain/Likely → 1 lub 2
      - P2 actionable → 2
      - P3 maintenance → 3
      - Info → 5 (informacyjne)
      - Guessing → nie może wyprzedzić równoważnego Certain/Likely
      - Zablokowane → pozostają widoczne, ale nie awansują
    """
    sev_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "Info": 4}

    if action_type == "informational":
        return 5

    base = sev_order.get(severity, 4)

    if base <= 0:  # P0
        return 1
    if base <= 1:  # P1
        return 2 if confidence == "Guessing" else 1
    if base <= 2:  # P2
        if blocked:
            return 3
        return 3 if confidence == "Guessing" else 2
    if base <= 3:  # P3
        return 4 if blocked else 3

    return 5


@dataclass(frozen=True)
class RecommendationPlan:
    """Plan rekomendacji z widokami według priorytetu."""

    recommendations: tuple = ()

    @property
    def urgent(self) -> tuple:
        return tuple(r for r in self.recommendations if r.priority <= 2)

    @property
    def planned(self) -> tuple:
        return tuple(r for r in self.recommendations if r.priority == 3)

    @property
    def informational(self) -> tuple:
        return tuple(r for r in self.recommendations if r.priority >= 4)

    def validate(self) -> list[str]:
        errors = []
        ids = [r.recommendation_id for r in self.recommendations]
        if len(ids) != len(set(ids)):
            errors.append("Duplicate recommendation IDs detected")
        return errors


class RecommendationEngine:
    """Generuje rekomendacje z Finding + restrictions.

    Zależny tylko od Finding — nie czyta RAW, Observation, CmdResult.
    Nie wykonuje poleceń systemowych.
    """

    def generate(
        self,
        findings: list,
        restrictions: tuple = (),
    ) -> RecommendationPlan:
        recs = []
        for f in findings:
            rec = self._finding_to_recommendation(f, restrictions)
            if rec:
                recs.append(rec)
        recs.sort(key=lambda r: r.priority)
        return RecommendationPlan(recommendations=tuple(recs))

    def _finding_to_recommendation(
        self, f: "Finding", restrictions: tuple
    ) -> Optional["DiagnosticRecommendation"]:
        rec_id = f"REC-{f.finding_id}"

        # Classify action type
        action_type = self._classify_action(f)
        impact = self._classify_impact(f)
        effort = self._classify_effort(f)
        risk = self._classify_risk(f)

        # Check for blocked actions (restrictions mentioning sudo/permission)
        blocked = self._detect_blockers(f, restrictions)

        priority = derive_recommendation_priority(
            severity=f.severity,
            confidence=f.confidence,
            impact=impact,
            action_type=action_type,
            blocked=bool(blocked),
        )

        # Split diagnostics/remediation from Finding text
        diag_text = f.recommended_diagnostics
        rem_text = f.remediation
        ver_text = f.verification

        diagnostics = (
            tuple(s.strip() for s in diag_text.split("\n") if s.strip())
            if diag_text
            else ()
        )
        remediation = (
            tuple(s.strip() for s in rem_text.split("\n") if s.strip())
            if rem_text
            else ()
        )
        verification = (
            tuple(s.strip() for s in ver_text.split("\n") if s.strip())
            if ver_text
            else ()
        )

        return DiagnosticRecommendation(
            recommendation_id=rec_id,
            priority=priority,
            title=self._derive_title(f, action_type),
            rationale=self._derive_rationale(f),
            source_finding_ids=(f.finding_id,),
            impact=impact,
            effort=effort,
            risk=risk,
            action_type=action_type,
            recommended_diagnostics=diagnostics,
            remediation=remediation,
            verification=verification,
            blocked_by_restrictions=tuple(blocked),
        )

    @staticmethod
    def _classify_action(f: "Finding") -> str:
        """Klasyfikacja akcji z explicit recommendation_intent, nie z finding_id."""
        return f.recommendation_intent.value

    @staticmethod
    def _classify_impact(f: "Finding") -> str:
        sev = f.severity
        if sev == "P0":
            return "critical"
        if sev == "P1":
            return "high"
        if sev == "P2":
            return "medium"
        if sev == "Info":
            return "informational"
        return "low"

    @staticmethod
    def _classify_effort(f: "Finding") -> str:
        """Wysiłek na podstawie domain i kind, nie finding_id."""
        kind = f.kind
        if kind == FindingKind.SCRUB_STATUS:
            return "high"
        if kind == FindingKind.STORAGE_USAGE and f.severity in ("P0", "P1"):
            return "medium"
        if kind == FindingKind.KERNEL_COUNT:
            return "trivial"
        if f.actionability == Actionability.INFORMATIONAL:
            return "trivial"
        return "low"

    @staticmethod
    def _classify_risk(f: "Finding") -> str:
        sev = f.severity
        if sev in ("P0", "P1"):
            return "high"
        if sev == "P2":
            return "medium"
        return "low"

    @staticmethod
    def _detect_blockers(f: "Finding", restrictions: tuple) -> list:
        blocked = []
        domain = f.domain
        kind = f.kind
        for r in restrictions:
            r_lower = r.lower()
            if domain == DiagnosticDomain.FILESYSTEM and (
                "sudo" in r_lower or "btrfs" in r_lower
            ):
                blocked.append(r)
            if kind == FindingKind.KERNEL_TAINT and "dmesg" in r_lower:
                blocked.append(r)
        return blocked

    @staticmethod
    def _derive_title(f: "Finding", action_type: str) -> str:
        prefix = {
            "investigate": "Sprawdź: ",
            "verify": "Zweryfikuj: ",
            "remediate": "Napraw: ",
            "monitor": "Monitoruj: ",
            "informational": "Informacja: ",
        }.get(action_type, "")
        return prefix + f.title

    @staticmethod
    def _derive_rationale(f: "Finding") -> str:
        conf = f.confidence
        sev = f.severity
        if conf == "Guessing":
            return f"Dalsza diagnostyka wymagana ({sev}, niska pewność)."
        return f"{f.interpretation[:200]}"


def format_recommendation_markdown(plan: RecommendationPlan) -> str:
    """Generuje sekcję planu działania w Markdown."""
    lines = ["## Recommended action plan\n\n"]

    if not plan.recommendations:
        lines.append("No actionable recommendations.\n")
        return "".join(lines)

    # Priority groups
    groups = {
        "Priority 1 — Immediate attention": plan.urgent,
        "Priority 2 — Important": [r for r in plan.recommendations if r.priority == 2],
        "Priority 3 — Planned maintenance": [
            r for r in plan.recommendations if r.priority == 3
        ],
        "Priority 4 — Optional improvement": [
            r for r in plan.recommendations if r.priority == 4
        ],
        "Informational": plan.informational,
    }

    for group_title, recs in groups.items():
        if not recs:
            continue
        lines.append(f"### {group_title}\n\n")
        for i, r in enumerate(recs, 1):
            lines.append(f"{i}. **{r.title}**\n")
            lines.append(f"   - Why: {r.rationale}\n")
            lines.append(
                f"   - Impact: {r.impact} | Effort: {r.effort} | Risk: {r.risk}\n"
            )
            lines.append(f"   - Source: `{', '.join(r.source_finding_ids)}`\n")

            if r.blocked_by_restrictions:
                lines.append(
                    f"   - ⚠️ **Blocked:** {', '.join(r.blocked_by_restrictions)}\n"
                )

            if r.recommended_diagnostics:
                lines.append("   - Diagnostics:\n")
                for d in r.recommended_diagnostics[:3]:
                    lines.append(f"     - `{d}`\n")

            if r.remediation:
                lines.append("   - Remediation:\n")
                for rem in r.remediation[:3]:
                    lines.append(f"     - `{rem}`\n")

            if r.verification:
                lines.append(f"   - Verify: `{r.verification[0]}`\n")
            lines.append("\n")

    return "".join(lines)


SNAPSHOT_SCHEMA_VERSION = 3
VALID_SEVERITIES = frozenset({"P0", "P1", "P2", "P3", "Info"})
VALID_CONFIDENCES = frozenset({"Certain", "Likely", "Guessing"})


class UnsupportedSnapshotSchemaError(ValueError):
    """Rzucany gdy schema_version migawki jest nieobsługiwany lub nieprawidłowy."""

    pass


@dataclass(frozen=True)
class SnapshotMetadata:
    hostname: str = ""
    kernel: str = ""
    distro: str = ""
    syscheck_version: str = ""
    timestamp_utc: str = ""
    timestamp_local: str = ""

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "kernel": self.kernel,
            "distro": self.distro,
            "syscheck_version": self.syscheck_version,
            "timestamp_utc": self.timestamp_utc,
            "timestamp_local": self.timestamp_local,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotMetadata":
        return cls(
            hostname=str(data.get("hostname", "")),
            kernel=str(data.get("kernel", "")),
            distro=str(data.get("distro", "")),
            syscheck_version=str(data.get("syscheck_version", "")),
            timestamp_utc=str(data.get("timestamp_utc", "")),
            timestamp_local=str(data.get("timestamp_local", "")),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.hostname:
            errors.append("Missing hostname")
        if not self.kernel:
            errors.append("Missing kernel")
        if not self.syscheck_version:
            errors.append("Missing syscheck_version")
        return errors


@dataclass(frozen=True)
class EnvironmentSnapshot:
    storage: tuple = ()
    kernel_count: tuple = ()
    failed_units: tuple = ()
    boot_time: tuple = ()

    def to_dict(self) -> dict:
        return {
            "storage": list(self.storage),
            "kernel_count": list(self.kernel_count),
            "failed_units": list(self.failed_units),
            "boot_time": list(self.boot_time),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EnvironmentSnapshot":
        return cls(
            storage=tuple(data.get("storage", [])),
            kernel_count=tuple(data.get("kernel_count", [])),
            failed_units=tuple(data.get("failed_units", [])),
            boot_time=tuple(data.get("boot_time", [])),
        )


@dataclass(frozen=True)
class ExecutionSnapshot:
    commands_count: int = 0
    raw_diagnostics_count: int = 0
    observations_count: int = 0
    findings_count: int = 0

    def to_dict(self) -> dict:
        return {
            "commands_count": self.commands_count,
            "raw_diagnostics_count": self.raw_diagnostics_count,
            "observations_count": self.observations_count,
            "findings_count": self.findings_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionSnapshot":
        return cls(
            commands_count=int(data.get("commands_count", 0)),
            raw_diagnostics_count=int(data.get("raw_diagnostics_count", 0)),
            observations_count=int(data.get("observations_count", 0)),
            findings_count=int(data.get("findings_count", 0)),
        )

    def validate(self) -> list[str]:
        errors = []
        for field_name in (
            "commands_count",
            "raw_diagnostics_count",
            "observations_count",
            "findings_count",
        ):
            if getattr(self, field_name) < 0:
                errors.append(f"Negative {field_name}")
        return errors


@dataclass(frozen=True)
class ObservationSnapshot:
    obs_id: str = ""
    category: str = ""
    details: dict = field(default_factory=dict)
    data_complete: bool = True
    contradictory_evidence: bool = False
    direct_measurement: bool = True
    inference_required: bool = False
    independent_sources: int = 1
    source_raw_ids: tuple = ()

    def to_dict(self) -> dict:
        return {
            "obs_id": self.obs_id,
            "category": self.category,
            "details": self.details,
            "data_complete": self.data_complete,
            "contradictory_evidence": self.contradictory_evidence,
            "direct_measurement": self.direct_measurement,
            "inference_required": self.inference_required,
            "independent_sources": self.independent_sources,
            "source_raw_ids": list(self.source_raw_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ObservationSnapshot":
        return cls(
            obs_id=str(data.get("obs_id", "")),
            category=str(data.get("category", "")),
            details=data.get("details", {}),
            data_complete=bool(data.get("data_complete", True)),
            contradictory_evidence=bool(data.get("contradictory_evidence", False)),
            direct_measurement=bool(data.get("direct_measurement", True)),
            inference_required=bool(data.get("inference_required", False)),
            independent_sources=int(data.get("independent_sources", 1)),
            source_raw_ids=tuple(data.get("source_raw_ids", [])),
        )


@dataclass(frozen=True)
class FindingSnapshot:
    finding_id: str = ""
    title: str = ""
    severity: str = ""
    confidence: str = ""
    evidence: str = ""
    interpretation: str = ""
    recommended_diagnostics: str = ""
    remediation: str = ""
    verification: str = ""
    risk_level: str = ""
    domain: str = ""
    kind: str = ""
    actionability: str = ""
    recommendation_intent: str = ""
    source_observation_ids: tuple = ()

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "title": self.title,
            "severity": self.severity,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "interpretation": self.interpretation,
            "recommended_diagnostics": self.recommended_diagnostics,
            "remediation": self.remediation,
            "verification": self.verification,
            "risk_level": self.risk_level,
            "domain": self.domain,
            "kind": self.kind,
            "actionability": self.actionability,
            "recommendation_intent": self.recommendation_intent,
            "source_observation_ids": list(self.source_observation_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FindingSnapshot":
        return cls(
            finding_id=str(data.get("finding_id", "")),
            title=str(data.get("title", "")),
            severity=str(data.get("severity", "")),
            confidence=str(data.get("confidence", "")),
            evidence=str(data.get("evidence", "")),
            interpretation=str(data.get("interpretation", "")),
            recommended_diagnostics=str(data.get("recommended_diagnostics", "")),
            remediation=str(data.get("remediation", "")),
            verification=str(data.get("verification", "")),
            risk_level=str(data.get("risk_level", "")),
            domain=str(data.get("domain", "")),
            kind=str(data.get("kind", "")),
            actionability=str(data.get("actionability", "")),
            recommendation_intent=str(data.get("recommendation_intent", "")),
            source_observation_ids=tuple(data.get("source_observation_ids", [])),
        )


@dataclass(frozen=True)
class SystemSnapshot:
    """Migawka diagnostyczna — strukturalny, deterministyczny, typowany zapis stanu systemu."""

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    metadata: SnapshotMetadata = field(default_factory=SnapshotMetadata)
    environment: EnvironmentSnapshot = field(default_factory=EnvironmentSnapshot)
    observations: tuple = ()
    findings: tuple = ()
    recommendations: tuple = ()
    restrictions: tuple = ()
    execution: ExecutionSnapshot = field(default_factory=ExecutionSnapshot)

    def to_dict(self) -> dict:

        return {
            "schema_version": self.schema_version,
            "metadata": self.metadata.to_dict(),
            "environment": self.environment.to_dict(),
            "observations": [o.to_dict() for o in self.observations],
            "findings": [f.to_dict() for f in self.findings],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "restrictions": list(self.restrictions),
            "execution": self.execution.to_dict(),
        }

    def to_json(self, path: str) -> None:
        import json

        payload = json.dumps(
            self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True
        )
        _write_new_text(path, payload)

    @classmethod
    def from_json(cls, path: str) -> "SystemSnapshot":
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return cls._from_validated(data)

    @classmethod
    def _from_validated(cls, data: dict) -> "SystemSnapshot":
        # Schema version validation
        schema_ver = data.get("schema_version")
        if schema_ver is None:
            raise UnsupportedSnapshotSchemaError(
                "Missing required field: schema_version"
            )
        if not isinstance(schema_ver, int):
            raise UnsupportedSnapshotSchemaError(
                f"schema_version must be int, got {type(schema_ver).__name__}"
            )
        if schema_ver != SNAPSHOT_SCHEMA_VERSION:
            raise UnsupportedSnapshotSchemaError(
                f"Unsupported schema version {schema_ver} "
                f"(supported: {SNAPSHOT_SCHEMA_VERSION})"
            )

        metadata = SnapshotMetadata.from_dict(data.get("metadata", {}))
        env = EnvironmentSnapshot.from_dict(data.get("environment", {}))
        exe = ExecutionSnapshot.from_dict(data.get("execution", {}))

        obs_raw = data.get("observations", [])
        if not isinstance(obs_raw, list):
            raise ValueError("observations must be a list")
        observations = tuple(ObservationSnapshot.from_dict(o) for o in obs_raw)

        find_raw = data.get("findings", [])
        if not isinstance(find_raw, list):
            raise ValueError("findings must be a list")
        findings = tuple(FindingSnapshot.from_dict(f) for f in find_raw)

        restrictions = tuple(data.get("restrictions", []))

        recs_raw = data.get("recommendations", [])
        recommendations = tuple(DiagnosticRecommendation.from_dict(r) for r in recs_raw)

        snap = cls(
            schema_version=schema_ver,
            metadata=metadata,
            environment=env,
            observations=observations,
            findings=findings,
            recommendations=recommendations,
            restrictions=restrictions,
            execution=exe,
        )

        errors = snap.validate()
        if errors:
            raise ValueError(f"Snapshot validation failed: {'; '.join(errors)}")

        return snap

    def validate(self) -> list[str]:
        errors = []
        errors.extend(self.metadata.validate())
        errors.extend(self.execution.validate())

        obs_ids = [o.obs_id for o in self.observations]
        if len(obs_ids) != len(set(obs_ids)):
            errors.append("Duplicate observation IDs detected")

        finding_ids = [f.finding_id for f in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            errors.append("Duplicate finding IDs detected")

        for f in self.findings:
            if f.severity and f.severity not in VALID_SEVERITIES:
                errors.append(
                    f"Invalid severity '{f.severity}' in finding '{f.finding_id}'"
                )
            if f.confidence and f.confidence not in VALID_CONFIDENCES:
                errors.append(
                    f"Invalid confidence '{f.confidence}' in finding '{f.finding_id}'"
                )

        if self.metadata.hostname and not isinstance(self.metadata.hostname, str):
            errors.append("metadata.hostname must be string")

        return errors


# ── Snapshot builder ───────────────────────────────────────────


class SnapshotBuilder:
    """Konstruuje SystemSnapshot z danych diagnostycznych.

    Nie wykonuje poleceń systemowych. Nie czyta report_lines ani CLI.
    """

    @staticmethod
    def build(
        *,
        metadata: SnapshotMetadata,
        environment: EnvironmentSnapshot,
        observations: list,
        findings: list,
        recommendations: list = None,
        restrictions: list = None,
        execution: ExecutionSnapshot = None,
    ) -> SystemSnapshot:
        if recommendations is None:
            recommendations = []
        if restrictions is None:
            restrictions = []
        if execution is None:
            execution = ExecutionSnapshot()

        obs_snapshots = tuple(
            ObservationSnapshot(
                obs_id=str(o.get("obs_id", "")),
                category=str(o.get("category", "")),
                details=o.get("details", {}),
                data_complete=bool(o.get("data_complete", True)),
                contradictory_evidence=bool(o.get("contradictory_evidence", False)),
                direct_measurement=bool(o.get("direct_measurement", True)),
                inference_required=bool(o.get("inference_required", False)),
                independent_sources=int(o.get("independent_sources", 1)),
                source_raw_ids=tuple(o.get("source_raw_ids", [])),
            )
            for o in observations
        )

        find_snapshots = tuple(
            FindingSnapshot(
                finding_id=str(f.get("finding_id", "")),
                title=str(f.get("title", "")),
                severity=str(f.get("severity", "")),
                confidence=str(f.get("confidence", "")),
                evidence=str(f.get("evidence", "")),
                interpretation=str(f.get("interpretation", "")),
                recommended_diagnostics=str(f.get("recommended_diagnostics", "")),
                remediation=str(f.get("remediation", "")),
                verification=str(f.get("verification", "")),
                risk_level=str(f.get("risk_level", "")),
                domain=str(f.get("domain", "")),
                kind=str(f.get("kind", "")),
                actionability=str(f.get("actionability", "")),
                recommendation_intent=str(f.get("recommendation_intent", "")),
                source_observation_ids=tuple(f.get("source_observation_ids", [])),
            )
            for f in findings
        )

        return SystemSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            metadata=metadata,
            environment=environment,
            observations=obs_snapshots,
            findings=find_snapshots,
            recommendations=tuple(recommendations),
            restrictions=tuple(restrictions),
            execution=execution,
        )


def build_snapshot(engine: "SysCheckEngine") -> SystemSnapshot:
    """Buduje SystemSnapshot z danych silnika diagnostycznego."""
    metadata = SnapshotMetadata(
        hostname=engine.hostname,
        kernel=engine.active_kernel,
        distro=engine.distro_id,
        syscheck_version=SCRIPT_VERSION,
        timestamp_utc=engine.start_time.isoformat(),
        timestamp_local=engine.start_time_local.isoformat(),
    )

    environment = EnvironmentSnapshot(
        storage=tuple(
            {
                "mountpoint": o.details.get("mountpoint", "/"),
                "usage_percent": o.details.get("usage_percent"),
                "threshold_state": o.details.get("threshold_state"),
            }
            for o in engine.observations
            if o.category == "storage_usage"
        ),
        kernel_count=tuple(
            o.details.get("count")
            for o in engine.observations
            if o.category == "kernel_count"
        ),
        failed_units=tuple(
            {
                "scope": o.details.get("scope"),
                "units": o.details.get("units", []),
            }
            for o in engine.observations
            if o.category == "systemd_failed"
        ),
        boot_time=tuple(
            o.details for o in engine.observations if o.category == "boot_time"
        ),
    )

    observations_data = [
        {
            "obs_id": o.obs_id,
            "category": o.category,
            "details": o.details,
            "data_complete": o.data_complete,
            "contradictory_evidence": o.contradictory_evidence,
            "direct_measurement": o.direct_measurement,
            "inference_required": o.inference_required,
            "independent_sources": o.independent_sources,
            "source_raw_ids": o.source_raw_ids,
        }
        for o in engine.observations
    ]

    findings_data = [
        {
            "finding_id": f.finding_id,
            "title": f.title,
            "severity": f.severity,
            "confidence": f.confidence,
            "evidence": f.evidence,
            "interpretation": f.interpretation,
            "recommended_diagnostics": f.recommended_diagnostics,
            "remediation": f.remediation,
            "verification": f.verification,
            "risk_level": f.risk_level,
            "domain": f.domain.value
            if isinstance(f.domain, DiagnosticDomain)
            else str(f.domain),
            "kind": f.kind.value if isinstance(f.kind, FindingKind) else str(f.kind),
            "actionability": f.actionability.value
            if isinstance(f.actionability, Actionability)
            else str(f.actionability),
            "recommendation_intent": f.recommendation_intent.value
            if isinstance(f.recommendation_intent, RecommendationIntent)
            else str(f.recommendation_intent),
            "source_observation_ids": f.source_observation_ids,
        }
        for f in engine.findings
    ]

    execution = ExecutionSnapshot(
        commands_count=len(engine.commands_used),
        raw_diagnostics_count=len(engine.raw_diagnostics),
        observations_count=len(engine.observations),
        findings_count=len(engine.findings),
    )

    recs_data = []
    if hasattr(engine, "recommendation_plan") and engine.recommendation_plan:
        recs_data = [r.to_dict() for r in engine.recommendation_plan.recommendations]

    return SnapshotBuilder.build(
        metadata=metadata,
        environment=environment,
        observations=observations_data,
        findings=findings_data,
        recommendations=recs_data,
        restrictions=list(engine.restrictions),
        execution=execution,
    )


# ── Migration hook ─────────────────────────────────────────────


class SnapshotMigrator:
    """Granica migracji dla przyszłych zmian schematu.

    v1 → v2: dodaje puste pole recommendations.
    v2 → v3: dodaje classification (domain, kind, actionability, recommendation_intent)
              do każdego finding na podstawie historycznego finding_id.
    v3+:     no-op.
    """

    _V2_TO_V3_CLASSIFICATION: ClassVar[dict] = {
        "BTRFS-ERR-001": ("filesystem", "device_error", "actionable", "verify"),
        "BTRFS-SCRUB-001": ("filesystem", "scrub_status", "actionable", "remediate"),
        "SEGFAULT-WP-001": ("audio", "segfault", "actionable", "investigate"),
        "SEGFAULT-SYS-001": ("kernel", "segfault", "actionable", "investigate"),
        "SEGFAULT-MIN-001": ("kernel", "segfault", "actionable", "monitor"),
        "KERNEL-TAINT-001": ("kernel", "kernel_taint", "conditional", "monitor"),
        "SYSD-SYS-FAIL-001": ("systemd", "failed_unit", "actionable", "investigate"),
        "SYSD-USR-FAIL-001": ("systemd", "failed_unit", "actionable", "investigate"),
        "KRNL-INFO-001": ("packages", "kernel_count", "informational", "informational"),
        "BOOT-SLOW-001": ("boot", "boot_delay", "conditional", "monitor"),
        "STORAGE-USAGE-CRITICAL": (
            "storage",
            "storage_usage",
            "actionable",
            "remediate",
        ),
        "STORAGE-USAGE-WARNING": (
            "storage",
            "storage_usage",
            "actionable",
            "remediate",
        ),
    }

    _FALLBACK_CLASSIFICATION: ClassVar[tuple] = (
        "other",
        "general",
        "conditional",
        "verify",
    )

    @staticmethod
    def migrate(data: dict) -> dict:
        schema_ver = data.get("schema_version")
        if schema_ver is None:
            raise UnsupportedSnapshotSchemaError("Missing schema_version")
        if schema_ver == 1:
            data["schema_version"] = 2
            data.setdefault("recommendations", [])
            schema_ver = 2
        if schema_ver == 2:
            data["schema_version"] = 3
            findings = data.get("findings", [])
            for f in findings:
                fid = f.get("finding_id", "")
                cls_data = SnapshotMigrator._V2_TO_V3_CLASSIFICATION.get(
                    fid, SnapshotMigrator._FALLBACK_CLASSIFICATION
                )
                f["domain"] = cls_data[0]
                f["kind"] = cls_data[1]
                f["actionability"] = cls_data[2]
                f["recommendation_intent"] = cls_data[3]
            return data
        if schema_ver == SNAPSHOT_SCHEMA_VERSION:
            return data
        raise UnsupportedSnapshotSchemaError(
            f"Cannot migrate schema version {schema_ver}"
        )


# ── Snapshot comparison ─────────────────────────────────────────


@dataclass
class SnapshotComparison:
    """Wynik porównania dwóch migawek."""

    old_metadata: dict = field(default_factory=dict)
    new_metadata: dict = field(default_factory=dict)
    new_findings: list = field(default_factory=list)
    resolved_findings: list = field(default_factory=list)
    changed_findings: list = field(default_factory=list)
    environment_changes: dict = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.new_findings
            or self.resolved_findings
            or self.changed_findings
            or self.environment_changes
        )


class SnapshotComparator:
    """Porównuje dwie migawki SystemSnapshot po stabilnych ID."""

    @staticmethod
    def compare(old: SystemSnapshot, new: SystemSnapshot) -> SnapshotComparison:
        comp = SnapshotComparison(
            old_metadata=old.metadata.to_dict(),
            new_metadata=new.metadata.to_dict(),
        )
        comp.new_findings = SnapshotComparator._new_findings(old, new)
        comp.resolved_findings = SnapshotComparator._resolved_findings(old, new)
        comp.changed_findings = SnapshotComparator._changed_findings(old, new)
        comp.environment_changes = SnapshotComparator._environment_changes(old, new)
        return comp

    @staticmethod
    def _new_findings(old: SystemSnapshot, new: SystemSnapshot) -> list:
        old_ids = {f.finding_id for f in old.findings}
        return [f.to_dict() for f in new.findings if f.finding_id not in old_ids]

    @staticmethod
    def _resolved_findings(old: SystemSnapshot, new: SystemSnapshot) -> list:
        new_ids = {f.finding_id for f in new.findings}
        return [f.to_dict() for f in old.findings if f.finding_id not in new_ids]

    @staticmethod
    def _changed_findings(old: SystemSnapshot, new: SystemSnapshot) -> list:
        old_by_id = {f.finding_id: f for f in old.findings}
        new_by_id = {f.finding_id: f for f in new.findings}
        changes = []
        for fid in old_by_id:
            if fid in new_by_id:
                of = old_by_id[fid]
                nf = new_by_id[fid]
                diffs = {}
                for key in ("severity", "confidence", "interpretation", "evidence"):
                    o_val = getattr(of, key, "")
                    n_val = getattr(nf, key, "")
                    if o_val != n_val:
                        diffs[key] = {"old": o_val, "new": n_val}
                if diffs:
                    changes.append(
                        {
                            "finding_id": fid,
                            "title": nf.title,
                            "changes": diffs,
                        }
                    )
        return changes

    @staticmethod
    def _environment_changes(old: SystemSnapshot, new: SystemSnapshot) -> dict:
        changes: dict = {}
        om = old.metadata
        nm = new.metadata
        oe = old.environment
        ne = new.environment

        if om.kernel != nm.kernel:
            changes["kernel"] = {"old": om.kernel, "new": nm.kernel}

        old_storage = {
            s.get("mountpoint", "/"): s.get("usage_percent") for s in oe.storage
        }
        new_storage = {
            s.get("mountpoint", "/"): s.get("usage_percent") for s in ne.storage
        }
        storage_diffs = {}
        for mp in set(list(old_storage.keys()) + list(new_storage.keys())):
            o_pct = old_storage.get(mp)
            n_pct = new_storage.get(mp)
            if o_pct != n_pct:
                storage_diffs[mp] = {"old": o_pct, "new": n_pct}
        if storage_diffs:
            changes["storage"] = storage_diffs

        if list(oe.kernel_count) != list(ne.kernel_count):
            changes["kernel_count"] = {
                "old": list(oe.kernel_count),
                "new": list(ne.kernel_count),
            }

        old_units = {
            (u.get("scope"), tuple(sorted(u.get("units", [])))) for u in oe.failed_units
        }
        new_units = {
            (u.get("scope"), tuple(sorted(u.get("units", [])))) for u in ne.failed_units
        }
        if old_units != new_units:
            changes["failed_units"] = {
                "old": [list(t[1]) for t in old_units],
                "new": [list(t[1]) for t in new_units],
            }

        return changes


def format_comparison_markdown(comp: SnapshotComparison) -> str:
    """Generuje raport porównania w formacie Markdown."""
    lines = [
        "# System comparison\n\n",
        f"**Previous:** {comp.old_metadata.get('timestamp_local', '?')}\n\n",
        f"**Current:** {comp.new_metadata.get('timestamp_local', '?')}\n\n",
    ]

    if not comp.has_changes:
        lines.append("No significant changes detected.\n")
        return "".join(lines)

    if comp.new_findings:
        lines.append("## New problems\n\n")
        for f in comp.new_findings:
            lines.append(f"+ **{f.get('finding_id', '?')}**: {f.get('title', '?')}\n")
        lines.append("\n")

    if comp.resolved_findings:
        lines.append("## Resolved\n\n")
        for f in comp.resolved_findings:
            lines.append(
                f"+ \u2713 **{f.get('finding_id', '?')}**: {f.get('title', '?')}\n"
            )
        lines.append("\n")

    if comp.changed_findings:
        lines.append("## Changed findings\n\n")
        for cf in comp.changed_findings:
            lines.append(f"### {cf['finding_id']}: {cf['title']}\n\n")
            for key, vals in cf["changes"].items():
                lines.append(
                    f"**{key}**\n\n{vals['old']}\n\n\u2193\n\n{vals['new']}\n\n"
                )
        lines.append("\n")

    if comp.environment_changes:
        lines.append("## Environment changes\n\n")
        for key, vals in comp.environment_changes.items():
            lines.append(f"**{key}**\n\n")
            if (
                isinstance(vals, dict)
                and "old" in vals
                and "new" in vals
                and not isinstance(vals.get("old"), dict)
            ):
                lines.append(f"  {vals['old']}  \u2192  {vals['new']}\n\n")
            else:
                lines.append(f"  Changed: {vals}\n\n")

    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="syscheck — tylko do odczytu diagnostyka systemu Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Komendy")

    # ── Komenda główna: diagnostyka ──────────────────────────────
    diag_parser = subparsers.add_parser(
        "run", help="Uruchom diagnostykę (domyślna)", aliases=["diagnose"]
    )
    diag_parser.add_argument(
        "--output-dir",
        "-o",
        default=OUTPUT_DIR_DEFAULT,
        help=f"Katalog docelowy (domyślnie: {OUTPUT_DIR_DEFAULT})",
    )
    diag_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Wycisz komunikaty diagnostyczne na stderr",
    )
    diag_parser.add_argument(
        "--full",
        "-f",
        action="store_true",
        help="Pełny output — nie obcinaj długich wyników w raporcie",
    )
    diag_parser.add_argument(
        "--snapshot",
        "-s",
        type=str,
        default=None,
        help="Zapisz migawkę JSON (np. snapshot.json)",
    )

    # ── Komenda compare ──────────────────────────────────────────
    cmp_parser = subparsers.add_parser("compare", help="Porównaj dwie migawki JSON")
    cmp_parser.add_argument("old", help="Ścieżka do starej migawki JSON")
    cmp_parser.add_argument("new", help="Ścieżka do nowej migawki JSON")
    cmp_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Zapisz raport porównania do pliku Markdown",
    )

    args = parser.parse_args()

    # ── Obsługa compare ──────────────────────────────────────────
    if args.command == "compare":
        old_snapshot = SystemSnapshot.from_json(args.old)
        new_snapshot = SystemSnapshot.from_json(args.new)
        comp = SnapshotComparator.compare(old_snapshot, new_snapshot)
        md = format_comparison_markdown(comp)
        if args.output:
            _write_new_text(args.output, md)
            print(f"Comparison saved to: {args.output}")
        print(md)
        return

    # ── Obsługa run (domyślna) ───────────────────────────────────
    cmd_args = args if hasattr(args, "output_dir") else parser.parse_args(["run"])

    if not getattr(cmd_args, "quiet", False):
        print("╔══════════════════════════════════════════════╗", file=sys.stderr)
        print("║   syscheck — diagnostyka systemu Linux      ║", file=sys.stderr)
        print("║   Tylko do odczytu | Bez sudo | Bez zmian   ║", file=sys.stderr)
        print("╚══════════════════════════════════════════════╝", file=sys.stderr)
        print(
            f"  Agent: {AGENT_NAME}   Model: {MODEL_NAME}   v{SCRIPT_VERSION}",
            file=sys.stderr,
        )
        print(
            f"  Start: {datetime.datetime.now().strftime('%H:%M:%S')}",
            file=sys.stderr,
        )
        print("", file=sys.stderr)

    output_dir = getattr(cmd_args, "output_dir", OUTPUT_DIR_DEFAULT)
    quiet = getattr(cmd_args, "quiet", False)
    full = getattr(cmd_args, "full", False)
    snapshot_path = getattr(cmd_args, "snapshot", None)

    engine = SysCheckEngine(output_dir=output_dir, quiet=quiet, full=full)
    report_path = engine.run_all()

    # Save snapshot if requested
    if snapshot_path:
        snap = build_snapshot(engine)
        snap.to_json(snapshot_path)
        print(f"\nSnapshot saved to: {snapshot_path}")

    print(f"\n{'=' * 72}")
    print(f"Pełna ścieżka raportu: {report_path}")
    print(f"{'=' * 72}")
    print(f"\nLiczba wykrytych problemów: {len(engine.findings)}")
    print(f"Liczba ograniczeń:         {len(engine.restrictions)}")
    print(f"Liczba wykonanych poleceń: {len(engine.commands_used)}")
    print(f"Liczba obserwacji:         {len(engine.observations)}")
    if full:
        print("Tryb:                      --full (pełny output)")
    print(f"\n{'─' * 72}")

    report_content = Path(report_path).read_text(encoding="utf-8")
    print(report_content)


if __name__ == "__main__":
    main()
