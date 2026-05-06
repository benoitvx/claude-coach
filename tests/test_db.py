from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from strava_connect.db import (
    MIGRATIONS,
    connect,
    count_activities,
    get_athlete,
    get_last_sync,
    get_schema_version,
    migrate,
    stats_by_sport,
    upsert_athlete,
)
from strava_connect.models import Athlete


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
