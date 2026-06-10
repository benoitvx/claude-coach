from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from claude_coach.auth import AuthError, ConfigError
from claude_coach.intervals import (
    IntervalsClient,
    IntervalsClientError,
    build_event_payload,
    intervals_sport_type,
    load_intervals_config,
    workout_doc_from_items,
)
from claude_coach.models import IntervalsConfig, PlannedSession
from claude_coach.workout import parse_workout


def _session(**overrides: object) -> PlannedSession:
    base: dict[str, object] = {
        "id": 12,
        "training_plan_id": 3,
        "planned_date": date(2026, 9, 1),
        "sport_type": "Run",
        "status": "planned",
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return PlannedSession(**base)  # type: ignore[arg-type]


# --- config -----------------------------------------------------------------


def test_load_config_env_priority(tmp_path: Path) -> None:
    config = load_intervals_config(
        env={"INTERVALS_API_KEY": "k_env", "INTERVALS_ATHLETE_ID": "i999"},
        path=tmp_path / "absent.json",
    )
    assert config == IntervalsConfig(api_key="k_env", athlete_id="i999")


def test_load_config_from_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"intervals_api_key": "k_file", "intervals_athlete_id": "i123"}),
        encoding="utf-8",
    )
    config = load_intervals_config(env={}, path=path)
    assert config == IntervalsConfig(api_key="k_file", athlete_id="i123")


def test_load_config_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_intervals_config(env={}, path=tmp_path / "absent.json")


# --- sport map --------------------------------------------------------------


def test_intervals_sport_type_known() -> None:
    assert intervals_sport_type("Run") == "Run"
    assert intervals_sport_type("TrailRun") == "Run"
    assert intervals_sport_type("Swim") == "Swim"


def test_intervals_sport_type_unknown_raises() -> None:
    with pytest.raises(ValueError):
        intervals_sport_type("Kitesurf")


# --- mapping blocs → workout_doc structuré ----------------------------------


def test_workout_doc_warmup_rep_cooldown() -> None:
    # FC convertie en %FCmax (Suunto refuse les bpm absolus) avec max_hr=190 :
    # 120→63, 140→74, 130→68 ; allure m/s → secs/km ; répétition → reps/steps.
    items = parse_workout("warmup:15min@h120-140 ; 6x[400m@p3:45;rest:90s] ; cooldown:10min@h130")
    assert workout_doc_from_items(items, max_hr=190) == {
        "steps": [
            {"text": "Warmup", "duration": 900, "hr": {"units": "%hr", "start": 63, "end": 74}},
            {
                "reps": 6,
                "steps": [
                    {"distance": 400, "pace": {"units": "secs/km", "value": 225}},
                    {"text": "Recovery", "duration": 90},
                ],
            },
            {"text": "Cooldown", "duration": 600, "hr": {"units": "%hr", "value": 68}},
        ]
    }


def test_workout_doc_hr_target_without_max_hr_raises() -> None:
    # une cible FC sans FCmax connue → erreur claire (pas de conversion possible).
    with pytest.raises(ValueError, match="FCmax"):
        workout_doc_from_items(parse_workout("30min@h140"), max_hr=None)


def test_workout_doc_pace_range_fast_is_start() -> None:
    # plage d'allure : le plus rapide (secs/km le plus petit) est `start`. Sans FC.
    (step,) = workout_doc_from_items(parse_workout("1km@p4:00-4:30"))["steps"]
    assert step == {"distance": 1000, "pace": {"units": "secs/km", "start": 240, "end": 270}}


def test_workout_doc_no_target_and_power() -> None:
    doc = workout_doc_from_items(parse_workout("5km ; 30s@w200"))
    assert doc["steps"] == [
        {"distance": 5000},
        {"duration": 30, "power": {"units": "w", "value": 200}},
    ]


# --- payload builder --------------------------------------------------------


def test_build_event_payload() -> None:
    workout_doc = workout_doc_from_items(parse_workout("30min@h140"), max_hr=190)
    payload = build_event_payload(
        _session(), plan_name="Bloc Trail", sport_type="TrailRun", workout_doc=workout_doc
    )
    assert payload == {
        "start_date_local": "2026-09-01T00:00:00",
        "category": "WORKOUT",
        "type": "Run",
        "name": "Bloc Trail — 2026-09-01",
        "external_id": "claude-coach-12",
        "workout_doc": {"steps": [{"duration": 1800, "hr": {"units": "%hr", "value": 74}}]},
    }


