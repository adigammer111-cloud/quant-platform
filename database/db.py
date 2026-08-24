"""DuckDB connection management.

DuckDB file access is single-writer. We expose a simple context-managed
connection getter rather than a global open connection, so short-lived
CLI commands and the Streamlit app (which reruns scripts on every
interaction) don't fight over file locks.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import duckdb

from config import settings
from database.schema import init_schema

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    con = duckdb.connect(str(settings.duckdb_path), read_only=read_only)
    try:
        if not read_only:
            init_schema(con)
        yield con
    finally:
        con.close()


def ensure_database() -> None:
    with get_connection(read_only=False) as con:
        logger.info("Database ready at %s", settings.duckdb_path)
        tables = con.execute("SHOW TABLES").fetchall()
        logger.debug("Tables: %s", [t[0] for t in tables])
