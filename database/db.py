"""DuckDB connection management.

DuckDB file access is single-writer: opening a fresh connection on every
call (the original approach here) works fine for a single-threaded CLI
script, but under a server that can process overlapping requests (Streamlit
Cloud reruns scripts per interaction and can overlap runs), two connections
briefly racing to open the same file raises `duckdb.TransactionException`.
The fix is the standard one for embedded DuckDB under a live server: keep
exactly one connection alive for the process and serialize all access to
it through a lock, rather than opening a new one per call. The connection
is recreated if `settings.duckdb_path` changes (this keeps per-test
database isolation working - see tests/conftest.py's `temp_db` fixture).
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

import duckdb

from config import settings
from database.schema import init_schema

logger = logging.getLogger(__name__)

_connection: duckdb.DuckDBPyConnection | None = None
_connection_path: str | None = None
_lock = threading.Lock()


@contextmanager
def get_connection(read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    global _connection, _connection_path
    target_path = str(settings.duckdb_path)

    with _lock:
        if _connection is None or _connection_path != target_path:
            if _connection is not None:
                _connection.close()
            _connection = duckdb.connect(target_path, read_only=False)
            init_schema(_connection)
            _connection_path = target_path
        yield _connection


def ensure_database() -> None:
    with get_connection(read_only=False) as con:
        logger.info("Database ready at %s", settings.duckdb_path)
        tables = con.execute("SHOW TABLES").fetchall()
        logger.debug("Tables: %s", [t[0] for t in tables])
