from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer

from strava_connect.auth import AuthError, save_tokens
from strava_connect.client import DEFAULT_STREAMS, MAX_ATTEMPTS, StravaClient
from strava_connect.models import Config, Tokens


@pytest.fixture
def valid_tokens(tokens_path: Path) -> Tokens:
    tokens = Tokens(
        access_token="ACCESS_VALID",
        refresh_token="REFRESH_VALID",
        expires_at=datetime.now(tz=UTC) + timedelta(hours=4),  # > 5 min seuil
        athlete_id=42,
    )
    save_tokens(tokens_path, tokens)
    return tokens


@pytest.fixture
def client(
    fake_config: Config,
    tokens_path: Path,
    valid_tokens: Tokens,
    httpserver: HTTPServer,
) -> StravaClient:
    sleeps: list[float] = []
    return StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        sleep=sleeps.append,
    )


def test_list_activities_includes_bearer_and_params(
    httpserver: HTTPServer, client: StravaClient
) -> None:
    httpserver.expect_request(
        "/athlete/activities",
        method="GET",
        headers={"Authorization": "Bearer ACCESS_VALID"},
        query_string="after=1700000000&page=1&per_page=30",
    ).respond_with_json([{"id": 1, "name": "Run"}])

    result = client.list_activities(after_epoch=1_700_000_000)
    assert result == [{"id": 1, "name": "Run"}]


def test_get_activity_returns_detail(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/activities/123").respond_with_json({"id": 123, "sport_type": "Run"})
    result = client.get_activity(123)
    assert result["sport_type"] == "Run"


def test_get_streams_query_string_keys(httpserver: HTTPServer, client: StravaClient) -> None:
    expected_keys = ",".join(DEFAULT_STREAMS)
    httpserver.expect_request(
        "/activities/123/streams",
        query_string=f"keys={expected_keys.replace(',', '%2C')}&key_by_type=true",
    ).respond_with_json({"time": {"data": [0, 1, 2], "resolution": "high"}})
    result = client.get_streams(123)
    assert "time" in result


def test_get_laps_returns_list(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/activities/123/laps").respond_with_json([{"id": 1, "lap_index": 1}])
    laps = client.get_laps(123)
    assert len(laps) == 1


def test_get_zones_returns_list(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/activities/123/zones").respond_with_json(
        [{"type": "heartrate", "distribution_buckets": []}]
    )
    zones = client.get_zones(123)
    assert zones is not None
    assert zones[0]["type"] == "heartrate"


def test_get_zones_returns_none_on_402(httpserver: HTTPServer, client: StravaClient) -> None:
    # Strava renvoie 402 Payment Required pour les comptes non-Summit.
    httpserver.expect_request("/activities/123/zones").respond_with_data("pay up", status=402)
    assert client.get_zones(123) is None


def test_get_zones_returns_none_on_403(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/activities/123/zones").respond_with_data("forbidden", status=403)
    assert client.get_zones(123) is None


def test_get_zones_returns_none_on_404(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/activities/123/zones").respond_with_data("nope", status=404)
    assert client.get_zones(123) is None


def test_401_raises_auth_error(httpserver: HTTPServer, client: StravaClient) -> None:
    httpserver.expect_request("/athlete/activities").respond_with_data("nope", status=401)
    with pytest.raises(AuthError):
        client.list_activities(after_epoch=0)


def test_5xx_retries_then_succeeds(
    fake_config: Config,
    tokens_path: Path,
    valid_tokens: Tokens,
    httpserver: HTTPServer,
) -> None:
    sleeps: list[float] = []
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        sleep=sleeps.append,
    )

    # ordered_responses : 1ère = 503, 2ème = 200 OK
    httpserver.expect_ordered_request("/athlete/activities").respond_with_data("boom", status=503)
    httpserver.expect_ordered_request("/athlete/activities").respond_with_json([{"id": 1}])

    result = client.list_activities(after_epoch=0)
    assert result == [{"id": 1}]
    assert sleeps == [1.0]  # 2**0 entre 1ère et 2ème tentative


def test_5xx_exhausts_retries_then_raises(
    fake_config: Config,
    tokens_path: Path,
    valid_tokens: Tokens,
    httpserver: HTTPServer,
) -> None:
    sleeps: list[float] = []
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        sleep=sleeps.append,
    )
    for _ in range(MAX_ATTEMPTS):
        httpserver.expect_ordered_request("/athlete/activities").respond_with_data(
            "boom", status=500
        )
    with pytest.raises(httpx.HTTPStatusError):
        client.list_activities(after_epoch=0)
    # 2 sleeps entre 3 tentatives : 2**0, 2**1
    assert sleeps == [1.0, 2.0]


def test_429_waits_then_retries(
    fake_config: Config,
    tokens_path: Path,
    valid_tokens: Tokens,
    httpserver: HTTPServer,
) -> None:
    sleeps: list[float] = []
    client = StravaClient(
        fake_config,
        tokens_path,
        base_url=httpserver.url_for(""),
        sleep=sleeps.append,
    )

    httpserver.expect_ordered_request("/athlete/activities").respond_with_data(
        "throttled", status=429, headers={"Retry-After": "7"}
    )
    httpserver.expect_ordered_request("/athlete/activities").respond_with_json([{"id": 9}])

    result = client.list_activities(after_epoch=0)
    assert result == [{"id": 9}]
    assert sleeps == [7.0]


def test_rate_limiter_updated_from_response_headers(
    httpserver: HTTPServer, client: StravaClient
) -> None:
    httpserver.expect_request("/athlete/activities").respond_with_json(
        [],
        headers={
            "X-ReadRateLimit-Usage": "12,50",
            "X-ReadRateLimit-Limit": "100,1000",
        },
    )
    client.list_activities(after_epoch=0)
    assert client.rate_limiter.state.usage_15min == 12
    assert client.rate_limiter.state.usage_daily == 50


def test_close_releases_owned_client(
    fake_config: Config, tokens_path: Path, valid_tokens: Tokens
) -> None:
    client = StravaClient(fake_config, tokens_path)
    client.close()
    # Pas d'assertion forte — on vérifie surtout qu'aucune exception n'est levée.


def test_inject_external_http_client_not_closed(
    fake_config: Config, tokens_path: Path, valid_tokens: Tokens, monkeypatch: MonkeyPatch
) -> None:
    external = httpx.Client()
    closed = {"value": False}
    real_close = external.close

    def _spy_close() -> None:
        closed["value"] = True
        real_close()

    monkeypatch.setattr(external, "close", _spy_close)
    client = StravaClient(fake_config, tokens_path, http_client=external)
    client.close()
    assert closed["value"] is False
    external.close()  # cleanup
