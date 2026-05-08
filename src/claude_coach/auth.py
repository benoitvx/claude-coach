from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from claude_coach.models import Config, Tokens

STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
SCOPE = "read,activity:read_all"

CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8000

TOKEN_FILE_DEFAULT = Path("data/tokens.json")
CONFIG_FILE_DEFAULT = Path("data/config.json")


def token_path_from_env() -> Path:
    return Path(os.environ.get("STRAVA_TOKEN_FILE", str(TOKEN_FILE_DEFAULT)))


REFRESH_THRESHOLD = timedelta(minutes=5)
CALLBACK_TIMEOUT = timedelta(minutes=5)
HTTP_TIMEOUT_S = 30.0


class ConfigError(Exception):
    pass


class AuthError(Exception):
    pass


def _redirect_uri(port: int = CALLBACK_PORT) -> str:
    return f"http://{CALLBACK_HOST}:{port}/callback"


def load_config(
    env: dict[str, str] | None = None,
    path: Path = CONFIG_FILE_DEFAULT,
) -> Config:
    """Charge la config Strava. Priorité : env vars > data/config.json."""
    env = env if env is not None else dict(os.environ)
    client_id = env.get("STRAVA_CLIENT_ID")
    client_secret = env.get("STRAVA_CLIENT_SECRET")
    history_days_raw = env.get("STRAVA_HISTORY_DAYS")

    file_data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            file_data = json.load(f)

    client_id = client_id or file_data.get("client_id")
    client_secret = client_secret or file_data.get("client_secret")
    if not client_id or not client_secret:
        raise ConfigError(
            "client_id/client_secret manquants : définir STRAVA_CLIENT_ID et "
            "STRAVA_CLIENT_SECRET, ou créer data/config.json. "
            "Cf. https://www.strava.com/settings/api"
        )

    history_days = int(history_days_raw or file_data.get("history_days") or 730)
    return Config(
        client_id=str(client_id),
        client_secret=str(client_secret),
        history_days=history_days,
    )


def load_tokens(path: Path = TOKEN_FILE_DEFAULT) -> Tokens | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Tokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=datetime.fromisoformat(data["expires_at"]),
        athlete_id=int(data["athlete_id"]),
    )


def save_tokens(path: Path, tokens: Tokens) -> None:
    """Écrit tokens.json de façon atomique avec permissions 0o600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at.astimezone(UTC).isoformat(),
        "athlete_id": tokens.athlete_id,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Permissions restrictives dès la création (un chmod a posteriori est fenêtré par umask).
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


def exchange_code(config: Config, code: str) -> Tokens:
    """Échange un code OAuth contre des tokens."""
    response = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=HTTP_TIMEOUT_S,
    )
    response.raise_for_status()
    body = response.json()
    return Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.fromtimestamp(body["expires_at"], tz=UTC),
        athlete_id=int(body["athlete"]["id"]),
    )


def refresh_tokens(config: Config, current: Tokens) -> Tokens:
    """Rafraîchit les tokens. Le nouveau refresh_token doit être stocké immédiatement."""
    response = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": current.refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=HTTP_TIMEOUT_S,
    )
    response.raise_for_status()
    body = response.json()
    return Tokens(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.fromtimestamp(body["expires_at"], tz=UTC),
        athlete_id=current.athlete_id,
    )


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def get_valid_tokens(config: Config, tokens_path: Path = TOKEN_FILE_DEFAULT) -> Tokens:
    """Retourne des tokens valides, en rafraîchissant si nécessaire.

    Persiste le nouveau refresh_token AVANT de retourner (il est à usage unique côté Strava).
    """
    current = load_tokens(tokens_path)
    if current is None:
        raise AuthError("Aucun token stocké. Lance d'abord `claude-coach auth`.")
    if current.expires_at - _now_utc() > REFRESH_THRESHOLD:
        return current
    fresh = refresh_tokens(config, current)
    save_tokens(tokens_path, fresh)
    return fresh


# --- OAuth interactive flow -------------------------------------------------


@dataclass
class _CallbackResult:
    event: threading.Event = field(default_factory=threading.Event)
    code: str | None = None
    state: str | None = None
    error: str | None = None


def _first(qs: dict[str, list[str]], key: str) -> str | None:
    values = qs.get(key)
    return values[0] if values else None


def _make_callback_handler(result: _CallbackResult) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # silence default access log

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = parse_qs(parsed.query)
            result.code = _first(qs, "code")
            result.state = _first(qs, "state")
            result.error = _first(qs, "error")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if result.error:
                self.wfile.write(
                    b"<h1>Erreur d'authentification</h1>"
                    b"<p>Tu peux fermer cet onglet et relancer la commande.</p>"
                )
            else:
                self.wfile.write(
                    b"<h1>Authentification reussie</h1><p>Tu peux fermer cet onglet.</p>"
                )
            result.event.set()

    return _Handler


def _generate_state() -> str:
    return secrets.token_urlsafe(32)


def _build_authorize_url(config: Config, state: str, redirect_uri: str) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "approval_prompt": "auto",
        "state": state,
    }
    return f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"


def start_oauth_flow(
    config: Config,
    tokens_path: Path = TOKEN_FILE_DEFAULT,
    *,
    open_browser: bool = True,
    callback_port: int = CALLBACK_PORT,
) -> Tokens:
    """Lance le flow OAuth2 complet : autorise, callback, échange code, persiste."""
    state = _generate_state()
    redirect_uri = _redirect_uri(callback_port)
    authorize_url = _build_authorize_url(config, state, redirect_uri)

    result = _CallbackResult()
    server = HTTPServer((CALLBACK_HOST, callback_port), _make_callback_handler(result))
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
        # Laisse au thread une fenêtre courte pour quitter proprement.
        thread.join(timeout=2.0)

    if result.error:
        raise AuthError(f"Strava a refusé l'autorisation : {result.error}")
    if result.state != state:
        raise AuthError("State CSRF mismatch — flow OAuth interrompu.")
    if not result.code:
        raise AuthError("Callback reçu sans code d'autorisation.")

    tokens = exchange_code(config, result.code)
    save_tokens(tokens_path, tokens)
    return tokens


# Petit helper pour les tests intégration : laisser un délai au server pour démarrer.
def _wait_for_callback_server(host: str, port: int, timeout_s: float = 2.0) -> None:
    """Attend que le serveur callback accepte des connexions. Usage tests."""
    import socket

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"Callback server {host}:{port} indisponible après {timeout_s}s")
