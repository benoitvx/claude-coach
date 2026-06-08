"""OAuth2 Nolio (lot 9) — calqué sur `auth.py` (Strava), différences clés :

- Auth client par **HTTP Basic** (`client_id:client_secret`) sur `/api/token/`,
  pas dans le corps comme Strava.
- Réponse token avec `expires_in` (secondes), pas `expires_at` (epoch).
- Pas d'`athlete_id` (le push vise le compte connecté).

Le `refresh_token` est rotatif (usage unique) → on persiste le nouveau AVANT de
retourner, exactement comme côté Strava. Le serveur de callback local générique
est réutilisé depuis `auth.py`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from claude_coach.auth import (
    CALLBACK_TIMEOUT,
    HTTP_TIMEOUT_S,
    REFRESH_THRESHOLD,
    AuthError,
    ConfigError,
    _CallbackResult,
    _generate_state,
    _make_callback_handler,
)
from claude_coach.models import NolioConfig, NolioTokens

NOLIO_AUTHORIZE_URL = "https://www.nolio.io/api/authorize/"
NOLIO_TOKEN_URL = "https://www.nolio.io/api/token/"
NOLIO_API_BASE = "https://www.nolio.io/api"

TOKEN_FILE_DEFAULT = Path("data/nolio_tokens.json")
CONFIG_FILE_DEFAULT = Path("data/config.json")
DEFAULT_REDIRECT_URI = "http://localhost:8001/callback"


def nolio_token_path_from_env() -> Path:
    return Path(os.environ.get("NOLIO_TOKEN_FILE", str(TOKEN_FILE_DEFAULT)))


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def load_nolio_config(
    env: dict[str, str] | None = None,
    path: Path = CONFIG_FILE_DEFAULT,
) -> NolioConfig:
    """Charge la config Nolio. Priorité : env vars > data/config.json."""
    env = env if env is not None else dict(os.environ)
    client_id = env.get("NOLIO_CLIENT_ID")
    client_secret = env.get("NOLIO_CLIENT_SECRET")
    redirect_uri = env.get("NOLIO_REDIRECT_URI")

    file_data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            file_data = json.load(f)

    client_id = client_id or file_data.get("nolio_client_id")
    client_secret = client_secret or file_data.get("nolio_client_secret")
    redirect_uri = redirect_uri or file_data.get("nolio_redirect_uri") or DEFAULT_REDIRECT_URI
    if not client_id or not client_secret:
        raise ConfigError(
            "client_id/client_secret Nolio manquants : définir NOLIO_CLIENT_ID et "
            "NOLIO_CLIENT_SECRET (ou les clés nolio_client_id/nolio_client_secret dans "
            "data/config.json). Inscription : https://www.nolio.io/api/"
        )
    return NolioConfig(
        client_id=str(client_id),
        client_secret=str(client_secret),
        redirect_uri=str(redirect_uri),
    )


def load_tokens(path: Path = TOKEN_FILE_DEFAULT) -> NolioTokens | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return NolioTokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=datetime.fromisoformat(data["expires_at"]),
    )


def save_tokens(path: Path, tokens: NolioTokens) -> None:
    """Écrit les tokens Nolio de façon atomique avec permissions 0o600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at.astimezone(UTC).isoformat(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def _tokens_from_body(body: dict[str, Any]) -> NolioTokens:
    """Construit des `NolioTokens` à partir de la réponse `/api/token/`."""
    expires_in = int(body.get("expires_in", 86400))
    return NolioTokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=_now_utc() + timedelta(seconds=expires_in),
    )


def exchange_code(config: NolioConfig, code: str) -> NolioTokens:
    """Échange un code OAuth contre des tokens (client auth = HTTP Basic)."""
    response = httpx.post(
        NOLIO_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
        },
        auth=(config.client_id, config.client_secret),
        timeout=HTTP_TIMEOUT_S,
    )
    response.raise_for_status()
    return _tokens_from_body(response.json())


def refresh_tokens(config: NolioConfig, current: NolioTokens) -> NolioTokens:
    """Rafraîchit les tokens. Le nouveau refresh_token (rotatif) doit être stocké aussitôt."""
    response = httpx.post(
        NOLIO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": current.refresh_token,
        },
        auth=(config.client_id, config.client_secret),
        timeout=HTTP_TIMEOUT_S,
    )
    response.raise_for_status()
    return _tokens_from_body(response.json())


def get_valid_tokens(config: NolioConfig, tokens_path: Path = TOKEN_FILE_DEFAULT) -> NolioTokens:
    """Retourne des tokens valides, en rafraîchissant si nécessaire.

    Persiste le nouveau refresh_token AVANT de retourner (rotatif côté Nolio).
    """
    current = load_tokens(tokens_path)
    if current is None:
        raise AuthError("Aucun token Nolio stocké. Lance d'abord `claude-coach nolio auth`.")
    if current.expires_at - _now_utc() > REFRESH_THRESHOLD:
        return current
    fresh = refresh_tokens(config, current)
    save_tokens(tokens_path, fresh)
    return fresh


def _build_authorize_url(config: NolioConfig, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "state": state,
    }
    return f"{NOLIO_AUTHORIZE_URL}?{urlencode(params)}"


def _callback_bind(redirect_uri: str) -> tuple[str, int]:
    """Extrait (host, port) du redirect_uri pour binder le serveur de callback local."""
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    return host, port


def start_oauth_flow(
    config: NolioConfig,
    tokens_path: Path = TOKEN_FILE_DEFAULT,
    *,
    open_browser: bool = True,
) -> NolioTokens:
    """Lance le flow OAuth2 Nolio complet : autorise, callback, échange code, persiste."""
    state = _generate_state()
    authorize_url = _build_authorize_url(config, state)
    host, port = _callback_bind(config.redirect_uri)

    result = _CallbackResult()
    server = HTTPServer((host, port), _make_callback_handler(result))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if open_browser:
            webbrowser.open(authorize_url)
        else:
            print(f"Ouvre cette URL dans ton navigateur :\n{authorize_url}", file=sys.stderr)
        if not result.event.wait(timeout=CALLBACK_TIMEOUT.total_seconds()):
            raise AuthError(
                f"Timeout : pas de callback reçu après {CALLBACK_TIMEOUT.total_seconds():.0f}s."
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    if result.error:
        raise AuthError(f"Nolio a refusé l'autorisation : {result.error}")
    # State CSRF : on vérifie s'il est renvoyé. Nolio peut ne pas l'échoer ; sur ce flow
    # localhost personnel on tolère son absence plutôt que d'échouer.
    if result.state is not None and result.state != state:
        raise AuthError("State CSRF mismatch — flow OAuth interrompu.")
    if not result.code:
        raise AuthError("Callback reçu sans code d'autorisation.")

    tokens = exchange_code(config, result.code)
    save_tokens(tokens_path, tokens)
    return tokens
