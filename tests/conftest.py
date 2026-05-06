from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from strava_connect.db import connect, migrate
from strava_connect.models import Config


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db_conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tokens_path(tmp_path: Path) -> Path:
    return tmp_path / "tokens.json"


@pytest.fixture
def fake_config() -> Config:
    return Config(client_id="123456", client_secret="s3cr3t", history_days=730)
