from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from strava_connect.db import (
    MIGRATIONS,
    connect,
    count_activities,
    finish_sync,
    get_athlete,
    get_last_sync,
    get_schema_version,
    has_complete_activity,
    insert_full_activity,
    migrate,
    start_sync,
    stats_by_sport,
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
    now = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    a = Athlete(
        id=42,
        weight_kg=72.5,
        ftp_watts=250,
        fc_max=190,
        fc_repos=48,
        vma_kmh=17.5,
        updated_at=now,
    )
    upsert_athlete(db_conn, a)
    got = get_athlete(db_conn, 42)
    assert got is not None
    assert got.id == 42
    assert got.weight_kg == 72.5
    assert got.ftp_watts == 250
    assert got.updated_at == now

    # Update existing
    updated = Athlete(id=42, weight_kg=73.0, ftp_watts=255)
    upsert_athlete(db_conn, updated)
    got2 = get_athlete(db_conn, 42)
    assert got2 is not None
    assert got2.weight_kg == 73.0
    assert got2.ftp_watts == 255
    assert got2.fc_max is None  # was overwritten


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
