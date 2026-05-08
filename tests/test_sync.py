from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from claude_coach.auth import save_tokens
from claude_coach.client import StravaClient
from claude_coach.db import connect, count_activities, get_last_sync, has_complete_activity
from claude_coach.models import Config, RateLimitState, Tokens
from claude_coach.rate_limiter import DailyLimitReached, RateLimiter
from claude_coach.sync import LOOKBACK_DAYS_DEFAULT, sync_full, sync_incremental


@pytest.fixture(autouse=True)
def _store_valid_tokens(tokens_path: Path) -> None:
    save_tokens(
        tokens_path,
        Tokens(
            access_token="ACCESS",
            refresh_token="REFRESH",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            athlete_id=42,
        ),
    )


# --- builders de fixtures JSON ---------------------------------------------


def _summary(activity_id: int, name: str = "Test") -> dict[str, Any]:
    return {"id": activity_id, "name": name}


def _detail(
    activity_id: int,
    *,
    sport_type: str = "Run",
    distance: float = 10000.0,
    name: str = "Test",
) -> dict[str, Any]:
    return {
        "id": activity_id,
        "athlete": {"id": 42},
        "name": name,
        "sport_type": sport_type,
        "type": sport_type,
        "start_date": "2026-04-01T08:00:00Z",
        "start_date_local": "2026-04-01T10:00:00Z",
        "timezone": "(GMT+02:00) Europe/Paris",
        "distance": distance,
        "moving_time": 3600,
        "elapsed_time": 3700,
        "total_elevation_gain": 120.0,
        "average_speed": 2.78,
        "max_speed": 4.5,
        "average_heartrate": 150.0,
        "max_heartrate": 175.0,
        "has_heartrate": True,
        "trainer": False,
        "device_watts": False,
        "map": {"summary_polyline": "abc123"},
    }


def _streams_payload() -> dict[str, Any]:
    return {
        "time": {"data": [0, 1, 2], "resolution": "high", "series_type": "distance"},
        "heartrate": {"data": [120, 130, 140], "resolution": "high"},
    }


def _laps_payload(activity_id: int) -> list[dict[str, Any]]:
    return [
        {
            "id": activity_id * 100 + 1,
            "lap_index": 1,
            "name": "Lap 1",
            "distance": 1000.0,
            "moving_time": 360,
            "elapsed_time": 360,
            "start_index": 0,
            "end_index": 100,
            "average_speed": 2.78,
            "max_speed": 3.0,
            "average_heartrate": 150,
        }
    ]


def _zones_payload() -> list[dict[str, Any]]:
    return [{"type": "heartrate", "score": 50, "distribution_buckets": []}]


def _setup_strava_routes(
    httpserver: HTTPServer,
    activities: list[tuple[int, str]],
    *,
    streams_status: int = 200,
    zones_status: int = 200,
    register_pagination: bool = True,
) -> None:
    if register_pagination:
        # Handler dynamique : page=1 → summaries, page≥2 → [] (fin pagination).
        summaries_payload = [_summary(aid, name) for aid, name in activities]

        def _athlete_activities(request: Request) -> Response:
            page = int(request.args.get("page", "1"))
            data = summaries_payload if page == 1 else []
            return Response(json.dumps(data), status=200, content_type="application/json")

        httpserver.expect_request("/athlete/activities").respond_with_handler(_athlete_activities)
    for aid, name in activities:
        sport = "Ride" if "ride" in name.lower() else "Swim" if "swim" in name.lower() else "Run"
        httpserver.expect_request(f"/activities/{aid}").respond_with_json(
            _detail(aid, sport_type=sport, name=name)
        )
        if streams_status == 200:
            httpserver.expect_request(f"/activities/{aid}/streams").respond_with_json(
                _streams_payload()
            )
        else:
            httpserver.expect_request(f"/activities/{aid}/streams").respond_with_data(
                "boom", status=streams_status
            )
        httpserver.expect_request(f"/activities/{aid}/laps").respond_with_json(_laps_payload(aid))
        if zones_status == 200:
            httpserver.expect_request(f"/activities/{aid}/zones").respond_with_json(
                _zones_payload()
            )
        else:
            httpserver.expect_request(f"/activities/{aid}/zones").respond_with_data(
                "no summit", status=zones_status
            )


def _make_client(fake_config: Config, tokens_path: Path, httpserver: HTTPServer) -> StravaClient:
    return StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        sleep=lambda _s: None,
    )


# --- tests -----------------------------------------------------------------


