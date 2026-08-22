from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# El panel se calcula sobre eventos ya redactados: el backend nunca tuvo el
# contenido, asi que ninguna metrica de aca puede exponerlo aunque quisiera.

SEVERITY_ORDER = ("critical", "high", "medium", "low")

# Con dos incidentes se puede hablar de descuido; a partir del tercero hay un
# habito, y es la senal que dispara la intervencion pedagogica dirigida.
REPEAT_THRESHOLD = 3


@dataclass
class Metrics:
    total: int = 0
    blocked: int = 0
    warned: int = 0
    allowed: int = 0
    by_severity: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_rule: list[tuple[str, int]] = field(default_factory=list)
    by_destination: list[tuple[str, str, int]] = field(default_factory=list)
    by_area: list[tuple[str, int, int]] = field(default_factory=list)
    # Que herramienta se uso, no que dominio. Son cosas distintas y las dos
    # importan: `by_destination` dice "chatgpt.com" y esto dice si quien lo
    # abrio fue el navegador o un agente de codigo mandando un repositorio
    # entero. En 2026 esa es la diferencia que decide una politica.
    by_process: list[tuple[str, int]] = field(default_factory=list)
    people_at_risk: list[tuple[str, str, int, int]] = field(default_factory=list)
    shadow_domains: list[str] = field(default_factory=list)
    uncatalogued_domains: list[str] = field(default_factory=list)
    timeline: list[tuple[str, int]] = field(default_factory=list)

    @property
    def block_rate(self) -> float:
        return (self.blocked / self.total * 100) if self.total else 0.0


def load_events(queue: Path) -> list[dict]:
    if not queue.exists():
        events = []
    else:
        events = [
            json.loads(line)
            for line in queue.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return events


def compute(events: list[dict]) -> Metrics:
    metrics = Metrics(total=len(events))

    severity: Counter[str] = Counter()
    category: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    destinations: Counter[str] = Counter()
    destination_class: dict[str, str] = {}
    area_total: Counter[str] = Counter()
    area_critical: Counter[str] = Counter()
    person_total: Counter[str] = Counter()
    person_critical: Counter[str] = Counter()
    person_area: dict[str, str] = {}
    hours: Counter[str] = Counter()
    processes: Counter[str] = Counter()
    shadow: set[str] = set()
    uncatalogued: set[str] = set()

    for event in events:
        action = event.get("action", "allowed")
        if action == "blocked":
            metrics.blocked += 1
        else:
            if action == "warned":
                metrics.warned += 1
            else:
                metrics.allowed += 1

        destination = event.get("destination", {})
        domain = destination.get("domain", "desconocido")
        classification = destination.get("classification", "non_ai")
        destinations[domain] += 1
        destination_class[domain] = classification
        # "desconocido" es un valor legitimo del contrato -no siempre se puede
        # atribuir la conexion a un proceso- asi que se cuenta como los demas en
        # vez de descartarlo: esconderlo daria un ranking que no suma al total.
        processes[destination.get("process") or "desconocido"] += 1
        if classification == "ai_unapproved":
            shadow.add(domain)
        if classification == "ai_unknown":
            uncatalogued.add(domain)

        actor = event.get("actor", {})
        user = actor.get("user_id", "desconocido")
        area = actor.get("area", "sin area")
        person_area[user] = area
        person_total[user] += 1
        area_total[area] += 1

        detection = event.get("detection")
        if detection:
            severity[detection.get("severity", "low")] += 1
            category[detection.get("category", "secret")] += 1
            rules[detection.get("rule_id", "desconocida")] += 1
            if detection.get("severity") == "critical":
                area_critical[area] += 1
                person_critical[user] += 1

        occurred = event.get("occurred_at", "")
        if len(occurred) >= 13:
            hours[occurred[:13]] += 1

    metrics.by_severity = {name: severity.get(name, 0) for name in SEVERITY_ORDER}
    metrics.by_category = dict(category.most_common())
    metrics.by_rule = rules.most_common(10)
    metrics.by_destination = [
        (domain, destination_class.get(domain, "non_ai"), count)
        for domain, count in destinations.most_common(10)
    ]
    metrics.by_area = [
        (area, count, area_critical.get(area, 0))
        for area, count in area_total.most_common()
    ]
    metrics.people_at_risk = sorted(
        (
            (user, person_area.get(user, "sin area"), total, person_critical.get(user, 0))
            for user, total in person_total.items()
        ),
        key=lambda row: (-row[3], -row[2], row[0]),
    )[:10]
    metrics.by_process = processes.most_common(10)
    metrics.shadow_domains = sorted(shadow)
    metrics.uncatalogued_domains = sorted(uncatalogued)
    metrics.timeline = sorted(hours.items())
    return metrics


def repeat_offenders(events: list[dict]) -> dict[str, list[str]]:
    """Quien repite el mismo error, que es donde la pedagogia tiene que apuntar.

    Un incidente aislado se corrige con el mensaje del bloqueo. El mismo error
    tres veces significa que la persona no entendio el porque, y ahi hace falta
    una intervencion distinta, no otro bloqueo igual.
    """

    by_user: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        detection = event.get("detection")
        if detection:
            user = event.get("actor", {}).get("user_id", "desconocido")
            by_user[user][detection.get("rule_id", "desconocida")] += 1

    return {
        user: sorted(rule for rule, count in counts.items() if count >= REPEAT_THRESHOLD)
        for user, counts in by_user.items()
        if any(count >= REPEAT_THRESHOLD for count in counts.values())
    }
