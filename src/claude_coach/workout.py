"""Séances structurées multi-cibles (course, natation, vélo outdoor) — Lot 9.

Contrairement au vélo home-trainer (puissance %FTP, cf. `zwo.py`), ces séances se
cadrent en **allure**, **fréquence cardiaque**, **durée** ou **distance**. Ce module
parse un mini-DSL en blocs canoniques (`Step` / `Repetition`), forme neutre vis-à-vis
de la cible d'export. Le mapping vers le `workout_doc` intervals.icu vit dans
`intervals.py` (`workout_doc_from_items`).

Mini-DSL (segments séparés par `;` au niveau racine) :

    warmup:15min@h120-140 ; 6x[400m@p3:45;rest:90s@h130] ; cooldown:10min@h120

Un segment est soit une **répétition** `Nx[ step ; step ; ... ]`, soit un **step** :

    [<intensité>:]<durée>[@<cible>]

- intensité ∈ {warmup, cooldown, active, rest} (défaut `active`).
- durée : `<int>min` / `<int>s` (temps) **ou** `<int>km` / `<int>m` (distance).
  `min` lève l'ambiguïté avec `m` (mètres) : `10min` = 10 minutes, `10m` = 10 mètres.
- cible (optionnelle) : `p<m:ss>` allure min/km (convertie en m/s), `h<bpm>` FC,
  `w<watts>` puissance. Plage possible : `p3:45-4:15`, `h140-150`. Absente → sans cible.

Les cibles sont **absolues** (le coach calcule bpm/allure depuis `athlete show`).
Pas de dépendance externe.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from claude_coach.zwo import _split_top_level

INTENSITIES = ("warmup", "cooldown", "active", "rest")

# Bornes de validation (cibles absolues).
_HR_MIN_BPM = 30
_HR_MAX_BPM = 240
_POWER_MIN_W = 1
_POWER_MAX_W = 2000
_PACE_MIN_S_PER_KM = 120  # 2:00/km (sprint) — plancher de garde
_PACE_MAX_S_PER_KM = 1200  # 20:00/km (marche) — plafond de garde

_INTENSITY_RE = re.compile(r"^(warmup|cooldown|active|rest):(.+)$")
_DURATION_RE = re.compile(r"^(\d+)(min|s|km|m)$")
_REPETITION_RE = re.compile(r"^(\d+)x\[(.+)\]$")
_PACE_TOKEN_RE = re.compile(r"^(\d+):([0-5]\d)$")


@dataclass(frozen=True)
class Step:
    """Un bloc élémentaire. `target_type` ∈ {pace, heartrate, power, no_target}.

    Pour `no_target`, `target_min`/`target_max` restent `None`. Pour une cible
    simple, `target_min == target_max`. Allure stockée en m/s, FC en bpm, puissance
    en watts. Durée en secondes (`duration_type=duration`) ou mètres (`distance`).
    """

    intensity: str
    duration_type: str  # "duration" (s) | "distance" (m)
    duration_value: int
    target_type: str
    target_min: float | None = None
    target_max: float | None = None


@dataclass(frozen=True)
class Repetition:
    """Une répétition d'un groupe ordonné de steps (`value` fois)."""

    repeat: int
    steps: tuple[Step, ...]


WorkoutItem = Step | Repetition


def _parse_duration(token: str) -> tuple[str, int]:
    """`<int>{min,s,km,m}` → ('duration', secondes) ou ('distance', mètres)."""
    m = _DURATION_RE.match(token)
    if not m:
        raise ValueError(
            f"Durée invalide '{token}' (attendu <entier> suivi de min/s pour le temps "
            "ou km/m pour la distance, ex: 10min, 90s, 5km, 400m)"
        )
    value, unit = int(m.group(1)), m.group(2)
    if value <= 0:
        raise ValueError(f"Durée invalide '{token}' : doit être > 0")
    if unit == "min":
        return ("duration", value * 60)
    if unit == "s":
        return ("duration", value)
    if unit == "km":
        return ("distance", value * 1000)
    return ("distance", value)  # unit == "m"


def _pace_to_mps(token: str) -> float:
    """Allure 'm:ss' (min/km) → vitesse en m/s (forme canonique interne)."""
    m = _PACE_TOKEN_RE.match(token)
    if not m:
        raise ValueError(f"Allure invalide '{token}' (attendu m:ss par km, ex: 3:45)")
    seconds_per_km = int(m.group(1)) * 60 + int(m.group(2))
    if not (_PACE_MIN_S_PER_KM <= seconds_per_km <= _PACE_MAX_S_PER_KM):
        raise ValueError(f"Allure '{token}' hors bornes [2:00, 20:00] par km")
    return round(1000 / seconds_per_km, 3)


def _parse_int_target(token: str, lo: int, hi: int, label: str) -> float:
    if not token.isdigit():
        raise ValueError(f"{label} invalide '{token}' (attendu un entier)")
    value = int(token)
    if not (lo <= value <= hi):
        raise ValueError(f"{label} '{value}' hors bornes [{lo}, {hi}]")
    return float(value)


