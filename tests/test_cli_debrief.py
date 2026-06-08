from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from claude_coach.cli import main
from claude_coach.db import (
    connect,
    insert_full_activity,
    migrate,
    upsert_athlete,
)
from claude_coach.models import Activity, Athlete


def _setup_db_env(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("STRAVA_DB_PATH", str(db_path))


def _seed_activity(db_path: Path, aid: int = 7001) -> None:
    conn = connect(db_path)
    migrate(conn)
    upsert_athlete(conn, Athlete(id=42))
    insert_full_activity(
        conn,
        Activity(
            id=aid,
            athlete_id=42,
            name="Ride test",
            sport_type="VirtualRide",
            start_date="2026-06-08T06:42:00+00:00",
            start_date_local="2026-06-08T06:42:00",
            raw_json="{}",
        ),
        [],
        [],
        [],
    )
    conn.close()


def test_debrief_add_minimal(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(
        main, ["debrief", "add", "--date", "2026-06-08", "--rpe", "3", "--feeling", "RAS"]
    )
    assert result.exit_code == 0, result.output
    assert "débrief #1" in result.output
    assert "RPE 3" in result.output


def test_debrief_add_requires_content(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["debrief", "add", "--date", "2026-06-08"])
    assert result.exit_code != 0
    assert "au moins" in result.output


def test_debrief_add_rejects_bad_rpe(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["debrief", "add", "--rpe", "11", "--feeling", "x"])
    assert result.exit_code != 0  # click.IntRange refuse 11


def test_debrief_add_unknown_activity(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["debrief", "add", "--activity", "999", "--rpe", "3"])
    assert result.exit_code != 0
    assert "Aucune activité #999" in result.output


def test_debrief_add_with_activity_link(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    _seed_activity(db_path)
    result = CliRunner().invoke(
        main,
        ["debrief", "add", "--activity", "7001", "--rpe", "3", "--feeling", "RAS"],
    )
    assert result.exit_code == 0, result.output


def test_debrief_list_json(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    CliRunner().invoke(main, ["debrief", "add", "--date", "2026-06-01", "--feeling", "vieux"])
    CliRunner().invoke(
        main, ["debrief", "add", "--date", "2026-06-08", "--rpe", "5", "--pain", "mollet"]
    )

    result = CliRunner().invoke(main, ["debrief", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 2
    # Plus récent en premier ; clés stables, null jamais omis.
    assert payload[0]["debrief_date"] == "2026-06-08"
    assert payload[0]["rpe"] == 5
    assert payload[0]["pain"] == "mollet"
    assert payload[1]["rpe"] is None  # champ optionnel présent à null


def test_debrief_list_filter_date(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    CliRunner().invoke(main, ["debrief", "add", "--date", "2026-05-01", "--feeling", "a"])
    CliRunner().invoke(main, ["debrief", "add", "--date", "2026-06-08", "--feeling", "b"])

    result = CliRunner().invoke(main, ["debrief", "list", "--from", "2026-06-01", "--json"])
    payload = json.loads(result.output)
    assert [d["feeling"] for d in payload] == ["b"]


def test_debrief_show(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    CliRunner().invoke(
        main, ["debrief", "add", "--date", "2026-06-08", "--rpe", "3", "--pain", "genou"]
    )
    result = CliRunner().invoke(main, ["debrief", "show", "1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == 1
    assert payload["pain"] == "genou"


def test_debrief_show_missing(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    result = CliRunner().invoke(main, ["debrief", "show", "999"])
    assert result.exit_code != 0
    assert "Aucun débrief #999" in result.output


def test_debrief_edit(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    CliRunner().invoke(
        main, ["debrief", "add", "--date", "2026-06-08", "--rpe", "3", "--feeling", "RAS"]
    )
    result = CliRunner().invoke(main, ["debrief", "edit", "1", "--rpe", "5"])
    assert result.exit_code == 0, result.output
    show = CliRunner().invoke(main, ["debrief", "show", "1", "--json"])
    payload = json.loads(show.output)
    assert payload["rpe"] == 5
    assert payload["feeling"] == "RAS"  # inchangé


def test_debrief_delete(monkeypatch: MonkeyPatch, db_path: Path) -> None:
    _setup_db_env(monkeypatch, db_path)
    CliRunner().invoke(main, ["debrief", "add", "--date", "2026-06-08", "--feeling", "x"])
    result = CliRunner().invoke(main, ["debrief", "delete", "1"])
    assert result.exit_code == 0, result.output
    show = CliRunner().invoke(main, ["debrief", "show", "1"])
    assert show.exit_code != 0
