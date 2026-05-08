"""Sérialiseurs JSON-friendly pour les modèles (sortie CLI --json).

Conventions :
- snake_case pour les clés (cohérent avec la DB).
- Datetimes en ISO 8601, dates en YYYY-MM-DD.
- Champs absents : ``null`` (jamais omis), pour que l'agent puisse compter dessus.
- Ne pas inclure ``raw_json``, ``map_polyline``, ``splits_metric`` côté Activity :
  bruit pour l'agent et redondance avec les autres champs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strava_connect.models import Activity, ActivityBucket


def activity_to_dict(a: Activity) -> dict[str, object | None]:
    return {
        "id": a.id,
        "athlete_id": a.athlete_id,
        "name": a.name,
        "sport_type": a.sport_type,
        "start_date": a.start_date,
        "start_date_local": a.start_date_local,
        "timezone": a.timezone,
        "distance_m": a.distance_m,
        "moving_time_s": a.moving_time_s,
        "elapsed_time_s": a.elapsed_time_s,
        "total_elevation_gain_m": a.total_elevation_gain_m,
        "average_speed_ms": a.average_speed_ms,
        "max_speed_ms": a.max_speed_ms,
        "average_heartrate": a.average_heartrate,
        "max_heartrate": a.max_heartrate,
        "average_watts": a.average_watts,
        "max_watts": a.max_watts,
        "average_cadence": a.average_cadence,
        "calories": a.calories,
        "suffer_score": a.suffer_score,
        "description": a.description,
        "device_name": a.device_name,
        "gear_id": a.gear_id,
        "has_heartrate": a.has_heartrate,
        "has_power": a.has_power,
        "trainer": a.trainer,
        "synced_at": a.synced_at.isoformat() if a.synced_at else None,
    }


def bucket_to_dict(b: ActivityBucket) -> dict[str, object]:
    return {
        "key": b.key,
        "count": b.count,
        "distance_m": b.distance_m,
        "moving_time_s": b.moving_time_s,
        "elevation_gain_m": b.elevation_gain_m,
    }