def _conv_hr(token: str) -> float:
    return _parse_int_target(token, _HR_MIN_BPM, _HR_MAX_BPM, "FC")


def _conv_power(token: str) -> float:
    return _parse_int_target(token, _POWER_MIN_W, _POWER_MAX_W, "Puissance")


# Préfixe de cible → (target_type canonique, converti vers l'unité absolue attendue).
_TARGET_PREFIXES: dict[str, tuple[str, Callable[[str], float]]] = {
    "p": ("pace", _pace_to_mps),  # allure min/km → m/s
    "h": ("heartrate", _conv_hr),  # bpm
    "w": ("power", _conv_power),  # watts
}


def _parse_target(token: str | None) -> tuple[str, float | None, float | None]:
    """Parse une cible. `None` → ('no_target', None, None)."""
    if token is None:
        return ("no_target", None, None)
    if not token:
        raise ValueError("Cible vide après '@'")
    prefix, body = token[0], token[1:]
    entry = _TARGET_PREFIXES.get(prefix)
    if entry is None:
        raise ValueError(
            f"Cible '{token}' non reconnue : préfixe attendu p (allure), h (FC) ou w (watts)"
        )
    kind, conv = entry
    parts = body.split("-")
    if len(parts) == 1:
        v = conv(parts[0])
        return (kind, v, v)
    if len(parts) == 2:
        lo, hi = sorted((conv(parts[0]), conv(parts[1])))
        return (kind, lo, hi)
    raise ValueError(f"Cible '{token}' : au plus une plage 'min-max' attendue")


def _parse_step(segment: str, *, default_intensity: str = "active") -> Step:
    m = _INTENSITY_RE.match(segment)
    if m:
        intensity, rest = m.group(1), m.group(2)
    else:
        intensity, rest = default_intensity, segment
    if "@" in rest:
        dur_token, target_token = rest.split("@", 1)
    else:
        dur_token, target_token = rest, None
    duration_type, duration_value = _parse_duration(dur_token.strip())
    target_type, target_min, target_max = _parse_target(
        target_token.strip() if target_token is not None else None
    )
    return Step(
        intensity=intensity,
        duration_type=duration_type,
        duration_value=duration_value,
        target_type=target_type,
        target_min=target_min,
        target_max=target_max,
    )


def _parse_repetition(repeat_str: str, inner: str) -> Repetition:
    repeat = int(repeat_str)
    if repeat < 1:
        raise ValueError(f"Répétitions invalides '{repeat}x[...]' : doit être ≥ 1")
    parts = [p.strip() for p in inner.split(";") if p.strip()]
    if not parts:
        raise ValueError(f"Répétition '{repeat}x[{inner}]' vide")
    return Repetition(repeat=repeat, steps=tuple(_parse_step(p) for p in parts))


def parse_workout(dsl: str) -> list[WorkoutItem]:
    """Parse le mini-DSL en liste de blocs (`Step`/`Repetition`). Lève `ValueError`."""
    segments = _split_top_level(dsl)
    if not segments:
        raise ValueError("Aucun bloc : le DSL est vide")
    items: list[WorkoutItem] = []
    for seg in segments:
        rep = _REPETITION_RE.match(seg)
        if rep:
            items.append(_parse_repetition(rep.group(1), rep.group(2)))
        else:
            items.append(_parse_step(seg))
    return items


def _step_to_dict(s: Step) -> dict[str, Any]:
    d: dict[str, Any] = {
        "intensity": s.intensity,
        "duration_type": s.duration_type,
        "duration_value": s.duration_value,
        "target_type": s.target_type,
    }
    if s.target_min is not None:
        d["target_min"] = s.target_min
    if s.target_max is not None:
        d["target_max"] = s.target_max
    return d


def _item_to_dict(item: WorkoutItem) -> dict[str, Any]:
    if isinstance(item, Repetition):
        return {"repeat": item.repeat, "steps": [_step_to_dict(s) for s in item.steps]}
    return _step_to_dict(item)


def workout_to_json(items: list[WorkoutItem]) -> str:
    return json.dumps([_item_to_dict(i) for i in items])


def _step_from_dict(raw: dict[str, Any]) -> Step:
    return Step(
        intensity=raw["intensity"],
        duration_type=raw["duration_type"],
        duration_value=raw["duration_value"],
        target_type=raw["target_type"],
        target_min=raw.get("target_min"),
        target_max=raw.get("target_max"),
    )


def workout_from_json(raw: str) -> list[WorkoutItem]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("workout JSON doit être une liste")
    items: list[WorkoutItem] = []
    for entry in data:
        if "steps" in entry:
            items.append(
                Repetition(
                    repeat=entry["repeat"],
                    steps=tuple(_step_from_dict(s) for s in entry["steps"]),
                )
            )
        else:
            items.append(_step_from_dict(entry))
    return items
