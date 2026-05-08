from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from strava_connect.db import (
    MIGRATIONS,
    aggregate_activities,
    connect,
    count_activities,
    finish_sync,
    get_athlete,
    get_goal,
    get_last_sync,
    get_latest_metrics,
    get_metrics_history,
    get_planned_session,
    get_schema_version,
    get_training_plan,
    has_complete_activity,
    insert_athlete_metrics,
    insert_full_activity,
    insert_goal,
    insert_planned_session,
    insert_training_plan,
    list_activities,
    list_goals,
    list_planned_sessions,
    list_training_plans,
    metrics_values_equal,
    migrate,
    start_sync,
    stats_by_sport,
    update_goal_status,
    update_planned_session_status,
    upsert_athlete,
)
from strava_connect.models import Activity, Athlete, Lap, Stream, Zone


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_migrate_creates_all_tables(db_path: Path) -> None:
    conn = connect(db_path)
    assert get_schema_version(conn) == 0
    new_version = migrate(conn)
    assert new_version == len(MIGRATIONS)
    assert get_schema_version(conn) == new_version
    expected = {
        "athletes",
        "activities",
        "activity_streams",
        "activity_laps",
        "activity_zones",
        "sync_log",
    }
    assert expected.issubset(_table_names(conn))


def test_migrate_idempotent(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)
    v1 = get_schema_version(conn)
    # Re-running should be a no-op.
    migrate(conn)
    assert get_schema_version(conn) == v1


def test_upsert_athlete_then_get(db_conn: sqlite3.Connection) -> None:
    upsert_athlete(db_conn, Athlete(id=42))
    got = get_athlete(db_conn, 42)
    assert got is not None
    assert got.id == 42

    # Réappel idempotent (INSERT OR IGNORE)
    upsert_athlete(db_conn, Athlete(id=42))
    got2 = get_athlete(db_conn, 42)
    assert got2 is not None
    assert got2.id == 42


def test_get_athlete_missing_returns_none(db_conn: sqlite3.Connection) -> None:
    assert get_athlete(db_conn, 999) is None


def test_get_last_sync_empty_returns_none(db_conn: sqlite3.Connection) -> None:
    assert get_last_sync(db_conn) is None


def test_count_activities_zero(db_conn: sqlite3.Connection) -> None:
    assert count_activities(db_conn) == 0


def test_stats_by_sport_empty(db_conn: sqlite3.Connection) -> None:
    assert stats_by_sport(db_conn) == {}


def test_foreign_keys_enforced(db_conn: sqlite3.Connection) -> None:
    import pytest as _pytest

    with _pytest.raises(sqlite3.IntegrityError), db_conn:
        db_conn.execute(
            "INSERT INTO activities (id, athlete_id) VALUES (?, ?)",
            (1, 999),
        )


# --- Lot 2 : insert_full_activity / has_complete_activity / sync_log -------


def _seed_activity(
    db_conn: sqlite3.Connection,
    activity_id: int = 1001,
    *,
    streams: bool = True,
    laps: bool = True,
    zones: bool = True,
) -> None:
    upsert_athlete(db_conn, Athlete(id=42))
    streams_list = (
        [Stream(activity_id=activity_id, stream_type="time", data="[0,1,2]", resolution="high")]
        if streams
        else []
    )
    laps_list = (
        [Lap(id=activity_id * 10 + 1, activity_id=activity_id, lap_index=1, distance_m=1000.0)]
        if laps
        else []
    )
    zones_list = (
        [Zone(activity_id=activity_id, zone_type="heartrate", data='[{"min":120,"max":140}]')]
        if zones
        else []
    )
    insert_full_activity(
        db_conn,
        Activity(
            id=activity_id,
            athlete_id=42,
            sport_type="Run",
            distance_m=10000.0,
            raw_json='{"id":' + str(activity_id) + "}",
        ),
        streams_list,
        laps_list,
        zones_list,
    )


def test_insert_full_activity_inserts_all(db_conn: sqlite3.Connection) -> None:
    _seed_activity(db_conn, activity_id=1001)
    assert count_activities(db_conn) == 1
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM activity_streams WHERE activity_id = ?", (1001,)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM activity_laps WHERE activity_id = ?", (1001,)
        ).fetchone()[0]
        == 1
    )
    assert (
        db_conn.execute(
            "SELECT COUNT(*) FROM activity_zones WHERE activity_id = ?", (1001,)
        ).fetchone()[0]
        == 1
    )