def test_build_event_payload_includes_description() -> None:
    workout_doc = workout_doc_from_items(parse_workout("30min@h140"), max_hr=190)
    payload = build_event_payload(
        _session(description="Z2 facile"),
        plan_name="P",
        sport_type="Run",
        workout_doc=workout_doc,
        description="Z2 facile",
    )
    assert payload["description"] == "Z2 facile"


# --- client (upsert) --------------------------------------------------------


@pytest.fixture
def intervals_config() -> IntervalsConfig:
    return IntervalsConfig(api_key="KTEST", athlete_id="i123")


@pytest.fixture
def intervals_client(
    intervals_config: IntervalsConfig, httpserver: HTTPServer
) -> tuple[IntervalsClient, list[float]]:
    sleeps: list[float] = []
    client = IntervalsClient(intervals_config, base_url=httpserver.url_for(""), sleep=sleeps.append)
    return client, sleeps


# Payloads SANS external_id → upsert saute le GET de recherche et POST directement.


def test_upsert_sends_basic_auth_and_body(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    expected_auth = "Basic " + base64.b64encode(b"API_KEY:KTEST").decode()
    httpserver.expect_request(
        "/athlete/i123/events",
        method="POST",
        headers={"Authorization": expected_auth},
    ).respond_with_json({"id": 555})
    result = client.upsert_event({"category": "WORKOUT"})
    assert result == {"id": 555}


def test_upsert_401_raises_auth(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    httpserver.expect_request("/athlete/i123/events", method="POST").respond_with_data(
        "unauthorized", status=401
    )
    with pytest.raises(AuthError):
        client.upsert_event({})


def test_upsert_403_raises_auth(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    httpserver.expect_request("/athlete/i123/events", method="POST").respond_with_data(
        "forbidden", status=403
    )
    with pytest.raises(AuthError):
        client.upsert_event({})


def test_upsert_422_raises_client_error(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    httpserver.expect_request("/athlete/i123/events", method="POST").respond_with_data(
        "invalid description", status=422
    )
    with pytest.raises(IntervalsClientError):
        client.upsert_event({})


def test_upsert_429_then_success(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, sleeps = intervals_client
    httpserver.expect_ordered_request("/athlete/i123/events", method="POST").respond_with_data(
        "slow down", status=429, headers={"Retry-After": "5"}
    )
    httpserver.expect_ordered_request("/athlete/i123/events", method="POST").respond_with_json(
        {"id": 666}
    )
    result = client.upsert_event({})
    assert result == {"id": 666}
    assert sleeps == [5.0]


# Idempotence : avec external_id, upsert cherche d'abord (GET) puis POST ou PUT.


def _event_payload() -> dict[str, object]:
    return {
        "start_date_local": "2026-09-01T00:00:00",
        "category": "WORKOUT",
        "external_id": "claude-coach-12",
    }


def test_upsert_posts_when_no_existing_event(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    httpserver.expect_request(
        "/athlete/i123/events",
        method="GET",
        query_string={"oldest": "2026-09-01", "newest": "2026-09-01"},
    ).respond_with_json([])
    httpserver.expect_request("/athlete/i123/events", method="POST").respond_with_json({"id": 1})
    assert client.upsert_event(_event_payload()) == {"id": 1}


def test_upsert_puts_when_external_id_exists(
    httpserver: HTTPServer, intervals_client: tuple[IntervalsClient, list[float]]
) -> None:
    client, _ = intervals_client
    # le GET renvoie un event existant (même external_id) → on doit PUT, pas POST.
    httpserver.expect_request("/athlete/i123/events", method="GET").respond_with_json(
        [{"id": 99, "external_id": "other"}, {"id": 77, "external_id": "claude-coach-12"}]
    )
    httpserver.expect_request("/athlete/i123/events/77", method="PUT").respond_with_json(
        {"id": 77, "updated": True}
    )
    assert client.upsert_event(_event_payload()) == {"id": 77, "updated": True}
