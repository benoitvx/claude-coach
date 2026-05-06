from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer

from strava_connect import auth
from strava_connect.auth import (
    AuthError,
    ConfigError,
    exchange_code,
    get_valid_tokens,
    load_config,
    load_tokens,
    refresh_tokens,
    save_tokens,
)
from strava_connect.models import Config, Tokens

# --- save_tokens / load_tokens ---------------------------------------------


def _sample_tokens(expires_at: datetime | None = None) -> Tokens:
    return Tokens(
        access_token="ACCESS_X",
        refresh_token="REFRESH_X",
        expires_at=expires_at or datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
        athlete_id=42,
    )


def test_save_tokens_creates_file_with_0600(tokens_path: Path) -> None:
    save_tokens(tokens_path, _sample_tokens())
    assert tokens_path.exists()
    mode = stat.S_IMODE(os.stat(tokens_path).st_mode)
    assert mode == 0o600


def test_save_tokens_atomic_no_tmp_left(tokens_path: Path) -> None:
    save_tokens(tokens_path, _sample_tokens())
    leftover = list(tokens_path.parent.glob("*.tmp"))
    assert leftover == []


def test_save_tokens_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nest" / "tokens.json"
    save_tokens(nested, _sample_tokens())
    assert nested.exists()


def test_load_tokens_roundtrip(tokens_path: Path) -> None:
    original = _sample_tokens()
    save_tokens(tokens_path, original)
    loaded = load_tokens(tokens_path)
    assert loaded == original


def test_load_tokens_missing_returns_none(tmp_path: Path) -> None:
    assert load_tokens(tmp_path / "absent.json") is None


# --- load_config ------------------------------------------------------------


def test_load_config_from_env(tmp_path: Path) -> None:
    cfg = load_config(
        env={"STRAVA_CLIENT_ID": "111", "STRAVA_CLIENT_SECRET": "222"},
        path=tmp_path / "no.json",
    )
    assert cfg.client_id == "111"
    assert cfg.client_secret == "222"
    assert cfg.history_days == 730


def test_load_config_from_json(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"client_id": "AAA", "client_secret": "BBB"}))
    cfg = load_config(env={}, path=cfg_path)
    assert cfg.client_id == "AAA"
    assert cfg.client_secret == "BBB"


def test_load_config_env_overrides_json(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"client_id": "JSON_ID", "client_secret": "JSON_SEC"}))
    cfg = load_config(
        env={"STRAVA_CLIENT_ID": "ENV_ID", "STRAVA_CLIENT_SECRET": "ENV_SEC"},
        path=cfg_path,
    )
    assert cfg.client_id == "ENV_ID"
    assert cfg.client_secret == "ENV_SEC"


def test_load_config_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(env={}, path=tmp_path / "absent.json")


def test_load_config_history_days_from_env(tmp_path: Path) -> None:
    cfg = load_config(
        env={
            "STRAVA_CLIENT_ID": "1",
            "STRAVA_CLIENT_SECRET": "2",
            "STRAVA_HISTORY_DAYS": "365",
        },
        path=tmp_path / "no.json",
    )
    assert cfg.history_days == 365


# --- exchange_code / refresh_tokens (via pytest-httpserver) -----------------


@pytest.fixture
def patched_token_url(monkeypatch: MonkeyPatch, httpserver: HTTPServer) -> str:
    url = httpserver.url_for("/oauth/token")
    monkeypatch.setattr(auth, "STRAVA_TOKEN_URL", url)
    return url


def test_exchange_code_posts_and_parses(
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
) -> None:
    expires_at = int((datetime.now(tz=UTC) + timedelta(hours=6)).timestamp())
    httpserver.expect_request(
        "/oauth/token",
        method="POST",
        data=(
            f"client_id={fake_config.client_id}"
            f"&client_secret={fake_config.client_secret}"
            "&code=THE_CODE"
            "&grant_type=authorization_code"
        ),
    ).respond_with_json(
        {
            "access_token": "ACCESS",
            "refresh_token": "REFRESH",
            "expires_at": expires_at,
            "athlete": {"id": 42},
        }
    )

    tokens = exchange_code(fake_config, "THE_CODE")
    assert tokens.access_token == "ACCESS"
    assert tokens.refresh_token == "REFRESH"
    assert tokens.athlete_id == 42
    assert tokens.expires_at.tzinfo is UTC


def test_refresh_tokens_keeps_athlete_id(
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
) -> None:
    new_expires = int((datetime.now(tz=UTC) + timedelta(hours=6)).timestamp())
    httpserver.expect_request("/oauth/token", method="POST").respond_with_json(
        {
            "access_token": "ACCESS_NEW",
            "refresh_token": "REFRESH_NEW",
            "expires_at": new_expires,
        }
    )

    current = _sample_tokens()
    fresh = refresh_tokens(fake_config, current)
    assert fresh.access_token == "ACCESS_NEW"
    assert fresh.refresh_token == "REFRESH_NEW"
    assert fresh.athlete_id == current.athlete_id


def test_exchange_code_raises_on_http_error(
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
) -> None:
    httpserver.expect_request("/oauth/token", method="POST").respond_with_data("bad", status=400)
    with pytest.raises(httpx.HTTPStatusError):
        exchange_code(fake_config, "BAD_CODE")


# --- get_valid_tokens -------------------------------------------------------


def test_get_valid_tokens_not_expired_does_not_refresh(
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    # Token expirant dans 1h → pas de refresh
    far_future = datetime.now(tz=UTC) + timedelta(hours=1)
    save_tokens(tokens_path, _sample_tokens(expires_at=far_future))

    # Aucun expect_request → si refresh est appelé, le test échouera côté server.
    tokens = get_valid_tokens(fake_config, tokens_path)
    assert tokens.access_token == "ACCESS_X"


def test_get_valid_tokens_expired_refreshes_and_persists(
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    soon_expired = datetime.now(tz=UTC) + timedelta(minutes=2)  # < 5 min seuil
    save_tokens(tokens_path, _sample_tokens(expires_at=soon_expired))

    new_expires = int((datetime.now(tz=UTC) + timedelta(hours=6)).timestamp())
    httpserver.expect_request("/oauth/token", method="POST").respond_with_json(
        {
            "access_token": "ACCESS_REFRESHED",
            "refresh_token": "REFRESH_REFRESHED",
            "expires_at": new_expires,
        }
    )

    tokens = get_valid_tokens(fake_config, tokens_path)
    assert tokens.access_token == "ACCESS_REFRESHED"
    assert tokens.refresh_token == "REFRESH_REFRESHED"

    # Le nouveau refresh_token doit être persisté AVANT retour.
    on_disk = load_tokens(tokens_path)
    assert on_disk is not None
    assert on_disk.refresh_token == "REFRESH_REFRESHED"


def test_get_valid_tokens_no_tokens_raises(
    fake_config: Config,
    tokens_path: Path,
) -> None:
    with pytest.raises(AuthError):
        get_valid_tokens(fake_config, tokens_path)
