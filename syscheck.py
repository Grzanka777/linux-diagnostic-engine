#!/usr/bin/env python3
"""
Linux Diagnostic Engine (LDE) — kompleksowa, tylko do odczytu diagnostyka
systemu Linux.

Licencja:   MIT
Wersja produktu:                         0.3.0
Kompatybilność raportów/snapshotów:      2.1.0

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
  - Raport zapisywany do pliku .md; wyświetlenie na konsoli jest opcjonalne.
  - Wspiera Arch/CachyOS, Debian/Ubuntu, RHEL/Fedora (pakiety).

Użycie:
  lde [--version]
  lde run [--output-dir DIRECTORY] [--quiet] [--full] [--print-report] [--verbose]
"""

from __future__ import annotations

import os
import subprocess
import argparse
import datetime
import re
import shlex
import shutil
import sys
import threading
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, NoReturn, Optional, Tuple

# ── Stałe ────────────────────────────────────────────────────────
from constants import (  # type: ignore[import-untyped]
    DISTRO_CONFIG,
    MAX_RECOMMENDED_KERNELS,
    get_default_reports_dir,
    PRODUCT_NAME,
    PRODUCT_SHORT_NAME,
    PRODUCT_VERSION,
    REPORT_COMPATIBILITY_VERSION,
    RE_AUTH_FAIL,
    RE_FIRMWARE,
    RE_GFX_ERROR,
    RE_KERNEL_ERROR,
    RE_KERNEL_TAINT,
    RE_AMDGPU_RESET_FAIL,
    RE_FILESYSTEM_IO_ERROR,
    RE_GPU_I915_HANG,
    RE_HARDWARE_MCE_EDAC,
    RE_HARDWARE_THERMAL_THROTTLE,
    RE_KERNEL_HARD_LOCKUP,
    RE_KERNEL_HUNG_TASK,
    RE_KERNEL_OOPS_BUG,
    RE_KERNEL_OOPS_PANIC,
    RE_KERNEL_PANIC,
    RE_KERNEL_RCU_STALL,
    RE_KERNEL_SOFT_LOCKUP,
    RE_KERNEL_STALL_RELIABILITY,
    RE_PLATFORM_ACPI_FIRMWARE_ERROR,
    RE_KERNEL_FIRMWARE_LOAD_FAIL,
    RE_USB_ENUMERATION_FAIL,
    RE_IOMMU_FAULT,
    RE_PLATFORM_DEVICE_RELIABILITY,
    RE_NVIDIA_XID_79,
    RE_NVME_CONTROLLER_RELIABILITY,
    RE_OOM,
    RE_PCIE_AER,
    RE_SEGFAULT,
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


_SYSTEMD_DURATION_COMPONENT_RE = re.compile(
    r"(?P<value>(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"(?P<unit>usec|us|µs|ms|seconds?|sec|s|minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|days?|d|weeks?|w)",
    re.IGNORECASE,
)
_SYSTEMD_DURATION_FACTORS = {
    "usec": 1e-6,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "second": 1.0,
    "seconds": 1.0,
    "sec": 1.0,
    "s": 1.0,
    "minute": 60.0,
    "minutes": 60.0,
    "mins": 60.0,
    "min": 60.0,
    "m": 60.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "hrs": 3600.0,
    "hr": 3600.0,
    "h": 3600.0,
    "day": 86400.0,
    "days": 86400.0,
    "d": 86400.0,
    "week": 604800.0,
    "weeks": 604800.0,
    "w": 604800.0,
}
_SYSTEMD_DURATION_EXPRESSION = (
    r"(?:\d+(?:\.\d*)?|\.\d+)\s*"
    r"(?:usec|us|µs|ms|seconds?|sec|s|minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|days?|d|weeks?|w)"
    r"(?:\s+(?:\d+(?:\.\d*)?|\.\d+)\s*"
    r"(?:usec|us|µs|ms|seconds?|sec|s|minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|days?|d|weeks?|w))*"
)


def _parse_systemd_duration(text: str) -> Optional[float]:
    """Parse a systemd duration expression into seconds.

    The parser accepts the fixed-length units emitted by systemd-analyze,
    including compound values such as ``1min 31.345s``.  Invalid or partial
    expressions return None instead of silently accepting a numeric suffix.
    """
    value = text.strip()
    if value.endswith("."):
        value = value[:-1].rstrip()
    if not value:
        return None

    matches = list(_SYSTEMD_DURATION_COMPONENT_RE.finditer(value))
    if not matches:
        return None

    seconds = 0.0
    cursor = 0
    for match in matches:
        if value[cursor : match.start()].strip():
            return None
        unit = match.group("unit").lower()
        seconds += float(match.group("value")) * _SYSTEMD_DURATION_FACTORS[unit]
        cursor = match.end()
    if value[cursor:].strip():
        return None
    return seconds


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
            if self.stdout:
                return with_capture_marker(self.stdout) + "\n(wymaga sudo — pominięto)"
            return "(wymaga sudo — pominięto)"
        if self.execution_status == "empty_ok":
            return with_capture_marker(self.stdout if self.stdout else "(brak wyników)")
        if self.stdout or self.stderr:
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
    SOURCE_FAILURE = "source_failure"
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
    HARDWARE_THERMAL_THROTTLING = "hardware_thermal_throttling"
    KERNEL_OOPS_PANIC = "kernel_oops_panic"
    KERNEL_SOFT_LOCKUP = "kernel_soft_lockup"
    KERNEL_HARD_LOCKUP = "kernel_hard_lockup"
    KERNEL_HUNG_TASK = "kernel_hung_task"
    KERNEL_RCU_STALL = "kernel_rcu_stall"
    PLATFORM_ACPI_FIRMWARE_ERROR = "platform_acpi_firmware_error"
    KERNEL_FIRMWARE_LOAD_FAIL = "kernel_firmware_load_fail"
    USB_ENUMERATION_FAIL = "usb_enumeration_fail"
    IOMMU_FAULT = "iommu_fault"
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
    Nie zawiera interpretacji, severity, confidence, ani rekomendacji. Metadane
    pochodzenia są przechowywane osobno od payloadu diagnostycznego.
    """

    source_id: str
    category: str
    payload: dict
    collected_at: str = ""
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "category": self.category,
            "payload": dict(self.payload),
            "collected_at": self.collected_at,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RawDiagnostic":
        return cls(
            source_id=str(data.get("source_id", "")),
            category=str(data.get("category", "")),
            payload=dict(data.get("payload", {})),
            collected_at=str(data.get("collected_at", "")),
            provenance=dict(data.get("provenance", {})),
        )


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


def _cmd_result_provenance(result: CmdResult) -> dict:
    """Return non-sensitive execution metadata for a raw diagnostic."""
    return {
        "command": result.command,
        "return_code": result.return_code,
        "execution_status": result.execution_status,
        "privilege_required": result.privilege_required,
        "optional_dependency": result.optional_dependency,
        "truncated": result.truncated,
        "collected_at": result.collected_at,
    }


def _raw_from_result(
    result: CmdResult, *, source_id: str, category: str, payload: dict
) -> RawDiagnostic:
    """Build a RAW record without dropping command capture metadata."""
    return RawDiagnostic(
        source_id=source_id,
        category=category,
        payload=_capture_payload(result, payload),
        collected_at=result.collected_at,
        provenance=_cmd_result_provenance(result),
    )


def _storage_diagnostic_id(threshold_state: str, mountpoint: str) -> str:
    """Return a deterministic, mount-specific storage diagnostic ID.

    Keep the historical root IDs stable while encoding every other mountpoint
    injectively so two qualifying mounts cannot share an Observation/Finding ID.
    """
    base = (
        "STORAGE-USAGE-CRITICAL"
        if threshold_state == "critical"
        else "STORAGE-USAGE-WARNING"
    )
    if mountpoint == "/":
        return base
    return f"{base}-MOUNT-{quote(mountpoint, safe='')}"


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


def _cli_error(message: str) -> NoReturn:
    """Render an expected command-line failure without a traceback."""
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


CLI_STATUS_HEALTHY = "HEALTHY"
CLI_STATUS_ATTENTION = "ATTENTION"
CLI_STATUS_PROBLEMS = "PROBLEMS"
_CLI_COLLECTION_SECTIONS = (
    "Environment",
    "CPU & memory",
    "Storage / NVMe / Btrfs",
    "Kernel & hardware",
    "systemd & boot",
    "Packages",
    "Graphics",
    "Network & security",
    "User environment",
)
_CLI_STATUS_MARKERS = {
    CLI_STATUS_HEALTHY: "✓",
    CLI_STATUS_ATTENTION: "!",
    CLI_STATUS_PROBLEMS: "✗",
}


def determine_cli_status(findings: Iterable[Finding]) -> str:
    """Return the stable public status derived only from finding severity."""
    severities = {finding.severity for finding in findings}
    if severities.intersection({"P0", "P1"}):
        return CLI_STATUS_PROBLEMS
    if severities.intersection({"P2", "P3"}):
        return CLI_STATUS_ATTENTION
    return CLI_STATUS_HEALTHY


def _terminal_width(stream: Any) -> int:
    """Return a safe width for compact CLI rules on unusual terminals."""
    try:
        columns = int(shutil.get_terminal_size(fallback=(80, 24)).columns)
    except (AttributeError, OSError, TypeError, ValueError):
        columns = 80
    return max(1, columns)


def _ansi_enabled(stream: Any) -> bool:
    """Enable presentation color only for an actual TTY and never for NO_COLOR."""
    if "NO_COLOR" in os.environ:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _style_cli_status(status: str, stream: Any) -> str:
    if not _ansi_enabled(stream):
        return status
    color = {
        CLI_STATUS_HEALTHY: "\033[32m",
        CLI_STATUS_ATTENTION: "\033[33m",
        CLI_STATUS_PROBLEMS: "\033[31m",
    }.get(status, "")
    return f"{color}{status}\033[0m" if color else status


def format_cli_summary(
    engine: "SysCheckEngine", report_path: str | Path, *, stream: Any = None
) -> str:
    """Format the compact, English public summary for a completed run."""
    output_stream = sys.stdout if stream is None else stream
    status = determine_cli_status(engine.findings)
    rule = "-" * min(72, _terminal_width(output_stream))
    recommendation_plan = getattr(engine, "recommendation_plan", None)
    recommendation_count = (
        len(recommendation_plan.recommendations) if recommendation_plan else 0
    )
    confirmed_problem_count = sum(
        finding.severity != "Info" for finding in engine.findings
    )
    os_name = getattr(engine, "os_name", "") or getattr(engine, "distro_id", "unknown")
    desktop = getattr(engine, "desktop_environment", "") or "?"
    session_type = getattr(engine, "session_type", "") or "?"
    session = f"{desktop} / {session_type}"

    lines = [
        rule,
        f"{PRODUCT_NAME} {PRODUCT_VERSION}",
        "Read-only diagnostics | no sudo | no system changes",
        rule,
        "",
        "System",
        f"  Host        {getattr(engine, 'hostname', '') or 'unknown'}",
        f"  OS          {os_name}",
        f"  Kernel      {getattr(engine, 'active_kernel', '') or 'unknown'}",
        f"  Session     {session}",
        "",
        "Collecting diagnostics",
    ]
    lines.extend(f"  ✓ {section}" for section in _CLI_COLLECTION_SECTIONS)
    lines.extend(
        [
            "",
            "Analyzing evidence",
            f"  ✓ {len(engine.commands_used)} commands executed",
            f"  ✓ {len(engine.observations)} actionable observations",
            "",
            rule,
            "",
            f"HEALTH STATUS    {_CLI_STATUS_MARKERS[status]} "
            f"{_style_cli_status(status, output_stream)}",
            "",
            f"Confirmed problems              {confirmed_problem_count}",
            f"Actionable recommendations      {recommendation_count}",
            f"Analysis limitations            {len(engine.restrictions)}",
            f"Commands executed              {len(engine.commands_used)}",
            "",
            "Report",
            f"  {report_path}",
            rule,
            "",
        ]
    )
    return "\n".join(lines)


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


_BTRFS_DEVICE_RECORD_RE = re.compile(
    r"^\s*devid\s+\d+\b.*\bpath\s+\S+(?:\s+MISSING)?\s*$",
    re.IGNORECASE,
)
_BTRFS_MISSING_DEVICE_RE = re.compile(
    r"^\s*devid\s+\d+\b.*\bpath\s+\S+\s+MISSING\s*$",
    re.IGNORECASE,
)
_BTRFS_DEVICE_STAT_RECORD_RE = re.compile(
    r"^\s*(?P<device>\[[^\]\r\n]+\])\.(?P<counter>[A-Za-z0-9_]+)\s+"
    r"(?P<value>\d+)\s*$"
)


def _btrfs_missing_device_lines(text: str) -> List[str]:
    """Return only structured Btrfs device records marked ``MISSING``."""
    return [line for line in text.splitlines() if _BTRFS_MISSING_DEVICE_RE.search(line)]


def _classify_btrfs_status(
    cmd_result: CmdResult, *, command_kind: Optional[str] = None
) -> str:
    """
    Klasyfikuje wynik polecenia btrfs.
    Zwraca: "ok", "no_scrub", "scrub_inactive", "permission_denied",
    "command_not_found", "device_missing", "error".

    ``no_scrub`` means that the command reported no scrub history. A status
    such as ``No scrub is running`` only means that a scrub is inactive; it
    must not be interpreted as evidence that a scrub has never run.
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

    # Distinguish no history from a currently inactive scrub.
    if "no scrub data" in stdout_lower or "no scrub data" in stderr_lower:
        return "no_scrub"
    if (
        "no scrub found" in stdout_lower
        or "no scrub found" in stderr_lower
        or "no scrub has been run" in stdout_lower
        or "no scrub has been run" in stderr_lower
    ):
        return "no_scrub"
    if (
        "no scrub is running" in stdout_lower
        or "no scrub is running" in stderr_lower
        or "scrub not running" in stdout_lower
        or "scrub not running" in stderr_lower
    ):
        return "scrub_inactive"

    # Only a structured device record is evidence of a missing device.  Text
    # such as "No missing devices" is a healthy/negative control, not a
    # device error.  The optional kind allows filesystem-show to reject a
    # successful but unrecognizable capture as non-authoritative.
    if _btrfs_missing_device_lines(cmd_result.stdout):
        return "device_missing"

    if command_kind == "show" and (
        not cmd_result.stdout.strip()
        or not any(
            _BTRFS_DEVICE_RECORD_RE.search(line)
            for line in cmd_result.stdout.splitlines()
        )
    ):
        return "error"

    # Jeśli wszystko OK
    if cmd_result.return_code == 0:
        return "ok"

    return "error"


def _btrfs_missing_capture_is_authoritative(result: CmdResult, status: str) -> bool:
    """Whether a structured Btrfs ``MISSING`` line is usable as evidence."""
    return (
        status == "device_missing"
        and result.execution_status == "ok"
        and result.return_code == 0
        and not result.privilege_required
        and not result.truncated
    )


def _parse_btrfs_device_stats(text: str) -> Tuple[Dict[str, int], int, bool]:
    """Parse Btrfs device-stat records and retain malformed-output evidence.

    Returns ``(non_zero_error_counters, valid_record_count, malformed)``.  A
    valid record may be a non-error counter such as ``cleaner_ios``; only
    counters ending in ``_errs`` can become a device-error observation.
    """
    counters: Dict[str, int] = {}
    valid_records = 0
    malformed = False
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _BTRFS_DEVICE_STAT_RECORD_RE.match(line)
        if match is None:
            malformed = True
            continue
        valid_records += 1
        counter = match.group("counter")
        if counter.endswith("_errs"):
            value = int(match.group("value"))
            if value != 0:
                counters[f"{match.group('device')}.{counter}"] = value
    return counters, valid_records, malformed


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
    # The diagnostic regexes use Python/PCRE constructs such as ``(?:...)``
    # and ``\b``.  Keep the shell stage aligned with those existing patterns,
    # and quote the pattern so messages such as ``can't set address`` cannot
    # terminate the shell string.
    stages = [f"grep -iP -- {shlex.quote(regex)}" for regex in regexes]
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
        f"{upstream_cmd} | grep -iP -- {shlex.quote(regex)} | wc -l; "
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
        or "read-only" in normalized
        or "read only" in normalized
    ):
        return "critical_or_fatal"
    return "io_error"