def test_insert_full_activity_idempotent(db_conn: sqlite3.Connection) -> None:
    _seed_activity(db_conn, activity_id=1001)
    _seed_activity(db_conn, activity_id=1001)  # rerun
    assert count_activities(db_conn) == 1
    # Streams/laps/zones doivent rester à 1 chacun (DELETE+INSERT à chaque tour).
    for table in ("activity_streams", "activity_laps", "activity_zones"):
        n = db_conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE activity_id = ?", (1001,)
        ).fetchone()[0]
        assert n == 1, f"{table} a {n} lignes au lieu de 1"


def test_has_complete_activity_true_when_all_present(db_conn: sqlite3.Connection) -> None:
    _seed_activity(db_conn, activity_id=1001)
    assert has_complete_activity(db_conn, 1001) is True


def test_has_complete_activity_true_when_streams_missing(db_conn: sqlite3.Connection) -> None:
    # Activité manuelle (Étirements, etc.) : Strava renvoie 404 sur /streams.
    _seed_activity(db_conn, activity_id=1001, streams=False)
    assert has_complete_activity(db_conn, 1001) is True


def test_has_complete_activity_true_when_laps_missing(db_conn: sqlite3.Connection) -> None:
    _seed_activity(db_conn, activity_id=1001, laps=False)
    assert has_complete_activity(db_conn, 1001) is True


def test_has_complete_activity_true_without_zones(db_conn: sqlite3.Connection) -> None:
    # Zones sont optionnelles (Summit-only).
    _seed_activity(db_conn, activity_id=1001, zones=False)
    assert has_complete_activity(db_conn, 1001) is True


def test_has_complete_activity_false_when_unknown(db_conn: sqlite3.Connection) -> None:
    assert has_complete_activity(db_conn, 99999) is False


def test_start_finish_sync_roundtrip(db_conn: sqlite3.Connection) -> None:
    sync_id = start_sync(db_conn, "full")
    assert sync_id > 0

    last = get_last_sync(db_conn)
    assert last is not None
    assert last.id == sync_id
    assert last.status == "running"
    assert last.activities_fetched == 0

    finish_sync(db_conn, sync_id, "success", activities_fetched=42)
    last = get_last_sync(db_conn)
    assert last is not None
    assert last.status == "success"
    assert last.activities_fetched == 42
    assert last.finished_at is not None
    assert last.error_message is None


def test_finish_sync_with_error(db_conn: sqlite3.Connection) -> None:
    sync_id = start_sync(db_conn, "full")
    finish_sync(db_conn, sync_id, "error", activities_fetched=3, error_message="boom")
    last = get_last_sync(db_conn)
    assert last is not None
    assert last.status == "error"
    assert last.error_message == "boom"


# --- Lot 4 : athlete_metrics + migration 002 -------------------------------


def test_migration_002_creates_metrics_table_and_drops_columns(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)
    tables = _table_names(conn)
    assert "athlete_metrics" in tables

    # Les colonnes obsolètes doivent avoir disparu de athletes.
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(athletes)").fetchall()}
    assert cols == {"id"}


