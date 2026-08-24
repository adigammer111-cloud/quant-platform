"""Trading calendar helpers (NSE sessions) used for missing-session detection
and for backtesting (no trades/signals should ever be evaluated on a
non-trading day).
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal


@lru_cache(maxsize=1)
def _nse_calendar():
    return mcal.get_calendar("NSE")


def trading_sessions(start: date, end: date) -> pd.DatetimeIndex:
    """All NSE trading session dates in [start, end], inclusive."""
    if start > end:
        return pd.DatetimeIndex([])
    schedule = _nse_calendar().schedule(start_date=start, end_date=end)
    return pd.DatetimeIndex(schedule.index.date)


def missing_sessions(present_dates: pd.Series | list, start: date, end: date) -> list[date]:
    """Given the dates actually present in a dataset, return NSE trading
    sessions in [start, end] that are missing."""
    expected = set(trading_sessions(start, end).date)
    present = {pd.Timestamp(d).date() for d in present_dates}
    return sorted(expected - present)
