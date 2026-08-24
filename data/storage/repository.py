"""Read/write access to the DuckDB tables. This is the only module that
should contain raw SQL against daily_prices / instruments / etc. - everything
else (ingestion, strategies, backtesting) goes through these functions.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import duckdb
import pandas as pd

from data.providers.base import InstrumentInfo
from database.db import get_connection

logger = logging.getLogger(__name__)


def upsert_instruments(instruments: list[InstrumentInfo]) -> None:
    if not instruments:
        return
    rows = [
        (
            i.symbol,
            i.base_symbol,
            i.exchange,
            i.name,
            i.isin,
            i.sector,
            i.industry,
            i.instrument_type,
            i.first_listed_date,
        )
        for i in instruments
    ]
    with get_connection() as con:
        con.executemany(
            """
            INSERT INTO instruments
                (symbol, base_symbol, exchange, name, isin, sector, industry,
                 instrument_type, first_listed_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol) DO UPDATE SET
                base_symbol = excluded.base_symbol,
                exchange = excluded.exchange,
                name = COALESCE(excluded.name, instruments.name),
                isin = COALESCE(excluded.isin, instruments.isin),
                sector = COALESCE(excluded.sector, instruments.sector),
                industry = COALESCE(excluded.industry, instruments.industry),
                instrument_type = excluded.instrument_type
            """,
            rows,
        )


def upsert_daily_prices(symbol: str, df: pd.DataFrame, source: str) -> int:
    """Upsert a daily OHLCV DataFrame (columns: date, open, high, low, close,
    adj_close, volume) for a single symbol. Returns rows written."""
    if df.empty:
        return 0
    payload = df.copy()
    payload["symbol"] = symbol
    payload["source"] = source
    payload = payload[
        ["symbol", "date", "open", "high", "low", "close", "adj_close", "volume", "source"]
    ]
    with get_connection() as con:
        con.register("df_payload", payload)
        con.execute(
            """
            INSERT INTO daily_prices
                (symbol, date, open, high, low, close, adj_close, volume, source)
            SELECT symbol, date, open, high, low, close, adj_close, volume, source
            FROM df_payload
            ON CONFLICT (symbol, date) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                adj_close = excluded.adj_close,
                volume = excluded.volume,
                source = excluded.source,
                inserted_at = now()
            """
        )
        con.unregister("df_payload")
    return len(payload)


def upsert_corporate_actions(symbol: str, df: pd.DataFrame, source: str) -> int:
    if df.empty:
        return 0
    payload = df.copy()
    payload["symbol"] = symbol
    payload["source"] = source
    cols = [
        "symbol",
        "ex_date",
        "action_type",
        "ratio_numerator",
        "ratio_denominator",
        "dividend_amount",
        "new_symbol",
        "notes",
        "source",
    ]
    payload = payload[cols]
    with get_connection() as con:
        con.register("df_payload", payload)
        con.execute(
            """
            INSERT INTO corporate_actions
                (symbol, ex_date, action_type, ratio_numerator, ratio_denominator,
                 dividend_amount, new_symbol, notes, source)
            SELECT * FROM df_payload
            ON CONFLICT (symbol, ex_date, action_type) DO UPDATE SET
                ratio_numerator = excluded.ratio_numerator,
                ratio_denominator = excluded.ratio_denominator,
                dividend_amount = excluded.dividend_amount,
                new_symbol = excluded.new_symbol,
                notes = excluded.notes,
                source = excluded.source
            """
        )
        con.unregister("df_payload")
    return len(payload)


def get_last_daily_date(symbol: str) -> Optional[date]:
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT max(date) FROM daily_prices WHERE symbol = ?", [symbol]
        ).fetchone()
    return row[0] if row and row[0] else None


def get_daily_prices(
    symbol: str, start: Optional[date] = None, end: Optional[date] = None
) -> pd.DataFrame:
    query = "SELECT date, open, high, low, close, adj_close, volume FROM daily_prices WHERE symbol = ?"
    params: list = [symbol]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY date"
    with get_connection(read_only=True) as con:
        return con.execute(query, params).fetchdf()


def get_daily_prices_multi(
    symbols: list[str], start: Optional[date] = None, end: Optional[date] = None
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in symbols)
    query = (
        f"SELECT symbol, date, open, high, low, close, adj_close, volume "
        f"FROM daily_prices WHERE symbol IN ({placeholders})"
    )
    params: list = list(symbols)
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY symbol, date"
    with get_connection(read_only=True) as con:
        return con.execute(query, params).fetchdf()


def get_corporate_actions(symbol: str) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            """
            SELECT ex_date, action_type, ratio_numerator, ratio_denominator,
                   dividend_amount, new_symbol, notes
            FROM corporate_actions WHERE symbol = ? ORDER BY ex_date
            """,
            [symbol],
        ).fetchdf()


def upsert_data_metadata(symbol: str, data_type: str, stats: dict) -> None:
    with get_connection() as con:
        con.execute(
            """
            INSERT INTO data_metadata
                (symbol, data_type, first_date, last_date, row_count,
                 missing_sessions, duplicate_rows, invalid_ohlc_rows,
                 suspicious_moves, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (symbol, data_type) DO UPDATE SET
                first_date = excluded.first_date,
                last_date = excluded.last_date,
                row_count = excluded.row_count,
                missing_sessions = excluded.missing_sessions,
                duplicate_rows = excluded.duplicate_rows,
                invalid_ohlc_rows = excluded.invalid_ohlc_rows,
                suspicious_moves = excluded.suspicious_moves,
                status = excluded.status,
                notes = excluded.notes,
                last_updated_at = now()
            """,
            [
                symbol,
                data_type,
                stats.get("first_date"),
                stats.get("last_date"),
                stats.get("row_count"),
                stats.get("missing_sessions", 0),
                stats.get("duplicate_rows", 0),
                stats.get("invalid_ohlc_rows", 0),
                stats.get("suspicious_moves", 0),
                stats.get("status"),
                stats.get("notes"),
            ],
        )


def list_instruments() -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute("SELECT * FROM instruments ORDER BY symbol").fetchdf()


def get_data_status() -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            """
            SELECT m.symbol, i.name, m.data_type, m.first_date, m.last_date,
                   m.row_count, m.status, m.last_updated_at
            FROM data_metadata m
            LEFT JOIN instruments i ON i.symbol = m.symbol
            ORDER BY m.symbol
            """
        ).fetchdf()
