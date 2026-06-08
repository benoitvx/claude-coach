from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from claude_coach.db import (
    connect,
    delete_debrief,
    get_debrief,
    insert_debrief,
    insert_full_activity,
    insert_planned_session,
    insert_training_plan,
    list_debriefs,
    migrate,
    update_debrief,
    upsert_athlete,
)
from claude_coach.models import Activity, Athlete


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _seed_activity(conn: sqlite3.Connection, aid: int = 5001) -> Activity:
    upsert_athlete(conn, Athlete(id=42))
    act = Activity(
        id=aid,
        athlete_id=42,
        name="Run test",
        sport_type="Run",
        start_date="2026-06-07T08:00:00+00:00",
        start_date_local="2026-06-07T10:00:00",
        raw_json="{}",
    )
    insert_full_activity(conn, act, [], [], [])
    return act


def test_migration_005_creates_debriefs_table(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn)
    assert "session_debriefs" in _table_names(conn)


def test_insert_debrief_minimal_then_get(db_conn: sqlite3.Connection) -> None:
    d = insert_debrief(db_conn, debrief_date=date(2026, 6, 8), rpe=3, feeling="RAS")
    assert d.id > 0
    assert d.rpe == 3
    assert d.feeling == "RAS"
    assert d.activity_id is None
    assert d.planned_session_id is None
    fetched = get_debrief(db_conn, d.id)
    assert fetched == d


def test_insert_debrief_with_links(db_conn: sqlite3.Connection) -> None:
    act = _seed_activity(db_conn)
    plan = insert_training_plan(
        db_conn, name="P", start_date=date(2026, 6, 1), end_date=date(2026, 7, 1)
    )
    sess = insert_planned_session(
        db_conn, training_plan_id=plan.id, planned_date=date(2026, 6, 8), sport_type="Ride"
    )
    d = insert_debrief(
        db_conn,
        debrief_date=date(2026, 6, 8),
        activity_id=act.id,
        planned_session_id=sess.id,
        rpe=5,
        pain="mollet D léger",
    )
    assert d.activity_id == act.id
    assert d.planned_session_id == sess.id
    assert d.pain == "mollet D léger"


def test_insert_debrief_rejects_invalid_rpe(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        insert_debrief(db_conn, debrief_date=date(2026, 6, 8), rpe=11)
    with pytest.raises(ValueError):
        insert_debrief(db_conn, debrief_date=date(2026, 6, 8), rpe=0)


def test_list_debriefs_orders_recent_first(db_conn: sqlite3.Connection) -> None:
    insert_debrief(db_conn, debrief_date=date(2026, 6, 1), feeling="vieux")
    insert_debrief(db_conn, debrief_date=date(2026, 6, 8), feeling="récent")
    insert_debrief(db_conn, debrief_date=date(2026, 6, 5), feeling="milieu")
    dates = [d.debrief_date.isoformat() for d in list_debriefs(db_conn)]
    assert dates == ["2026-06-08", "2026-06-05", "2026-06-01"]


def test_list_debriefs_filters(db_conn: sqlite3.Connection) -> None:
    act = _seed_activity(db_conn)
    insert_debrief(db_conn, debrief_date=date(2026, 6, 1), feeling="hors fenêtre")
    insert_debrief(db_conn, debrief_date=date(2026, 6, 8), activity_id=act.id, feeling="liée")

    in_window = list_debriefs(db_conn, since=date(2026, 6, 5), until=date(2026, 6, 10))
    assert [d.feeling for d in in_window] == ["liée"]

    by_activity = list_debriefs(db_conn, activity_id=act.id)
    assert [d.feeling for d in by_activity] == ["liée"]

    assert len(list_debriefs(db_conn, limit=1)) == 1


def test_update_debrief_partial(db_conn: sqlite3.Connection) -> None:
    d = insert_debrief(db_conn, debrief_date=date(2026, 6, 8), rpe=3, feeling="RAS")
    updated = update_debrief(db_conn, d.id, rpe=4)
    assert updated.rpe == 4
    assert updated.feeling == "RAS"  # champ non fourni → inchangé


def test_update_debrief_rejects_invalid_rpe(db_conn: sqlite3.Connection) -> None:
    d = insert_debrief(db_conn, debrief_date=date(2026, 6, 8), rpe=3)
    with pytest.raises(ValueError):
        update_debrief(db_conn, d.id, rpe=99)


def test_update_debrief_missing_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        update_debrief(db_conn, 99999, rpe=3)


def test_delete_debrief(db_conn: sqlite3.Connection) -> None:
    d = insert_debrief(db_conn, debrief_date=date(2026, 6, 8), feeling="à supprimer")
    deleted = delete_debrief(db_conn, d.id)
    assert deleted.id == d.id
    assert get_debrief(db_conn, d.id) is None


def test_delete_debrief_missing_raises(db_conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        delete_debrief(db_conn, 99999)


def test_debrief_activity_link_set_null_on_delete(db_conn: sqlite3.Connection) -> None:
    """ON DELETE SET NULL : le débrief survit à la disparition de l'activité liée."""
    act = _seed_activity(db_conn)
    d = insert_debrief(db_conn, debrief_date=date(2026, 6, 8), activity_id=act.id, rpe=3)
    db_conn.execute("PRAGMA foreign_keys = ON")
    with db_conn:
        db_conn.execute("DELETE FROM activities WHERE id = ?", (act.id,))
    survivor = get_debrief(db_conn, d.id)
    assert survivor is not None
    assert survivor.activity_id is None
    assert survivor.rpe == 3
