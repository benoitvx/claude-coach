from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from strava_connect.client import StravaClient
from strava_connect.db import (
    connect,
    finish_sync,
    has_complete_activity,
    insert_full_activity,
    migrate,
    start_sync,
    upsert_athlete,
)
from strava_connect.models import Activity, Athlete, Config, Lap, Stream, Zone
from strava_connect.rate_limiter import DailyLimitReached

ProgressFn = Callable[[int, str], None]


# --- Conversions JSON Strava → dataclasses ---------------------------------


def _activity_from_detail(detail: dict[str, Any]) -> Activity:
    athlete = detail.get("athlete") or {}
    map_obj = detail.get("map") or {}
    splits = detail.get("splits_metric")
    has_power = detail.get("device_watts") if "device_watts" in detail else detail.get("has_power")
    return Activity(
        id=int(detail["id"]),
        athlete_id=int(athlete.get("id", 0)),
        name=detail.get("name"),
        sport_type=detail.get("sport_type") or detail.get("type"),
        start_date=detail.get("start_date"),
        start_date_local=detail.get("start_date_local"),
        timezone=detail.get("timezone"),
        distance_m=detail.get("distance"),
        moving_time_s=detail.get("moving_time"),
        elapsed_time_s=detail.get("elapsed_time"),
        total_elevation_gain_m=detail.get("total_elevation_gain"),
        average_speed_ms=detail.get("average_speed"),
        max_speed_ms=detail.get("max_speed"),
        average_heartrate=detail.get("average_heartrate"),
        max_heartrate=detail.get("max_heartrate"),
        average_watts=detail.get("average_watts"),
        max_watts=detail.get("max_watts"),
        average_cadence=detail.get("average_cadence"),
        calories=detail.get("calories"),
        suffer_score=detail.get("suffer_score"),
        description=detail.get("description"),
        device_name=detail.get("device_name"),
        gear_id=detail.get("gear_id"),
        has_heartrate=detail.get("has_heartrate"),
        has_power=has_power,
        trainer=detail.get("trainer"),
        map_polyline=map_obj.get("summary_polyline") or map_obj.get("polyline"),
        splits_metric=json.dumps(splits) if splits is not None else None,
        raw_json=json.dumps(detail),
        synced_at=datetime.now(tz=UTC),
    )


def _streams_from_payload(activity_id: int, payload: dict[str, Any]) -> list[Stream]:
    """Strava `key_by_type=true` retourne dict[type, {data, resolution, ...}]."""
    out: list[Stream] = []
    for stream_type, body in payload.items():
        data = body.get("data") if isinstance(body, dict) else None
        resolution = body.get("resolution") if isinstance(body, dict) else None
        out.append(
            Stream(
                activity_id=activity_id,
                stream_type=stream_type,
                data=json.dumps(data),
                resolution=resolution,
            )
        )
    return out


def _laps_from_payload(activity_id: int, payload: list[dict[str, Any]]) -> list[Lap]:
    out: list[Lap] = []
    for lap in payload:
        out.append(
            Lap(
                id=int(lap["id"]),
                activity_id=activity_id,
                name=lap.get("name"),
                lap_index=lap.get("lap_index"),
                distance_m=lap.get("distance"),
                moving_time_s=lap.get("moving_time"),
                elapsed_time_s=lap.get("elapsed_time"),
                start_index=lap.get("start_index"),
                end_index=lap.get("end_index"),
                average_speed_ms=lap.get("average_speed"),
                max_speed_ms=lap.get("max_speed"),
                average_heartrate=lap.get("average_heartrate"),
                max_heartrate=lap.get("max_heartrate"),
                average_watts=lap.get("average_watts"),
                average_cadence=lap.get("average_cadence"),
                total_elevation_gain_m=lap.get("total_elevation_gain"),
            )
        )
    return out


def _zones_from_payload(activity_id: int, payload: list[dict[str, Any]]) -> list[Zone]:
    out: list[Zone] = []
    for zone in payload:
        zone_type = zone.get("type") or "unknown"
        out.append(
            Zone(
                activity_id=activity_id,
                zone_type=zone_type,
                data=json.dumps(zone),
            )
        )
    return out


# --- sleep inhibitor (macOS only) ------------------------------------------


