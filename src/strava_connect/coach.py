"""Logique de matching planifié vs réalisé (Lot 5b).

Étant donné les `planned_sessions` d'un (ou tous les) plan(s) d'entraînement
et les `activities` importées via `sync`, peuple `actual_activity_id` en
appariant chaque séance à l'activité Strava la plus probable. Pas de schéma
DB, pas d'appel réseau — pure logique en lecture/écriture sur SQLite.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from strava_connect.db import _row_to_activity, list_planned_sessions, list_training_plans
from strava_connect.models import Activity, PlannedSession

SPORT_FAMILIES: dict[str, str] = {
    "Run": "run",
    "TrailRun": "run",
    "VirtualRun": "run",
    "Ride": "ride",
    "VirtualRide": "ride",
    "GravelRide": "ride",
    "EBikeRide": "ride",
    "MountainBikeRide": "ride",
    "Swim": "swim",
    "Walk": "walk",
    "Hike": "walk",
    "Workout": "workout",
    "WeightTraining": "workout",
    "Yoga": "yoga",
}


def sport_family(sport_type: str) -> str:
    """Renvoie la famille canonique d'un sport_type Strava.

    Les sports listés explicitement (Run/TrailRun/...) tombent sur leur famille.
    Tout autre sport_type est sa propre famille (`sport_type.lower()`).
    """
    return SPORT_FAMILIES.get(sport_type, sport_type.lower())


def matching_sport_types(sport_type: str) -> list[str]:
    """Liste des sport_types qui appartiennent à la même famille que `sport_type`.

    Inclut toujours `sport_type` lui-même même s'il n'est pas dans `SPORT_FAMILIES`.
    """
    family = sport_family(sport_type)
    matches = [s for s, f in SPORT_FAMILIES.items() if f == family]
    if sport_type not in matches:
        matches.append(sport_type)
    return matches


def sport_types_in_family(family: str) -> list[str]:
    """Liste des sport_types Strava connus dans la famille canonique demandée.

    Familles supportées : voir `SPORT_FAMILIES` (run, ride, swim, walk, workout, yoga).
    Famille inconnue → liste vide (aucun match).
    """
    return [s for s, f in SPORT_FAMILIES.items() if f == family]


KNOWN_FAMILIES: tuple[str, ...] = tuple(sorted(set(SPORT_FAMILIES.values())))


@dataclass(frozen=True)
class MatchResult:
    session: PlannedSession
    activity: Activity | None


def _already_linked_ids(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute(
        "SELECT actual_activity_id FROM planned_sessions WHERE actual_activity_id IS NOT NULL"
    ).fetchall()
    return {int(row[0]) for row in rows}


def _best_candidate(
    conn: sqlite3.Connection,
    session: PlannedSession,
    *,
    exclude: set[int],
) -> Activity | None:
    """Cherche la meilleure activité matchant la séance (famille sport + ±1 jour).

    Tri : (1) même jour > ±1 jour, (2) moving_time_s décroissant, (3) id croissant.
    Renvoie None si aucun candidat dans la fenêtre.
    """
    sports = matching_sport_types(session.sport_type)
    low = (session.planned_date - timedelta(days=1)).isoformat()
    high = (session.planned_date + timedelta(days=1)).isoformat()
    target = session.planned_date.isoformat()

    sport_placeholders = ",".join("?" * len(sports))
    sql = (
        "SELECT id, athlete_id, name, sport_type, start_date, start_date_local, "
        "timezone, distance_m, moving_time_s, elapsed_time_s, total_elevation_gain_m, "
        "average_speed_ms, max_speed_ms, average_heartrate, max_heartrate, "
        "average_watts, max_watts, average_cadence, calories, suffer_score, "
        "description, device_name, gear_id, has_heartrate, has_power, trainer, "
        "map_polyline, splits_metric, raw_json, synced_at "
        "FROM activities "
        f"WHERE sport_type IN ({sport_placeholders}) "
        "AND DATE(start_date_local) BETWEEN ? AND ?"
    )
    params: list[object] = [*sports, low, high]
    if exclude:
        excl_placeholders = ",".join("?" * len(exclude))
        sql += f" AND id NOT IN ({excl_placeholders})"
        params.extend(exclude)
    sql += (
        " ORDER BY ABS(julianday(DATE(start_date_local)) - julianday(?)) ASC, "
        "moving_time_s DESC, id ASC LIMIT 1"
    )
    params.append(target)

    row = conn.execute(sql, tuple(params)).fetchone()
    return _row_to_activity(row) if row else None


def _link_session_to_activity(conn: sqlite3.Connection, session_id: int, activity_id: int) -> None:
    now = datetime.now(tz=UTC).isoformat()
    with conn:
        conn.execute(
            "UPDATE planned_sessions "
            "SET actual_activity_id = ?, status = 'done', updated_at = ? "
            "WHERE id = ?",
            (activity_id, now, session_id),
        )


def _sessions_to_match(conn: sqlite3.Connection, *, plan_id: int | None) -> list[PlannedSession]:
    """Séances en statut 'planned' à traiter, triées par date croissante.

    Si `plan_id` fourni : ce plan uniquement. Sinon : tous les plans actifs.
    """
    if plan_id is not None:
        plans = [plan_id]
    else:
        plans = [p.id for p in list_training_plans(conn, status="active")]

    sessions: list[PlannedSession] = []
    for pid in plans:
        sessions.extend(list_planned_sessions(conn, training_plan_id=pid, status="planned"))
    sessions.sort(key=lambda s: (s.planned_date, s.id))
    return sessions


def match_all_planned_sessions(
    conn: sqlite3.Connection,
    *,
    plan_id: int | None = None,
    dry_run: bool = False,
) -> list[MatchResult]:
    """Apparie chaque séance planifiée à la meilleure activité Strava disponible.

    Greedy chronologique : si deux séances peuvent prétendre à la même activité,
    c'est la plus ancienne (planned_date) qui l'obtient. Idempotent : re-lancer
    sans rien changer ne re-matche pas les sessions déjà 'done'.
    """
    sessions = _sessions_to_match(conn, plan_id=plan_id)
    used_activity_ids = _already_linked_ids(conn)

    results: list[MatchResult] = []
    for s in sessions:
        candidate = _best_candidate(conn, s, exclude=used_activity_ids)
        if candidate is not None:
            used_activity_ids.add(candidate.id)
            if not dry_run:
                _link_session_to_activity(conn, s.id, candidate.id)
        results.append(MatchResult(session=s, activity=candidate))
    return results


def session_deltas(session: PlannedSession, activity: Activity) -> dict[str, float | None]:
    """Calcule les écarts entre cible et réalisé. Renvoie None par champ si non comparable."""
    duration_delta = (
        (activity.moving_time_s - session.target_duration_s)
        if (activity.moving_time_s is not None and session.target_duration_s is not None)
        else None
    )
    distance_delta = (
        (activity.distance_m - session.target_distance_m)
        if (activity.distance_m is not None and session.target_distance_m is not None)
        else None
    )
    return {
        "duration_delta_s": duration_delta,
        "distance_delta_m": distance_delta,
    }


# Re-exports utiles pour les modules consommateurs (cli.py).
__all__ = [
    "KNOWN_FAMILIES",
    "MatchResult",
    "SPORT_FAMILIES",
    "match_all_planned_sessions",
    "matching_sport_types",
    "session_deltas",
    "sport_family",
    "sport_types_in_family",
]
