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
    from strava_connect.models import (
        Activity,
        ActivityBucket,
        AthleteMetrics,
        Goal,
        PlannedSession,
        SyncLog,
        TrainingPlan,
    )


def activity_to_dict(a: Activity) -> dict[str, object]:
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


def goal_to_dict(g: Goal) -> dict[str, object]:
    return {
        "id": g.id,
        "name": g.name,
        "discipline": g.discipline,
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "description": g.description,
        "success_criteria": g.success_criteria,
        "status": g.status,
        "created_at": g.created_at.isoformat(),
        "updated_at": g.updated_at.isoformat(),
    }


def training_plan_to_dict(p: TrainingPlan) -> dict[str, object]:
    return {
        "id": p.id,
        "goal_id": p.goal_id,
        "name": p.name,
        "start_date": p.start_date.isoformat(),
        "end_date": p.end_date.isoformat(),
        "status": p.status,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def planned_session_to_dict(s: PlannedSession) -> dict[str, object]:
    return {
        "id": s.id,
        "training_plan_id": s.training_plan_id,
        "planned_date": s.planned_date.isoformat(),
        "sport_type": s.sport_type,
        "session_type": s.session_type,
        "target_duration_s": s.target_duration_s,
        "target_distance_m": s.target_distance_m,
        "target_intensity": s.target_intensity,
        "description": s.description,
        "actual_activity_id": s.actual_activity_id,
        "status": s.status,
        "notes": s.notes,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def athlete_metrics_to_dict(m: AthleteMetrics) -> dict[str, object]:
    return {
        "id": m.id,
        "athlete_id": m.athlete_id,
        "recorded_at": m.recorded_at.isoformat(),
        "weight_kg": m.weight_kg,
        "ftp_watts": m.ftp_watts,
        "fc_max": m.fc_max,
        "fc_repos": m.fc_repos,
        "vma_kmh": m.vma_kmh,
        "note": m.note,
    }


def sync_log_to_dict(log: SyncLog) -> dict[str, object]:
    return {
        "id": log.id,
        "started_at": log.started_at.isoformat(),
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "sync_type": log.sync_type,
        "activities_fetched": log.activities_fetched,
        "status": log.status,
        "error_message": log.error_message,
    }
