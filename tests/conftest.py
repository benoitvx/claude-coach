from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_coach.db import connect, insert_full_activity, migrate, upsert_athlete
from claude_coach.models import Activity, Athlete, Config


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db_conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tokens_path(tmp_path: Path) -> Path:
    return tmp_path / "tokens.json"


@pytest.fixture
def fake_config() -> Config:
    return Config(client_id="123456", client_secret="s3cr3t", history_days=730)


@pytest.fixture
def seed_activities(db_conn: sqlite3.Connection) -> list[Activity]:
    """Échantillon d'activités multi-sports/dates pour les tests de lecture."""
    upsert_athlete(db_conn, Athlete(id=42))
    samples = [
        # (id, date locale, sport, distance_m, moving_time_s, elev_m)
        (1001, "2026-01-05", "Run", 10000.0, 3600, 100.0),
        (1002, "2026-01-12", "TrailRun", 15000.0, 5400, 500.0),
        (1003, "2026-01-19", "Ride", 40000.0, 5400, 300.0),
        (1004, "2026-02-09", "Swim", 2000.0, 3600, 0.0),
        (1005, "2026-02-16", "Run", 12000.0, 4200, 120.0),
        (1006, "2026-03-02", "VirtualRide", 30000.0, 3600, 0.0),
        (1007, "2026-03-16", "TrailRun", 20000.0, 7200, 800.0),
        (1008, "2026-04-01", "Run", 8000.0, 3000, 80.0),
    ]
    activities: list[Activity] = []
    for aid, day, sport, dist, moving, elev in samples:
        act = Activity(
            id=aid,
            athlete_id=42,
            name=f"{sport} du {day}",
            sport_type=sport,
            start_date=f"{day}T08:00:00+00:00",
            start_date_local=f"{day}T10:00:00",
            distance_m=dist,
            moving_time_s=moving,
            total_elevation_gain_m=elev,
            raw_json="{}",
        )
        insert_full_activity(db_conn, act, [], [], [])
        activities.append(act)
    return activities
