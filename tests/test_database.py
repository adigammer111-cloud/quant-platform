from __future__ import annotations

from datetime import date

import pandas as pd

from data.providers.base import InstrumentInfo
from data.storage import repository


def test_schema_creates_all_tables(temp_db):
    from database.db import get_connection

    with get_connection(read_only=True) as con:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    expected = {
        "instruments",
        "daily_prices",
        "intraday_prices",
        "corporate_actions",
        "index_membership",
        "data_metadata",
        "backtest_runs",
        "backtest_trades",
        "backtest_equity_curve",
        "strategy_parameters",
    }
    assert expected.issubset(tables)


def test_upsert_instruments(temp_db):
    info = InstrumentInfo(
        symbol="TEST.NS", base_symbol="TEST", exchange="NSE", name="Test Co"
    )
    repository.upsert_instruments([info])
    df = repository.list_instruments()
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "TEST.NS"
    assert df.iloc[0]["name"] == "Test Co"

    # Upserting again with a different name should update, not duplicate.
    info2 = InstrumentInfo(
        symbol="TEST.NS", base_symbol="TEST", exchange="NSE", name="Test Co Renamed"
    )
    repository.upsert_instruments([info2])
    df = repository.list_instruments()
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Test Co Renamed"


def test_upsert_daily_prices_and_query(temp_db):
    df = pd.DataFrame(
        {
            "date": [date(2024, 1, 1), date(2024, 1, 2)],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "adj_close": [101.0, 102.0],
            "volume": [1000, 1100],
        }
    )
    written = repository.upsert_daily_prices("TEST.NS", df, source="unittest")
    assert written == 2

    fetched = repository.get_daily_prices("TEST.NS")
    assert len(fetched) == 2
    assert fetched.iloc[0]["close"] == 101.0

    # Upsert same date range with changed close should overwrite, not duplicate.
    df2 = df.copy()
    df2["close"] = [105.0, 106.0]
    repository.upsert_daily_prices("TEST.NS", df2, source="unittest")
    fetched2 = repository.get_daily_prices("TEST.NS")
    assert len(fetched2) == 2  # no duplicate rows
    assert fetched2.iloc[0]["close"] == 105.0


def test_get_last_daily_date_none_when_empty(temp_db):
    assert repository.get_last_daily_date("NOPE.NS") is None


def test_get_daily_prices_multi(temp_db):
    df_a = pd.DataFrame(
        {
            "date": [date(2024, 1, 1)],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "adj_close": [1.0],
            "volume": [10],
        }
    )
    df_b = df_a.copy()
    repository.upsert_daily_prices("A.NS", df_a, source="unittest")
    repository.upsert_daily_prices("B.NS", df_b, source="unittest")
    combined = repository.get_daily_prices_multi(["A.NS", "B.NS"])
    assert set(combined["symbol"]) == {"A.NS", "B.NS"}
