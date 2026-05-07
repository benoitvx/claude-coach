from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from strava_connect.models import Activity, Athlete, Lap, Stream, SyncLog, Zone

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


# --- Activités, streams, laps, zones (Lot 2) -------------------------------

_ACTIVITY_COLUMNS = (
    "id, athlete_id, name, sport_type, start_date, start_date_local, timezone, "
    "distance_m, moving_time_s, elapsed_time_s, total_elevation_gain_m, "
    "average_speed_ms, max_speed_ms, average_heartrate, max_heartrate, "
    "average_watts, max_watts, average_cadence, calories, suffer_score, "
    "description, device_name, gear_id, has_heartrate, has_power, trainer, "
    "map_polyline, splits_metric, raw_json, synced_at"
)

_ACTIVITY_PLACEHOLDERS = ", ".join("?" for _ in _ACTIVITY_COLUMNS.split(", "))


def _activity_row(activity: Activity) -> tuple[object, ...]:
    return (
        activity.id,
        activity.athlete_id,
        activity.name,
        activity.sport_type,
        activity.start_date,
        activity.start_date_local,
        activity.timezone,
        activity.distance_m,
        activity.moving_time_s,
        activity.elapsed_time_s,
        activity.total_elevation_gain_m,
        activity.average_speed_ms,
        activity.max_speed_ms,
        activity.average_heartrate,
        activity.max_heartrate,
        activity.average_watts,
        activity.max_watts,
        activity.average_cadence,
        activity.calories,
        activity.suffer_score,
        activity.description,
        activity.device_name,
        activity.gear_id,
        int(activity.has_heartrate) if activity.has_heartrate is not None else None,
        int(activity.has_power) if activity.has_power is not None else None,
        int(activity.trainer) if activity.trainer is not None else None,
        activity.map_polyline,
        activity.splits_metric,
        activity.raw_json,
        activity.synced_at.isoformat() if activity.synced_at else None,
    )


def insert_full_activity(
    conn: sqlite3.Connection,
    activity: Activity,
    streams: list[Stream],
    laps: list[Lap],
    zones: list[Zone],
) -> None:
    """Insère ou remplace une activité et toutes ses dépendances dans une transaction."""
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO activities ({_ACTIVITY_COLUMNS}) "
            f"VALUES ({_ACTIVITY_PLACEHOLDERS})",
            _activity_row(activity),
        )
        # Streams : remplacer entièrement le set existant pour rester idempotent.
        conn.execute("DELETE FROM activity_streams WHERE activity_id = ?", (activity.id,))
        if streams:
            conn.executemany(
                "INSERT INTO activity_streams (activity_id, stream_type, data, resolution) "
                "VALUES (?, ?, ?, ?)",
                [(s.activity_id, s.stream_type, s.data, s.resolution) for s in streams],
            )
        conn.execute("DELETE FROM activity_laps WHERE activity_id = ?", (activity.id,))
        if laps:
            conn.executemany(
                """
                INSERT INTO activity_laps (
                    id, activity_id, name, lap_index, distance_m, moving_time_s,
                    elapsed_time_s, start_index, end_index, average_speed_ms,
                    max_speed_ms, average_heartrate, max_heartrate, average_watts,
                    average_cadence, total_elevation_gain_m
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        lap.id,
                        lap.activity_id,
                        lap.name,
                        lap.lap_index,
                        lap.distance_m,
                        lap.moving_time_s,
                        lap.elapsed_time_s,
                        lap.start_index,
                        lap.end_index,
                        lap.average_speed_ms,
                        lap.max_speed_ms,
                        lap.average_heartrate,
                        lap.max_heartrate,
                        lap.average_watts,
                        lap.average_cadence,
                        lap.total_elevation_gain_m,
                    )
                    for lap in laps
                ],
            )
        conn.execute("DELETE FROM activity_zones WHERE activity_id = ?", (activity.id,))
        if zones:
            conn.executemany(
                "INSERT INTO activity_zones (activity_id, zone_type, data) VALUES (?, ?, ?)",
                [(z.activity_id, z.zone_type, z.data) for z in zones],
            )


def has_complete_activity(conn: sqlite3.Connection, activity_id: int) -> bool:
    """True si l'activité existe ET a au moins 1 stream ET au moins 1 lap.

    Les zones sont optionnelles (Summit-only) → exclues du critère.
    """
    row = conn.execute(
        """
        SELECT
            EXISTS(SELECT 1 FROM activities WHERE id = ?) AS has_act,
            EXISTS(SELECT 1 FROM activity_streams WHERE activity_id = ?) AS has_str,
            EXISTS(SELECT 1 FROM activity_laps WHERE activity_id = ?) AS has_lap
        """,
        (activity_id, activity_id, activity_id),
    ).fetchone()
    return bool(row["has_act"]) and bool(row["has_str"]) and bool(row["has_lap"])


def start_sync(conn: sqlite3.Connection, sync_type: str) -> int:
    """Insère une ligne sync_log avec started_at = now et status='running'. Retourne l'id."""
    started_at = datetime.now(tz=UTC).isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO sync_log (started_at, sync_type, status) VALUES (?, ?, ?)",
            (started_at, sync_type, "running"),
        )
    return int(cur.lastrowid or 0)


def finish_sync(
    conn: sqlite3.Connection,
    sync_id: int,
    status: str,
    activities_fetched: int,
    error_message: str | None = None,
) -> None:
    finished_at = datetime.now(tz=UTC).isoformat()
    with conn:
        conn.execute(
            "UPDATE sync_log SET finished_at = ?, status = ?, activities_fetched = ?, "
            "error_message = ? WHERE id = ?",
            (finished_at, status, activities_fetched, error_message, sync_id),
        )
