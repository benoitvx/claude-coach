from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.cli import main
from claude_coach.models import Activity


def _setup_db_env(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    """Pointe le CLI sur la DB tests (les commandes activity ne lisent pas les tokens)."""
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))


def test_activity_list_human_format(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list"])
    assert result.exit_code == 0, result.output
    # Tri par date desc → 2026-04-01 (Run du 2026-04-01) est listé en premier après l'entête.
    assert "Run du 2026-04-01" in result.output
    assert "TrailRun du 2026-01-12" in result.output


def test_activity_list_json_returns_array(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == len(seed_activities)
    # Première entrée = la plus récente (2026-04-01) ; clés stables snake_case.
    assert payload[0]["id"] == 1008
    assert payload[0]["sport_type"] == "Run"
    assert payload[0]["start_date_local"].startswith("2026-04-01")
    # Champ optionnel jamais omis.
    assert "average_heartrate" in payload[0]


def test_activity_list_filters_by_date_range(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(
        main,
        ["activity", "list", "--from", "2026-02-01", "--to", "2026-02-28", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {row["id"] for row in payload} == {1004, 1005}


def test_activity_list_filter_family_expands_run(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list", "--family", "run", "--json"])
    assert result.exit_code == 0, result.output
    ids = {row["id"] for row in json.loads(result.output)}
    # Famille run = Run + TrailRun + VirtualRun (les VirtualRun ne sont pas dans la fixture)
    assert ids == {1001, 1002, 1005, 1007, 1008}


def test_activity_list_filter_sport_exact(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list", "--sport", "Ride", "--json"])
    assert result.exit_code == 0, result.output
    ids = [row["id"] for row in json.loads(result.output)]
    assert ids == [1003]  # Ride seul, pas VirtualRide


def test_activity_list_limit(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list", "--limit", "3", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 3


def test_activity_list_empty_db(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "list"])
    assert result.exit_code == 0, result.output
    assert "Aucune activité" in result.output

    result_json = CliRunner().invoke(main, ["activity", "list", "--json"])
    assert result_json.exit_code == 0
    assert json.loads(result_json.output) == []


def test_activity_show_human_format(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "show", "1002"])
    assert result.exit_code == 0, result.output
    assert "Activité #1002" in result.output
    assert "TrailRun" in result.output
    assert "15.00 km" in result.output


def test_activity_show_json(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "show", "1002", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == 1002
    assert payload["sport_type"] == "TrailRun"
    assert payload["distance_m"] == 15000.0
    assert "raw_json" not in payload  # exclu volontairement


def test_activity_show_unknown_id_exits_non_zero(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "show", "999999"])
    assert result.exit_code != 0
    assert "Aucune activité" in result.output


def test_activity_stats_by_sport_human(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "stats", "--by", "sport"])
    assert result.exit_code == 0, result.output
    # Ordre count DESC : Run (3) en premier.
    out = result.output
    run_idx = out.find("Run ")
    trail_idx = out.find("TrailRun ")
    assert 0 < run_idx < trail_idx


def test_activity_stats_by_month_json(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["activity", "stats", "--by", "month", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["group_by"] == "month"
    keys = [b["key"] for b in payload["buckets"]]
    assert keys == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert payload["total"]["count"] == len(seed_activities)


def test_activity_stats_filter_window(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(
        main,
        [
            "activity",
            "stats",
            "--by",
            "sport",
            "--from",
            "2026-03-01",
            "--to",
            "2026-04-30",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    keys = {b["key"] for b in payload["buckets"]}
    # Mars-avril 2026 : VirtualRide (1006), TrailRun (1007), Run (1008)
    assert keys == {"VirtualRide", "TrailRun", "Run"}
    assert payload["total"]["count"] == 3


def test_activity_stats_empty_window(
    monkeypatch: MonkeyPatch, db_path: Path, seed_activities: list[Activity]
) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(
        main,
        ["activity", "stats", "--from", "2027-01-01", "--to", "2027-12-31"],
    )
    assert result.exit_code == 0, result.output
    assert "Aucune activité" in result.output
