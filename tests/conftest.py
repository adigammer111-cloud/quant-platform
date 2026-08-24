from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from config import settings


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway DuckDB file for the duration of a test."""
    db_path = tmp_path / "test.duckdb"
    monkeypatch.setattr(settings, "duckdb_path", db_path)
    from database.db import ensure_database

    ensure_database()
    yield db_path
