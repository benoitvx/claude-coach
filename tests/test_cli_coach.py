from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.cli import main
from claude_coach.db import (
    connect,
    get_goal,
    get_planned_session,
    get_training_plan,
    insert_full_activity,
    list_goals,
    list_planned_sessions,
    migrate,
    upsert_athlete,
)
from claude_coach.models import Activity, Athlete


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


def test_goal_abandon_updates_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "X"])

    result = runner.invoke(main, ["goal", "abandon", "1"])
    assert result.exit_code == 0, result.output
    assert "abandoned" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        abandoned = list_goals(conn, status="abandoned")
    assert len(abandoned) == 1
    assert abandoned[0].name == "X"


def test_goal_abandon_unknown_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["goal", "abandon", "999"])
    assert result.exit_code != 0
    assert "Aucun objectif" in result.output


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


def test_plan_complete_and_pause(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )
    runner.invoke(
        main, ["plan", "add", "--name", "Q", "--start", "2026-10-01", "--end", "2026-12-15"]
    )

    result_pause = runner.invoke(main, ["plan", "pause", "1"])
    assert result_pause.exit_code == 0, result_pause.output
    assert "paused" in result_pause.output

    result_done = runner.invoke(main, ["plan", "complete", "2"])
    assert result_done.exit_code == 0, result_done.output
    assert "completed" in result_done.output

    with connect(db_path) as conn:
        migrate(conn)
        p1 = get_training_plan(conn, 1)
        p2 = get_training_plan(conn, 2)
    assert p1 is not None and p1.status == "paused"
    assert p2 is not None and p2.status == "completed"


def test_plan_complete_unknown_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["plan", "complete", "999"])
    assert result.exit_code != 0
    assert "Aucun plan" in result.output


def test_plan_abandon_updates_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )

    result = runner.invoke(main, ["plan", "abandon", "1"])
    assert result.exit_code == 0, result.output
    assert "abandoned" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        p = get_training_plan(conn, 1)
    assert p is not None and p.status == "abandoned"


def test_plan_abandon_unknown_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["plan", "abandon", "999"])
    assert result.exit_code != 0
    assert "Aucun plan" in result.output


def test_plan_session_skip_updates_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )
    runner.invoke(
        main,
        ["plan", "session", "add", "--plan-id", "1", "--date", "2026-06-15", "--sport", "Run"],
    )

    result = CliRunner().invoke(main, ["plan", "session", "skip", "1"])
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        s = get_planned_session(conn, 1)
    assert s is not None
    assert s.status == "skipped"


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


# --- Lot 5b : plan match -----------------------------------------------------


def _seed_plan_with_session_and_activity(
    db_path: Path,
    *,
    plan_name: str = "P",
    session_date: str = "2026-06-15",
    activity_date_local: str = "2026-06-15T08:00:00",
    sport: str = "Run",
    activity_id: int = 5001,
    moving_time_s: int = 3500,
    distance_m: float = 10500.0,
) -> None:
    """Crée plan + 1 séance + 1 activité matchable. Sert plusieurs tests CLI."""
    runner = CliRunner()
    runner.invoke(
        main,
        ["plan", "add", "--name", plan_name, "--start", "2026-06-01", "--end", "2026-09-15"],
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
            session_date,
            "--sport",
            sport,
            "--duration",
            "3600",
            "--distance",
            "10000",
        ],
    )
    with connect(db_path) as conn:
        migrate(conn)
        upsert_athlete(conn, Athlete(id=42))
        insert_full_activity(
            conn,
            Activity(
                id=activity_id,
                athlete_id=42,
                sport_type=sport,
                start_date_local=activity_date_local,
                moving_time_s=moving_time_s,
                distance_m=distance_m,
                average_heartrate=152.0,
                raw_json="{}",
            ),
            [],
            [],
            [],
        )


def test_plan_match_no_sessions(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["plan", "match"])
    assert result.exit_code == 0, result.output
    assert "Aucune séance" in result.output


