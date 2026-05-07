from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from strava_connect.models import (
    Activity,
    Athlete,
    AthleteMetrics,
    Goal,
    Lap,
    PlannedSession,
    Stream,
    SyncLog,
    TrainingPlan,
    Zone,
)

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


def _migration_002_athlete_metrics(conn: sqlite3.Connection) -> None:
    """Sépare les métriques (poids/FTP/...) historisées dans `athlete_metrics`.

    `athletes` devient une table de référence (juste l'id, FK des activités).
    """
    conn.executescript("""
        CREATE TABLE athlete_metrics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_id  INTEGER NOT NULL REFERENCES athletes(id),
            recorded_at TEXT NOT NULL,
            weight_kg   REAL,
            ftp_watts   INTEGER,
            fc_max      INTEGER,
            fc_repos    INTEGER,
            vma_kmh     REAL,
            note        TEXT
        );
        CREATE INDEX idx_athlete_metrics_athlete_recorded
            ON athlete_metrics(athlete_id, recorded_at DESC);

        -- Préserve les données existantes (filet de sécurité même si table vide).
        INSERT INTO athlete_metrics
            (athlete_id, recorded_at, weight_kg, ftp_watts, fc_max, fc_repos, vma_kmh)
        SELECT id,
               COALESCE(updated_at, '1970-01-01T00:00:00+00:00'),
               weight_kg, ftp_watts, fc_max, fc_repos, vma_kmh
        FROM athletes
        WHERE weight_kg IS NOT NULL
           OR ftp_watts IS NOT NULL
           OR fc_max IS NOT NULL
           OR fc_repos IS NOT NULL
           OR vma_kmh IS NOT NULL;

        ALTER TABLE athletes DROP COLUMN weight_kg;
        ALTER TABLE athletes DROP COLUMN ftp_watts;
        ALTER TABLE athletes DROP COLUMN fc_max;
        ALTER TABLE athletes DROP COLUMN fc_repos;
        ALTER TABLE athletes DROP COLUMN vma_kmh;
        ALTER TABLE athletes DROP COLUMN updated_at;
    """)


def _migration_003_goals_training_plans(conn: sqlite3.Connection) -> None:
    """Tables d'objectifs sportifs, plans d'entraînement et séances planifiées (Lot 5a)."""
    conn.executescript("""
        CREATE TABLE goals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL,
            discipline        TEXT,
            target_date       TEXT,
            description       TEXT,
            success_criteria  TEXT,
            status            TEXT NOT NULL DEFAULT 'active',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );
        CREATE INDEX idx_goals_target_date ON goals(target_date);

        CREATE TABLE training_plans (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id      INTEGER REFERENCES goals(id) ON DELETE SET NULL,
            name         TEXT NOT NULL,
            start_date   TEXT NOT NULL,
            end_date     TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            notes        TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE INDEX idx_training_plans_goal ON training_plans(goal_id);

        CREATE TABLE planned_sessions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            training_plan_id    INTEGER NOT NULL REFERENCES training_plans(id) ON DELETE CASCADE,
            planned_date        TEXT NOT NULL,
            sport_type          TEXT NOT NULL,
            session_type        TEXT,
            target_duration_s   INTEGER,
            target_distance_m   REAL,
            target_intensity    TEXT,
            description         TEXT,
            actual_activity_id  INTEGER REFERENCES activities(id) ON DELETE SET NULL,
            status              TEXT NOT NULL DEFAULT 'planned',
            notes               TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );
        CREATE INDEX idx_planned_sessions_plan_date
            ON planned_sessions(training_plan_id, planned_date);
        CREATE INDEX idx_planned_sessions_actual_activity
            ON planned_sessions(actual_activity_id);
    """)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_001_initial_schema,
    _migration_002_athlete_metrics,
    _migration_003_goals_training_plans,
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
    row = conn.execute("SELECT id FROM athletes WHERE id = ?", (athlete_id,)).fetchone()
    if row is None:
        return None
    return Athlete(id=row["id"])


