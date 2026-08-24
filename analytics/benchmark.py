"""Benchmark comparison: builds a buy-and-hold equity curve (for a single
stock or an index like NIFTY 50) over the same window as a strategy
backtest, in the same schema as `BacktestResult.equity_curve`, so it can be
run through the exact same `compute_performance_metrics` function for a
like-for-like comparison. Buy-and-hold is modeled cost-free and without
share rounding (the conventional passive-benchmark treatment) - it is a
reference line, not a strategy being tested for realism.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def build_buy_and_hold_curve(
    price_df: pd.DataFrame, initial_capital: float, start_date: date, end_date: date
) -> pd.DataFrame:
    """`price_df` columns: date, open, high, low, close, adj_close, volume."""
    df = price_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["date"].dt.date >= start_date) & (df["date"].dt.date <= end_date)]
    df = df.sort_values("date").drop_duplicates(subset="date")
    if df.empty:
        raise ValueError("No benchmark price data in the requested window")

    price_col = "adj_close" if "adj_close" in df.columns and df["adj_close"].notna().any() else "close"
    base_price = df[price_col].iloc[0]
    total_value = initial_capital * (df[price_col] / base_price)

    out = pd.DataFrame(
        {
            "date": df["date"].dt.date.values,
            "total_value": total_value.values,
        }
    )
    out["daily_return"] = out["total_value"].pct_change().fillna(0.0)
    out["cummax"] = out["total_value"].cummax()
    out["drawdown"] = out["total_value"] / out["cummax"] - 1
    return out