def _filesystem_io_error_family(line: str) -> Optional[str]:
    """Classify a matched I/O event without inferring its root cause."""
    if not re.search(RE_FILESYSTEM_IO_ERROR, line, re.IGNORECASE):
        return None
    normalized = line.lower()
    if any(
        marker in normalized
        for marker in (
            "corrupt",
            "checksum",
            "parent transid",
            "generation",
        )
    ):
        return "filesystem_corruption"
    if "read-only" in normalized or "read only" in normalized:
        return "filesystem_read_only"
    if any(
        marker in normalized
        for marker in (
            "buffer i/o error",
            "blk_update_request",
            "i/o error, dev",
            "critical medium error",
        )
    ):
        return "block_io"
    if any(marker in normalized for marker in ("ext4-fs", "xfs", "btrfs")):
        return "filesystem"
    return "unknown"


def _kernel_oops_panic_severity(line: str) -> Optional[str]:
    """Return the explicit severity ('P0' or 'P1') encoded in a matched kernel oops/panic line."""
    if re.search(RE_KERNEL_PANIC, line, re.IGNORECASE):
        return "P0"
    if re.search(RE_KERNEL_OOPS_BUG, line, re.IGNORECASE):
        return "P1"
    return None


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
        "systemd_user_source_failure": FindingClassification(
            DiagnosticDomain.SYSTEMD,
            FindingKind.SOURCE_FAILURE,
            Actionability.CONDITIONAL,
            RecommendationIntent.VERIFY,
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
        "hardware_thermal_throttling": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.HARDWARE_THERMAL_THROTTLING,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_oops_panic": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_OOPS_PANIC,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_soft_lockup": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_SOFT_LOCKUP,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_hard_lockup": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_HARD_LOCKUP,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_hung_task": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_HUNG_TASK,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_rcu_stall": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_RCU_STALL,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "platform_acpi_firmware_error": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.PLATFORM_ACPI_FIRMWARE_ERROR,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "kernel_firmware_load_fail": FindingClassification(
            DiagnosticDomain.KERNEL,
            FindingKind.KERNEL_FIRMWARE_LOAD_FAIL,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "usb_enumeration_fail": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.USB_ENUMERATION_FAIL,
            Actionability.ACTIONABLE,
            RecommendationIntent.INVESTIGATE,
        ),
        "iommu_fault": FindingClassification(
            DiagnosticDomain.HARDWARE,
            FindingKind.IOMMU_FAULT,
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
        if cat == "systemd_user_source_failure":
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.COMMAND_RESULT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    "User systemd failed-unit query was not authoritative; "
                    "failed user services were not inferred"
                ),
                data={
                    "scope": d.get("scope", "user"),
                    "query": d.get("query", ""),
                    "failure_kind": d.get("failure_kind", ""),
                    "authoritative": bool(d.get("authoritative", False)),
                    "execution_status": d.get("execution_status", ""),
                    "return_code": d.get("return_code"),
                    "stdout": d.get("stdout", ""),
                    "stderr": d.get("stderr", ""),
                },
                strength=EvidenceStrength.WEAK,
                directness=EvidenceDirectness.DIRECT,
                completeness=EvidenceCompleteness.PARTIAL,
            )
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
                completeness=(
                    EvidenceCompleteness.COMPLETE
                    if observation.data_complete
                    else EvidenceCompleteness.PARTIAL
                ),
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
                completeness=(
                    EvidenceCompleteness.COMPLETE
                    if observation.data_complete
                    else EvidenceCompleteness.PARTIAL
                ),
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
                completeness=(
                    EvidenceCompleteness.COMPLETE
                    if observation.data_complete
                    else EvidenceCompleteness.PARTIAL
                ),
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

            # Factual summary based on the measurement used for the threshold.
            total = d.get("total_seconds")
            userspace = d.get("userspace_time")
            target = d.get("target_time")
            measurement = (
                target
                if target is not None
                else userspace
                if userspace is not None
                else total
            )
            threshold = d.get("threshold", 30)
            fstrim_in_cc = d.get("fstrim_in_critical_chain")
            if target is not None:
                summary = f"Boot-to-graphical.target time was {target} seconds"
            elif userspace is not None:
                summary = f"Userspace initialization took {userspace} seconds"
            elif total is not None:
                summary = f"Total measured boot time was {total} seconds"
            else:
                summary = "Boot time measurement recorded."
            if (
                measurement is not None
                and threshold is not None
                and measurement > threshold
            ):
                summary += (
                    f", exceeding the configured threshold of {threshold} seconds"
                )
            elif not summary.endswith("."):
                summary += "."
            if total is not None and target is not None:
                summary += f" Total measured boot time was {total} seconds."
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
                    "event_families": d.get("event_families", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "filesystem_io_error"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "hardware_thermal_throttling":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Hardware thermal throttling event detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "thermal_throttle_detected": d.get(
                        "thermal_throttle_detected", False
                    ),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "hardware_thermal_throttling"
                    ),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_oops_panic":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            has_panic = d.get("panic_detected", False)
            event_desc = "Kernel panic" if has_panic else "Kernel oops / BUG"
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"{event_desc} event detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "oops_panic_detected": d.get("oops_panic_detected", False),
                    "panic_detected": has_panic,
                    "highest_severity": d.get("highest_severity", "P1"),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "kernel_oops_panic"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_soft_lockup":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Kernel watchdog soft lockup detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "soft_lockup_detected": d.get("soft_lockup_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "kernel_stall_reliability"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_hard_lockup":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Kernel watchdog hard LOCKUP detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "hard_lockup_detected": d.get("hard_lockup_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "kernel_stall_reliability"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_hung_task":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Kernel hung task detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "hung_task_detected": d.get("hung_task_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "kernel_stall_reliability"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_rcu_stall":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Kernel RCU stall / starvation detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "rcu_stall_detected": d.get("rcu_stall_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get("source_query", "kernel_stall_reliability"),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "platform_acpi_firmware_error":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Platform ACPI BIOS / interpreter error detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "acpi_firmware_error_detected": d.get(
                        "acpi_firmware_error_detected", False
                    ),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "platform_device_reliability"
                    ),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "kernel_firmware_load_fail":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"Kernel firmware loader failure detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "firmware_load_fail_detected": d.get(
                        "firmware_load_fail_detected", False
                    ),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "platform_device_reliability"
                    ),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "usb_enumeration_fail":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"USB descriptor / enumeration failure detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "usb_enumeration_fail_detected": d.get(
                        "usb_enumeration_fail_detected", False
                    ),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "platform_device_reliability"
                    ),
                },
                strength=strength,
                directness=directness,
                completeness=completeness,
            )
        if cat == "iommu_fault":
            strength = EvidenceStrength.STRONG
            directness = EvidenceDirectness.DIRECT
            completeness = EvidenceCompleteness.COMPLETE
            if not observation.data_complete:
                completeness = EvidenceCompleteness.PARTIAL

            count = d.get("match_count", 0)
            return Evidence(
                evidence_id=eid,
                evidence_type=EvidenceType.JOURNAL_EVENT,
                source_observation_ids=(oid,),
                source_raw_ids=observation.source_raw_ids,
                summary=(
                    f"IOMMU DMA translation fault detected "
                    f"during current boot ({count} matching journal line(s))"
                ),
                data={
                    "iommu_fault_detected": d.get("iommu_fault_detected", False),
                    "match_count": count,
                    "matched_lines": d.get("matched_lines", []),
                    "journal_scope": d.get("journal_scope", "current_boot_kernel"),
                    "source_query": d.get(
                        "source_query", "platform_device_reliability"
                    ),
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
SystemdUserSourceFailureRule = _diagnostic_rules.SystemdUserSourceFailureRule
FilesystemIoErrorRule = _diagnostic_rules.FilesystemIoErrorRule
GeneralSegfaultRule = _diagnostic_rules.GeneralSegfaultRule
GpuI915HangRule = _diagnostic_rules.GpuI915HangRule
GpuNvidiaXid79Rule = _diagnostic_rules.GpuNvidiaXid79Rule
HardwareMceEdacRule = _diagnostic_rules.HardwareMceEdacRule
HardwareThermalThrottlingRule = _diagnostic_rules.HardwareThermalThrottlingRule
KernelOopsPanicRule = _diagnostic_rules.KernelOopsPanicRule
KernelSoftLockupRule = _diagnostic_rules.KernelSoftLockupRule
KernelHardLockupRule = _diagnostic_rules.KernelHardLockupRule
KernelHungTaskRule = _diagnostic_rules.KernelHungTaskRule
KernelRcuStallRule = _diagnostic_rules.KernelRcuStallRule
PlatformAcpiFirmwareErrorRule = _diagnostic_rules.PlatformAcpiFirmwareErrorRule
KernelFirmwareLoadFailRule = _diagnostic_rules.KernelFirmwareLoadFailRule
UsbEnumerationFailRule = _diagnostic_rules.UsbEnumerationFailRule
IommuFaultRule = _diagnostic_rules.IommuFaultRule
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
        self.output_dir = Path(output_dir).expanduser().resolve()
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
        self.os_name: str = ""
        self.desktop_environment: str = ""
        self.session_type: str = ""
        self.distro_config: dict = DISTRO_CONFIG.get("arch", DISTRO_CONFIG["arch"])
        self.report_lines: List[str] = []
        self.findings: List[Finding] = []
        self.observations: List[Observation] = []  # Stage 2: OBS
        self.recommendation_plan: Optional[RecommendationPlan] = None  # Stage 4: REC
        self.raw_diagnostics: List[RawDiagnostic] = []
        self.evidence_objects: List[Evidence] = []
        self.pipeline_accounting: List[Dict[str, str]] = []
        self.restrictions: List[str] = []
        self.commands_used: List[str] = []
        self._script_pids: List[str] = []

    # ── Logowanie ────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        if not self.quiet:
            print(f"  {msg}", file=sys.stderr, flush=True)

    def log_section(self, name: str) -> None:
        if not self.quiet:
            public_names = {
                "Identyfikacja środowiska": "Environment identification",
                "Stan zasobów": "Resource status",
                "Dyski, NVMe, Btrfs": "Storage, NVMe, and Btrfs",
                "Kernel i sprzęt": "Kernel and hardware",
                "Systemd i usługi": "Systemd and services",
                "Pakiety i spójność": "Packages and integrity",
                "Warstwa graficzna": "Graphics stack",
                "Sieć i bezpieczeństwo": "Network and security",
                "Środowisko użytkownika": "User environment",
                "Budowanie podsumowania": "Building summary",
            }
            print(
                f"\n=== {public_names.get(name, 'Diagnostics')} ===",
                file=sys.stderr,
                flush=True,
            )

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

    def _record_truncated_capture(
        self, result: Optional[CmdResult], source_name: str
    ) -> None:
        """Record that a bounded result cannot prove absence of a finding."""
        if result is None or not result.truncated:
            return
        restriction = (
            f"Capture truncated for {source_name} (status=TRUNCATED_OUTPUT); "
            "absence of matching data is not authoritative."
        )
        if restriction not in self.restrictions:
            self.restrictions.append(restriction)

    def _record_source_status(
        self,
        result: Optional[CmdResult],
        source_name: str,
        *,
        authority_state: Optional[str] = None,
    ) -> None:
        """Record a source state that cannot prove health or failure.

        Collection failures are deliberately kept out of diagnostic Findings.
        The status token remains explicit so command failure is not confused
        with a successful zero-result query.
        """
        if result is None:
            return
        if authority_state is None:
            if result.execution_status == "ok" and not result.truncated:
                return
            if result.execution_status == "ok" and result.truncated:
                self._record_truncated_capture(result, source_name)
                return
            authority_state = {
                "error": "FAILED_EXECUTION",
                "timeout": "TIMEOUT",
                "not_found": "COMMAND_NOT_FOUND",
                "permission_denied": "PERMISSION_DENIED",
                "empty_ok": "MALFORMED_OUTPUT",
            }.get(result.execution_status, "FAILED_EXECUTION")
        if authority_state == "SUCCESS_AUTHORITATIVE":
            return
        restriction = (
            f"Source {source_name} cannot establish an authoritative state "
            f"(status={authority_state}, rc={result.return_code}); "
            "no healthy or failure state was inferred."
        )
        if restriction not in self.restrictions:
            self.restrictions.append(restriction)

    @staticmethod
    def _pipeline_rejection_reason(observation: Observation) -> str:
        """Return a stable reason when an Observation has no Finding."""
        details = observation.details
        if (
            observation.category == "btrfs_error"
            and details.get("status") == "device_missing"
            and details.get("privilege_limited", False)
        ):
            return "privilege_limited_btrfs_missing"
        if observation.category == "btrfs_error" and details.get("status") in (
            "permission_denied",
            "command_not_found",
        ):
            return "btrfs_state_requires_privilege_or_tool"
        if (
            observation.category == "btrfs_scrub"
            and details.get("scrub_status") == "scrub_inactive"
        ):
            return "btrfs_scrub_inactive"
        if observation.category == "systemd_user_source_failure":
            if details.get("failure_kind") == "malformed_output":
                return "user_systemd_query_non_authoritative"
            return "user_systemd_query_unavailable"
        return "rule_returned_no_finding"

    def _refresh_pipeline_accounting(self) -> None:
        """Expose deterministic RAW -> OBS -> Finding/rejection accounting."""
        findings_by_observation = {
            observation_id: finding
            for finding in self.findings
            for observation_id in finding.source_observation_ids
        }
        self.pipeline_accounting = []
        for observation in self.observations:
            finding = findings_by_observation.get(observation.obs_id)
            self.pipeline_accounting.append(
                {
                    "raw_source_id": (
                        observation.source_raw_ids[0]
                        if observation.source_raw_ids
                        else ""
                    ),
                    "observation_id": observation.obs_id,
                    "finding_id": finding.finding_id if finding else "",
                    "outcome": "finding" if finding else "rejected",
                    "reason": ""
                    if finding
                    else self._pipeline_rejection_reason(observation),
                }
            )

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
        self.os_name = pretty_name
        self.desktop_environment = xdg_desktop
        self.session_type = xdg_type

        self.report_lines.append(
            heading(1, f"{PRODUCT_NAME} ({PRODUCT_SHORT_NAME}) — Raport diagnostyczny")
        )
        self.report_lines.append(
            f"**Produkt:** `{PRODUCT_NAME} ({PRODUCT_SHORT_NAME})`  \n"
        )
        self.report_lines.append(f"**Wersja produktu:** `{PRODUCT_VERSION}`  \n")
        self.report_lines.append(
            "**Kompatybilność raportów/snapshotów:** "
            f"`{REPORT_COMPATIBILITY_VERSION}`  \n"
        )
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
        btrfs_show = r["btrfs_show"]
        btrfs_stats = r["btrfs_stats"]
        btrfs_scrub = r["btrfs_scrub"]
        btrfs_statuses = {
            name: _classify_btrfs_status(result, command_kind=name)
            for name, result in (
                ("show", btrfs_show),
                ("stats", btrfs_stats),
                ("scrub", btrfs_scrub),
            )
        }
        btrfs_missing_lines = {
            name: _btrfs_missing_device_lines(result.stdout)
            for name, result in (
                ("show", btrfs_show),
                ("stats", btrfs_stats),
                ("scrub", btrfs_scrub),
            )
        }

        self.report_lines.append(heading(2, "3. Dyski, NVMe i Btrfs"))
        self.report_lines.append(heading(3, "Urządzenia blokowe"))
        self.report_lines.append(codeblock(r["lsblk"].to_fallback_text()))
        self.report_lines.append(heading(3, "Systemy plików (df -h)"))
        self.report_lines.append(codeblock(r["df_h"].to_fallback_text()))
        self.report_lines.append(heading(3, "Inode (df -i)"))
        self.report_lines.append(codeblock(r["df_i"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — filesystem show"))
        self.report_lines.append(codeblock(r["btrfs_show"].to_fallback_text()))
        if btrfs_missing_lines["show"]:
            self.report_lines.append(
                "⚠️ Btrfs show reports `MISSING`; this unprivileged capture is "
                "incomplete and non-authoritative. Raw output is preserved; "
                "no finding is emitted from `MISSING` alone.\n\n"
            )
        self.report_lines.append(heading(3, "Btrfs — filesystem df"))
        self.report_lines.append(codeblock(r["btrfs_df"].to_fallback_text()))
        self.report_lines.append(heading(3, "Btrfs — device stats"))
        self.report_lines.append(codeblock(r["btrfs_stats"].to_fallback_text()))
        if btrfs_missing_lines["stats"]:
            self.report_lines.append(
                "⚠️ Btrfs device stats reports `MISSING`; this unprivileged "
                "capture is incomplete and non-authoritative. Raw output is "
                "preserved; no finding is emitted from `MISSING` alone.\n\n"
            )
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
        self._record_source_status(nvme_result, "NVMe tool output")

        # Analiza Btrfs
        for name, result in r.items():
            self._record_truncated_capture(result, f"storage command {name}")

        # Sprawdź czy Btrfs wymaga roota
        for name in ("show", "stats", "scrub"):
            status = btrfs_statuses[name]
            if status == "permission_denied":
                restriction = (
                    f"Btrfs {name} — wymaga sudo. "
                    f"Nie można zweryfikować stanu filesystemu Btrfs bez podwyższonych uprawnień."
                )
                if btrfs_missing_lines[name]:
                    restriction += (
                        " Captured MISSING is incomplete and non-authoritative; "
                        "raw output is preserved."
                    )
            elif (
                status == "device_missing"
                and not _btrfs_missing_capture_is_authoritative(
                    {"show": btrfs_show, "stats": btrfs_stats, "scrub": btrfs_scrub}[
                        name
                    ],
                    status,
                )
            ):
                restriction = (
                    f"Btrfs {name} reports MISSING under an unprivileged collection; "
                    "device state is incomplete and non-authoritative. Raw output "
                    "is preserved; no finding is emitted from MISSING alone."
                )
            elif name == "show" and status in {"error", "command_not_found"}:
                restriction = (
                    "Btrfs show returned no authoritative device inventory; "
                    "Btrfs device state is unknown."
                )
            else:
                continue
            if restriction not in self.restrictions:
                self.restrictions.append(restriction)

        if btrfs_stats.execution_status != "ok" and btrfs_statuses["stats"] != (
            "permission_denied"
        ):
            self._record_source_status(btrfs_stats, "Btrfs device stats")
        if btrfs_show.execution_status != "ok" and btrfs_statuses["show"] != (
            "permission_denied"
        ):
            self._record_source_status(btrfs_show, "Btrfs filesystem show")
        if btrfs_scrub.execution_status != "ok" and btrfs_statuses["scrub"] != (
            "permission_denied"
        ):
            self._record_source_status(btrfs_scrub, "Btrfs scrub status")

        # Analiza Btrfs device stats (tylko jeśli mamy dane)
        btrfs_stats_error_recorded = False
        if btrfs_stats.execution_status == "ok" and not btrfs_stats.stdout.strip():
            self._record_source_status(
                btrfs_stats,
                "Btrfs device stats",
                authority_state="MALFORMED_OUTPUT",
            )
        if btrfs_stats.execution_status == "ok" and btrfs_stats.stdout:
            error_counters, valid_records, stats_malformed = _parse_btrfs_device_stats(
                btrfs_stats.stdout
            )
            has_errors = bool(error_counters)
            if stats_malformed:
                self._record_source_status(
                    btrfs_stats,
                    "Btrfs device stats",
                    authority_state="MALFORMED_OUTPUT",
                )
            if has_errors:
                btrfs_stats_error_recorded = True
                self.raw_diagnostics.append(
                    _raw_from_result(
                        btrfs_stats,
                        source_id="BTRFS-ERR-001",
                        category="btrfs_error",
                        payload={
                            "device_error_counters": dict(error_counters),
                            "stats_malformed": stats_malformed,
                        },
                    )
                )
            if not has_errors and valid_records == 0 and not stats_malformed:
                self._record_source_status(
                    btrfs_stats,
                    "Btrfs device stats",
                    authority_state="MALFORMED_OUTPUT",
                )
            elif not has_errors and stats_malformed:
                self.report_lines.append(
                    "⚠️ Wynik Btrfs device stats jest niepełny lub nierozpoznawalny; "
                    "brak błędów nie jest rozstrzygający.\n\n"
                )
            elif not has_errors and not btrfs_stats.truncated:
                self.report_lines.append(
                    "✅ Liczniki błędów Btrfs: wszystkie zerowe.\n\n"
                )
            elif not has_errors:
                self.report_lines.append(
                    "⚠️ Liczniki błędów Btrfs są niepełne z powodu obcięcia capture; "
                    "brak błędów nie jest rozstrzygający.\n\n"
                )

        if btrfs_missing_lines["show"] and not btrfs_stats_error_recorded:
            authoritative_missing = _btrfs_missing_capture_is_authoritative(
                btrfs_show, btrfs_statuses["show"]
            )
            self.raw_diagnostics.append(
                _raw_from_result(
                    btrfs_show,
                    source_id=(
                        "BTRFS-DEVICE-MISSING-001"
                        if authoritative_missing
                        else "BTRFS-MISSING-INCOMPLETE-001"
                    ),
                    category="btrfs_error",
                    payload={
                        "status": "device_missing",
                        "privilege_limited": not authoritative_missing,
                        "authoritative": authoritative_missing,
                        "missing_detected": True,
                        "matched_lines": btrfs_missing_lines["show"][:20],
                        "match_count": len(btrfs_missing_lines["show"]),
                        "source_query": "btrfs_show",
                    },
                )
            )

        # Analiza Btrfs scrub status
        scrub_status = btrfs_statuses["scrub"]
        if scrub_status == "no_scrub":
            self.raw_diagnostics.append(
                _raw_from_result(
                    btrfs_scrub,
                    source_id="BTRFS-SCRUB-001",
                    category="btrfs_scrub",
                    payload={
                        "scrub_status": scrub_status,
                        "scrub_semantics": "never_run",
                    },
                )
            )
        elif scrub_status == "scrub_inactive":
            self.report_lines.append(
                "ℹ️ Btrfs scrub nie jest obecnie uruchomiony; status nie oznacza "
                "braku wcześniejszej historii scrubowania.\n\n"
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
                            _raw_from_result(
                                r["df_h"],
                                source_id=_storage_diagnostic_id("critical", mount),
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
                            _raw_from_result(
                                r["df_h"],
                                source_id=_storage_diagnostic_id("warning", mount),
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
            "hardware_thermal_throttling": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_HARDWARE_THERMAL_THROTTLE,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "kernel_oops_panic": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_KERNEL_OOPS_PANIC,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "kernel_stall_reliability": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_KERNEL_STALL_RELIABILITY,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "platform_device_reliability": (
                _oom_collector_command(
                    "journalctl -b -k --no-pager 2>/dev/null",
                    RE_PLATFORM_DEVICE_RELIABILITY,
                ),
                TIMEOUT_LONG,
                False,
            ),
            "lspci": (["lspci", "-k"], TIMEOUT_SHORT, False),
            "lsusb": (["lsusb"], TIMEOUT_SHORT, False),
        }
        r = self._parallel_cmd(tasks_cmd)

        for name, result in r.items():
            if name not in {"lspci", "lsusb"}:
                self._record_truncated_capture(result, f"current-boot query {name}")

        reliability_query_names = (
            "kernel_errors",
            "segfaults",
            "oom_events",
            "pcie_aer",
            "nvme_controller_reliability",
            "filesystem_io_error",
            "kernel_oops_panic",
            "kernel_stall_reliability",
            "platform_device_reliability",
        )
        for name in reliability_query_names:
            result = r.get(name)
            if result is not None and result.execution_status != "ok":
                self._record_source_status(result, f"current-boot journal query {name}")

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
        hardware_thermal_throttling_result = r.get("hardware_thermal_throttling")
        kernel_oops_panic_result = r.get("kernel_oops_panic")
        kernel_stall_reliability_result = r.get("kernel_stall_reliability")
        soft_lockup_result = (
            r.get("kernel_soft_lockup") or kernel_stall_reliability_result
        )
        hard_lockup_result = (
            r.get("kernel_hard_lockup") or kernel_stall_reliability_result
        )
        hung_task_result = r.get("kernel_hung_task") or kernel_stall_reliability_result
        rcu_stall_result = r.get("kernel_rcu_stall") or kernel_stall_reliability_result
        platform_device_reliability_result = r.get("platform_device_reliability")
        acpi_firmware_result = (
            r.get("platform_acpi_firmware_error") or platform_device_reliability_result
        )
        firmware_load_result = (
            r.get("kernel_firmware_load_fail") or platform_device_reliability_result
        )
        usb_enum_result = (
            r.get("usb_enumeration_fail") or platform_device_reliability_result
        )
        iommu_fault_result = r.get("iommu_fault") or platform_device_reliability_result
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
                    _raw_from_result(
                        segfaults_result,
                        source_id="SEGFAULT-WP-001",
                        category="segfault",
                        payload={
                            "segfault_type": "wireplumber",
                            "count": unique_segfault_count,
                        },
                    )
                )
            else:
                # Poważniejsze segfaulty — wiele procesów lub nieznana przyczyna
                self.raw_diagnostics.append(
                    _raw_from_result(
                        segfaults_result,
                        source_id="SEGFAULT-SYS-001",
                        category="segfault",
                        payload={
                            "segfault_type": "system_wide",
                            "count": unique_segfault_count,
                        },
                    )
                )
        elif unique_segfault_count > 0:
            self.raw_diagnostics.append(
                _raw_from_result(
                    segfaults_result,
                    source_id="SEGFAULT-MIN-001",
                    category="segfault_minor",
                    payload={"count": unique_segfault_count},
                )
            )

        # Sprawdź taint — akceptuj wyłącznie jawne markery kernela, a nie
        # przypadkowe wystąpienia słowa "tainted" w komunikatach.
        taint_matching = []
        if kernel_errors_result.is_ok() and kernel_errors_result.stdout.strip():
            taint_matching = [
                line
                for line in kernel_errors_result.stdout.splitlines()
                if re.search(RE_KERNEL_TAINT, line, re.IGNORECASE)
                and not re.search(
                    r"\bnot\s+(?:tainted|tainting|taints)\b",
                    line,
                    re.IGNORECASE,
                )
            ]
        if taint_matching:
            self.raw_diagnostics.append(
                _raw_from_result(
                    kernel_errors_result,
                    source_id="KERNEL-TAINT-001",
                    category="tainted",
                    payload={
                        "tainted": True,
                        "matched_lines": taint_matching[:20],
                        "match_count": len(taint_matching),
                        "journal_scope": "current_boot_kernel",
                        "source_query": "kernel_errors",
                    },
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
                    _raw_from_result(
                        oom_events_result,
                        source_id="KERNEL-OOM-001",
                        category="oom_event",
                        payload={
                            "oom_detected": True,
                            "matched_lines": oom_matching[:20],
                            "match_count": len(oom_matching),
                            "match_classes": match_classes,
                            "journal_scope": "current_boot_kernel",
                            "source_query": "oom_events",
                        },
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
                    _raw_from_result(
                        gpu_i915_hang_result,
                        source_id="GPU-I915-HANG-001",
                        category="gpu_i915_hang",
                        payload={
                            "hang_detected": True,
                            "matched_lines": hang_matching[:20],
                            "match_count": len(hang_matching),
                            "driver": "i915",
                            "driver_attribution_source": "in_message",
                            "journal_scope": "current_boot_kernel",
                            "source_query": "gpu_i915_hang",
                        },
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
                    _raw_from_result(
                        amdgpu_reset_fail_result,
                        source_id="AMDGPU-RESET-FAIL-001",
                        category="amdgpu_reset_fail",
                        payload={
                            "reset_failure_detected": True,
                            "matched_lines": reset_matching[:20],
                            "match_count": len(reset_matching),
                            "driver": "amdgpu",
                            "driver_attribution_source": "in_message",
                            "journal_scope": "current_boot_kernel",
                            "source_query": "amdgpu_reset_fail",
                        },
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
                    _raw_from_result(
                        gpu_nvidia_xid_79_result,
                        source_id="GPU-NVIDIA-XID-79-001",
                        category="gpu_nvidia_xid_79",
                        payload={
                            "xid_detected": True,
                            "xid_code": 79,
                            "matched_lines": xid79_matching[:20],
                            "match_count": len(xid79_matching),
                            "driver": "nvidia",
                            "driver_attribution_source": "in_message",
                            "journal_scope": "current_boot_kernel",
                            "source_query": "gpu_nvidia_xid_79",
                        },
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
                    _raw_from_result(
                        pcie_aer_result,
                        source_id="PCIE-AER-001",
                        category="pcie_aer_error",
                        payload={
                            "aer_detected": True,
                            "aer_severity": aer_severity,
                            "matched_lines": aer_matching[:20],
                            "match_count": len(aer_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "pcie_aer",
                        },
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
                    _raw_from_result(
                        nvme_controller_reliability_result,
                        source_id="NVME-CONTROLLER-RESET-001",
                        category="nvme_controller_reliability",
                        payload={
                            "nvme_detected": True,
                            "event_severity": event_severity,
                            "matched_lines": nvme_matching[:20],
                            "match_count": len(nvme_matching),
                            "event_classes": list(dict.fromkeys(severities)),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "nvme_controller_reliability",
                        },
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
                    _raw_from_result(
                        hardware_mce_edac_result,
                        source_id="HW-MCE-EDAC-001",
                        category="hardware_mce_edac_error",
                        payload={
                            "mce_edac_detected": True,
                            "event_severity": event_severity,
                            "matched_lines": mce_edac_matching[:20],
                            "match_count": len(mce_edac_matching),
                            "event_classes": list(dict.fromkeys(severities)),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "hardware_mce_edac",
                        },
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
                event_families = [
                    event_family
                    for line in fs_io_matching
                    if (event_family := _filesystem_io_error_family(line)) is not None
                ]
                event_severity = max(
                    severities,
                    key={"io_error": 1, "critical_or_fatal": 2}.get,
                )
                self.raw_diagnostics.append(
                    _raw_from_result(
                        filesystem_io_error_result,
                        source_id="FS-IO-ERROR-001",
                        category="filesystem_io_error",
                        payload={
                            "fs_io_detected": True,
                            "event_severity": event_severity,
                            "matched_lines": fs_io_matching[:20],
                            "match_count": len(fs_io_matching),
                            "event_classes": list(dict.fromkeys(severities)),
                            "event_families": list(dict.fromkeys(event_families)),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "filesystem_io_error",
                        },
                    )
                )

        # Sprawdź dławienie termiczne procesora (Hardware Thermal Throttling) — tylko jawne komunikaty z bieżącego bootu.
        if (
            hardware_thermal_throttling_result
            and hardware_thermal_throttling_result.is_ok()
            and hardware_thermal_throttling_result.stdout.strip()
        ):
            throttle_matching = [
                line
                for line in hardware_thermal_throttling_result.stdout.split("\n")
                if re.search(RE_HARDWARE_THERMAL_THROTTLE, line, re.IGNORECASE)
            ]
            if throttle_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        hardware_thermal_throttling_result,
                        source_id="HW-THERMAL-THROTTLE-001",
                        category="hardware_thermal_throttling",
                        payload={
                            "thermal_throttle_detected": True,
                            "matched_lines": throttle_matching[:20],
                            "match_count": len(throttle_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "hardware_thermal_throttling",
                        },
                    )
                )

        # Sprawdź błędy krytyczne jądra (Kernel Panic / Oops / BUG) — tylko jawne komunikaty z bieżącego bootu.
        if (
            kernel_oops_panic_result
            and kernel_oops_panic_result.is_ok()
            and kernel_oops_panic_result.stdout.strip()
        ):
            oops_panic_matching = [
                line
                for line in kernel_oops_panic_result.stdout.split("\n")
                if re.search(RE_KERNEL_OOPS_PANIC, line, re.IGNORECASE)
            ]
            if oops_panic_matching:
                severities = [
                    _kernel_oops_panic_severity(line) for line in oops_panic_matching
                ]
                has_panic = any(s == "P0" for s in severities)
                highest_severity = "P0" if has_panic else "P1"
                self.raw_diagnostics.append(
                    _raw_from_result(
                        kernel_oops_panic_result,
                        source_id="KERNEL-OOPS-PANIC-001",
                        category="kernel_oops_panic",
                        payload={
                            "oops_panic_detected": True,
                            "panic_detected": has_panic,
                            "highest_severity": highest_severity,
                            "matched_lines": oops_panic_matching[:20],
                            "match_count": len(oops_panic_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "kernel_oops_panic",
                        },
                    )
                )

        # Sprawdź zablokowanie programowe procesora (Kernel Soft Lockup) — tylko jawne komunikaty z bieżącego bootu.
        if (
            soft_lockup_result
            and soft_lockup_result.is_ok()
            and soft_lockup_result.stdout.strip()
        ):
            soft_matching = [
                line
                for line in soft_lockup_result.stdout.split("\n")
                if re.search(RE_KERNEL_SOFT_LOCKUP, line, re.IGNORECASE)
            ]
            if soft_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        soft_lockup_result,
                        source_id="KERNEL-SOFT-LOCKUP-001",
                        category="kernel_soft_lockup",
                        payload={
                            "soft_lockup_detected": True,
                            "matched_lines": soft_matching[:20],
                            "match_count": len(soft_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "kernel_stall_reliability",
                        },
                    )
                )

        # Sprawdź zablokowanie sprzętowe procesora (Kernel Hard Lockup) — tylko jawne komunikaty z bieżącego bootu.
        if (
            hard_lockup_result
            and hard_lockup_result.is_ok()
            and hard_lockup_result.stdout.strip()
        ):
            hard_matching = [
                line
                for line in hard_lockup_result.stdout.split("\n")
                if re.search(RE_KERNEL_HARD_LOCKUP, line, re.IGNORECASE)
            ]
            if hard_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        hard_lockup_result,
                        source_id="KERNEL-HARD-LOCKUP-001",
                        category="kernel_hard_lockup",
                        payload={
                            "hard_lockup_detected": True,
                            "matched_lines": hard_matching[:20],
                            "match_count": len(hard_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "kernel_stall_reliability",
                        },
                    )
                )

        # Sprawdź zablokowane zadania jądra (Kernel Hung Task) — tylko jawne komunikaty z bieżącego bootu.
        if (
            hung_task_result
            and hung_task_result.is_ok()
            and hung_task_result.stdout.strip()
        ):
            hung_matching = [
                line
                for line in hung_task_result.stdout.split("\n")
                if re.search(RE_KERNEL_HUNG_TASK, line, re.IGNORECASE)
            ]
            if hung_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        hung_task_result,
                        source_id="KERNEL-HUNG-TASK-001",
                        category="kernel_hung_task",
                        payload={
                            "hung_task_detected": True,
                            "matched_lines": hung_matching[:20],
                            "match_count": len(hung_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "kernel_stall_reliability",
                        },
                    )
                )

        # Sprawdź zablokowania podsystemu RCU (Kernel RCU Stall) — tylko jawne komunikaty z bieżącego bootu.
        if (
            rcu_stall_result
            and rcu_stall_result.is_ok()
            and rcu_stall_result.stdout.strip()
        ):
            rcu_matching = [
                line
                for line in rcu_stall_result.stdout.split("\n")
                if re.search(RE_KERNEL_RCU_STALL, line, re.IGNORECASE)
            ]
            if rcu_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        rcu_stall_result,
                        source_id="KERNEL-RCU-STALL-001",
                        category="kernel_rcu_stall",
                        payload={
                            "rcu_stall_detected": True,
                            "matched_lines": rcu_matching[:20],
                            "match_count": len(rcu_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "kernel_stall_reliability",
                        },
                    )
                )

        # Sprawdź błędy ACPI / BIOS (Platform ACPI Firmware Error) — tylko jawne komunikaty z bieżącego bootu.
        if (
            acpi_firmware_result
            and acpi_firmware_result.is_ok()
            and acpi_firmware_result.stdout.strip()
        ):
            acpi_matching = [
                line
                for line in acpi_firmware_result.stdout.split("\n")
                if re.search(RE_PLATFORM_ACPI_FIRMWARE_ERROR, line, re.IGNORECASE)
            ]
            if acpi_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        acpi_firmware_result,
                        source_id="PLATFORM-ACPI-FIRMWARE-ERROR-001",
                        category="platform_acpi_firmware_error",
                        payload={
                            "acpi_firmware_error_detected": True,
                            "matched_lines": acpi_matching[:20],
                            "match_count": len(acpi_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "platform_device_reliability",
                        },
                    )
                )

        # Sprawdź błędy ładowania oprogramowania układowego (Kernel Firmware Load Fail) — tylko jawne komunikaty z bieżącego bootu.
        if (
            firmware_load_result
            and firmware_load_result.is_ok()
            and firmware_load_result.stdout.strip()
        ):
            fw_matching = [
                line
                for line in firmware_load_result.stdout.split("\n")
                if re.search(RE_KERNEL_FIRMWARE_LOAD_FAIL, line, re.IGNORECASE)
            ]
            if fw_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        firmware_load_result,
                        source_id="KERNEL-FIRMWARE-LOAD-FAIL-001",
                        category="kernel_firmware_load_fail",
                        payload={
                            "firmware_load_fail_detected": True,
                            "matched_lines": fw_matching[:20],
                            "match_count": len(fw_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "platform_device_reliability",
                        },
                    )
                )

        # Sprawdź błędy enumeracji USB (USB Enumeration Fail) — tylko jawne komunikaty z bieżącego bootu.
        if (
            usb_enum_result
            and usb_enum_result.is_ok()
            and usb_enum_result.stdout.strip()
        ):
            usb_matching = [
                line
                for line in usb_enum_result.stdout.split("\n")
                if re.search(RE_USB_ENUMERATION_FAIL, line, re.IGNORECASE)
            ]
            if usb_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        usb_enum_result,
                        source_id="USB-ENUMERATION-FAIL-001",
                        category="usb_enumeration_fail",
                        payload={
                            "usb_enumeration_fail_detected": True,
                            "matched_lines": usb_matching[:20],
                            "match_count": len(usb_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "platform_device_reliability",
                        },
                    )
                )

        # Sprawdź błędy translacji IOMMU (IOMMU Fault) — tylko jawne komunikaty z bieżącego bootu.
        if (
            iommu_fault_result
            and iommu_fault_result.is_ok()
            and iommu_fault_result.stdout.strip()
        ):
            iommu_matching = [
                line
                for line in iommu_fault_result.stdout.split("\n")
                if re.search(RE_IOMMU_FAULT, line, re.IGNORECASE)
            ]
            if iommu_matching:
                self.raw_diagnostics.append(
                    _raw_from_result(
                        iommu_fault_result,
                        source_id="IOMMU-FAULT-001",
                        category="iommu_fault",
                        payload={
                            "iommu_fault_detected": True,
                            "matched_lines": iommu_matching[:20],
                            "match_count": len(iommu_matching),
                            "journal_scope": "current_boot_kernel",
                            "source_query": "platform_device_reliability",
                        },
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

        for name, result in r.items():
            self._record_truncated_capture(result, f"systemd command {name}")

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
        system_failed_state, _sys_units = self._classify_failed_units(sys_failed)
        if system_failed_state == "failed":
            self.raw_diagnostics.append(
                _raw_from_result(
                    sys_failed,
                    source_id="SYSD-SYS-FAIL-001",
                    category="systemd_failed",
                    payload={"scope": "system", "units": _sys_units},
                )
            )
        elif system_failed_state in {"source_failure", "malformed_output"}:
            self._record_source_status(
                sys_failed,
                "system systemd failed-unit query",
                authority_state=(
                    "MALFORMED_OUTPUT"
                    if system_failed_state == "malformed_output"
                    else None
                ),
            )

        # Analiza user failed units
        usr_failed = r["usr_failed"]
        user_failed_state, _failed_units = self._classify_user_failed_units(usr_failed)
        if user_failed_state == "failed":
            self.raw_diagnostics.append(
                _raw_from_result(
                    usr_failed,
                    source_id="SYSD-USR-FAIL-001",
                    category="systemd_failed",
                    payload={"scope": "user", "units": _failed_units},
                )
            )
        elif user_failed_state in {"source_failure", "malformed_output"}:
            self.raw_diagnostics.append(
                _raw_from_result(
                    usr_failed,
                    source_id="SYSD-USR-SOURCE-FAIL-001",
                    category="systemd_user_source_failure",
                    payload={
                        "scope": "user",
                        "query": usr_failed.command,
                        "failure_kind": user_failed_state,
                        "authoritative": False,
                        "execution_status": usr_failed.execution_status,
                        "return_code": usr_failed.return_code,
                        "stdout": usr_failed.stdout,
                        "stderr": usr_failed.stderr,
                    },
                )
            )
            if user_failed_state == "source_failure":
                restriction = (
                    "User systemd failed-unit query unavailable; user service state "
                    "is unknown "
                )
            else:
                restriction = (
                    "User systemd failed-unit query returned non-authoritative "
                    "output; user service state is unknown "
                )
            restriction += (
                f"(status={usr_failed.execution_status}, rc={usr_failed.return_code})."
            )
            if usr_failed.stderr:
                restriction += f" Captured stderr: {usr_failed.stderr}"
            self.restrictions.append(restriction)
            self.report_lines.append(
                "ℹ️ Nie można potwierdzić stanu nieudanych usług użytkownika; "
                "błąd lub nieautorytatywny wynik źródła nie jest traktowany jako "
                "nieudana usługa.\n\n"
            )

        # Analiza boot time — korelacja blame z critical-chain
        blame_out = r["blame"].to_fallback_text()
        critical_out = r["critical"].to_fallback_text()
        analyze_out = r["analyze"].to_fallback_text()

        # Track fstrim critical-chain membership when available
        # None = unknown, True = in critical chain, False = outside critical chain
        fstrim_in_critical_chain = None
        userspace_time = None
        target_time = None
        total_seconds = None

        if analyze_out:
            # Parse userspace, target, and total values using the same parser.
            # systemd-analyze may emit compound values such as
            # "1min 31.345s (userspace) = 1min 47.963s".
            userspace_match = re.search(
                rf"(?P<duration>{_SYSTEMD_DURATION_EXPRESSION})\s*\(userspace\)",
                analyze_out,
                re.IGNORECASE,
            )
            userspace_time = (
                _parse_systemd_duration(userspace_match.group("duration"))
                if userspace_match
                else None
            )
            target_match = re.search(
                rf"graphical\.target\s+reached\s+after\s+"
                rf"(?P<duration>{_SYSTEMD_DURATION_EXPRESSION})\s+in\s+userspace\b",
                analyze_out,
                re.IGNORECASE,
            )
            target_time = (
                _parse_systemd_duration(target_match.group("duration"))
                if target_match
                else None
            )
            total_match = re.search(r"=\s*([^\n]+)", analyze_out)
            total_seconds = (
                _parse_systemd_duration(total_match.group(1)) if total_match else None
            )
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
        if userspace_time is not None:
            measurement_time = (
                target_time if target_time is not None else userspace_time
            )
            measurement_source = (
                "graphical.target" if target_time is not None else "userspace"
            )
            if measurement_time > 30:
                payload = {
                    "userspace_time": userspace_time,
                    "measurement_source": measurement_source,
                    "threshold": 30.0,
                }
                if target_time is not None:
                    payload["target_time"] = target_time
                if total_seconds is not None:
                    payload["total_seconds"] = total_seconds
                if fstrim_in_critical_chain is not None:
                    payload["fstrim_in_critical_chain"] = fstrim_in_critical_chain
                self.raw_diagnostics.append(
                    _raw_from_result(
                        r["analyze"],
                        source_id="BOOT-SLOW-001",
                        category="boot_time",
                        payload=payload,
                    )
                )

    # ── Pomocnicze do analizy jednostek systemd ──────────────────
    @classmethod
    def _classify_failed_units(cls, result: CmdResult) -> Tuple[str, List[str]]:
        """Classify a systemd failed-unit query before interpretation."""
        if result.execution_status == "empty_ok":
            return "malformed_output", []
        if not result.is_ok():
            return "source_failure", []
        if result.truncated:
            return "malformed_output", []

        output = result.stdout.strip()
        if re.search(r"(?im)^\s*0 loaded units listed\.?\s*$", output):
            return "zero", []
        if cls._has_failed_units(output):
            units = cls._extract_failed_unit_names(output)
            if units:
                return "failed", units
        return "malformed_output", []

    @classmethod
    def _classify_user_failed_units(cls, result: CmdResult) -> Tuple[str, List[str]]:
        """Backward-compatible name for the user-systemd classifier."""
        return cls._classify_failed_units(result)

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

        for name, result in r.items():
            self._record_truncated_capture(result, f"package command {name}")

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
                    _raw_from_result(
                        kernels_result,
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
                data_complete=capture_complete
                and not bool(payload.get("stats_malformed")),
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
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "systemd_user_source_failure":
            return Observation(
                obs_id="SYSD-USR-SOURCE-FAIL-001",
                category="systemd_user_source_failure",
                details={**payload},
                direct_measurement=True,
                data_complete=False,
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
                data_complete=capture_complete,
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
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "storage_usage":
            state = payload.get("threshold_state", "warning")
            return Observation(
                obs_id=src_id,
                category="storage_usage",
                details={
                    "mountpoint": payload.get("mountpoint", "/"),
                    "usage_percent": payload.get("usage_percent", 0),
                    "threshold_state": state,
                    "capture_truncated": payload.get("capture_truncated", False),
                },
                direct_measurement=True,
                data_complete=capture_complete,
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
        elif cat == "hardware_thermal_throttling":
            return Observation(
                obs_id="HW-THERMAL-THROTTLE-001",
                category="hardware_thermal_throttling",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_oops_panic":
            return Observation(
                obs_id="KERNEL-OOPS-PANIC-001",
                category="kernel_oops_panic",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_soft_lockup":
            return Observation(
                obs_id="KERNEL-SOFT-LOCKUP-001",
                category="kernel_soft_lockup",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_hard_lockup":
            return Observation(
                obs_id="KERNEL-HARD-LOCKUP-001",
                category="kernel_hard_lockup",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_hung_task":
            return Observation(
                obs_id="KERNEL-HUNG-TASK-001",
                category="kernel_hung_task",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_rcu_stall":
            return Observation(
                obs_id="KERNEL-RCU-STALL-001",
                category="kernel_rcu_stall",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "platform_acpi_firmware_error":
            return Observation(
                obs_id="PLATFORM-ACPI-FIRMWARE-ERROR-001",
                category="platform_acpi_firmware_error",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "kernel_firmware_load_fail":
            return Observation(
                obs_id="KERNEL-FIRMWARE-LOAD-FAIL-001",
                category="kernel_firmware_load_fail",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "usb_enumeration_fail":
            return Observation(
                obs_id="USB-ENUMERATION-FAIL-001",
                category="usb_enumeration_fail",
                details={**payload},
                direct_measurement=True,
                data_complete=capture_complete,
                contradictory_evidence=False,
                inference_required=False,
                independent_sources=1,
                source_raw_ids=(src_id,),
            )
        elif cat == "iommu_fault":
            return Observation(
                obs_id="IOMMU-FAULT-001",
                category="iommu_fault",
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
        self._refresh_pipeline_accounting()

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
        self.log(f"{PRODUCT_NAME} {PRODUCT_VERSION} — starting diagnostics...\n")

        # Collect existing diagnostic data.
        self.log("Collecting diagnostics...")
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

        # Analyze existing observations.
        self.log("\nAnalyzing evidence...")
        self._derive_observations()

        # Generate the existing report from findings.
        self.log("\nGenerating report...")
        self._interpret()

        self.build_summary()

        self.report_lines.append("\n---\n")
        self.report_lines.append(
            f"*Raport wygenerowany {self.start_time_local.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"{PRODUCT_NAME} {PRODUCT_VERSION}; "
            f"kompatybilność raportów/snapshotów {REPORT_COMPATIBILITY_VERSION}*\n"
        )

        # Zapis
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = self.start_time_local.strftime("%Y%m%d-%H%M%S")
        report_filename = f"lde-{self.hostname}-{timestamp}.md"
        report_path = self.output_dir / report_filename

        full_report = "".join(self.report_lines)
        _write_new_text(report_path, full_report)

        self.log(f"\nReport saved to: {report_path}")
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
        return tuple(r for r in self.recommendations if r.priority >= 5)

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
        recs.sort(key=lambda r: (r.priority, r.recommendation_id))
        unique_recs = []
        seen_ids = set()
        for rec in recs:
            if rec.recommendation_id in seen_ids:
                continue
            seen_ids.add(rec.recommendation_id)
            unique_recs.append(rec)
        return RecommendationPlan(recommendations=tuple(unique_recs))

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
        kind = f.kind
        for r in restrictions:
            r_lower = r.lower()
            if kind in (FindingKind.DEVICE_ERROR, FindingKind.SCRUB_STATUS) and (
                "btrfs" in r_lower
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
        "Priority 1 — Immediate attention": [
            r for r in plan.recommendations if r.priority == 1
        ],
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
class EvidenceSnapshot:
    """Persisted Evidence with both upstream lineage reference sets."""

    evidence_id: str = ""
    evidence_type: str = ""
    data: dict = field(default_factory=dict)
    source_observation_ids: tuple = ()
    source_raw_ids: tuple = ()
    summary: str = ""
    strength: str = ""
    directness: str = ""
    completeness: str = ""
    contradictory: bool = False

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "data": self.data,
            "source_observation_ids": list(self.source_observation_ids),
            "source_raw_ids": list(self.source_raw_ids),
            "summary": self.summary,
            "strength": self.strength,
            "directness": self.directness,
            "completeness": self.completeness,
            "contradictory": self.contradictory,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceSnapshot":
        return cls(
            evidence_id=str(data.get("evidence_id", "")),
            evidence_type=str(data.get("evidence_type", "")),
            data=dict(data.get("data", {})),
            source_observation_ids=tuple(data.get("source_observation_ids", [])),
            source_raw_ids=tuple(data.get("source_raw_ids", [])),
            summary=str(data.get("summary", "")),
            strength=str(data.get("strength", "")),
            directness=str(data.get("directness", "")),
            completeness=str(data.get("completeness", "")),
            contradictory=bool(data.get("contradictory", False)),
        )


@dataclass(frozen=True)
class RawDiagnosticSnapshot:
    """Persisted bounded command output and its non-sensitive provenance."""

    source_id: str = ""
    category: str = ""
    payload: dict = field(default_factory=dict)
    collected_at: str = ""
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "category": self.category,
            "payload": self.payload,
            "collected_at": self.collected_at,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RawDiagnosticSnapshot":
        return cls(
            source_id=str(data.get("source_id", "")),
            category=str(data.get("category", "")),
            payload=dict(data.get("payload", {})),
            collected_at=str(data.get("collected_at", "")),
            provenance=dict(data.get("provenance", {})),
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
    evidence_ids: tuple = ()

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
            "evidence_ids": list(self.evidence_ids),
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
            evidence_ids=tuple(data.get("evidence_ids", [])),
        )


@dataclass(frozen=True)
class SystemSnapshot:
    """Migawka diagnostyczna — strukturalny, deterministyczny, typowany zapis stanu systemu."""

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    metadata: SnapshotMetadata = field(default_factory=SnapshotMetadata)
    environment: EnvironmentSnapshot = field(default_factory=EnvironmentSnapshot)
    observations: tuple = ()
    evidence: tuple = ()
    raw_diagnostics: tuple = ()
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
            "evidence": [e.to_dict() for e in self.evidence],
            "raw_diagnostics": [r.to_dict() for r in self.raw_diagnostics],
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

        if not isinstance(data, dict):
            raise ValueError("Snapshot root must be a JSON object")

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

        evidence_raw = data.get("evidence", [])
        if not isinstance(evidence_raw, list):
            raise ValueError("evidence must be a list")
        evidence = tuple(EvidenceSnapshot.from_dict(e) for e in evidence_raw)

        raw_diagnostics_raw = data.get("raw_diagnostics", [])
        if not isinstance(raw_diagnostics_raw, list):
            raise ValueError("raw_diagnostics must be a list")
        raw_diagnostics = tuple(
            RawDiagnosticSnapshot.from_dict(r) for r in raw_diagnostics_raw
        )

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
            evidence=evidence,
            raw_diagnostics=raw_diagnostics,
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

        evidence_ids = [e.evidence_id for e in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            errors.append("Duplicate evidence IDs detected")

        raw_ids = [r.source_id for r in self.raw_diagnostics]
        if len(raw_ids) != len(set(raw_ids)):
            errors.append("Duplicate raw diagnostic IDs detected")

        for f in self.findings:
            if f.severity and f.severity not in VALID_SEVERITIES:
                errors.append(
                    f"Invalid severity '{f.severity}' in finding '{f.finding_id}'"
                )
            if f.confidence and f.confidence not in VALID_CONFIDENCES:
                errors.append(
                    f"Invalid confidence '{f.confidence}' in finding '{f.finding_id}'"
                )

        # Legacy v3 snapshots predate persisted lineage. Validate references
        # whenever the new collections are present, while allowing those old
        # snapshots to load unchanged.
        if (
            self.evidence
            or self.raw_diagnostics
            or any(f.evidence_ids for f in self.findings)
        ):
            observation_id_set = set(obs_ids)
            evidence_id_set = set(evidence_ids)
            raw_id_set = set(raw_ids)
            for finding in self.findings:
                for obs_id in finding.source_observation_ids:
                    if obs_id not in observation_id_set:
                        errors.append(
                            f"Finding '{finding.finding_id}' references missing "
                            f"observation '{obs_id}'"
                        )
                for evidence_id in finding.evidence_ids:
                    if evidence_id not in evidence_id_set:
                        errors.append(
                            f"Finding '{finding.finding_id}' references missing "
                            f"evidence '{evidence_id}'"
                        )
            for ev in self.evidence:
                for obs_id in ev.source_observation_ids:
                    if obs_id not in observation_id_set:
                        errors.append(
                            f"Evidence '{ev.evidence_id}' references missing "
                            f"observation '{obs_id}'"
                        )
                for raw_id in ev.source_raw_ids:
                    if raw_id not in raw_id_set:
                        errors.append(
                            f"Evidence '{ev.evidence_id}' references missing raw "
                            f"diagnostic '{raw_id}'"
                        )
            for obs in self.observations:
                for raw_id in obs.source_raw_ids:
                    if raw_id not in raw_id_set:
                        errors.append(
                            f"Observation '{obs.obs_id}' references missing raw "
                            f"diagnostic '{raw_id}'"
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
        evidence: Optional[List[dict]] = None,
        raw_diagnostics: Optional[List[dict]] = None,
        recommendations: Optional[List[dict | DiagnosticRecommendation]] = None,
        restrictions: Optional[List[str]] = None,
        execution: Optional[ExecutionSnapshot] = None,
    ) -> SystemSnapshot:
        if evidence is None:
            evidence = []
        if raw_diagnostics is None:
            raw_diagnostics = []
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

        evidence_snapshots = tuple(
            EvidenceSnapshot(
                evidence_id=str(e.get("evidence_id", "")),
                evidence_type=str(e.get("evidence_type", "")),
                data=e.get("data", {}),
                source_observation_ids=tuple(e.get("source_observation_ids", [])),
                source_raw_ids=tuple(e.get("source_raw_ids", [])),
                summary=str(e.get("summary", "")),
                strength=str(e.get("strength", "")),
                directness=str(e.get("directness", "")),
                completeness=str(e.get("completeness", "")),
                contradictory=bool(e.get("contradictory", False)),
            )
            for e in evidence
        )

        raw_snapshots = tuple(
            RawDiagnosticSnapshot(
                source_id=str(r.get("source_id", "")),
                category=str(r.get("category", "")),
                payload=r.get("payload", {}),
                collected_at=str(r.get("collected_at", "")),
                provenance=r.get("provenance", {}),
            )
            for r in raw_diagnostics
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
                evidence_ids=tuple(f.get("evidence_ids", [])),
            )
            for f in findings
        )

        recommendation_objects = tuple(
            DiagnosticRecommendation.from_dict(r) if isinstance(r, dict) else r
            for r in recommendations
        )

        return SystemSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            metadata=metadata,
            environment=environment,
            observations=obs_snapshots,
            evidence=evidence_snapshots,
            raw_diagnostics=raw_snapshots,
            findings=find_snapshots,
            recommendations=recommendation_objects,
            restrictions=tuple(restrictions),
            execution=execution,
        )


def build_snapshot(engine: "SysCheckEngine") -> SystemSnapshot:
    """Buduje SystemSnapshot z danych silnika diagnostycznego."""
    metadata = SnapshotMetadata(
        hostname=engine.hostname,
        kernel=engine.active_kernel,
        distro=engine.distro_id,
        # Keep the legacy schema-3 key and value for snapshot compatibility.
        syscheck_version=REPORT_COMPATIBILITY_VERSION,
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
            "evidence_ids": f.evidence_ids,
        }
        for f in engine.findings
    ]

    evidence_data = [e.to_dict() for e in engine.evidence_objects]
    raw_diagnostics_data = [r.to_dict() for r in engine.raw_diagnostics]

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
        evidence=evidence_data,
        raw_diagnostics=raw_diagnostics_data,
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
        for mp in sorted(
            set(list(old_storage.keys()) + list(new_storage.keys())), key=str
        ):
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
                "old": [
                    list(t[1])
                    for t in sorted(
                        old_units,
                        key=lambda item: (
                            str(item[0]),
                            tuple(str(unit) for unit in item[1]),
                        ),
                    )
                ],
                "new": [
                    list(t[1])
                    for t in sorted(
                        new_units,
                        key=lambda item: (
                            str(item[0]),
                            tuple(str(unit) for unit in item[1]),
                        ),
                    )
                ],
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
        description=(
            f"{PRODUCT_NAME} ({PRODUCT_SHORT_NAME}) — "
            "read-only Linux system diagnostics"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PRODUCT_NAME} {PRODUCT_VERSION}",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # ── Main command: diagnostics ─────────────────────────────────
    diag_parser = subparsers.add_parser(
        "run", help="Run diagnostics (default)", aliases=["diagnose"]
    )
    diag_parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help=f"Output directory (default: {get_default_reports_dir()})",
    )
    diag_parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output on stderr",
    )
    diag_parser.add_argument(
        "--full",
        "-f",
        action="store_true",
        help="Keep full command output in the Markdown report",
    )
    diag_parser.add_argument(
        "--snapshot",
        "-s",
        type=str,
        default=None,
        help="Write a JSON snapshot (for example, snapshot.json)",
    )
    diag_parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print the full Markdown report after the summary",
    )
    diag_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed diagnostic progress",
    )

    # ── Compare command ───────────────────────────────────────────
    cmp_parser = subparsers.add_parser("compare", help="Compare two JSON snapshots")
    cmp_parser.add_argument("old", help="Path to the older JSON snapshot")
    cmp_parser.add_argument("new", help="Path to the newer JSON snapshot")
    cmp_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Write the comparison report to a Markdown file",
    )

    args = parser.parse_args()

    # ── Compare handling ──────────────────────────────────────────
    if args.command == "compare":
        try:
            old_snapshot = SystemSnapshot.from_json(args.old)
            new_snapshot = SystemSnapshot.from_json(args.new)
        except FileNotFoundError as exc:
            missing_path = exc.filename or "snapshot input"
            _cli_error(f"Snapshot input not found: {missing_path}")
        except (IsADirectoryError, PermissionError) as exc:
            _cli_error(f"Cannot read snapshot input: {exc}")
        except ValueError as exc:
            _cli_error(f"Invalid snapshot input: {exc}")
        comp = SnapshotComparator.compare(old_snapshot, new_snapshot)
        md = format_comparison_markdown(comp)
        if args.output:
            try:
                _write_new_text(args.output, md)
            except FileExistsError as exc:
                _cli_error(str(exc))
            print(f"Comparison saved to: {args.output}")
        print(md)
        return

    # ── Run handling (default) ────────────────────────────────────
    cmd_args = args if hasattr(args, "output_dir") else parser.parse_args(["run"])

    output_dir = getattr(cmd_args, "output_dir", None)
    if output_dir is None:
        output_dir = str(get_default_reports_dir())
    quiet = getattr(cmd_args, "quiet", False)
    full = getattr(cmd_args, "full", False)
    snapshot_path = getattr(cmd_args, "snapshot", None)
    print_report = getattr(cmd_args, "print_report", False)
    verbose = getattr(cmd_args, "verbose", False)

    if not quiet:
        print("Running diagnostics...", file=sys.stderr, flush=True)

    # The engine's existing diagnostic progress is reserved for --verbose;
    # default output stays compact without changing collection or rules.
    engine = SysCheckEngine(
        output_dir=output_dir,
        quiet=quiet or not verbose,
        full=full,
    )
    try:
        report_path = Path(engine.run_all()).expanduser().resolve()
    except FileExistsError as exc:
        _cli_error(str(exc))

    if not quiet:
        print("Diagnostics complete.", file=sys.stderr, flush=True)

    # Save snapshot if requested
    if snapshot_path:
        snap = build_snapshot(engine)
        try:
            snap.to_json(snapshot_path)
        except FileExistsError as exc:
            _cli_error(str(exc))
        snapshot_message = f"Snapshot saved to: {snapshot_path}"
    else:
        snapshot_message = None

    try:
        report_content = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _cli_error(f"Cannot read generated report: {exc}")

    sys.stdout.write(format_cli_summary(engine, report_path))
    if snapshot_message:
        print(snapshot_message)
    if print_report:
        print("\nFull Markdown report:")
        sys.stdout.write(report_content)


if __name__ == "__main__":
    main()