def test_migration_002_preserves_existing_data(db_path: Path) -> None:
    """Pré-pose une row dans athletes (schéma migration 1) puis applique la 2."""
    conn = connect(db_path)
    # Applique seulement la migration 1 manuellement.
    from strava_connect.db import MIGRATIONS as _MIGRATIONS
    from strava_connect.db import _set_schema_version

    _MIGRATIONS[0](conn)
    _set_schema_version(conn, 1)
    conn.execute(
        "INSERT INTO athletes (id, weight_kg, ftp_watts, updated_at) VALUES (?, ?, ?, ?)",
        (42, 70.0, 250, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()

    # Maintenant migrate va appliquer la 2.
    migrate(conn)

    row = conn.execute(
        "SELECT athlete_id, weight_kg, ftp_watts FROM athlete_metrics WHERE athlete_id = ?",
        (42,),
    ).fetchone()
    assert row is not None
    assert row["weight_kg"] == 70.0
    assert row["ftp_watts"] == 250


def test_insert_athlete_metrics_basic_then_get(db_conn: sqlite3.Connection) -> None:
    upsert_athlete(db_conn, Athlete(id=42))
    inserted = insert_athlete_metrics(
        db_conn,
        42,
        weight_kg=72.5,
        ftp_watts=260,
        fc_max=190,
        fc_repos=48,
        vma_kmh=17.5,
        note="initial",
    )
    assert inserted.athlete_id == 42
    assert inserted.weight_kg == 72.5
    assert inserted.note == "initial"

    latest = get_latest_metrics(db_conn, 42)
    assert latest is not None
    assert latest.id == inserted.id
    assert latest.ftp_watts == 260


def test_insert_athlete_metrics_creates_athlete_if_missing(db_conn: sqlite3.Connection) -> None:
    # athletes vide initialement
    inserted = insert_athlete_metrics(db_conn, 99, weight_kg=70.0)
    assert inserted.athlete_id == 99
    # FK satisfaite : athletes contient bien l'id
    row = db_conn.execute("SELECT id FROM athletes WHERE id = 99").fetchone()
    assert row is not None


def test_insert_athlete_metrics_merges_missing_fields(db_conn: sqlite3.Connection) -> None:
    insert_athlete_metrics(
        db_conn, 42, weight_kg=70.0, ftp_watts=250, fc_max=190, fc_repos=48, vma_kmh=17.0
    )
    # 2e insertion : on ne fournit que le poids → les autres sont repris.
    second = insert_athlete_metrics(db_conn, 42, weight_kg=71.0)
    assert second.weight_kg == 71.0
    assert second.ftp_watts == 250
    assert second.fc_max == 190
    assert second.vma_kmh == 17.0


def test_get_metrics_history_ordering(db_conn: sqlite3.Connection) -> None:
    insert_athlete_metrics(
        db_conn,
        42,
        weight_kg=70.0,
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    insert_athlete_metrics(
        db_conn,
        42,
        weight_kg=71.0,
        recorded_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    insert_athlete_metrics(
        db_conn,
        42,
        weight_kg=72.0,
        recorded_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    history = get_metrics_history(db_conn, 42)
    assert [m.weight_kg for m in history] == [72.0, 71.0, 70.0]


def test_get_metrics_history_limit(db_conn: sqlite3.Connection) -> None:
    for i in range(5):
        insert_athlete_metrics(
            db_conn,
            42,
            weight_kg=70.0 + i,
            recorded_at=datetime(2026, 1, 1 + i, tzinfo=UTC),
        )
    history = get_metrics_history(db_conn, 42, limit=2)
    assert len(history) == 2


def test_get_latest_metrics_empty(db_conn: sqlite3.Connection) -> None:
    assert get_latest_metrics(db_conn, 42) is None


def test_metrics_values_equal_handles_none() -> None:
    assert (
        metrics_values_equal(
            None, weight_kg=None, ftp_watts=None, fc_max=None, fc_repos=None, vma_kmh=None
        )
        is False
    )


# --- Lot 5a : objectifs / plans / séances planifiées -----------------------


def test_migration_003_creates_goal_and_plan_tables(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)
    tables = _table_names(conn)
    assert {"goals", "training_plans", "planned_sessions"}.issubset(tables)


def test_insert_goal_then_get_roundtrip(db_conn: sqlite3.Connection) -> None:
    g = insert_goal(
        db_conn,
        name="Swim&Run Sept 2026",
        discipline="swim_run",
        target_date=date(2026, 9, 15),
        description="13.5km run + 3.5km nage",
        success_criteria="terminer en moins de 2h",
    )
    assert g.id > 0
    assert g.status == "active"
    assert g.target_date == date(2026, 9, 15)

    fetched = get_goal(db_conn, g.id)
    assert fetched is not None
    assert fetched.name == "Swim&Run Sept 2026"
    assert fetched.discipline == "swim_run"
    assert fetched.success_criteria == "terminer en moins de 2h"


def test_list_goals_filters_by_status(db_conn: sqlite3.Connection) -> None:
    insert_goal(db_conn, name="Goal A")
    g_b = insert_goal(db_conn, name="Goal B")
    update_goal_status(db_conn, g_b.id, "completed")

    actives = list_goals(db_conn, status="active")
    assert [g.name for g in actives] == ["Goal A"]
    completed = list_goals(db_conn, status="completed")
    assert [g.name for g in completed] == ["Goal B"]


def test_list_goals_orders_by_target_date(db_conn: sqlite3.Connection) -> None:
    insert_goal(db_conn, name="Late", target_date=date(2027, 6, 1))
    insert_goal(db_conn, name="Early", target_date=date(2026, 9, 15))
    insert_goal(db_conn, name="Undated")  # NULL target_date → fin de liste

    names = [g.name for g in list_goals(db_conn)]
    assert names == ["Early", "Late", "Undated"]


def test_update_goal_status_rejects_invalid_value(db_conn: sqlite3.Connection) -> None:
    g = insert_goal(db_conn, name="X")
    with pytest.raises(ValueError):
        update_goal_status(db_conn, g.id, "bogus")


def test_insert_training_plan_with_and_without_goal(db_conn: sqlite3.Connection) -> None:
    g = insert_goal(db_conn, name="Goal", target_date=date(2026, 9, 15))
    p1 = insert_training_plan(
        db_conn,
        name="Prépa",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 9, 15),
        goal_id=g.id,
    )
    assert p1.goal_id == g.id

    p2 = insert_training_plan(
        db_conn, name="Rebuild", start_date=date(2026, 1, 1), end_date=date(2026, 3, 1)
    )
    assert p2.goal_id is None

    plans_for_goal = list_training_plans(db_conn, goal_id=g.id)
    assert [p.id for p in plans_for_goal] == [p1.id]


def test_get_training_plan_missing(db_conn: sqlite3.Connection) -> None:
    assert get_training_plan(db_conn, 99999) is None


def test_planned_sessions_cascade_on_plan_delete(db_conn: sqlite3.Connection) -> None:
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
    )
    insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 1, 5),
        sport_type="Run",
    )
    insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 1, 7),
        sport_type="Ride",
    )
    assert len(list_planned_sessions(db_conn, training_plan_id=p.id)) == 2

    with db_conn:
        db_conn.execute("DELETE FROM training_plans WHERE id = ?", (p.id,))
    # ON DELETE CASCADE → sessions supprimées avec le plan.
    assert len(list_planned_sessions(db_conn, training_plan_id=p.id)) == 0