@contextmanager
def sleep_inhibitor(*, on_warn: Callable[[str], None] | None = None) -> Iterator[None]:
    if sys.platform != "darwin":
        if on_warn:
            on_warn(
                "Pas d'inhibiteur de veille (non-macOS) — garde la machine éveillée "
                "pendant le sync."
            )
        yield
        return

    proc = subprocess.Popen(  # noqa: S603, S607 — caffeinate avec args fixés
        ["caffeinate", "-i", "-w", str(os.getpid())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


LOOKBACK_DAYS_DEFAULT = 7


# --- sync orchestrator ------------------------------------------------------


def sync_full(
    config: Config,
    db_path: Path,
    tokens_path: Path,
    *,
    history_days: int = 730,
    limit: int | None = None,
    on_progress: ProgressFn | None = None,
    on_warn: Callable[[str], None] | None = None,
    client: StravaClient | None = None,
) -> tuple[int, str]:
    """Importe l'historique d'activités sur les `history_days` derniers jours.

    Retourne (activités_importées, status) avec status ∈ {success, partial, error}.
    """
    after_epoch = int((datetime.now(tz=UTC) - timedelta(days=history_days)).timestamp())
    return _execute_sync(
        config=config,
        db_path=db_path,
        tokens_path=tokens_path,
        sync_type="full",
        after_epoch=after_epoch,
        limit=limit,
        on_progress=on_progress,
        on_warn=on_warn,
        client=client,
    )


def sync_incremental(
    config: Config,
    db_path: Path,
    tokens_path: Path,
    *,
    lookback_days: int = LOOKBACK_DAYS_DEFAULT,
    history_days_fallback: int = 730,
    limit: int | None = None,
    on_progress: ProgressFn | None = None,
    on_warn: Callable[[str], None] | None = None,
    client: StravaClient | None = None,
) -> tuple[int, str]:
    """Sync incrémentale : depuis `max(start_date) - lookback_days`.

    Si la DB est vide, bascule automatiquement sur `sync_full` avec
    `history_days_fallback`.
    """
    with closing(connect(db_path)) as conn:
        migrate(conn)
        last_epoch = _max_start_date_epoch(conn)

    if last_epoch is None:
        # DB vide → bascule sur full avec history_days_fallback
        return sync_full(
            config,
            db_path,
            tokens_path,
            history_days=history_days_fallback,
            limit=limit,
            on_progress=on_progress,
            on_warn=on_warn,
            client=client,
        )

    after_epoch = last_epoch - lookback_days * 86_400
    return _execute_sync(
        config=config,
        db_path=db_path,
        tokens_path=tokens_path,
        sync_type="incremental",
        after_epoch=after_epoch,
        limit=limit,
        on_progress=on_progress,
        on_warn=on_warn,
        client=client,
    )


def _execute_sync(
    *,
    config: Config,
    db_path: Path,
    tokens_path: Path,
    sync_type: str,
    after_epoch: int,
    limit: int | None,
    on_progress: ProgressFn | None,
    on_warn: Callable[[str], None] | None,
    client: StravaClient | None,
) -> tuple[int, str]:
    fetched = 0
    status = "success"
    error_message: str | None = None

    own_client = client is None
    client = client or StravaClient(config, tokens_path)

    try:
        with closing(connect(db_path)) as conn:
            migrate(conn)
            sync_id = start_sync(conn, sync_type)
            try:
                with sleep_inhibitor(on_warn=on_warn):
                    fetched, partial_msg = _run_pagination(
                        client=client,
                        conn=conn,
                        after_epoch=after_epoch,
                        limit=limit,
                        on_progress=on_progress,
                    )
                if partial_msg is not None:
                    status = "partial"
                    error_message = partial_msg
            except Exception as exc:
                status = "error"
                error_message = str(exc)
                raise
            finally:
                finish_sync(conn, sync_id, status, fetched, error_message)
    finally:
        if own_client:
            client.close()

    return fetched, status


def _max_start_date_epoch(conn: Any) -> int | None:
    """Retourne l'epoch UTC de l'activité la plus récente, ou None si DB vide."""
    row = conn.execute("SELECT MAX(start_date) FROM activities").fetchone()
    raw = row[0] if row else None
    if not raw:
        return None
    # Strava renvoie 'YYYY-MM-DDTHH:MM:SSZ' ; on remplace Z pour fromisoformat ≤ 3.10.
    return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())


def _run_pagination(
    *,
    client: StravaClient,
    conn: Any,
    after_epoch: int,
    limit: int | None,
    on_progress: ProgressFn | None,
) -> tuple[int, str | None]:
    """Itère sur les activités à importer.

    Retourne (fetched, partial_msg) où `partial_msg` vaut None en cas de succès
    et le message de DailyLimitReached si on a tapé le quota journalier. Le compteur
    reflète les imports réellement committés, même en sortie partielle.
    """
    fetched = 0
    page = 1
    try:
        while True:
            summaries = client.list_activities(after_epoch=after_epoch, page=page)
            if not summaries:
                break
            for summary in summaries:
                activity_id = int(summary["id"])
                if has_complete_activity(conn, activity_id):
                    continue
                if limit is not None and fetched >= limit:
                    return fetched, None
                _import_one_activity(client, conn, activity_id)
                fetched += 1
                if on_progress:
                    on_progress(fetched, str(summary.get("name", "")))
            if limit is not None and fetched >= limit:
                return fetched, None
            page += 1
    except DailyLimitReached as exc:
        return fetched, str(exc)
    return fetched, None


def _import_one_activity(client: StravaClient, conn: Any, activity_id: int) -> None:
    detail = client.get_activity(activity_id)
    streams_payload = client.get_streams(activity_id)
    laps_payload = client.get_laps(activity_id)
    zones_payload = client.get_zones(activity_id) or []

    activity = _activity_from_detail(detail)
    streams = _streams_from_payload(activity_id, streams_payload)
    laps = _laps_from_payload(activity_id, laps_payload)
    zones = _zones_from_payload(activity_id, zones_payload)

    # Garantir que l'athlete existe (FK) avant l'insert.
    if activity.athlete_id:
        upsert_athlete(conn, Athlete(id=activity.athlete_id))

    insert_full_activity(conn, activity, streams, laps, zones)
