from __future__ import annotations

import socket
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer

from claude_coach import nolio_auth
from claude_coach.auth import AuthError, _wait_for_callback_server
from claude_coach.models import NolioConfig, NolioTokens

# base64("cid:sec") — auth client Basic attendu côté token endpoint.
_BASIC = "Basic Y2lkOnNlYw=="
_FIXED_NOW = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def nolio_config() -> NolioConfig:
    return NolioConfig(
        client_id="cid", client_secret="sec", redirect_uri="http://localhost:8001/callback"
    )


@pytest.fixture
def patched_token_url(monkeypatch: MonkeyPatch, httpserver: HTTPServer) -> str:
    url = httpserver.url_for("/api/token/")
    monkeypatch.setattr(nolio_auth, "NOLIO_TOKEN_URL", url)
    return url


def test_exchange_code_basic_auth_and_expires_in(
    monkeypatch: MonkeyPatch,
    httpserver: HTTPServer,
    patched_token_url: str,
    nolio_config: NolioConfig,
) -> None:
    monkeypatch.setattr(nolio_auth, "_now_utc", lambda: _FIXED_NOW)
    httpserver.expect_request(
        "/api/token/", method="POST", headers={"Authorization": _BASIC}
    ).respond_with_json(
        {
            "access_token": "ACCESS_OK",
            "refresh_token": "REFRESH_OK",
            "expires_in": 86400,
            "token_type": "bearer",
        }
    )
    tokens = nolio_auth.exchange_code(nolio_config, "CODE_123")
    assert tokens.access_token == "ACCESS_OK"
    assert tokens.refresh_token == "REFRESH_OK"
    # expires_in (secondes) → expires_at = now + 24h.
    assert tokens.expires_at == _FIXED_NOW + timedelta(seconds=86400)


def test_get_valid_tokens_refreshes_and_persists_new_refresh(
    httpserver: HTTPServer,
    patched_token_url: str,
    nolio_config: NolioConfig,
    tmp_path: Path,
) -> None:
    path = tmp_path / "nolio_tokens.json"
    # Token déjà expiré → refresh forcé.
    nolio_auth.save_tokens(
        path,
        NolioTokens(
            access_token="OLD_ACCESS",
            refresh_token="OLD_REFRESH",
            expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        ),
    )
    httpserver.expect_request("/api/token/", method="POST").respond_with_json(
        {"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH", "expires_in": 86400}
    )
    fresh = nolio_auth.get_valid_tokens(nolio_config, path)
    assert fresh.access_token == "NEW_ACCESS"
    # Le refresh_token rotatif est persisté AVANT retour.
    persisted = nolio_auth.load_tokens(path)
    assert persisted is not None
    assert persisted.refresh_token == "NEW_REFRESH"


def test_get_valid_tokens_without_stored_raises(nolio_config: NolioConfig, tmp_path: Path) -> None:
    with pytest.raises(AuthError):
        nolio_auth.get_valid_tokens(nolio_config, tmp_path / "absent.json")


def test_save_tokens_permissions_0600(tmp_path: Path) -> None:
    path = tmp_path / "nolio_tokens.json"
    nolio_auth.save_tokens(
        path,
        NolioTokens(access_token="A", refresh_token="R", expires_at=datetime.now(tz=UTC)),
    )
    assert (path.stat().st_mode & 0o777) == 0o600


def _trigger_callback(port: int, code: str, state: str) -> None:
    _wait_for_callback_server("localhost", port)
    httpx.get(
        f"http://localhost:{port}/callback",
        params={"code": code, "state": state},
        timeout=5.0,
    )


def test_oauth_flow_happy_path(
    monkeypatch: MonkeyPatch,
    httpserver: HTTPServer,
    patched_token_url: str,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(nolio_auth, "_generate_state", lambda: "FAKE_STATE")
    port = _free_port()
    config = NolioConfig(
        client_id="cid",
        client_secret="sec",
        redirect_uri=f"http://localhost:{port}/callback",
    )
    httpserver.expect_request("/api/token/", method="POST").respond_with_json(
        {"access_token": "ACCESS_OK", "refresh_token": "REFRESH_OK", "expires_in": 86400}
    )
    tokens_path = tmp_path / "nolio_tokens.json"

    threading.Thread(
        target=_trigger_callback, args=(port, "FAKE_CODE", "FAKE_STATE"), daemon=True
    ).start()

    tokens = nolio_auth.start_oauth_flow(config, tokens_path, open_browser=False)
    assert tokens.access_token == "ACCESS_OK"
    assert tokens_path.exists()


def test_oauth_flow_state_mismatch_raises(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(nolio_auth, "_generate_state", lambda: "EXPECTED")
    port = _free_port()
    config = NolioConfig(
        client_id="cid",
        client_secret="sec",
        redirect_uri=f"http://localhost:{port}/callback",
    )
    tokens_path = tmp_path / "nolio_tokens.json"

    threading.Thread(
        target=_trigger_callback, args=(port, "ANY_CODE", "WRONG_STATE"), daemon=True
    ).start()

    with pytest.raises(AuthError, match="CSRF"):
        nolio_auth.start_oauth_flow(config, tokens_path, open_browser=False)
    assert not tokens_path.exists()