def test_planned_session_full_roundtrip(db_conn: sqlite3.Connection) -> None:
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
    )
    s = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 1, 5),
        sport_type="Run",
        session_type="intervals",
        target_duration_s=3600,
        target_distance_m=10000.0,
        target_intensity="vo2max",
        description="5×3' VMA r=2'",
    )
    fetched = get_planned_session(db_conn, s.id)
    assert fetched is not None
    assert fetched.sport_type == "Run"
    assert fetched.session_type == "intervals"
    assert fetched.target_duration_s == 3600
    assert fetched.target_intensity == "vo2max"
    assert fetched.actual_activity_id is None  # rempli en 5b


def test_update_planned_session_status(db_conn: sqlite3.Connection) -> None:
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
    )
    s = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 1, 5),
        sport_type="Run",
    )
    updated = update_planned_session_status(db_conn, s.id, "done")
    assert updated.status == "done"
    assert updated.updated_at >= updated.created_at

    with pytest.raises(ValueError):
        update_planned_session_status(db_conn, s.id, "bogus")


def test_planned_session_actual_activity_set_null_on_activity_delete(
    db_conn: sqlite3.Connection,
) -> None:
    """Si l'activité matchée disparaît, la séance reste mais actual_activity_id repasse NULL."""
    upsert_athlete(db_conn, Athlete(id=42))
    insert_full_activity(
        db_conn,
        Activity(id=2001, athlete_id=42, sport_type="Run", raw_json="{}"),
        [],
        [],
        [],
    )
    p = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 1, 1), end_date=date(2026, 2, 1)
    )
    s = insert_planned_session(
        db_conn,
        training_plan_id=p.id,
        planned_date=date(2026, 1, 5),
        sport_type="Run",
    )
    # Pré-remplit le lien manuellement (simule ce que 5b fera).
    with db_conn:
        db_conn.execute(
            "UPDATE planned_sessions SET actual_activity_id = ? WHERE id = ?",
            (2001, s.id),
        )
    # Suppression de l'activité → FK ON DELETE SET NULL.
    with db_conn:
        db_conn.execute("DELETE FROM activities WHERE id = ?", (2001,))
    refreshed = get_planned_session(db_conn, s.id)
    assert refreshed is not None
    assert refreshed.actual_activity_id is None
    # La séance elle-même n'a pas été supprimée.
    assert refreshed.id == s.id


