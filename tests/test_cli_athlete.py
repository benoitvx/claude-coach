from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.auth import save_tokens
from claude_coach.cli import main
from claude_coach.db import connect, get_metrics_history, migrate
from claude_coach.models import Tokens


def _setup_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "strava.db"
    tokens_path = tmp_path / "tokens.json"
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tokens_path))
    save_tokens(
        tokens_path,
        Tokens(
            access_token="A",
            refresh_token="R",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            athlete_id=99,
        ),
    )
    return db_path, tokens_path


def test_set_first_time_creates_entry(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path, _ = _setup_env(monkeypatch, tmp_path)

    result = CliRunner().invoke(
        main,
        ["athlete", "set", "--weight", "75", "--ftp", "260", "--note", "init"],
    )
    assert result.exit_code == 0, result.output
    assert "OK — entrée" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        history = get_metrics_history(conn, 99)
    assert len(history) == 1
    assert history[0].weight_kg == 75.0
    assert history[0].ftp_watts == 260
    assert history[0].note == "init"


def test_set_skips_when_unchanged(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path, _ = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["athlete", "set", "--weight", "75", "--ftp", "260"])
    result = runner.invoke(main, ["athlete", "set", "--weight", "75", "--ftp", "260"])
    assert result.exit_code == 0, result.output
    assert "Aucun changement" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        history = get_metrics_history(conn, 99)
    assert len(history) == 1


def test_set_partial_update_keeps_previous_values(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path, _ = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(
        main,
        ["athlete", "set", "--weight", "70", "--ftp", "250", "--fc-max", "190"],
    )
    result = runner.invoke(main, ["athlete", "set", "--weight", "71"])
    assert result.exit_code == 0, result.output

    with connect(db_path) as conn:
        migrate(conn)
        history = get_metrics_history(conn, 99)
    assert len(history) == 2
    latest = history[0]
    assert latest.weight_kg == 71.0
    assert latest.ftp_watts == 250
    assert latest.fc_max == 190


def test_set_no_value_provided_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["athlete", "set"])
    assert result.exit_code != 0
    assert "Aucune valeur" in result.output


def test_show_displays_latest(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["athlete", "set", "--weight", "75", "--ftp", "260"])

    result = runner.invoke(main, ["athlete", "show"])
    assert result.exit_code == 0, result.output
    assert "poids     : 75.0" in result.output
    assert "FTP       : 260" in result.output


def test_show_message_when_empty(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["athlete", "show"])
    assert result.exit_code == 0
    assert "Aucune métrique" in result.output


def test_history_shows_entries_in_reverse_chrono_order(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["athlete", "set", "--weight", "70"])
    runner.invoke(main, ["athlete", "set", "--weight", "71"])
    runner.invoke(main, ["athlete", "set", "--weight", "72"])

    result = runner.invoke(main, ["athlete", "history"])
    assert result.exit_code == 0
    # 3 lignes attendues, la plus récente (72) en premier après l'entête
    weight_markers = ("72.0", "71.0", "70.0")
    lines = [line for line in result.output.splitlines() if any(m in line for m in weight_markers)]
    assert len(lines) == 3
    assert "72.0" in lines[0]
    assert "70.0" in lines[2]


def test_history_empty(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["athlete", "history"])
    assert result.exit_code == 0
    assert "Aucune métrique" in result.output


def test_athlete_command_without_tokens_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STRAVA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "absent.json"))

    result = CliRunner().invoke(main, ["athlete", "show"])
    assert result.exit_code != 0
    assert "auth" in result.output.lower()


def test_show_json_returns_object_or_null(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()

    # Pas encore de métriques.
    result = runner.invoke(main, ["athlete", "show", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) is None

    runner.invoke(main, ["athlete", "set", "--weight", "75", "--ftp", "260"])
    result = runner.invoke(main, ["athlete", "show", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["weight_kg"] == 75.0
    assert payload["ftp_watts"] == 260
    assert payload["athlete_id"] == 99


def test_history_json_returns_array(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["athlete", "set", "--weight", "70"])
    runner.invoke(main, ["athlete", "set", "--weight", "71"])

    result = runner.invoke(main, ["athlete", "history", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert [m["weight_kg"] for m in payload] == [71.0, 70.0]
