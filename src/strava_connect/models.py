from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Athlete:
    id: int
    weight_kg: float | None = None
    ftp_watts: int | None = None
    fc_max: int | None = None
    fc_repos: int | None = None
    vma_kmh: float | None = None
    updated_at: datetime | None = None


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
