"""Ingestion pipeline tests using a fake in-memory provider (no network)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from data.ingestion.downloader import update_symbol
from data.providers.base import (
    CORPORATE_ACTION_COLUMNS,
    DAILY_COLUMNS,
    InstrumentInfo,
    MarketDataProvider,
)
from data.storage import repository


class FakeProvider(MarketDataProvider):
    """Deterministic in-memory provider for tests. Generates one bar per
    calendar day (not a real trading calendar) so tests can control exactly
    what data exists without hitting the network."""

    name = "fake"

    def __init__(self):
        self.daily_calls: list[tuple[str, date, date]] = []

    def get_daily_data(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self.daily_calls.append((symbol, start, end))
        rows = []
        d = start
        while d <= end:
            rows.append(
                {
                    "date": d,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "adj_close": 100.5,
                    "volume": 1000,
                }
            )
            d += timedelta(days=1)
        return pd.DataFrame(rows, columns=DAILY_COLUMNS)

    def get_intraday_data(self, symbol, start, end, interval="5m"):
        return pd.DataFrame()

    def get_corporate_actions(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)

    def get_instruments(self, symbols: list[str]) -> list[InstrumentInfo]:
        return [InstrumentInfo(symbol=s, base_symbol=s, exchange="NSE") for s in symbols]


def test_first_download_uses_history_days_window(temp_db):
    provider = FakeProvider()
    end = date(2024, 1, 31)
    result = update_symbol(provider, "FAKE.NS", history_days=10, end=end)
    assert result.ok
    assert result.rows_written == 11  # 10 days back through end, inclusive
    assert provider.daily_calls[0][1] == end - timedelta(days=10)
    assert provider.daily_calls[0][2] == end


def test_second_run_only_downloads_missing_tail(temp_db):
    provider = FakeProvider()
    end1 = date(2024, 1, 10)
    update_symbol(provider, "FAKE.NS", history_days=10, end=end1)

    end2 = date(2024, 1, 15)
    result2 = update_symbol(provider, "FAKE.NS", history_days=10, end=end2)

    assert result2.ok
    # Second call should only request the 5 missing days after end1.
    second_call = provider.daily_calls[-1]
    assert second_call[1] == end1 + timedelta(days=1)
    assert second_call[2] == end2
    assert result2.rows_downloaded == 5


def test_no_download_when_already_up_to_date(temp_db):
    provider = FakeProvider()
    end = date(2024, 1, 10)
    update_symbol(provider, "FAKE.NS", history_days=5, end=end)
    calls_before = len(provider.daily_calls)

    result = update_symbol(provider, "FAKE.NS", history_days=5, end=end)
    assert result.rows_downloaded == 0
    assert result.rows_written == 0
    assert len(provider.daily_calls) == calls_before  # no new network call made

    # But metadata should still reflect the existing data (regression check).
    from data.storage.repository import get_data_status

    status = get_data_status()
    assert "FAKE.NS" in set(status["symbol"])


def test_full_refresh_redownloads_everything(temp_db):
    provider = FakeProvider()
    end = date(2024, 1, 10)
    update_symbol(provider, "FAKE.NS", history_days=5, end=end)

    result = update_symbol(provider, "FAKE.NS", history_days=5, end=end, full_refresh=True)
    assert result.rows_downloaded == 6  # full window re-requested
    # No duplicate rows created in the DB despite re-downloading.
    all_rows = repository.get_daily_prices("FAKE.NS")
    assert len(all_rows) == 6


def test_upsert_is_idempotent_no_duplicates(temp_db):
    provider = FakeProvider()
    end = date(2024, 1, 5)
    update_symbol(provider, "FAKE.NS", history_days=5, end=end)
    update_symbol(provider, "FAKE.NS", history_days=5, end=end, full_refresh=True)
    update_symbol(provider, "FAKE.NS", history_days=5, end=end, full_refresh=True)

    all_rows = repository.get_daily_prices("FAKE.NS")
    assert len(all_rows) == len(all_rows["date"].unique())