def test_insert_goal_uses_utc_timestamps(db_conn: sqlite3.Connection) -> None:
    before = datetime.now(tz=UTC)
    g = insert_goal(db_conn, name="X")
    after = datetime.now(tz=UTC)
    assert before <= g.created_at <= after
    assert g.created_at == g.updated_at  # à la création


# --- Lot 5c.1 : list_activities / aggregate_activities ---------------------


def test_list_activities_orders_by_local_date_desc(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    rows = list_activities(db_conn)
    # Plus récent en premier.
    assert [a.id for a in rows] == [1008, 1007, 1006, 1005, 1004, 1003, 1002, 1001]


def test_list_activities_filters_by_date_range(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    rows = list_activities(db_conn, since=date(2026, 2, 1), until=date(2026, 2, 28))
    assert {a.id for a in rows} == {1004, 1005}


def test_list_activities_filters_by_sport_types(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    runs = list_activities(db_conn, sport_types=["Run"])
    assert {a.id for a in runs} == {1001, 1005, 1008}

    run_family = list_activities(db_conn, sport_types=["Run", "TrailRun"])
    assert {a.id for a in run_family} == {1001, 1002, 1005, 1007, 1008}


def test_list_activities_limit(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    rows = list_activities(db_conn, limit=3)
    assert [a.id for a in rows] == [1008, 1007, 1006]


def test_list_activities_empty(db_conn: sqlite3.Connection) -> None:
    assert list_activities(db_conn) == []


def test_aggregate_activities_by_sport(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    buckets = aggregate_activities(db_conn, group_by="sport")
    # Tri par count DESC : Run(3) > TrailRun(2) > {Ride, Swim, VirtualRide}(1) tri alpha
    assert [b.key for b in buckets] == ["Run", "TrailRun", "Ride", "Swim", "VirtualRide"]
    run_bucket = next(b for b in buckets if b.key == "Run")
    assert run_bucket.count == 3
    assert run_bucket.distance_m == 30000.0  # 10000 + 12000 + 8000
    assert run_bucket.moving_time_s == 10800  # 3600 + 4200 + 3000
    assert run_bucket.elevation_gain_m == 300.0  # 100 + 120 + 80


def test_aggregate_activities_by_month(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    buckets = aggregate_activities(db_conn, group_by="month")
    assert [b.key for b in buckets] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    counts = {b.key: b.count for b in buckets}
    assert counts == {"2026-01": 3, "2026-02": 2, "2026-03": 2, "2026-04": 1}


def test_aggregate_activities_by_week(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    buckets = aggregate_activities(db_conn, group_by="week")
    # Format SQLite '%Y-W%W' : 2 chiffres, semaines Monday-based.
    keys = [b.key for b in buckets]
    assert all(k.startswith("2026-W") for k in keys)
    assert keys == sorted(keys)  # ordre chronologique ascendant
    # 8 activités sur 8 semaines distinctes.
    assert len(buckets) == 8
    assert all(b.count == 1 for b in buckets)


def test_aggregate_activities_with_filters(
    seed_activities: list[Activity], db_conn: sqlite3.Connection
) -> None:
    buckets = aggregate_activities(
        db_conn,
        group_by="sport",
        since=date(2026, 2, 1),
        until=date(2026, 3, 31),
        sport_types=["Run", "TrailRun", "VirtualRide"],
    )
    keys = {b.key: b for b in buckets}
    assert set(keys) == {"Run", "TrailRun", "VirtualRide"}
    assert keys["Run"].count == 1  # 1005 (Feb 16) ; 1001 et 1008 hors fenêtre
    assert keys["TrailRun"].count == 1  # 1007 (Mar 16) ; 1002 hors fenêtre
    assert keys["VirtualRide"].count == 1  # 1006


def test_aggregate_activities_empty(db_conn: sqlite3.Connection) -> None:
    assert aggregate_activities(db_conn, group_by="sport") == []
    assert aggregate_activities(db_conn, group_by="week") == []
    assert aggregate_activities(db_conn, group_by="month") == []


def test_aggregate_activities_invalid_group_by(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        aggregate_activities(db_conn, group_by="day")  # type: ignore[arg-type]
