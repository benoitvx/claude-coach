from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.auth import save_tokens
from claude_coach.cli import main
from claude_coach.db import connect, insert_athlete_metrics, migrate
from claude_coach.models import Tokens


def _seed_db_with_athlete(db_path: Path, athlete_id: int = 99) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        insert_athlete_metrics(
            conn,
            athlete_id,
            weight_kg=72.0,
            ftp_watts=240,
            fc_max=190,
            fc_repos=48,
            vma_kmh=17.0,
        )
    finally:
        conn.close()


def test_status_no_db_no_tokens(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRAVA_DB_PATH", str(tmp_path / "absent.db"))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "absent.json"))

    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0
    assert "fichier absent" in result.output
    assert "absent — lance `claude-coach auth`" in result.output


def test_status_with_tokens_and_db(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "strava.db"
    tokens_path = tmp_path / "tokens.json"
    _seed_db_with_athlete(db_path, athlete_id=99)
    save_tokens(
        tokens_path,
        Tokens(
            access_token="A",
            refresh_token="R",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            athlete_id=99,
        ),
    )
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tokens_path))

    result = CliRunner().invoke(main, ["status"])
    assert result.exit_code == 0
    assert "activités  : 0" in result.output
    assert "dernière sync : jamais" in result.output
    assert "athlete_id : 99" in result.output
    assert "profil athlète : poids=72.0 kg" in result.output


def test_auth_command_missing_config_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    # Pas de data/config.json non plus → ConfigError attendue.
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["auth"])
    assert result.exit_code != 0
    assert "client_id" in result.output


def test_status_json_no_db_no_tokens(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRAVA_DB_PATH", str(tmp_path / "absent.db"))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "absent.json"))

    result = CliRunner().invoke(main, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["db_exists"] is False
    assert payload["activities_count"] is None
    assert payload["tokens"] is None
    assert payload["athlete_metrics"] is None
    assert payload["last_sync"] is None


def test_status_json_with_tokens_and_metrics(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = tmp_path / "strava.db"
    tokens_path = tmp_path / "tokens.json"
    _seed_db_with_athlete(db_path, athlete_id=99)
    save_tokens(
        tokens_path,
        Tokens(
            access_token="A",
            refresh_token="R",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            athlete_id=99,
        ),
    )
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tokens_path))

    result = CliRunner().invoke(main, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["db_exists"] is True
    assert payload["activities_count"] == 0
    assert payload["tokens"]["athlete_id"] == 99
    assert payload["tokens"]["expires_in_seconds"] > 0
    assert "access_token" not in payload["tokens"]  # secret jamais exposé
    assert payload["athlete_metrics"]["weight_kg"] == 72.0
    assert payload["athlete_metrics"]["ftp_watts"] == 240
