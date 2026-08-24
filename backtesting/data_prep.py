"""Turn raw OHLCV (as stored in daily_prices) into a corporate-action-
adjusted OHLC series suitable for signal generation and execution.

We scale open/high/low by the same day's close-to-adj_close ratio so the
whole bar moves consistently (not just the close), which keeps indicators
(SMA, RSI, Bollinger, breakout channels, etc.) free of the artificial
cliffs that raw prices show across a split or bonus issue ex-date. Position
sizes and P&L are therefore computed in "adjusted" price terms too - the
standard simplification used by most retail backtesting tools. This means
exact historical share counts/cash amounts around a specific split are not
reproduced bar-for-bar, but aggregate portfolio value and returns are
correct and consistent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def prepare_ohlcv(df: pd.DataFrame, use_adjusted: bool = True) -> pd.DataFrame:
    """Input columns: date, open, high, low, close, adj_close, volume.
    Returns a DataFrame indexed by date (ascending, deduplicated) with
    columns open, high, low, close, volume ready for the backtesting engine.
    """
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.drop_duplicates(subset="date").sort_values("date").set_index("date")

    if use_adjusted and "adj_close" in out.columns:
        factor = (out["adj_close"] / out["close"]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        out["open"] = out["open"] * factor
        out["high"] = out["high"] * factor
        out["low"] = out["low"] * factor
        out["close"] = out["adj_close"]

    return out[["open", "high", "low", "close", "volume"]]
