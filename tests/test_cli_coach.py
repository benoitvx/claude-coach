from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from strava_connect.cli import main
from strava_connect.db import (
    connect,
    get_goal,
    get_training_plan,
    list_goals,
    list_planned_sessions,
    migrate,
)


def _setup_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    """Pas de tokens nécessaires pour goal/plan : rien à voir avec l'auth Strava."""
    db_path = tmp_path / "strava.db"
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))
    return db_path


def test_goal_add_creates_entry(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "goal",
            "add",
            "--name",
            "Swim&Run Sept 2026",
            "--target-date",
            "2026-09-15",
            "--discipline",
            "swim_run",
            "--description",
            "13.5km run + 3.5km nage",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK — objectif #1" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        g = get_goal(conn, 1)
    assert g is not None
    assert g.name == "Swim&Run Sept 2026"
    assert g.discipline == "swim_run"
    assert g.target_date is not None
    assert g.target_date.isoformat() == "2026-09-15"


def test_goal_list_shows_all(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "Trail 50k", "--target-date", "2026-10-15"])
    runner.invoke(main, ["goal", "add", "--name", "70.3", "--target-date", "2027-04-15"])

    result = runner.invoke(main, ["goal", "list"])
    assert result.exit_code == 0, result.output
    assert "Trail 50k" in result.output
    assert "70.3" in result.output


def test_goal_show_missing_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["goal", "show", "42"])
    assert result.exit_code != 0
    assert "Aucun objectif" in result.output


def test_goal_complete_updates_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "X"])

    result = runner.invoke(main, ["goal", "complete", "1"])
    assert result.exit_code == 0, result.output

    with connect(db_path) as conn:
        migrate(conn)
        actives = list_goals(conn, status="active")
        completed = list_goals(conn, status="completed")
    assert actives == []
    assert len(completed) == 1


def test_plan_add_with_goal(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "Goal", "--target-date", "2026-09-15"])

    result = runner.invoke(
        main,
        [
            "plan",
            "add",
            "--name",
            "Prépa S&R",
            "--start",
            "2026-06-01",
            "--end",
            "2026-09-15",
            "--goal-id",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK — plan #1" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        p = get_training_plan(conn, 1)
    assert p is not None
    assert p.goal_id == 1
    assert p.name == "Prépa S&R"


def test_plan_add_rejects_unknown_goal(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "plan",
            "add",
            "--name",
            "Orphan",
            "--start",
            "2026-06-01",
            "--end",
            "2026-09-15",
            "--goal-id",
            "999",
        ],
    )
    assert result.exit_code != 0
    assert "Aucun objectif" in result.output


def test_plan_add_rejects_inverted_dates(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        main,
        [
            "plan",
            "add",
            "--name",
            "Bug",
            "--start",
            "2026-09-15",
            "--end",
            "2026-06-01",
        ],
    )
    assert result.exit_code != 0
    assert ">= --start" in result.output


def test_plan_session_add_then_list(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main,
        ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"],
    )

    result = runner.invoke(
        main,
        [
            "plan",
            "session",
            "add",
            "--plan-id",
            "1",
            "--date",
            "2026-06-15",
            "--sport",
            "Run",
            "--session-type",
            "endurance",
            "--duration",
            "3600",
            "--intensity",
            "easy",
            "--description",
            "Footing tranquille",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "séance #1" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        sessions = list_planned_sessions(conn, training_plan_id=1)
    assert len(sessions) == 1
    assert sessions[0].sport_type == "Run"
    assert sessions[0].target_duration_s == 3600

    result_list = runner.invoke(main, ["plan", "session", "list", "--plan-id", "1"])
    assert result_list.exit_code == 0
    assert "Run" in result_list.output


def test_plan_show_displays_sessions(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )
    runner.invoke(
        main,
        [
            "plan",
            "session",
            "add",
            "--plan-id",
            "1",
            "--date",
            "2026-06-15",
            "--sport",
            "Run",
        ],
    )

    result = runner.invoke(main, ["plan", "show", "1"])
    assert result.exit_code == 0, result.output
    assert "Plan #1" in result.output
    assert "1 séances planifiées" in result.output
    assert "Run" in result.output


def test_plan_session_done_updates_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )
    runner.invoke(
        main,
        [
            "plan",
            "session",
            "add",
            "--plan-id",
            "1",
            "--date",
            "2026-06-15",
            "--sport",
            "Run",
        ],
    )

    result = runner.invoke(main, ["plan", "session", "done", "1"])
    assert result.exit_code == 0, result.output

    with connect(db_path) as conn:
        migrate(conn)
        sessions = list_planned_sessions(conn, training_plan_id=1)
    assert sessions[0].status == "done"
