from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from strava_connect.models import Athlete, SyncLog

DEFAULT_DB_PATH = Path("data/strava.db")


def db_path_from_env() -> Path:
    return Path(os.environ.get("STRAVA_DB_PATH", str(DEFAULT_DB_PATH)))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA user_version doesn't accept parameter binding; version is int we set ourselves
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE athletes (
            id            INTEGER PRIMARY KEY,
            weight_kg     REAL,
            ftp_watts     INTEGER,
            fc_max        INTEGER,
            fc_repos      INTEGER,
            vma_kmh       REAL,
            updated_at    TEXT
        );

        CREATE TABLE activities (
            id                       INTEGER PRIMARY KEY,
            athlete_id               INTEGER NOT NULL REFERENCES athletes(id),
            name                     TEXT,
            sport_type               TEXT,
            start_date               TEXT,
            start_date_local         TEXT,
            timezone                 TEXT,
            distance_m               REAL,
            moving_time_s            INTEGER,
            elapsed_time_s           INTEGER,
            total_elevation_gain_m   REAL,
            average_speed_ms         REAL,
            max_speed_ms             REAL,
            average_heartrate        REAL,
            max_heartrate            REAL,
            average_watts            REAL,
            max_watts                REAL,
            average_cadence          REAL,
            calories                 REAL,
            suffer_score             INTEGER,
            description              TEXT,
            device_name              TEXT,
            gear_id                  TEXT,
            has_heartrate            INTEGER,
            has_power                INTEGER,
            trainer                  INTEGER,
            map_polyline             TEXT,
            splits_metric            TEXT,
            raw_json                 TEXT,
            synced_at                TEXT
        );
        CREATE INDEX idx_activities_start_date ON activities(start_date);
        CREATE INDEX idx_activities_sport_type ON activities(sport_type);

        CREATE TABLE activity_streams (
            activity_id   INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            stream_type   TEXT NOT NULL,
            data          TEXT,
            resolution    TEXT,
            PRIMARY KEY (activity_id, stream_type)
        );

        CREATE TABLE activity_laps (
            id                       INTEGER PRIMARY KEY,
            activity_id              INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            name                     TEXT,
            lap_index                INTEGER,
            distance_m               REAL,
            moving_time_s            INTEGER,
            elapsed_time_s           INTEGER,
            start_index              INTEGER,
            end_index                INTEGER,
            average_speed_ms         REAL,
            max_speed_ms             REAL,
            average_heartrate        REAL,
            max_heartrate            REAL,
            average_watts            REAL,
            average_cadence          REAL,
            total_elevation_gain_m   REAL
        );
        CREATE INDEX idx_activity_laps_activity_id ON activity_laps(activity_id);

        CREATE TABLE activity_zones (
            activity_id   INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            zone_type     TEXT NOT NULL,
            data          TEXT,
            PRIMARY KEY (activity_id, zone_type)
        );

        CREATE TABLE sync_log (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at           TEXT NOT NULL,
            finished_at          TEXT,
            sync_type            TEXT NOT NULL,
            activities_fetched   INTEGER DEFAULT 0,
            status               TEXT NOT NULL,
            error_message        TEXT
        );
    """)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_001_initial_schema,
]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the new schema version."""
    current = get_schema_version(conn)
    target = len(MIGRATIONS)
    for version in range(current, target):
        with conn:  # transaction
            MIGRATIONS[version](conn)
            _set_schema_version(conn, version + 1)
    return target


def get_athlete(conn: sqlite3.Connection, athlete_id: int) -> Athlete | None:
    row = conn.execute(
        "SELECT id, weight_kg, ftp_watts, fc_max, fc_repos, vma_kmh, updated_at "
        "FROM athletes WHERE id = ?",
        (athlete_id,),
    ).fetchone()
    if row is None:
        return None
    updated_at = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
    return Athlete(
        id=row["id"],
        weight_kg=row["weight_kg"],
        ftp_watts=row["ftp_watts"],
        fc_max=row["fc_max"],
        fc_repos=row["fc_repos"],
        vma_kmh=row["vma_kmh"],
        updated_at=updated_at,
    )


def upsert_athlete(conn: sqlite3.Connection, athlete: Athlete) -> None:
    updated_at = athlete.updated_at.isoformat() if athlete.updated_at else None
    with conn:
        conn.execute(
            """
            INSERT INTO athletes (id, weight_kg, ftp_watts, fc_max, fc_repos, vma_kmh, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                weight_kg  = excluded.weight_kg,
                ftp_watts  = excluded.ftp_watts,
                fc_max     = excluded.fc_max,
                fc_repos   = excluded.fc_repos,
                vma_kmh    = excluded.vma_kmh,
                updated_at = excluded.updated_at
            """,
            (
                athlete.id,
                athlete.weight_kg,
                athlete.ftp_watts,
                athlete.fc_max,
                athlete.fc_repos,
                athlete.vma_kmh,
                updated_at,
            ),
        )


def get_last_sync(conn: sqlite3.Connection) -> SyncLog | None:
    row = conn.execute(
        "SELECT id, started_at, finished_at, sync_type, activities_fetched, status, error_message "
        "FROM sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return SyncLog(
        id=row["id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        sync_type=row["sync_type"],
        activities_fetched=row["activities_fetched"],
        status=row["status"],
        error_message=row["error_message"],
    )


def count_activities(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM activities").fetchone()
    return int(row[0])


def stats_by_sport(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT sport_type, COUNT(*) AS n FROM activities GROUP BY sport_type ORDER BY n DESC"
    ).fetchall()
    return {row["sport_type"] or "unknown": int(row["n"]) for row in rows}
