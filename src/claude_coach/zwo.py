"""Génération de fichiers `.zwo` (Zwift Workout) pour les séances vélo (Lot 6.2).

Un `.zwo` est un XML FTP-relatif : chaque bloc exprime sa puissance comme une
fraction de la FTP du rider (Zwift applique la FTP localement, on n'en a donc
pas besoin ici). La structure d'une séance est décrite par une liste de **blocs**
stockée en DB (`planned_sessions.blocks_json`), saisie via un mini-DSL.

Mini-DSL (segments séparés par `;` au niveau racine, durées `<int>m`/`<int>s`,
puissance entière en % de FTP) :

    warmup:10m:50-65 ; 3x[12m@95;4m@60] ; 10m@65 ; cooldown:8m:65-50

Pas de dépendance externe : `xml.etree.ElementTree` (stdlib).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from claude_coach.coach import sport_family

# Bornes de validation (puissance en % de FTP).
_POWER_MIN_PCT = 1
_POWER_MAX_PCT = 200

_DURATION_RE = re.compile(r"^(\d+)(m|s)$")
_STEADY_RE = re.compile(r"^(\d+[ms])@(\d+)$")
_RAMP_RE = re.compile(r"^(warmup|cooldown):(\d+[ms]):(\d+)-(\d+)$")
_INTERVALS_RE = re.compile(r"^(\d+)x\[(.+)\]$")


@dataclass(frozen=True)
class Block:
    """Un bloc de séance, forme canonique indépendante du `.zwo`.

    `kind` ∈ {warmup, steady, intervals, cooldown}. Seuls les champs pertinents
    pour le `kind` sont renseignés (les autres restent `None`).
    """

    kind: str
    duration_s: int | None = None
    power: float | None = None
    power_from: float | None = None
    power_to: float | None = None
    repeat: int | None = None
    on_duration_s: int | None = None
    on_power: float | None = None
    off_duration_s: int | None = None
    off_power: float | None = None


def is_bike(sport_type: str) -> bool:
    """True si `sport_type` appartient à la famille vélo (Ride, VirtualRide, ...)."""
    return sport_family(sport_type) == "ride"


def _parse_duration(token: str) -> int:
    m = _DURATION_RE.match(token)
    if not m:
        raise ValueError(f"Durée invalide '{token}' (attendu <entier>m ou <entier>s, ex: 10m, 90s)")
    value, unit = int(m.group(1)), m.group(2)
    if value <= 0:
        raise ValueError(f"Durée invalide '{token}' : doit être > 0")
    return value * 60 if unit == "m" else value


def _parse_power_pct(token: str) -> float:
    if not token.isdigit():
        raise ValueError(f"Puissance invalide '{token}' (attendu un entier en % de FTP, ex: 95)")
    pct = int(token)
    if not (_POWER_MIN_PCT <= pct <= _POWER_MAX_PCT):
        raise ValueError(
            f"Puissance '{pct}%' hors bornes [{_POWER_MIN_PCT}, {_POWER_MAX_PCT}]% de FTP"
        )
    return round(pct / 100, 4)


def _split_top_level(dsl: str) -> list[str]:
    """Découpe sur `;` uniquement hors crochets (les intervalles contiennent `;`)."""
    segments: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in dsl:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth < 0:
                raise ValueError("Crochets déséquilibrés : ']' sans '[' correspondant")
        if ch == ";" and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
    if depth != 0:
        raise ValueError("Crochets déséquilibrés : '[' non fermé")
    segments.append("".join(current))
    return [s.strip() for s in segments if s.strip()]


def _parse_intervals(repeat_str: str, inner: str) -> Block:
    repeat = int(repeat_str)
    if repeat < 1:
        raise ValueError(f"Répétitions invalides 'x{repeat}' : doit être ≥ 1")
    parts = [p.strip() for p in inner.split(";") if p.strip()]
    if len(parts) != 2:
        raise ValueError(
            f"Intervalle '{repeat}x[{inner}]' : attendu exactement 2 sous-blocs "
            "(effort;récup), ex: 3x[12m@95;4m@60]"
        )
    on_m, off_m = _STEADY_RE.match(parts[0]), _STEADY_RE.match(parts[1])
    if not on_m or not off_m:
        raise ValueError(
            f"Intervalle '{repeat}x[{inner}]' : chaque sous-bloc doit être <durée>@<%FTP>"
        )
    return Block(
        kind="intervals",
        repeat=repeat,
        on_duration_s=_parse_duration(on_m.group(1)),
        on_power=_parse_power_pct(on_m.group(2)),
        off_duration_s=_parse_duration(off_m.group(1)),
        off_power=_parse_power_pct(off_m.group(2)),
    )


def _parse_segment(segment: str) -> Block:
    ramp = _RAMP_RE.match(segment)
    if ramp:
        kind, dur, p1, p2 = ramp.groups()
        return Block(
            kind=kind,
            duration_s=_parse_duration(dur),
            power_from=_parse_power_pct(p1),
            power_to=_parse_power_pct(p2),
        )
    intervals = _INTERVALS_RE.match(segment)
    if intervals:
        return _parse_intervals(intervals.group(1), intervals.group(2))
    steady = _STEADY_RE.match(segment)
    if steady:
        return Block(
            kind="steady",
            duration_s=_parse_duration(steady.group(1)),
            power=_parse_power_pct(steady.group(2)),
        )
    raise ValueError(
        f"Segment '{segment}' non reconnu. Formes valides : warmup:10m:50-65, "
        "40m@65, 3x[12m@95;4m@60], cooldown:8m:65-50"
    )


def parse_blocks(dsl: str) -> list[Block]:
    """Parse le mini-DSL en liste de `Block`. Lève `ValueError` si invalide."""
    segments = _split_top_level(dsl)
    if not segments:
        raise ValueError("Aucun bloc : le DSL est vide")
    return [_parse_segment(s) for s in segments]


def _block_to_dict(b: Block) -> dict[str, object]:
    """Forme canonique JSON-able d'un bloc (champs `None` omis)."""
    return {k: v for k, v in vars(b).items() if v is not None}


