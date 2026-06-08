from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from claude_coach.auth import AuthError
from claude_coach.models import NolioConfig, NolioTokens, PlannedSession
from claude_coach.nolio import (
    NolioClient,
    NolioClientError,
    build_planned_training_payload,
    nolio_sport_id,
    structured_workout_from_items,
)
from claude_coach.nolio_auth import save_tokens
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


# --- sport map --------------------------------------------------------------


def test_nolio_sport_id_known() -> None:
    assert nolio_sport_id("Run") == 2
    assert nolio_sport_id("TrailRun") == 52


def test_nolio_sport_id_unknown_raises() -> None:
    with pytest.raises(ValueError):
        nolio_sport_id("Kitesurf")


# --- structured_workout mapping ---------------------------------------------


def test_structured_workout_mapping_with_repetition_and_pace() -> None:
    items = parse_workout("warmup:15min@h120-140 ; 6x[400m@p3:45;rest:90s] ; cooldown:10min@h120")
    sw = structured_workout_from_items(items)
    assert sw == [
        {
            "type": "step",
            "intensity_type": "warmup",
            "step_duration_type": "duration",
            "step_duration_value": 900,
            "target_type": "heartrate",
            "target_value_min": 120.0,
            "target_value_max": 140.0,
        },
        {
            "type": "repetition",
            "value": 6,
            "steps": [
                {
                    "type": "step",
                    "intensity_type": "active",
                    "step_duration_type": "distance",
                    "step_duration_value": 400,
                    "target_type": "pace",
                    "target_value_min": 4.444,
                    "target_value_max": 4.444,
                },
                {
                    "type": "step",
                    "intensity_type": "rest",
                    "step_duration_type": "duration",
                    "step_duration_value": 90,
                    "target_type": "no_target",
                },
            ],
        },
        {
            "type": "step",
            "intensity_type": "cooldown",
            "step_duration_type": "duration",
            "step_duration_value": 600,
            "target_type": "heartrate",
            "target_value_min": 120.0,
            "target_value_max": 120.0,
        },
    ]


def test_no_target_step_omits_target_values() -> None:
    (step,) = structured_workout_from_items(parse_workout("10min"))
    assert "target_value_min" not in step
    assert "target_value_max" not in step
    assert step["target_type"] == "no_target"


# --- payload builder --------------------------------------------------------


def test_build_payload_minimal_and_idempotent() -> None:
    sw = structured_workout_from_items(parse_workout("30min@h140"))
    payload = build_planned_training_payload(
        _session(), plan_name="Bloc Trail", sport_id=2, structured_workout=sw
    )
    assert payload["id_partner"] == 12  # = id séance → idempotent
    assert payload["sport_id"] == 2
    assert payload["date_start"] == "2026-09-01"
    assert payload["name"] == "Bloc Trail — 2026-09-01"
    assert payload["structured_workout"] == sw
    assert "athlete_id" not in payload  # compte connecté par défaut


def test_build_payload_optional_fields() -> None:
    payload = build_planned_training_payload(
        _session(target_duration_s=3600, target_distance_m=12000.0, description="seuil"),
        plan_name="P",
        sport_id=2,
        structured_workout=None,
        athlete_id=99,
    )
    assert payload["duration"] == 3600
    assert payload["distance"] == 12  # mètres → km
    assert payload["description"] == "seuil"
    assert payload["athlete_id"] == 99
    assert "structured_workout" not in payload


# --- client POST ------------------------------------------------------------


@pytest.fixture
def nolio_config() -> NolioConfig:
    return NolioConfig(
        client_id="cid", client_secret="sec", redirect_uri="http://localhost:8001/callback"
    )


@pytest.fixture
def nolio_tokens_path(tmp_path: Path) -> Path:
    path = tmp_path / "nolio_tokens.json"
    save_tokens(
        path,
        NolioTokens(
            access_token="ACCESS_VALID",
            refresh_token="REFRESH_VALID",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
        ),
    )
    return path


@pytest.fixture
def nolio_client(
    nolio_config: NolioConfig,
    nolio_tokens_path: Path,
    httpserver: HTTPServer,
) -> tuple[NolioClient, list[float]]:
    sleeps: list[float] = []
    client = NolioClient(
        nolio_config,
        nolio_tokens_path,
        base_url=httpserver.url_for(""),
        sleep=sleeps.append,
    )
    return client, sleeps


def test_create_planned_training_sends_bearer_and_body(
    httpserver: HTTPServer, nolio_client: tuple[NolioClient, list[float]]
) -> None:
    client, _ = nolio_client
    httpserver.expect_request(
        "/create/planned/training/",
        method="POST",
        headers={"Authorization": "Bearer ACCESS_VALID"},
    ).respond_with_json({"id": 777})
    result = client.create_planned_training({"id_partner": 12, "sport_id": 2})
    assert result == {"id": 777}


def test_create_planned_training_401_raises_auth(
    httpserver: HTTPServer, nolio_client: tuple[NolioClient, list[float]]
) -> None:
    client, _ = nolio_client
    httpserver.expect_request("/create/planned/training/", method="POST").respond_with_data(
        "unauthorized", status=401
    )
    with pytest.raises(AuthError):
        client.create_planned_training({"id_partner": 12})


def test_create_planned_training_400_raises_client_error(
    httpserver: HTTPServer, nolio_client: tuple[NolioClient, list[float]]
) -> None:
    client, _ = nolio_client
    httpserver.expect_request("/create/planned/training/", method="POST").respond_with_data(
        "training already exists", status=400
    )
    with pytest.raises(NolioClientError):
        client.create_planned_training({"id_partner": 12})


def test_create_planned_training_403_raises_client_error(
    httpserver: HTTPServer, nolio_client: tuple[NolioClient, list[float]]
) -> None:
    client, _ = nolio_client
    httpserver.expect_request("/create/planned/training/", method="POST").respond_with_json(
        {"detail": "API access requires an active coach or premium subscription."}, status=403
    )
    with pytest.raises(NolioClientError, match="coach or premium"):
        client.create_planned_training({"id_partner": 12})


def test_create_planned_training_429_then_success(
    httpserver: HTTPServer, nolio_client: tuple[NolioClient, list[float]]
) -> None:
    client, sleeps = nolio_client
    httpserver.expect_ordered_request("/create/planned/training/", method="POST").respond_with_data(
        "slow down", status=429, headers={"Retry-After": "5"}
    )
    httpserver.expect_ordered_request("/create/planned/training/", method="POST").respond_with_json(
        {"id": 888}
    )
    result = client.create_planned_training({"id_partner": 12})
    assert result == {"id": 888}
    assert sleeps == [5.0]
