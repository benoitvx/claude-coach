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