def test_plan_match_writes_link_and_status(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    _seed_plan_with_session_and_activity(db_path)

    result = CliRunner().invoke(main, ["plan", "match"])
    assert result.exit_code == 0, result.output
    assert "1 séance(s) appariée(s)" in result.output
    assert "activity 5001" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        s = get_planned_session(conn, 1)
    assert s is not None
    assert s.actual_activity_id == 5001
    assert s.status == "done"


def test_plan_match_dry_run_shows_but_does_not_persist(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    _seed_plan_with_session_and_activity(db_path)

    result = CliRunner().invoke(main, ["plan", "match", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
    assert "1 séance(s) appariée(s)" in result.output

    with connect(db_path) as conn:
        migrate(conn)
        s = get_planned_session(conn, 1)
    assert s is not None
    assert s.actual_activity_id is None
    assert s.status == "planned"


def test_plan_match_unknown_plan_id_errors(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    result = CliRunner().invoke(main, ["plan", "match", "--plan-id", "999"])
    assert result.exit_code != 0
    assert "Aucun plan" in result.output


def test_plan_show_displays_realized_line_after_match(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    _seed_plan_with_session_and_activity(db_path)
    runner = CliRunner()
    runner.invoke(main, ["plan", "match"])

    result = runner.invoke(main, ["plan", "show", "1"])
    assert result.exit_code == 0, result.output
    assert "↳ réalisé" in result.output
    assert "FCmoy 152" in result.output
    # Δdurée -1 min (3600 cible - 3500 réalisé = -100s ≈ -1 min)
    assert "Δdurée" in result.output


# --- Lot 5c.3 : sortie --json ----------------------------------------------


def test_goal_list_json(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "Trail 50k", "--target-date", "2026-10-15"])
    runner.invoke(main, ["goal", "add", "--name", "70.3", "--target-date", "2027-04-15"])

    result = runner.invoke(main, ["goal", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 2
    # Tri par target_date ASC.
    assert payload[0]["name"] == "Trail 50k"
    assert payload[0]["target_date"] == "2026-10-15"
    assert payload[0]["status"] == "active"


def test_goal_show_json(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["goal", "add", "--name", "Goal", "--description", "détail"])

    result = runner.invoke(main, ["goal", "show", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == 1
    assert payload["name"] == "Goal"
    assert payload["description"] == "détail"


def test_plan_list_json(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )

    result = runner.invoke(main, ["plan", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["start_date"] == "2026-06-01"
    assert payload[0]["status"] == "active"


def test_plan_session_list_json(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
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
            "--duration",
            "3600",
        ],
    )

    result = runner.invoke(main, ["plan", "session", "list", "--plan-id", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["sport_type"] == "Run"
    assert payload[0]["target_duration_s"] == 3600
    assert payload[0]["status"] == "planned"


def test_plan_show_json_embeds_sessions_and_realized(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    _seed_plan_with_session_and_activity(db_path)
    runner = CliRunner()
    runner.invoke(main, ["plan", "match"])

    result = runner.invoke(main, ["plan", "show", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == 1
    assert "sessions" in payload
    assert len(payload["sessions"]) == 1
    sess = payload["sessions"][0]
    # Séance matchée au seed (3500s réalisé vs 3600s cible).
    assert sess["status"] == "done"
    assert sess["realized"] is not None
    assert sess["realized"]["activity_id"] == 5001
    assert sess["realized"]["duration_delta_s"] == -100  # 3500 - 3600


def test_plan_show_json_unmatched_session_realized_null(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _setup_env(monkeypatch, tmp_path)
    runner = CliRunner()
    runner.invoke(
        main, ["plan", "add", "--name", "P", "--start", "2026-06-01", "--end", "2026-09-15"]
    )
    runner.invoke(
        main,
        ["plan", "session", "add", "--plan-id", "1", "--date", "2026-06-15", "--sport", "Run"],
    )

    result = runner.invoke(main, ["plan", "show", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sessions"][0]["realized"] is None


def test_plan_match_json_separates_matched_and_unmatched(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    db_path = _setup_env(monkeypatch, tmp_path)
    _seed_plan_with_session_and_activity(db_path)

    result = CliRunner().invoke(main, ["plan", "match", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["plan_id"] is None
    assert len(payload["matched"]) == 1
    assert payload["matched"][0]["activity_id"] == 5001
    assert payload["matched"][0]["same_day"] is True
    assert payload["unmatched"] == []