def upsert_athlete(conn: sqlite3.Connection, athlete: Athlete) -> None:
    """Insert ou no-op si l'athlete existe déjà. Utilisé pour la FK des activités."""
    with conn:
        conn.execute("INSERT OR IGNORE INTO athletes (id) VALUES (?)", (athlete.id,))


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
    """True si l'activité existe en DB.

    `insert_full_activity` est transactionnel : si la ligne `activities` est présente,
    streams/laps/zones associés ont été insérés dans la même transaction (ou volontairement
    omis pour les activités manuelles sans streams ni les comptes non-Summit pour les zones).
    """
    row = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM activities WHERE id = ?) AS has_act",
        (activity_id,),
    ).fetchone()
    return bool(row["has_act"])


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


# --- Athlete metrics (Lot 4) -----------------------------------------------


def _row_to_metrics(row: sqlite3.Row) -> AthleteMetrics:
    return AthleteMetrics(
        id=row["id"],
        athlete_id=row["athlete_id"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
        weight_kg=row["weight_kg"],
        ftp_watts=row["ftp_watts"],
        fc_max=row["fc_max"],
        fc_repos=row["fc_repos"],
        vma_kmh=row["vma_kmh"],
        note=row["note"],
    )


def get_latest_metrics(conn: sqlite3.Connection, athlete_id: int) -> AthleteMetrics | None:
    row = conn.execute(
        "SELECT id, athlete_id, recorded_at, weight_kg, ftp_watts, fc_max, fc_repos, "
        "vma_kmh, note FROM athlete_metrics WHERE athlete_id = ? "
        "ORDER BY recorded_at DESC, id DESC LIMIT 1",
        (athlete_id,),
    ).fetchone()
    return _row_to_metrics(row) if row else None


def get_metrics_history(
    conn: sqlite3.Connection, athlete_id: int, *, limit: int | None = None
) -> list[AthleteMetrics]:
    sql = (
        "SELECT id, athlete_id, recorded_at, weight_kg, ftp_watts, fc_max, fc_repos, "
        "vma_kmh, note FROM athlete_metrics WHERE athlete_id = ? "
        "ORDER BY recorded_at DESC, id DESC"
    )
    params: tuple[object, ...] = (athlete_id,)
    if limit is not None:
        sql += " LIMIT ?"
        params = (athlete_id, int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_metrics(row) for row in rows]


def insert_athlete_metrics(
    conn: sqlite3.Connection,
    athlete_id: int,
    *,
    weight_kg: float | None = None,
    ftp_watts: int | None = None,
    fc_max: int | None = None,
    fc_repos: int | None = None,
    vma_kmh: float | None = None,
    note: str | None = None,
    recorded_at: datetime | None = None,
) -> AthleteMetrics:
    """Insère une nouvelle ligne `athlete_metrics`.

    Les champs non fournis (None) sont repris de la dernière entrée connue —
    permet un `set --weight 75` qui ne touche pas au FTP.
    """
    previous = get_latest_metrics(conn, athlete_id)

    def _merge(new: object, prev: object) -> object:
        return new if new is not None else prev

    final_weight = _merge(weight_kg, previous.weight_kg if previous else None)
    final_ftp = _merge(ftp_watts, previous.ftp_watts if previous else None)
    final_fc_max = _merge(fc_max, previous.fc_max if previous else None)
    final_fc_repos = _merge(fc_repos, previous.fc_repos if previous else None)
    final_vma = _merge(vma_kmh, previous.vma_kmh if previous else None)

    # Garantit que l'athlete existe (FK).
    upsert_athlete(conn, Athlete(id=athlete_id))

    recorded = (recorded_at or datetime.now(tz=UTC)).isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO athlete_metrics "
            "(athlete_id, recorded_at, weight_kg, ftp_watts, fc_max, fc_repos, vma_kmh, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                athlete_id,
                recorded,
                final_weight,
                final_ftp,
                final_fc_max,
                final_fc_repos,
                final_vma,
                note,
            ),
        )
    inserted = conn.execute(
        "SELECT id, athlete_id, recorded_at, weight_kg, ftp_watts, fc_max, fc_repos, "
        "vma_kmh, note FROM athlete_metrics WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _row_to_metrics(inserted)


def metrics_values_equal(
    a: AthleteMetrics | None,
    *,
    weight_kg: float | None,
    ftp_watts: int | None,
    fc_max: int | None,
    fc_repos: int | None,
    vma_kmh: float | None,
) -> bool:
    """True si toutes les valeurs métriques (poids/FTP/FC/VMA) correspondent à `a`.

    Le champ `note` est exclu — une entrée juste pour annoter doit être permise.
    """
    if a is None:
        return False
    return (
        a.weight_kg == weight_kg
        and a.ftp_watts == ftp_watts
        and a.fc_max == fc_max
        and a.fc_repos == fc_repos
        and a.vma_kmh == vma_kmh
    )


# --- Lot 5a : objectifs / plans / séances planifiées -----------------------

GOAL_STATUSES = ("active", "completed", "abandoned")
PLAN_STATUSES = ("active", "completed", "paused")
SESSION_STATUSES = ("planned", "done", "skipped", "missed")


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _opt_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _row_to_goal(row: sqlite3.Row) -> Goal:
    return Goal(
        id=row["id"],
        name=row["name"],
        discipline=row["discipline"],
        target_date=_opt_date(row["target_date"]),
        description=row["description"],
        success_criteria=row["success_criteria"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_training_plan(row: sqlite3.Row) -> TrainingPlan:
    return TrainingPlan(
        id=row["id"],
        goal_id=row["goal_id"],
        name=row["name"],
        start_date=date.fromisoformat(row["start_date"]),
        end_date=date.fromisoformat(row["end_date"]),
        status=row["status"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_planned_session(row: sqlite3.Row) -> PlannedSession:
    return PlannedSession(
        id=row["id"],
        training_plan_id=row["training_plan_id"],
        planned_date=date.fromisoformat(row["planned_date"]),
        sport_type=row["sport_type"],
        session_type=row["session_type"],
        target_duration_s=row["target_duration_s"],
        target_distance_m=row["target_distance_m"],
        target_intensity=row["target_intensity"],
        description=row["description"],
        actual_activity_id=row["actual_activity_id"],
        status=row["status"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


_GOAL_COLS = (
    "id, name, discipline, target_date, description, success_criteria, "
    "status, created_at, updated_at"
)
_PLAN_COLS = "id, goal_id, name, start_date, end_date, status, notes, created_at, updated_at"
_SESSION_COLS = (
    "id, training_plan_id, planned_date, sport_type, session_type, "
    "target_duration_s, target_distance_m, target_intensity, description, "
    "actual_activity_id, status, notes, created_at, updated_at"
)


def insert_goal(
    conn: sqlite3.Connection,
    *,
    name: str,
    discipline: str | None = None,
    target_date: date | None = None,
    description: str | None = None,
    success_criteria: str | None = None,
    status: str = "active",
) -> Goal:
    now = _now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO goals (name, discipline, target_date, description, "
            "success_criteria, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                discipline,
                target_date.isoformat() if target_date else None,
                description,
                success_criteria,
                status,
                now,
                now,
            ),
        )
    row = conn.execute(f"SELECT {_GOAL_COLS} FROM goals WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_goal(row)


def get_goal(conn: sqlite3.Connection, goal_id: int) -> Goal | None:
    row = conn.execute(f"SELECT {_GOAL_COLS} FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return _row_to_goal(row) if row else None


def list_goals(conn: sqlite3.Connection, *, status: str | None = None) -> list[Goal]:
    sql = f"SELECT {_GOAL_COLS} FROM goals"
    params: tuple[object, ...] = ()
    if status is not None:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY COALESCE(target_date, '9999-99-99') ASC, id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_goal(r) for r in rows]


def update_goal_status(conn: sqlite3.Connection, goal_id: int, status: str) -> Goal:
    if status not in GOAL_STATUSES:
        raise ValueError(f"Statut invalide '{status}', attendu parmi {GOAL_STATUSES}")
    with conn:
        cur = conn.execute(
            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), goal_id),
        )
    if cur.rowcount == 0:
        raise ValueError(f"Aucun objectif #{goal_id}")
    updated = get_goal(conn, goal_id)
    assert updated is not None
    return updated


def insert_training_plan(
    conn: sqlite3.Connection,
    *,
    name: str,
    start_date: date,
    end_date: date,
    goal_id: int | None = None,
    notes: str | None = None,
    status: str = "active",
) -> TrainingPlan:
    now = _now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO training_plans (goal_id, name, start_date, end_date, "
            "status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                goal_id,
                name,
                start_date.isoformat(),
                end_date.isoformat(),
                status,
                notes,
                now,
                now,
            ),
        )
    row = conn.execute(
        f"SELECT {_PLAN_COLS} FROM training_plans WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row_to_training_plan(row)


def get_training_plan(conn: sqlite3.Connection, plan_id: int) -> TrainingPlan | None:
    row = conn.execute(
        f"SELECT {_PLAN_COLS} FROM training_plans WHERE id = ?", (plan_id,)
    ).fetchone()
    return _row_to_training_plan(row) if row else None


def list_training_plans(
    conn: sqlite3.Connection,
    *,
    goal_id: int | None = None,
    status: str | None = None,
) -> list[TrainingPlan]:
    clauses: list[str] = []
    params: list[object] = []
    if goal_id is not None:
        clauses.append("goal_id = ?")
        params.append(goal_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    sql = f"SELECT {_PLAN_COLS} FROM training_plans"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY start_date ASC, id ASC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_training_plan(r) for r in rows]


def update_training_plan_status(
    conn: sqlite3.Connection, plan_id: int, status: str
) -> TrainingPlan:
    if status not in PLAN_STATUSES:
        raise ValueError(f"Statut invalide '{status}', attendu parmi {PLAN_STATUSES}")
    with conn:
        cur = conn.execute(
            "UPDATE training_plans SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), plan_id),
        )
    if cur.rowcount == 0:
        raise ValueError(f"Aucun plan #{plan_id}")
    updated = get_training_plan(conn, plan_id)
    assert updated is not None
    return updated


def insert_planned_session(
    conn: sqlite3.Connection,
    *,
    training_plan_id: int,
    planned_date: date,
    sport_type: str,
    session_type: str | None = None,
    target_duration_s: int | None = None,
    target_distance_m: float | None = None,
    target_intensity: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    status: str = "planned",
) -> PlannedSession:
    now = _now_iso()
    with conn:
        cur = conn.execute(
            "INSERT INTO planned_sessions (training_plan_id, planned_date, sport_type, "
            "session_type, target_duration_s, target_distance_m, target_intensity, "
            "description, status, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                training_plan_id,
                planned_date.isoformat(),
                sport_type,
                session_type,
                target_duration_s,
                target_distance_m,
                target_intensity,
                description,
                status,
                notes,
                now,
                now,
            ),
        )
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM planned_sessions WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row_to_planned_session(row)


def get_planned_session(conn: sqlite3.Connection, session_id: int) -> PlannedSession | None:
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM planned_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_planned_session(row) if row else None


def list_planned_sessions(
    conn: sqlite3.Connection,
    *,
    training_plan_id: int,
    status: str | None = None,
) -> list[PlannedSession]:
    sql = f"SELECT {_SESSION_COLS} FROM planned_sessions WHERE training_plan_id = ?"
    params: tuple[object, ...] = (training_plan_id,)
    if status is not None:
        sql += " AND status = ?"
        params = (training_plan_id, status)
    sql += " ORDER BY planned_date ASC, id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_planned_session(r) for r in rows]


def update_planned_session_status(
    conn: sqlite3.Connection, session_id: int, status: str
) -> PlannedSession:
    if status not in SESSION_STATUSES:
        raise ValueError(f"Statut invalide '{status}', attendu parmi {SESSION_STATUSES}")
    with conn:
        cur = conn.execute(
            "UPDATE planned_sessions SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), session_id),
        )
    if cur.rowcount == 0:
        raise ValueError(f"Aucune séance #{session_id}")
    updated = get_planned_session(conn, session_id)
    assert updated is not None
    return updated
