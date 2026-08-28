# Diagnostic rule runtime extracted from syscheck.py.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from syscheck import (
        Finding,
        FindingClassification,
        FindingClassificationPolicy,
        Observation,
    )


def _syscheck():
    import syscheck

    return syscheck


@dataclass(frozen=True)
class DiagnosticRuleResult:
    finding: Optional[Finding] = None
    evidence: tuple = ()


@dataclass(frozen=True)
class DiagnosticEvaluation:
    findings: tuple = ()
    evidence: tuple = ()


class DiagnosticRuleError(ValueError):
    pass


class UnsupportedObservationRuleError(DiagnosticRuleError):
    pass


class AmbiguousObservationRuleError(DiagnosticRuleError):
    pass


class DuplicateDiagnosticRuleError(DiagnosticRuleError):
    pass


class DuplicateFindingError(DiagnosticRuleError):
    pass


class DuplicateEvidenceError(DiagnosticRuleError):
    pass


class DiagnosticRule(ABC):
    rule_id: str
    supported_categories: frozenset = frozenset()

    @abstractmethod
    def evaluate(
        self, observation: Observation, classification: FindingClassification
    ) -> DiagnosticRuleResult: ...

    def supports(self, observation: Observation) -> bool:
        return observation.category in self.supported_categories


