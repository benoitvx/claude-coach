from __future__ import annotations

import sqlite3
from datetime import date, datetime

from claude_coach.coach import (
    SPORT_FAMILIES,
    match_all_planned_sessions,
    matching_sport_types,
    session_deltas,
    sport_family,
)
from claude_coach.db import (
    get_planned_session,
    insert_full_activity,
    insert_planned_session,
    insert_training_plan,
    update_planned_session_status,
    upsert_athlete,
)
from claude_coach.models import Activity, Athlete, PlannedSession


def _seed_activity(
    conn: sqlite3.Connection,
    *,
    activity_id: int,
    sport_type: str,
    start_date_local: str,
    moving_time_s: int = 3600,
    distance_m: float = 10000.0,
) -> None:
    upsert_athlete(conn, Athlete(id=42))
    insert_full_activity(
        conn,
        Activity(
            id=activity_id,
            athlete_id=42,
            sport_type=sport_type,
            start_date_local=start_date_local,
            moving_time_s=moving_time_s,
            distance_m=distance_m,
            raw_json="{}",
        ),
        [],
        [],
        [],
    )


def _seed_plan_with_session(
    conn: sqlite3.Connection,
    *,
    planned_date: date,
    sport_type: str,
    target_duration_s: int | None = None,
    target_distance_m: float | None = None,
) -> tuple[int, int]:
    """Crée un plan et une séance, renvoie (plan_id, session_id)."""
    p = insert_training_plan(
        conn,
        name="P",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    s = insert_planned_session(
        conn,
        training_plan_id=p.id,
        planned_date=planned_date,
        sport_type=sport_type,
        target_duration_s=target_duration_s,
        target_distance_m=target_distance_m,
    )
    return p.id, s.id


# --- Familles de sport ------------------------------------------------------


def test_sport_family_known_running() -> None:
    assert sport_family("Run") == "run"
    assert sport_family("TrailRun") == "run"
    assert sport_family("VirtualRun") == "run"


def test_sport_family_known_cycling() -> None:
    assert sport_family("Ride") == "ride"
    assert sport_family("VirtualRide") == "ride"
    assert sport_family("GravelRide") == "ride"


def test_sport_family_unknown_lowercases() -> None:
    assert sport_family("Kitesurf") == "kitesurf"
    assert sport_family("BackcountrySki") == "backcountryski"


def test_matching_sport_types_returns_family_members() -> None:
    matches = matching_sport_types("Run")
    assert "Run" in matches
    assert "TrailRun" in matches
    assert "Ride" not in matches


def test_matching_sport_types_unknown_includes_self() -> None:
    assert matching_sport_types("Kitesurf") == ["Kitesurf"]


def test_sport_families_consistent_with_constants() -> None:
    """Toutes les familles déclarées doivent être atteignables via sport_family."""
    for sport, family in SPORT_FAMILIES.items():
        assert sport_family(sport) == family


# --- Matching basique -------------------------------------------------------


def test_match_basic_same_day(db_conn: sqlite3.Connection) -> None:
    _, session_id = _seed_plan_with_session(
        db_conn, planned_date=date(2026, 6, 15), sport_type="Run"
    )
    _seed_activity(
        db_conn,
        activity_id=2001,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    results = match_all_planned_sessions(db_conn)
    assert len(results) == 1
    assert results[0].activity is not None
    assert results[0].activity.id == 2001

    s = get_planned_session(db_conn, session_id)
    assert s is not None
    assert s.actual_activity_id == 2001
    assert s.status == "done"


def test_match_with_family_equivalence(db_conn: sqlite3.Connection) -> None:
    """Une séance Run peut matcher une activité TrailRun."""
    _, _ = _seed_plan_with_session(db_conn, planned_date=date(2026, 6, 15), sport_type="Run")
    _seed_activity(
        db_conn,
        activity_id=2002,
        sport_type="TrailRun",
        start_date_local="2026-06-15T07:00:00",
    )

    results = match_all_planned_sessions(db_conn)
    assert results[0].activity is not None
    assert results[0].activity.sport_type == "TrailRun"


def test_no_match_outside_one_day_window(db_conn: sqlite3.Connection) -> None:
    _, _ = _seed_plan_with_session(db_conn, planned_date=date(2026, 6, 15), sport_type="Run")
    _seed_activity(
        db_conn,
        activity_id=2003,
        sport_type="Run",
        start_date_local="2026-06-13T08:00:00",  # J-2
    )

    results = match_all_planned_sessions(db_conn)
    assert results[0].activity is None


def test_no_match_different_family(db_conn: sqlite3.Connection) -> None:
    _, _ = _seed_plan_with_session(db_conn, planned_date=date(2026, 6, 15), sport_type="Run")
    _seed_activity(
        db_conn,
        activity_id=2004,
        sport_type="Swim",
        start_date_local="2026-06-15T08:00:00",
    )

    results = match_all_planned_sessions(db_conn)
    assert results[0].activity is None


# --- Tie-breaks --------------------------------------------------------------


def test_tiebreak_same_day_beats_adjacent(db_conn: sqlite3.Connection) -> None:
    _, _ = _seed_plan_with_session(db_conn, planned_date=date(2026, 6, 15), sport_type="Run")
    _seed_activity(
        db_conn,
        activity_id=2005,
        sport_type="Run",
        start_date_local="2026-06-14T08:00:00",  # J-1
        moving_time_s=7200,  # plus longue mais mauvais jour
    )
    _seed_activity(
        db_conn,
        activity_id=2006,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",  # J : doit gagner
        moving_time_s=1800,
    )

    results = match_all_planned_sessions(db_conn)
    assert results[0].activity is not None
    assert results[0].activity.id == 2006


def test_tiebreak_longer_duration_wins_same_day(db_conn: sqlite3.Connection) -> None:
    _, _ = _seed_plan_with_session(db_conn, planned_date=date(2026, 6, 15), sport_type="Run")
    _seed_activity(
        db_conn,
        activity_id=2007,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
        moving_time_s=1800,  # 30 min
    )
    _seed_activity(
        db_conn,
        activity_id=2008,
        sport_type="Run",
        start_date_local="2026-06-15T18:00:00",
        moving_time_s=3600,  # 60 min, doit gagner
    )

    results = match_all_planned_sessions(db_conn)
    assert results[0].activity is not None
    assert results[0].activity.id == 2008


# --- Greedy chronologique --------------------------------------------------


def test_greedy_chronological_first_session_wins_shared_activity(
    db_conn: sqlite3.Connection,
) -> None:
    """2 séances le même jour, 1 activité : la séance créée en premier (id plus petit) gagne."""
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    s1 = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    s2 = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    _seed_activity(
        db_conn,
        activity_id=2009,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    results = match_all_planned_sessions(db_conn)
    matched = {r.session.id: r.activity for r in results}
    s1_match = matched[s1.id]
    assert s1_match is not None
    assert s1_match.id == 2009
    assert matched[s2.id] is None


# --- Idempotence et exclusion ----------------------------------------------


def test_idempotent_second_run_is_noop(db_conn: sqlite3.Connection) -> None:
    _, session_id = _seed_plan_with_session(
        db_conn, planned_date=date(2026, 6, 15), sport_type="Run"
    )
    _seed_activity(
        db_conn,
        activity_id=2010,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    first = match_all_planned_sessions(db_conn)
    assert first[0].activity is not None

    # Second run: la séance est en 'done' donc plus traitée.
    second = match_all_planned_sessions(db_conn)
    assert second == []  # plus rien à matcher

    # La DB n'a pas changé.
    s = get_planned_session(db_conn, session_id)
    assert s is not None
    assert s.actual_activity_id == 2010


def test_skipped_session_ignored(db_conn: sqlite3.Connection) -> None:
    _, session_id = _seed_plan_with_session(
        db_conn, planned_date=date(2026, 6, 15), sport_type="Run"
    )
    update_planned_session_status(db_conn, session_id, "skipped")
    _seed_activity(
        db_conn,
        activity_id=2011,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    results = match_all_planned_sessions(db_conn)
    assert results == []


def test_already_linked_activity_not_reused(db_conn: sqlite3.Connection) -> None:
    """Si une activité est déjà liée à une séance, elle n'est pas proposée à une autre."""
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    s1 = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    _seed_activity(
        db_conn,
        activity_id=2012,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    # Premier run : s1 chope l'activité, s2 reste sans match.
    first = match_all_planned_sessions(db_conn)
    assert sum(1 for r in first if r.activity is not None) == 1
    matched_session_id = next(r.session.id for r in first if r.activity is not None)
    assert matched_session_id == s1.id

    # Second run : s1 est en done, s2 toujours planned mais l'activité est exclue.
    second = match_all_planned_sessions(db_conn)
    assert all(r.activity is None for r in second)


def test_dry_run_does_not_persist(db_conn: sqlite3.Connection) -> None:
    _, session_id = _seed_plan_with_session(
        db_conn, planned_date=date(2026, 6, 15), sport_type="Run"
    )
    _seed_activity(
        db_conn,
        activity_id=2013,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    results = match_all_planned_sessions(db_conn, dry_run=True)
    assert results[0].activity is not None  # le résultat est calculé

    # Mais rien n'a été écrit en DB.
    s = get_planned_session(db_conn, session_id)
    assert s is not None
    assert s.actual_activity_id is None
    assert s.status == "planned"


def test_plan_id_filters_to_one_plan(db_conn: sqlite3.Connection) -> None:
    p1 = insert_training_plan(
        db_conn, name="P1", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    p2 = insert_training_plan(
        db_conn, name="P2", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    s1 = insert_planned_session(
        db_conn,
        training_plan_id=p1.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    insert_planned_session(
        db_conn,
        training_plan_id=p2.id,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
    )
    _seed_activity(
        db_conn,
        activity_id=2014,
        sport_type="Run",
        start_date_local="2026-06-15T08:00:00",
    )

    # On ne traite que p1 → s1 matche, la séance de p2 n'est pas touchée
    # (et donc l'activité est toujours dispo, mais on ne la propose pas).
    results = match_all_planned_sessions(db_conn, plan_id=p1.id)
    assert len(results) == 1
    assert results[0].session.id == s1.id
    assert results[0].activity is not None


# --- Calcul des écarts ------------------------------------------------------


def _planned_session(
    *, target_duration_s: int | None = None, target_distance_m: float | None = None
) -> PlannedSession:
    return PlannedSession(
        id=1,
        training_plan_id=1,
        planned_date=date(2026, 6, 15),
        sport_type="Run",
        status="planned",
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        target_duration_s=target_duration_s,
        target_distance_m=target_distance_m,
    )


def test_session_deltas_basic() -> None:
    s = _planned_session(target_duration_s=3600, target_distance_m=10000.0)
    a = Activity(id=1, athlete_id=42, moving_time_s=3500, distance_m=10500.0)
    deltas = session_deltas(s, a)
    assert deltas["duration_delta_s"] == -100
    assert deltas["distance_delta_m"] == 500.0


def test_session_deltas_handles_missing_targets() -> None:
    s = _planned_session()  # pas de cibles
    a = Activity(id=1, athlete_id=42, moving_time_s=3500, distance_m=10500.0)
    deltas = session_deltas(s, a)
    assert deltas["duration_delta_s"] is None
    assert deltas["distance_delta_m"] is None
