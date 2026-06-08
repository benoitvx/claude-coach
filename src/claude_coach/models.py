from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Athlete:
    """Référence athlète (FK des activités). Les métriques d'entraînement sont
    historisées dans `AthleteMetrics`."""

    id: int


@dataclass(frozen=True)
class AthleteMetrics:
    id: int
    athlete_id: int
    recorded_at: datetime
    weight_kg: float | None = None
    ftp_watts: int | None = None
    fc_max: int | None = None
    fc_repos: int | None = None
    vma_kmh: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    athlete_id: int


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    history_days: int = 730


@dataclass(frozen=True)
class NolioConfig:
    """Config OAuth2 Nolio (lot 9). `redirect_uri` doit matcher l'enregistrement
    de l'app côté Nolio — son port pilote le serveur de callback local."""

    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class NolioTokens:
    """Tokens OAuth2 Nolio. Pas d'`athlete_id` (le push vise le compte connecté).
    `refresh_token` est rotatif (usage unique) → toujours persister le dernier."""

    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SyncLog:
    id: int
    started_at: datetime
    finished_at: datetime | None
    sync_type: str
    activities_fetched: int
    status: str
    error_message: str | None


@dataclass(frozen=True)
class Activity:
    id: int
    athlete_id: int
    name: str | None = None
    sport_type: str | None = None
    start_date: str | None = None
    start_date_local: str | None = None
    timezone: str | None = None
    distance_m: float | None = None
    moving_time_s: int | None = None
    elapsed_time_s: int | None = None
    total_elevation_gain_m: float | None = None
    average_speed_ms: float | None = None
    max_speed_ms: float | None = None
    average_heartrate: float | None = None
    max_heartrate: float | None = None
    average_watts: float | None = None
    max_watts: float | None = None
    average_cadence: float | None = None
    calories: float | None = None
    suffer_score: int | None = None
    description: str | None = None
    device_name: str | None = None
    gear_id: str | None = None
    has_heartrate: bool | None = None
    has_power: bool | None = None
    trainer: bool | None = None
    map_polyline: str | None = None
    splits_metric: str | None = None  # JSON
    raw_json: str = ""  # JSON brut DetailedActivity
    synced_at: datetime | None = None


@dataclass(frozen=True)
class ActivityBucket:
    """Agrégat d'activités sur une clé de regroupement (sport, semaine ou mois)."""

    key: str  # "Run" / "2026-W18" / "2026-04"
    count: int
    distance_m: float
    moving_time_s: int
    elevation_gain_m: float


@dataclass(frozen=True)
class Stream:
    activity_id: int
    stream_type: str
    data: str  # JSON-encoded list of values
    resolution: str | None = None


@dataclass(frozen=True)
class Lap:
    id: int
    activity_id: int
    name: str | None = None
    lap_index: int | None = None
    distance_m: float | None = None
    moving_time_s: int | None = None
    elapsed_time_s: int | None = None
    start_index: int | None = None
    end_index: int | None = None
    average_speed_ms: float | None = None
    max_speed_ms: float | None = None
    average_heartrate: float | None = None
    max_heartrate: float | None = None
    average_watts: float | None = None
    average_cadence: float | None = None
    total_elevation_gain_m: float | None = None


@dataclass(frozen=True)
class Zone:
    activity_id: int
    zone_type: str  # heartrate, power, pace
    data: str  # JSON-encoded distribution


@dataclass
class RateLimitState:
    """État courant du rate limiting Strava (mutable, alimenté par les headers)."""

    usage_15min: int = 0
    limit_15min: int = 100
    usage_daily: int = 0
    limit_daily: int = 1000
    last_seen: datetime | None = None


# --- Lot 5a : objectifs et planification -----------------------------------


@dataclass(frozen=True)
class Goal:
    id: int
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    discipline: str | None = None
    target_date: date | None = None
    description: str | None = None
    success_criteria: str | None = None


@dataclass(frozen=True)
class TrainingPlan:
    id: int
    name: str
    start_date: date
    end_date: date
    status: str
    created_at: datetime
    updated_at: datetime
    goal_id: int | None = None
    notes: str | None = None


@dataclass(frozen=True)
class PlannedSession:
    id: int
    training_plan_id: int
    planned_date: date
    sport_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    session_type: str | None = None
    target_duration_s: int | None = None
    target_distance_m: float | None = None
    target_intensity: str | None = None
    description: str | None = None
    actual_activity_id: int | None = None
    notes: str | None = None
    blocks_json: str | None = None


# --- Lot 7 : débriefs de séance (ressenti / RPE / douleurs) -----------------


@dataclass(frozen=True)
class SessionDebrief:
    """Ressenti subjectif d'une séance, saisi par l'athlète (via le coach).

    Liens optionnels vers une activité Strava ET/OU une séance planifiée :
    couvre la séance planifiée+réalisée, l'activité non planifiée (natation
    bonus) et le ressenti sans activité. `debrief_date` est la seule donnée
    obligatoire."""

    id: int
    debrief_date: date
    created_at: datetime
    updated_at: datetime
    activity_id: int | None = None
    planned_session_id: int | None = None
    rpe: int | None = None  # effort perçu 1-10
    feeling: str | None = None  # ressenti général
    pain: str | None = None  # signaux douleur (mollet, genou, ...)