def test_sync_full_happy_path_multi_sport(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    activities = [(1001, "Morning Run"), (1002, "Evening Ride"), (1003, "Pool Swim")]
    _setup_strava_routes(httpserver, activities)

    client = _make_client(fake_config, tokens_path, httpserver)
    fetched, status = sync_full(
        fake_config,
        db_path,
        tokens_path,
        history_days=730,
        client=client,
    )

    assert fetched == 3
    assert status == "success"
    with connect(db_path) as conn:
        assert count_activities(conn) == 3
        for aid, _ in activities:
            assert has_complete_activity(conn, aid) is True
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.status == "success"
        assert sync_log.activities_fetched == 3


def test_sync_full_skips_existing_activities(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    activities = [(2001, "A"), (2002, "B")]
    _setup_strava_routes(httpserver, activities)
    client = _make_client(fake_config, tokens_path, httpserver)
    sync_full(fake_config, db_path, tokens_path, client=client, limit=1)

    # 2e run : la même pagination handler (permanente) reste valide.
    httpserver.clear_log()
    client2 = _make_client(fake_config, tokens_path, httpserver)
    fetched, status = sync_full(fake_config, db_path, tokens_path, client=client2)

    assert fetched == 1
    assert status == "success"
    paths_called = [req.path for req, _ in httpserver.log]
    assert "/activities/2001" not in paths_called
    assert "/activities/2002" in paths_called


def test_sync_full_respects_limit(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    activities = [(3000 + i, f"Act {i}") for i in range(5)]
    _setup_strava_routes(httpserver, activities)

    client = _make_client(fake_config, tokens_path, httpserver)
    fetched, status = sync_full(fake_config, db_path, tokens_path, limit=2, client=client)
    assert fetched == 2
    assert status == "success"
    with connect(db_path) as conn:
        assert count_activities(conn) == 2


def test_sync_full_handles_zones_403(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    _setup_strava_routes(httpserver, [(4001, "No Summit")], zones_status=403)

    client = _make_client(fake_config, tokens_path, httpserver)
    fetched, status = sync_full(fake_config, db_path, tokens_path, client=client)
    assert fetched == 1
    assert status == "success"
    with connect(db_path) as conn:
        # Activité importée sans zones — toujours considérée complète.
        assert has_complete_activity(conn, 4001) is True
        zones_count = conn.execute(
            "SELECT COUNT(*) FROM activity_zones WHERE activity_id = 4001"
        ).fetchone()[0]
        assert zones_count == 0


def test_sync_full_handles_streams_404(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    # Activité manuelle (ex. Étirements) : Strava renvoie 404 sur /streams.
    _setup_strava_routes(httpserver, [(4101, "Étirements")], streams_status=404)

    client = _make_client(fake_config, tokens_path, httpserver)
    fetched, status = sync_full(fake_config, db_path, tokens_path, client=client)
    assert fetched == 1
    assert status == "success"
    with connect(db_path) as conn:
        # Activité importée sans streams — toujours considérée complète (existence suffit).
        assert has_complete_activity(conn, 4101) is True
        streams_count = conn.execute(
            "SELECT COUNT(*) FROM activity_streams WHERE activity_id = 4101"
        ).fetchone()[0]
        assert streams_count == 0


def test_sync_full_daily_limit_partial(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    # Pré-charge un état rate limiter au-dessus du seuil journalier
    rl = RateLimiter(
        RateLimitState(usage_15min=10, limit_15min=100, usage_daily=999, limit_daily=1000)
    )
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        rate_limiter=rl,
        sleep=lambda _s: None,
    )

    fetched, status = sync_full(fake_config, db_path, tokens_path, client=client)
    assert status == "partial"
    assert fetched == 0
    with connect(db_path) as conn:
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.status == "partial"
        assert sync_log.error_message is not None
        assert "journalier" in sync_log.error_message.lower()


def test_sync_full_partial_preserves_count_after_some_imports(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    """La limite quotidienne tombe en cours d'import : fetched doit refléter les imports
    déjà committés (pas 0 comme dans la version buggy de _run_pagination)."""

    activities = [(6001, "A"), (6002, "B"), (6003, "C")]
    _setup_strava_routes(httpserver, activities)

    # Rate limiter qui laisse passer 2 activités (8 requêtes : 1 list + ~4/activité), puis trip.
    class _TripAfter(RateLimiter):
        def __init__(self, trip_after: int) -> None:
            super().__init__()
            self._calls = 0
            self._trip_after = trip_after

        def before_request(self, *, sleep: Any = None, now: Any = None) -> None:  # noqa: ARG002
            if self._calls >= self._trip_after:
                raise DailyLimitReached("Quota journalier Strava atteint (test).")
            self._calls += 1

    # 1 list_activities + 2 × 4 (detail/streams/laps/zones) = 9 requêtes pour 2 imports.
    rl = _TripAfter(trip_after=9)
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        rate_limiter=rl,
        sleep=lambda _s: None,
    )

    fetched, status = sync_full(fake_config, db_path, tokens_path, client=client)
    assert status == "partial"
    assert fetched == 2
    with connect(db_path) as conn:
        assert count_activities(conn) == 2
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.status == "partial"
        assert sync_log.activities_fetched == 2


def test_sync_full_progress_callback(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    _setup_strava_routes(httpserver, [(5001, "First"), (5002, "Second")])

    client = _make_client(fake_config, tokens_path, httpserver)
    progress_calls: list[tuple[int, str]] = []
    sync_full(
        fake_config,
        db_path,
        tokens_path,
        client=client,
        on_progress=lambda n, name: progress_calls.append((n, name)),
    )
    assert progress_calls == [(1, "First"), (2, "Second")]


def test_sync_full_unexpected_error_logs_and_reraises(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/athlete/activities").respond_with_data("fatal", status=500)

    client = _make_client(fake_config, tokens_path, httpserver)
    with pytest.raises(Exception):  # noqa: B017,PT011 — vérification status="error" plus loin
        sync_full(fake_config, db_path, tokens_path, client=client)

    with connect(db_path) as conn:
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.status == "error"


# --- Lot 3 : sync_incremental ----------------------------------------------


def _seed_activity_with_date(
    db_path: Path, activity_id: int, start_date: str, name: str = "Seed"
) -> None:
    """Insère une activité complète directement en DB pour simuler un état post-import."""
    from claude_coach.db import insert_full_activity, migrate, upsert_athlete
    from claude_coach.models import Activity, Athlete, Lap, Stream

    with connect(db_path) as conn:
        migrate(conn)
        upsert_athlete(conn, Athlete(id=42))
        insert_full_activity(
            conn,
            Activity(
                id=activity_id,
                athlete_id=42,
                name=name,
                sport_type="Run",
                start_date=start_date,
                distance_m=10000.0,
                raw_json="{}",
            ),
            [Stream(activity_id=activity_id, stream_type="time", data="[0,1]", resolution="high")],
            [Lap(id=activity_id * 10 + 1, activity_id=activity_id, lap_index=1)],
            [],
        )


def test_sync_incremental_db_vide_fallback_full(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    # DB vide → bascule sur full, avec history_days_fallback explicite.
    _setup_strava_routes(httpserver, [(7001, "New")])
    client = _make_client(fake_config, tokens_path, httpserver)

    fetched, status = sync_incremental(
        fake_config, db_path, tokens_path, history_days_fallback=730, client=client
    )

    assert fetched == 1
    assert status == "success"
    with connect(db_path) as conn:
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        # Fallback → sync_type = "full"
        assert sync_log.sync_type == "full"


def test_sync_incremental_only_fetches_new_activities(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    # Pré-populer une activité ancienne, déjà complète.
    _seed_activity_with_date(db_path, 8001, "2026-04-01T08:00:00Z", "Old Run")

    # Strava retourne l'ancienne (qui sera skip) + une nouvelle.
    _setup_strava_routes(
        httpserver,
        [(8001, "Old Run"), (8002, "New Run")],
    )
    client = _make_client(fake_config, tokens_path, httpserver)

    fetched, status = sync_incremental(fake_config, db_path, tokens_path, client=client)

    assert fetched == 1
    assert status == "success"
    paths_called = [req.path for req, _ in httpserver.log]
    # L'activité ancienne ne doit PAS avoir été re-fetched.
    assert "/activities/8001" not in paths_called
    assert "/activities/8002" in paths_called


def test_sync_incremental_lookback_filter(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    """Vérifie que `after_epoch` envoyé à Strava = max(start_date) - lookback_days."""
    last_iso = "2026-05-01T12:00:00Z"
    _seed_activity_with_date(db_path, 9001, last_iso)
    expected_after = int(
        (datetime.fromisoformat(last_iso.replace("Z", "+00:00")) - timedelta(days=3)).timestamp()
    )

    captured: dict[str, str] = {}

    def _capture(request: Request) -> Response:
        captured["after"] = request.args.get("after", "")
        return Response("[]", status=200, content_type="application/json")

    httpserver.expect_request("/athlete/activities").respond_with_handler(_capture)
    client = _make_client(fake_config, tokens_path, httpserver)

    sync_incremental(fake_config, db_path, tokens_path, lookback_days=3, client=client)
    assert captured["after"] == str(expected_after)


def test_sync_incremental_log_type_incremental(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    _seed_activity_with_date(db_path, 9501, "2026-04-15T08:00:00Z")
    _setup_strava_routes(httpserver, [(9501, "Already there")])
    client = _make_client(fake_config, tokens_path, httpserver)

    sync_incremental(fake_config, db_path, tokens_path, client=client)
    with connect(db_path) as conn:
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.sync_type == "incremental"


def test_sync_incremental_daily_limit_partial(
    fake_config: Config,
    tokens_path: Path,
    db_path: Path,
    httpserver: HTTPServer,
) -> None:
    _seed_activity_with_date(db_path, 9601, "2026-04-15T08:00:00Z")
    rl = RateLimiter(
        RateLimitState(usage_15min=10, limit_15min=100, usage_daily=999, limit_daily=1000)
    )
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        rate_limiter=rl,
        sleep=lambda _s: None,
    )

    fetched, status = sync_incremental(fake_config, db_path, tokens_path, client=client)
    assert status == "partial"
    assert fetched == 0
    with connect(db_path) as conn:
        sync_log = get_last_sync(conn)
        assert sync_log is not None
        assert sync_log.status == "partial"
        assert sync_log.sync_type == "incremental"


def test_sync_incremental_default_lookback_is_7_days() -> None:
    assert LOOKBACK_DAYS_DEFAULT == 7
