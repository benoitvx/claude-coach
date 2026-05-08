from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.cli import main


def _setup_config(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Pose un environnement minimal pour qu'`auth.load_config` retourne un Config valide."""
    monkeypatch.setenv("STRAVA_CLIENT_ID", "111")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "222")
    monkeypatch.setenv("STRAVA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "tokens.json"))


def test_sync_default_calls_incremental(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_config(monkeypatch, tmp_path)
    calls: dict[str, object] = {}

    def fake_incremental(*args: object, **kwargs: object) -> tuple[int, str]:
        calls["incremental_args"] = args
        calls["incremental_kwargs"] = kwargs
        return (3, "success")

    def fake_full(*args: object, **kwargs: object) -> tuple[int, str]:
        calls["full_called"] = True
        return (0, "success")

    monkeypatch.setattr("claude_coach.cli.sync_incremental", fake_incremental)
    monkeypatch.setattr("claude_coach.cli.sync_full", fake_full)

    result = CliRunner().invoke(main, ["sync"])
    assert result.exit_code == 0, result.output
    assert "3 activités importées" in result.output
    assert "incremental_kwargs" in calls
    assert "full_called" not in calls
    # Lookback par défaut = 7
    assert calls["incremental_kwargs"]["lookback_days"] == 7  # type: ignore[index]


def test_sync_full_flag_calls_full(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_config(monkeypatch, tmp_path)
    called = {"full": False, "incr": False}

    def fake_full(*args: object, **kwargs: object) -> tuple[int, str]:
        called["full"] = True
        return (5, "success")

    def fake_incremental(*args: object, **kwargs: object) -> tuple[int, str]:
        called["incr"] = True
        return (0, "success")

    monkeypatch.setattr("claude_coach.cli.sync_full", fake_full)
    monkeypatch.setattr("claude_coach.cli.sync_incremental", fake_incremental)

    result = CliRunner().invoke(main, ["sync", "--full"])
    assert result.exit_code == 0, result.output
    assert called == {"full": True, "incr": False}
    assert "5 activités importées" in result.output


def test_sync_lookback_days_propagated(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_config(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_incremental(*args: object, **kwargs: object) -> tuple[int, str]:
        captured.update(kwargs)
        return (0, "success")

    monkeypatch.setattr("claude_coach.cli.sync_incremental", fake_incremental)

    result = CliRunner().invoke(main, ["sync", "--lookback-days", "21"])
    assert result.exit_code == 0, result.output
    assert captured["lookback_days"] == 21


def test_sync_partial_status_prints_resume_hint(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_config(monkeypatch, tmp_path)

    def fake_incremental(*args: object, **kwargs: object) -> tuple[int, str]:
        return (12, "partial")

    monkeypatch.setattr("claude_coach.cli.sync_incremental", fake_incremental)

    result = CliRunner().invoke(main, ["sync"])
    assert result.exit_code == 0
    assert "Quota journalier atteint" in result.output


def test_sync_missing_config_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("STRAVA_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("STRAVA_TOKEN_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["sync"])
    assert result.exit_code != 0
    assert "client_id" in result.output


# Garantit que json importé n'est pas marqué unused (utile si on étend les tests).
_ = json
