from __future__ import annotations

import socket
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer

from claude_coach import auth
from claude_coach.auth import AuthError, _wait_for_callback_server, start_oauth_flow
from claude_coach.models import Config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = int(s.getsockname()[1])
    return port


@pytest.fixture
def patched_token_url(monkeypatch: MonkeyPatch, httpserver: HTTPServer) -> str:
    url = httpserver.url_for("/oauth/token")
    monkeypatch.setattr(auth, "STRAVA_TOKEN_URL", url)
    return url


def _trigger_callback(port: int, code: str, state: str) -> None:
    _wait_for_callback_server("localhost", port)
    httpx.get(
        f"http://localhost:{port}/callback",
        params={"code": code, "state": state},
        timeout=5.0,
    )


def test_oauth_flow_full_happy_path(
    monkeypatch: MonkeyPatch,
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_generate_state", lambda: "FAKE_STATE")
    port = _free_port()

    new_expires = int((datetime.now(tz=UTC) + timedelta(hours=6)).timestamp())
    httpserver.expect_request("/oauth/token", method="POST").respond_with_json(
        {
            "access_token": "ACCESS_OK",
            "refresh_token": "REFRESH_OK",
            "expires_at": new_expires,
            "athlete": {"id": 99},
        }
    )

    threading.Thread(
        target=_trigger_callback,
        args=(port, "FAKE_CODE", "FAKE_STATE"),
        daemon=True,
    ).start()

    tokens = start_oauth_flow(
        fake_config,
        tokens_path,
        open_browser=False,
        callback_port=port,
    )

    assert tokens.access_token == "ACCESS_OK"
    assert tokens.athlete_id == 99
    assert tokens_path.exists()


def test_oauth_flow_state_mismatch_raises(
    monkeypatch: MonkeyPatch,
    httpserver: HTTPServer,
    patched_token_url: str,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    monkeypatch.setattr(auth, "_generate_state", lambda: "EXPECTED_STATE")
    port = _free_port()

    threading.Thread(
        target=_trigger_callback,
        args=(port, "ANY_CODE", "WRONG_STATE"),
        daemon=True,
    ).start()

    with pytest.raises(AuthError, match="CSRF"):
        start_oauth_flow(
            fake_config,
            tokens_path,
            open_browser=False,
            callback_port=port,
        )
    assert not tokens_path.exists()


def test_oauth_flow_strava_error_raises(
    monkeypatch: MonkeyPatch,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    port = _free_port()

    def _trigger_error_callback() -> None:
        _wait_for_callback_server("localhost", port)
        httpx.get(
            f"http://localhost:{port}/callback",
            params={"error": "access_denied"},
            timeout=5.0,
        )

    threading.Thread(target=_trigger_error_callback, daemon=True).start()

    with pytest.raises(AuthError, match="refusé"):
        start_oauth_flow(
            fake_config,
            tokens_path,
            open_browser=False,
            callback_port=port,
        )


def test_oauth_flow_timeout(
    monkeypatch: MonkeyPatch,
    fake_config: Config,
    tokens_path: Path,
) -> None:
    monkeypatch.setattr(auth, "CALLBACK_TIMEOUT", timedelta(milliseconds=200))
    port = _free_port()

    # Pas de callback déclenché → timeout
    with pytest.raises(AuthError, match="Timeout"):
        start_oauth_flow(
            fake_config,
            tokens_path,
            open_browser=False,
            callback_port=port,
        )