class BtrfsDeviceErrorRule(DiagnosticRule):
    rule_id = "RULE-BTRFS-DEVICE-ERROR"
    supported_categories = frozenset({"btrfs_error"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id

        # Safety: do not emit device-error Finding for non-error states
        status = observation.details.get("status")
        if status in ("ok", "permission_denied", "command_not_found"):
            return DiagnosticRuleResult()

        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Btrfs device stats wykazują błędy we/wy",
                severity="P1",
                confidence=conf,
                evidence=str(observation.details.get("line", "")),
                interpretation="Liczniki błędów Btrfs są niezerowe — możliwy problem sprzętowy.",
                recommended_diagnostics="`sudo btrfs scrub start /`; `sudo btrfs device stats /`",
                remediation="Jeśli błędy utrzymują się po scrubie, rozważ wymianę dysku.",
                verification="`sudo btrfs device stats /` — wszystkie liczniki zerowe",
                risk_level="Wysokie ryzyko utraty danych.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class BtrfsScrubStatusRule(DiagnosticRule):
    rule_id = "RULE-BTRFS-SCRUB-STATUS"
    supported_categories = frozenset({"btrfs_scrub"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Btrfs scrub nigdy nie był wykonany",
                severity="P2",
                confidence=conf,
                evidence="Brak historii skrubowania.",
                interpretation="Zaleca się wykonanie scrub do wykrycia bit-rot.",
                recommended_diagnostics="`sudo btrfs scrub start /`",
                remediation="Po scrubie skonfiguruj timer: `sudo systemctl enable btrfs-scrub@-.timer`",
                verification="`sudo btrfs scrub status /`",
                risk_level="Niskie ryzyko. Skrubowanie zapobiegawcze.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence[0].evidence_id,),
            ),
            evidence=evidence,
        )


class WirePlumberSegfaultRule(DiagnosticRule):
    rule_id = "RULE-SEGFAULT-WIREPLUMBER"
    supported_categories = frozenset({"segfault"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if observation.details.get("segfault_type") != "wireplumber":
            return DiagnosticRuleResult()
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        n = observation.details.get(
            "count", observation.details.get("segfault_type", "?")
        )
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"WirePlumber segfault ({n}) — libcamera",
                severity="P2",
                confidence=conf,
                evidence=f"Segfaulty WirePlumber: {n}.",
                interpretation="Wszystkie segfaulty w libspa-libcamera.so. Prawdopodobnie związane z tą biblioteką. Brak dowodów na uszkodzenie sprzętu.",
                recommended_diagnostics="`pacman -Q wireplumber libcamera pipewire`",
                remediation="`sudo pacman -Syu`; przeinstaluj wireplumber/libcamera.",
                verification="`journalctl -b | grep -c segfault` — 0",
                risk_level="Niskie. Ograniczone do jednej biblioteki.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class GeneralSegfaultRule(DiagnosticRule):
    rule_id = "RULE-SEGFAULT-GENERAL"
    supported_categories = frozenset({"segfault"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if observation.details.get("segfault_type") == "wireplumber":
            return DiagnosticRuleResult()
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        n = observation.details.get("count", "?")
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Wielokrotne segfaulty w systemie ({n})",
                severity="P1",
                confidence=conf,
                evidence=f"Liczba segfaultów: {n}.",
                interpretation="Segfaulty różnych procesów — możliwe uszkodzenie sprzętu.",
                recommended_diagnostics="`sudo memtest86+`; `sudo smartctl -a /dev/nvme0n1`",
                remediation="Test pamięci; sprawdź SMART; jeśli potwierdzone — wymień sprzęt.",
                verification="`journalctl -b -k | grep segfault` — brak wyników",
                risk_level="Wysokie ryzyko przy wielu procesach.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class MinorSegfaultRule(DiagnosticRule):
    rule_id = "RULE-SEGFAULT-MINOR"
    supported_categories = frozenset({"segfault_minor"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Pojedyncze segfaulty podczas bootu",
                severity="P3",
                confidence=conf,
                evidence=str(observation.details),
                interpretation="Incydentalne segfaulty — monitoruj.",
                recommended_diagnostics="`journalctl -b -k | grep segfault`",
                remediation="Jeśli powtarzalne: `sudo pacman -S <pakiet>`.",
                verification="`journalctl -b -k | grep -c segfault` — 0",
                risk_level="Niskie.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class KernelTaintRule(DiagnosticRule):
    rule_id = "RULE-KERNEL-TAINT"
    supported_categories = frozenset({"tainted"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Kernel tainted",
                severity="P2",
                confidence=conf,
                evidence="Wykryto 'taint' w logach.",
                interpretation="Załadowano moduł spoza drzewa jądra.",
                recommended_diagnostics="`cat /proc/sys/kernel/tainted`",
                remediation="Rozważ przejście na otwarte sterowniki.",
                verification="`cat /proc/sys/kernel/tainted` — 0",
                risk_level="Niskie. Informacja, nie awaria.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class KernelOomRule(DiagnosticRule):
    rule_id = "RULE-KERNEL-OOM"
    supported_categories = frozenset({"oom_event"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Wykryto zdarzenie OOM (Out of Memory) w bieżącym bocie",
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Jądro zgłosiło brak pamięci i uruchomiło OOM killer. "
                    "Proces(y) zostały zabite w celu odzyskania pamięci. "
                    "Diagnostyka nie określa przyczyny — może to być "
                    "niewystarczająca ilość RAM-u, brak/zbyt mały swap, "
                    "wyciek pamięci aplikacji, ograniczenie cgroup, "
                    "anormalne obciążenie lub konfiguracja.\n\n"
                    "Uwaga: diagnostyka wykrywa obecność zdarzenia OOM "
                    "w dzienniku bieżącego bota. Nie potwierdza ani nie "
                    "zaprzecza trwającej presji pamięci. Zdarzenia OOM "
                    "mogły zostać pominięte jeśli zostały usunięte z "
                    "dziennika przed uruchomieniem diagnostyki."
                ),
                recommended_diagnostics=(
                    "Sprawdź bieżące użycie pamięci: `free -h`\n"
                    "Sprawdź swap: `swapon --show`\n"
                    "Sprawdź procesy według zużycia pamięci: "
                    "`ps aux --sort=-%mem | head -20`"
                ),
                remediation=(
                    "Jeśli problem jest powtarzalny: zwiększ swap, "
                    "dodaj więcej RAM, zidentyfikuj wyciek pamięci, "
                    "lub ogranicz obciążenie."
                ),
                verification=(
                    "Sprawdź bieżące użycie pamięci komendą `free -h` — "
                    "czy dostępna pamięć nie jest zbyt niska.\n"
                    "Sprawdź swap: `swapon --show` — czy swap jest "
                    "włączony i ma odpowiedni rozmiar.\n"
                    "Po podjęciu działań naprawczych monitoruj dziennik "
                    "w kolejnym bocie: `journalctl -b -k --grep='oom'`."
                ),
                risk_level=(
                    "Umiarkowane. OOM wskazuje na wyczerpanie pamięci; "
                    "nieleczona przyczyna może prowadzić do dalszych "
                    "problemów stabilności."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class GpuI915HangRule(DiagnosticRule):
    rule_id = "RULE-GPU-I915-HANG"
    supported_categories = frozenset({"gpu_i915_hang"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=("Wykryto zawieszenie GPU obsługiwanego przez sterownik i915"),
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra odnotował zdarzenie "
                    "`GPU HANG:` dla sterownika i915 w bieżącym bocie. "
                    "Zdarzenie mogło mieć charakter historyczny "
                    "i może nie być już aktywne. "
                    "Diagnostyka nie potwierdza defektu sprzętowego — "
                    "możliwe przyczyny obejmują usterki jądra/sterownika, "
                    "interakcję z firmware lub platformą, "
                    "obciążenie wywołujące błąd, "
                    "lub niestabilność sprzętową.\n\n"
                    "Diagnostyka nie określa, czy dotknięte GPU "
                    "było aktywnym rendererem — "
                    "wpływ na użytkownika może być różny.\n\n"
                    "Uwaga: brak wykrytego zdarzenia nie dowodzi, "
                    "że nie wystąpiło zawieszenie — "
                    "retencja dziennika jądra może być niepełna."
                ),
                recommended_diagnostics=(
                    "Sprawdź aktualny dziennik jądra: "
                    "`journalctl -b -k --no-pager`\n"
                    "Sprawdź wersję jądra: `uname -r`\n"
                    "Sprawdź sterownik GPU: `lspci -k`\n"
                    "Sprawdź, czy zdarzenie powtarza się w kolejnych bootach."
                ),
                remediation=(
                    "Jeśli problem jest powtarzalny: "
                    "porównaj zachowanie na innym wspieranym jądrze, "
                    "przejrzyj ostatnie zmiany jądra/sterownika graficznego, "
                    "zachowaj dokładne linie zawieszenia do zgłoszenia błędu."
                ),
                verification=(
                    "Sprawdź, czy system jest obecnie responsywny.\n"
                    "Monitoruj, czy nowe zawieszenia występują: "
                    "`journalctl -b -k | grep -iE 'GPU HANG:'`.\n"
                    "Po podjęciu działań sprawdź w kolejnym bocie, "
                    "czy znacznik nadal występuje."
                ),
                risk_level=(
                    "Średnie. Zawieszenie GPU może wskazywać na "
                    "niestabilność; nieleczona przyczyna może prowadzić "
                    "do dalszych problemów."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class AmdgpuResetFailRule(DiagnosticRule):
    rule_id = "RULE-AMDGPU-RESET-FAIL"
    supported_categories = frozenset({"amdgpu_reset_fail"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=(
                    "Wykryto nieudany reset GPU obsługiwanego przez sterownik amdgpu"
                ),
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra odnotował zdarzenie "
                    "`GPU reset failed` dla sterownika amdgpu w bieżącym bocie. "
                    "Zdarzenie mogło mieć charakter historyczny "
                    "i może nie być już aktywne. "
                    "Diagnostyka nie potwierdza defektu sprzętowego — "
                    "możliwe przyczyny obejmują usterki jądra/sterownika, "
                    "interakcję z firmware lub platformą, "
                    "obciążenie wywołujące błąd, "
                    "niestabilność zasilania/termiczna/PCIe, "
                    "lub niestabilność sprzętową.\n\n"
                    "Diagnostyka nie określa, czy dotknięte GPU "
                    "było aktywnym rendererem — "
                    "wpływ na użytkownika może być różny.\n\n"
                    "Uwaga: brak wykrytego zdarzenia nie dowodzi, "
                    "że nie wystąpił reset — "
                    "retencja dziennika jądra może być niepełna."
                ),
                recommended_diagnostics=(
                    "Sprawdź aktualny dziennik jądra: "
                    "`journalctl -b -k --no-pager | grep -iE 'amdgpu'`\n"
                    "Sprawdź wersję jądra: `uname -r`\n"
                    "Sprawdź sterownik GPU: `lspci -k`\n"
                    "Sprawdź temperatury (jeśli dostępne): `sensors`\n"
                    "Sprawdź, czy zdarzenie powtarza się w kolejnych bootach."
                ),
                remediation=(
                    "Jeśli problem jest powtarzalny: "
                    "porównaj zachowanie na innym wspieranym jądrze, "
                    "przejrzyj ostatnie zmiany jądra/sterownika AMDGPU, "
                    "sprawdź wersje grafiki i firmware menedżerem pakietów systemu, "
                    "zachowaj dokładne linie błędu do zgłoszenia problemu. "
                    "Uwzględnij czynniki takie jak temperatura, "
                    "obciążenie, stabilność PCIe i jakość zasilania w diagnozie."
                ),
                verification=(
                    "Sprawdź, czy system jest obecnie responsywny.\n"
                    "Monitoruj, czy nowe reset występują: "
                    "`journalctl -b -k | grep -iE 'reset'`.\n"
                    "Po podjęciu działań sprawdź w kolejnym bocie, "
                    "czy znacznik nadal występuje."
                ),
                risk_level=(
                    "Średnie. Nieudany reset GPU może wskazywać na "
                    "niestabilność; nieleczona przyczyna może prowadzić "
                    "do dalszych problemów."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class PcieAerErrorRule(DiagnosticRule):
    rule_id = "RULE-PCIE-AER-ERROR"
    supported_categories = frozenset({"pcie_aer_error"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        severity = observation.details.get("aer_severity")
        severity_map = {"corrected": "P3", "non_fatal": "P2", "fatal": "P1"}
        if severity not in severity_map:
            return DiagnosticRuleResult()

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        label = severity.replace("_", " ")
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Wykryto zdarzenie PCIe AER: {label}",
                severity=severity_map[severity],
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra zawiera jawny komunikat PCIe AER "
                    f"o poziomie {label} w bieżącym bocie. "
                    "Diagnostyka rejestruje zdarzenie i nie określa jego przyczyny "
                    "ani nie potwierdza awarii sprzętu."
                ),
                recommended_diagnostics=(
                    "Zachowaj dokładne linie AER i sprawdź, czy zdarzenie powtarza się: "
                    "`journalctl -b -k --no-pager | grep -iE 'PCIe Bus Error|AER:'`"
                ),
                remediation=(
                    "Nie wykonuj zmian na podstawie pojedynczego wpisu. "
                    "Jeśli zdarzenia się powtarzają, zbierz pełny kontekst dziennika "
                    "i porównaj go między bootami."
                ),
                verification=(
                    "W kolejnym bocie sprawdź, czy nowe jawne wpisy AER nadal występują: "
                    "`journalctl -b -k --no-pager | grep -iE 'PCIe Bus Error|AER:'`."
                ),
                risk_level=(
                    "Niski dla corrected, umiarkowany dla non-fatal, wysoki dla fatal. "
                    "Sam wpis nie ustala przyczyny ani stanu sprzętu."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class NvmeControllerReliabilityRule(DiagnosticRule):
    rule_id = "RULE-NVME-CONTROLLER-RELIABILITY"
    supported_categories = frozenset({"nvme_controller_reliability"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        event_severity = observation.details.get("event_severity")
        severity_map = {"timeout_or_reset": "P2", "reset_failure": "P1"}
        if event_severity not in severity_map:
            return DiagnosticRuleResult()

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        event_description = (
            "nieudany reset kontrolera"
            if event_severity == "reset_failure"
            else "timeout lub reset kontrolera"
        )
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Wykryto NVMe: {event_description}",
                severity=severity_map[event_severity],
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra zawiera jawny komunikat NVMe o "
                    f"zdarzeniu: {event_description} w bieżącym bocie. "
                    "Diagnostyka rejestruje zdarzenie, ale nie potwierdza "
                    "trwałej awarii SSD ani utraty lub uszkodzenia danych."
                ),
                recommended_diagnostics=(
                    "Zachowaj dokładne linie NVMe i sprawdź, czy zdarzenie się powtarza: "
                    "`journalctl -b -k --no-pager | grep -iE 'nvme.*(timeout|reset|controller is down|Device not ready)'`\n"
                    "Sprawdź bieżący stan urządzenia i dane SMART/NVMe odpowiednim "
                    "narzędziem dla swojego systemu."
                ),
                remediation=(
                    "Nie wykonuj zmian na podstawie pojedynczego wpisu. "
                    "Jeśli zdarzenia się powtarzają, zachowaj pełny kontekst dziennika "
                    "i sprawdź stabilność połączenia oraz zasilania jako hipotezy."
                ),
                verification=(
                    "W kolejnym bocie sprawdź, czy nowe jawne wpisy NVMe nadal występują: "
                    "`journalctl -b -k --no-pager | grep -iE 'nvme.*(timeout|reset|controller is down|Device not ready)'`."
                ),
                risk_level=(
                    "Umiarkowane dla timeout/reset, wysokie dla komunikatu o nieudanym resecie. "
                    "Sam wpis nie ustala trwałego stanu SSD ani integralności danych."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class HardwareMceEdacRule(DiagnosticRule):
    rule_id = "RULE-HARDWARE-MCE-EDAC-ERROR"
    supported_categories = frozenset({"hardware_mce_edac_error"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        event_severity = observation.details.get("event_severity")
        severity_map = {"corrected": "P2", "uncorrected": "P1"}
        if event_severity not in severity_map:
            return DiagnosticRuleResult()

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        title = (
            "Wykryto zdarzenie MCE / EDAC: skorygowane błędy sprzętowe"
            if event_severity == "corrected"
            else "Wykryto zdarzenie MCE / EDAC: Machine Check / błąd nieskorygowany"
        )
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=title,
                severity=severity_map[event_severity],
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra zarejestrował jawne zdarzenie MCE (Machine Check Exception) "
                    "lub błędy EDAC w bieżącym bocie. Diagnostyka rejestruje zdarzenie na podstawie "
                    "dziennika i nie wnioskuje o trwałej awarii pamięci RAM, procesora ani "
                    "płyty głównej, ani nie przesądza o trwałym uszkodzeniu podzespołów."
                ),
                recommended_diagnostics=(
                    "Zachowaj dokładne linie zdarzeń i sprawdź, czy problem się powtarza:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'mce|edac'`\n"
                    "Sprawdź status podsystemów diagnostyki sprzętowej (jeśli są zainstalowane):\n"
                    "`rasdaemon --status` lub `edac-util -v`"
                ),
                remediation=(
                    "Nie wymieniaj komponentów na podstawie pojedynczego wpisu. "
                    "Jeśli błędy się powtarzają, zweryfikuj stabilność zasilania, chłodzenia "
                    "oraz aktualność mikrokodu procesora i oprogramowania układowego (BIOS/UEFI)."
                ),
                verification=(
                    "W kolejnym bocie sprawdź dziennik pod kątem nowych zdarzeń MCE/EDAC:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'mce|edac'`."
                ),
                risk_level=(
                    "Umiarkowane dla błędów skorygowanych (P2), wysokie dla zdarzeń Machine Check lub błędów nieskorygowanych (P1). "
                    "Sam wpis w dzienniku nie ustala trwałego uszkodzenia podzespołów."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class FilesystemIoErrorRule(DiagnosticRule):
    rule_id = "RULE-FILESYSTEM-IO-ERROR"
    supported_categories = frozenset({"filesystem_io_error"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        event_severity = observation.details.get("event_severity")
        severity_map = {"io_error": "P2", "critical_or_fatal": "P1"}
        if event_severity not in severity_map:
            return DiagnosticRuleResult()

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        title = (
            "Wykryto krytyczny błąd I/O systemu plików / podsystemu blokowego"
            if event_severity == "critical_or_fatal"
            else "Wykryto błąd wejścia/wyjścia systemu plików / podsystemu blokowego"
        )
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=title,
                severity=severity_map[event_severity],
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra zarejestrował jawne zdarzenie błędu wejścia/wyjścia (I/O) "
                    "lub błędu systemu plików w bieżącym bocie. Diagnostyka rejestruje zdarzenie "
                    "na podstawie dziennika i nie wnioskuje o trwałej awarii dysku, uszkodzeniu kabla "
                    "ani trwałym uszkodzeniu systemu plików lub konieczności wymiany sprzętu."
                ),
                recommended_diagnostics=(
                    "Zachowaj dokładne linie błędu i sprawdź, czy problem się powtarza:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'Buffer I/O|blk_update_request|EXT4-fs|XFS|BTRFS|critical medium error'`\n"
                    "Sprawdź stan systemu plików odpowiednim narzędziem diagnostycznym w trybie tylko do odczytu."
                ),
                remediation=(
                    "Nie wykonuj inwazyjnych zmian ani nie wymieniaj podzespołów wyłącznie na podstawie pojedynczego wpisu. "
                    "W razie powtarzających się błędów przeanalizuj kontekst dziennika i stan nośnika."
                ),
                verification=(
                    "W kolejnym bocie sprawdź dziennik pod kątem nowych zdarzeń błędów I/O:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'Buffer I/O|blk_update_request|EXT4-fs|XFS|BTRFS|critical medium error'`."
                ),
                risk_level=(
                    "Umiarkowane dla standardowych błędów I/O (P2), wysokie dla błędów krytycznych/fatalnych (P1). "
                    "Sam wpis w dzienniku nie ustala trwałego uszkodzenia nośnika ani utraty danych."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class HardwareThermalThrottlingRule(DiagnosticRule):
    rule_id = "RULE-HARDWARE-THERMAL-THROTTLING"
    supported_categories = frozenset({"hardware_thermal_throttling"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if not observation.details.get("thermal_throttle_detected"):
            return DiagnosticRuleResult()

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title="Wykryto zdarzenie dławienia termicznego procesora (thermal throttling)",
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra zarejestrował jawne przekroczenie progu termicznego i zdarzenie dławienia "
                    "zegara procesora (thermal throttling) w bieżącym bocie. Diagnostyka rejestruje zdarzenie "
                    "na podstawie dziennika i nie wnioskuje o awarii układu chłodzenia, zużyciu pasty termoprzewodzącej, "
                    "zablokowanym przepływie powietrza, uszkodzeniu wentylatora, błędzie BIOS/UEFI, trwałym uszkodzeniu "
                    "procesora ani o trwałym spadku wydajności lub dławieniu prądowym/zasilaniowym."
                ),
                recommended_diagnostics=(
                    "Zachowaj dokładne linie zdarzeń i sprawdź, czy dławienie termiczne się powtarza:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'temperature above threshold.*throttl|thermal threshold.*throttl'`\n"
                    "Sprawdź bieżące temperatury i limity chłodzenia narzędziami systemowymi (np. sensors)."
                ),
                remediation=(
                    "Nie podejmuj inwazyjnych działań sprzętowych wyłącznie na podstawie pojedynczego wpisu w dzienniku. "
                    "W razie powtarzających się zdarzeń zweryfikuj warunki termiczne systemu pod obciążeniem oraz konfigurację profilu zasilania i chłodzenia."
                ),
                verification=(
                    "W kolejnym bocie lub po zakończeniu obciążenia sprawdź dziennik pod kątem nowych zdarzeń dławienia termicznego:\n"
                    "`journalctl -b -k --no-pager | grep -iE 'temperature above threshold.*throttl|thermal threshold.*throttl'`."
                ),
                risk_level=(
                    "Średnie (P2). Zdarzenie wskazuje na zadziałanie mechanizmu ochronnego procesora przy przekroczeniu progu temperatury. "
                    "Sam wpis w dzienniku nie ustala trwałego uszkodzenia podzespołów ani permanentnego spadku wydajności."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class KernelOopsPanicRule(DiagnosticRule):
    rule_id = "RULE-KERNEL-OOPS-PANIC"
    supported_categories = frozenset({"kernel_oops_panic"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if not observation.details.get("oops_panic_detected"):
            return DiagnosticRuleResult()

        highest_severity = observation.details.get("highest_severity", "P1")
        if highest_severity not in ("P0", "P1"):
            highest_severity = "P1"

        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        is_panic = highest_severity == "P0"
        title = (
            "Wykryto awarię krytyczną jądra (Kernel Panic)"
            if is_panic
            else "Wykryto błąd jądra (Kernel Oops / BUG)"
        )
        interpretation = (
            (
                "Dziennik jądra zarejestrował jawny komunikat Kernel Panic w bieżącym rozruchu. "
                if is_panic
                else "Dziennik jądra zarejestrował jawny błąd jądra (Oops lub BUG) w bieżącym rozruchu. "
            )
            + "Diagnostyka rejestruje zdarzenie na podstawie dziennika jądra i nie przypisuje "
            "przyczyny źródłowej (root-cause) do konkretnego sprzętu, modułu jądra ani oprogramowania."
        )
        recommended_diagnostics = (
            "Zachowaj pełny zrzut dziennika jądra z bieżącego rozruchu przed ewentualnym restartem:\n"
            "`journalctl -b -k --no-pager > kernel-panic-oops.log`\n"
            "Sprawdź linie poprzedzające awarię pod kątem śladu wywołań (call trace) i rejestrów procesora."
        )
        remediation = (
            "Nie wykonuj inwazyjnych zmian w systemie bez zabezpieczenia dziennika. "
            "W razie powtarzających się awarii zweryfikuj stabilność sprzętu (np. pamięć RAM), "
            "wersję oprogramowania układowego (BIOS/UEFI, mikrokod) oraz moduły jądra i wersję kernela."
        )
        verification = (
            "W kolejnym rozruchu sprawdź, czy nowe zdarzenia błędu lub paniki jądra nadal występują:\n"
            "`journalctl -b -k --no-pager | grep -iE 'Kernel panic - not syncing|Oops:|kernel BUG at|BUG: unable to handle kernel'`."
        )
        risk_level = (
            "Krytyczne (P0). Awaria jądra uniemożliwia dalszą bezpieczną pracę systemu operacyjnego."
            if is_panic
            else "Wysokie (P1). Wystąpienie błędu Oops lub BUG w jądrze wskazuje na naruszenie spójności stanu jądra."
        )
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=title,
                severity=highest_severity,
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=interpretation,
                recommended_diagnostics=recommended_diagnostics,
                remediation=remediation,
                verification=verification,
                risk_level=risk_level,
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class GpuNvidiaXid79Rule(DiagnosticRule):
    rule_id = "RULE-GPU-NVIDIA-XID-79"
    supported_categories = frozenset({"gpu_nvidia_xid_79"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=(
                    "Wykryto zdarzenie NVIDIA Xid 79 "
                    "— utrata połączenia GPU z magistralą"
                ),
                severity="P2",
                confidence=conf,
                evidence=str(observation.details.get("matched_lines", [])),
                interpretation=(
                    "Dziennik jądra odnotował zdarzenie "
                    "NVIDIA Xid 79 w bieżącym bocie. "
                    "Zdarzenie mogło mieć charakter historyczny "
                    "i może nie być już aktywne. "
                    "Diagnostyka nie potwierdza defektu sprzętowego, "
                    "nie potwierdza aktualnej niedostępności GPU, "
                    "ani nie określa, czy dotknięte GPU "
                    "było aktywnym rendererem.\n\n"
                    "Xid 79 wskazuje na utratę połączenia GPU z magistralą PCIe. "
                    "Możliwe konteksty zdarzenia obejmują: "
                    "spontaniczną utratę PCIe/zasilania, "
                    "celowe odłączenie eGPU, "
                    "niepełną reinicjalizację po zawieszeniu/resume, "
                    "lub interakcję sterownika z firmware/platformą. "
                    "SysCheck nie rozróżnia tych przyczyn "
                    "na podstawie pojedynczej linii zdarzenia.\n\n"
                    "Uwaga: brak wykrytego zdarzenia nie dowodzi, "
                    "że nie wystąpiło — "
                    "retencja dziennika jądra może być niepełna."
                ),
                recommended_diagnostics=(
                    "Sprawdź aktualny dziennik jądra: "
                    "`journalctl -b -k --no-pager | grep -iE 'Xid'`\n"
                    "Sprawdź wersję jądra: `uname -r`\n"
                    "Sprawdź sterownik GPU: `lspci -k`\n"
                    "Sprawdź, czy GPU jest eGPU, które zostało celowo odłączone.\n"
                    "Sprawdź, czy zdarzenie powtarza się w kolejnych bootach.\n"
                    "Zachowaj dokładną linię Xid do analizy."
                ),
                remediation=(
                    "Jeśli problem jest powtarzalny bez znanej przyczyny: "
                    "porównaj zachowanie na innym wspieranym jądrze, "
                    "przejrzyj ostatnie zmiany sterownika NVIDIA, "
                    "sprawdź kontekst PCIe/zasilania/termiczny jako hipotezy, "
                    "zachowaj dokładne linie zdarzenia do zgłoszenia problemu."
                ),
                verification=(
                    "Sprawdź, czy system jest obecnie responsywny.\n"
                    "Monitoruj, czy nowe zdarzenia Xid występują: "
                    "`journalctl -b -k | grep -iE 'Xid'`.\n"
                    "Po podjęciu działań sprawdź w kolejnym bocie, "
                    "czy znacznik nadal występuje."
                ),
                risk_level=(
                    "Średnie. Zdarzenie Xid 79 może wskazywać na "
                    "niestabilność połączenia GPU; nieleczona przyczyna "
                    "może prowadzić do dalszych problemów."
                ),
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class FailedSystemUnitRule(DiagnosticRule):
    rule_id = "RULE-SYSTEMD-FAILED-SYSTEM"
    supported_categories = frozenset({"systemd_failed"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if observation.details.get("scope") != "system":
            return DiagnosticRuleResult()
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        units = observation.details.get("units", [])
        evidence = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Failed jednostki systemowe: {', '.join(units)}",
                severity="P2",
                confidence=conf,
                evidence=f"Jednostki: {units}",
                interpretation="Systemowe jednostki systemd nie uruchomiły się.",
                recommended_diagnostics="`systemctl status <unit>`; `journalctl -b -u <unit>`",
                remediation="`sudo systemctl reset-failed <unit>`; popraw konfigurację.",
                verification="`systemctl --failed` — 0 loaded units.",
                risk_level="Średnie.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence[0].evidence_id,),
            ),
            evidence=evidence,
        )


class FailedUserUnitRule(DiagnosticRule):
    rule_id = "RULE-SYSTEMD-FAILED-USER"
    supported_categories = frozenset({"systemd_failed"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        if observation.details.get("scope") != "user":
            return DiagnosticRuleResult()
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        units = observation.details.get("units", [])
        evidence = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Failed jednostki użytkownika: {', '.join(units)}",
                severity="P2",
                confidence=conf,
                evidence=f"Jednostki: {units}",
                interpretation="Użytkownicze jednostki systemd nie uruchomiły się.",
                recommended_diagnostics="`systemctl --user status <unit>`",
                remediation="`systemctl --user reset-failed <unit>`",
                verification="`systemctl --user --failed` — 0 loaded units.",
                risk_level="Niskie-średnie.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence[0].evidence_id,),
            ),
            evidence=evidence,
        )


class KernelCountRule(DiagnosticRule):
    rule_id = "RULE-KERNEL-COUNT"
    supported_categories = frozenset({"kernel_count"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        cnt = observation.details.get("count", "?")
        evidence = (self._evidence_builder.build(observation),)
        finding = _syscheck().Finding(
            finding_id=obs_id,
            title=f"Zainstalowane kernele ({cnt})",
            severity="Info",
            confidence=conf,
            evidence=f"Liczba kernel: {cnt}.",
            interpretation="Wszystkie obrazy kernel obecne. Rekomendacja dot. przestrzeni.",
            recommended_diagnostics="`uname -r`; `ls /boot/vmlinuz-*`",
            remediation="Można usunąć nieużywane: `sudo pacman -Rs <kernel>`. Zostaw zapasowy.",
            verification="`ls /boot/vmlinuz-* | wc -l` <= 2",
            risk_level="Informacja.",
            domain=classification.domain,
            kind=classification.kind,
            actionability=classification.actionability,
            recommendation_intent=classification.recommendation_intent,
            source_observation_ids=(obs_id,),
            evidence_ids=(evidence[0].evidence_id,),
        )
        return DiagnosticRuleResult(finding=finding, evidence=evidence)


class BootDelayRule(DiagnosticRule):
    rule_id = "RULE-BOOT-DELAY"
    supported_categories = frozenset({"boot_time"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        obs_id = observation.obs_id
        t = observation.details.get("userspace_time", "?")
        evidence_items = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=obs_id,
                title=f"Wydłużony czas bootu ({t}s userspace)",
                severity="P3",
                confidence=conf,
                evidence=f"Czas userspace: {t}s.",
                interpretation="Czas uruchamiania przekracza 30s.",
                recommended_diagnostics="`systemd-analyze blame`; `systemd-analyze critical-chain`",
                remediation="Wyłącz zbędne usługi: `systemctl disable <usługa>`.",
                verification="`systemd-analyze` — < 30s",
                risk_level="Niskie.",
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(obs_id,),
                evidence_ids=(evidence_items[0].evidence_id,),
            ),
            evidence=evidence_items,
        )


class StorageUsageRule(DiagnosticRule):
    rule_id = "RULE-STORAGE-USAGE"
    supported_categories = frozenset({"storage_usage"})

    def __init__(self, evidence_builder):
        self._evidence_builder = evidence_builder

    def evaluate(self, observation, classification):
        conf = _syscheck().derive_confidence(
            direct_measurement=observation.direct_measurement,
            data_complete=observation.data_complete,
            contradictory_evidence=observation.contradictory_evidence,
            inference_required=observation.inference_required,
            independent_sources=observation.independent_sources,
        )
        details = observation.details
        state = details.get("threshold_state", "warning")
        mp = details.get("mountpoint", "/")
        pct = details.get("usage_percent", 0)
        if state == "critical":
            fid, title, sev, interp, risk = (
                "STORAGE-USAGE-CRITICAL",
                f"Krytyczne użycie miejsca na {mp}: {pct}%",
                "P1",
                f"Przekroczono {pct}% — ryzyko braku miejsca.",
                "Wysokie ryzyko utraty danych.",
            )
        else:
            fid, title, sev, interp, risk = (
                "STORAGE-USAGE-WARNING",
                f"Znaczące użycie miejsca na {mp}: {pct}%",
                "P2",
                f"Zalecane monitorowanie użycia {mp}.",
                "Średnie ryzyko. Monitoruj i zaplanuj czyszczenie.",
            )
        evidence = (self._evidence_builder.build(observation),)
        return DiagnosticRuleResult(
            finding=_syscheck().Finding(
                finding_id=fid,
                title=title,
                severity=sev,
                confidence=conf,
                evidence=f"{mp}: {pct}%.",
                interpretation=interp,
                recommended_diagnostics="`du -sh /* | sort -rh | head -10`",
                remediation="`sudo pacman -Sc`; `sudo journalctl --vacuum-size=500M`",
                verification=f"`df -h {mp}` — < 75%",
                risk_level=risk,
                domain=classification.domain,
                kind=classification.kind,
                actionability=classification.actionability,
                recommendation_intent=classification.recommendation_intent,
                source_observation_ids=(observation.obs_id,),
                evidence_ids=(evidence[0].evidence_id,),
            ),
            evidence=evidence,
        )


class DiagnosticRuleRegistry:
    def __init__(self, rules: Iterable[DiagnosticRule]):
        rule_list = tuple(rules)
        if len({r.rule_id for r in rule_list}) != len(rule_list):
            raise DuplicateDiagnosticRuleError("Duplicate rule_id in registry")
        self._rules = rule_list

    @property
    def rules(self) -> tuple:
        return self._rules


class DiagnosticRuleEngine:
    def __init__(
        self,
        registry: DiagnosticRuleRegistry,
        classification_policy: FindingClassificationPolicy | None = None,
    ):
        self._registry = registry
        self._classification_policy = (
            classification_policy or _syscheck().FindingClassificationPolicy()
        )

    def evaluate(self, observations: Iterable[Observation]) -> DiagnosticEvaluation:
        findings = []
        evidence_list = []
        seen_fids = set()
        seen_eids = set()
        for obs in observations:
            classification = self._classification_policy.classify(obs)
            matching = [r for r in self._registry.rules if r.supports(obs)]
            if not matching:
                raise UnsupportedObservationRuleError(
                    f"No rule supports category '{obs.category}'"
                )
            raw_results = [r.evaluate(obs, classification) for r in matching]
            results = [self._normalize(r) for r in raw_results]
            results = [r for r in results if r is not None]
            if len(results) > 1:
                raise AmbiguousObservationRuleError(
                    f"Multiple rules produced findings for category '{obs.category}'"
                )
            for result in results:
                if result.finding is not None:
                    if result.finding.finding_id in seen_fids:
                        raise DuplicateFindingError(
                            f"Duplicate finding_id: {result.finding.finding_id}"
                        )
                    seen_fids.add(result.finding.finding_id)
                    findings.append(result.finding)
                for ev in result.evidence:
                    if ev.evidence_id in seen_eids:
                        raise DuplicateEvidenceError(
                            f"Duplicate evidence_id: {ev.evidence_id}"
                        )
                    seen_eids.add(ev.evidence_id)
                    evidence_list.append(ev)
        return DiagnosticEvaluation(
            findings=tuple(findings), evidence=tuple(evidence_list)
        )

    @staticmethod
    def _normalize(result: DiagnosticRuleResult) -> DiagnosticRuleResult | None:
        if result.finding is None and not result.evidence:
            return None
        return result


def build_default_rule_engine() -> DiagnosticRuleEngine:
    policy = _syscheck().FindingClassificationPolicy()
    eb = _syscheck().EvidenceBuilder()
    rules = (
        BtrfsDeviceErrorRule(eb),
        BtrfsScrubStatusRule(eb),
        WirePlumberSegfaultRule(eb),
        GeneralSegfaultRule(eb),
        MinorSegfaultRule(eb),
        KernelTaintRule(eb),
        KernelOomRule(eb),
        GpuI915HangRule(eb),
        AmdgpuResetFailRule(eb),
        GpuNvidiaXid79Rule(eb),
        PcieAerErrorRule(eb),
        NvmeControllerReliabilityRule(eb),
        HardwareMceEdacRule(eb),
        FilesystemIoErrorRule(eb),
        HardwareThermalThrottlingRule(eb),
        KernelOopsPanicRule(eb),
        FailedSystemUnitRule(eb),
        FailedUserUnitRule(eb),
        KernelCountRule(eb),
        BootDelayRule(eb),
        StorageUsageRule(eb),
    )
    return DiagnosticRuleEngine(DiagnosticRuleRegistry(rules), policy)