def blocks_to_json(blocks: list[Block]) -> str:
    return json.dumps([_block_to_dict(b) for b in blocks])


def blocks_from_json(raw: str) -> list[Block]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("blocks_json doit être une liste")
    return [Block(**item) for item in data]


def _fmt_power(fraction: float) -> str:
    """Formate une fraction de FTP pour Zwift (0.5, 0.95, 0.6, 1, ...)."""
    return f"{round(fraction, 4):g}"


def _append_block_element(workout: ET.Element, b: Block) -> None:
    if b.kind == "steady":
        ET.SubElement(
            workout,
            "SteadyState",
            Duration=str(b.duration_s),
            Power=_fmt_power(_require(b.power, "power")),
        )
    elif b.kind == "warmup":
        # Zwift <Warmup> monte de PowerLow vers PowerHigh.
        ET.SubElement(
            workout,
            "Warmup",
            Duration=str(b.duration_s),
            PowerLow=_fmt_power(_require(b.power_from, "power_from")),
            PowerHigh=_fmt_power(_require(b.power_to, "power_to")),
        )
    elif b.kind == "cooldown":
        # Zwift <Cooldown> descend de PowerHigh vers PowerLow → on inverse.
        ET.SubElement(
            workout,
            "Cooldown",
            Duration=str(b.duration_s),
            PowerLow=_fmt_power(_require(b.power_to, "power_to")),
            PowerHigh=_fmt_power(_require(b.power_from, "power_from")),
        )
    elif b.kind == "intervals":
        ET.SubElement(
            workout,
            "IntervalsT",
            Repeat=str(b.repeat),
            OnDuration=str(b.on_duration_s),
            OffDuration=str(b.off_duration_s),
            OnPower=_fmt_power(_require(b.on_power, "on_power")),
            OffPower=_fmt_power(_require(b.off_power, "off_power")),
        )
    else:
        raise ValueError(f"Type de bloc inconnu : '{b.kind}'")


def _require(value: float | None, field: str) -> float:
    if value is None:
        raise ValueError(f"Champ '{field}' manquant pour ce bloc")
    return value


def generate_zwo(*, name: str, description: str | None, blocks: list[Block]) -> str:
    """Construit le XML `.zwo` (sportType=bike) à partir des blocs."""
    if not blocks:
        raise ValueError("Impossible de générer un .zwo sans bloc")
    root = ET.Element("workout_file")
    ET.SubElement(root, "author").text = "claude-coach"
    ET.SubElement(root, "name").text = name
    ET.SubElement(root, "description").text = description or ""
    ET.SubElement(root, "sportType").text = "bike"
    workout = ET.SubElement(root, "workout")
    for b in blocks:
        _append_block_element(workout, b)
    ET.indent(root)
    xml = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"
