"""Rolling risk diagnostics (rolling Sharpe, rolling CAGR) used by the
reporting layer's charts - complements the point-in-time metrics in
`analytics/performance.py`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def rolling_sharpe(equity_curve: pd.DataFrame, window: int = 63, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    returns = equity_curve["daily_return"].fillna(0.0)
    roll_mean = returns.rolling(window).mean()
    roll_std = returns.rolling(window).std(ddof=1)
    sharpe = (roll_mean / roll_std) * np.sqrt(periods_per_year)
    return pd.Series(sharpe.values, index=pd.to_datetime(equity_curve["date"]), name="rolling_sharpe")


def rolling_cagr(equity_curve: pd.DataFrame, window: int = 252) -> pd.Series:
    values = equity_curve["total_value"]
    ratio = values / values.shift(window)
    years = window / TRADING_DAYS_PER_YEAR
    cagr = ratio ** (1 / years) - 1
    return pd.Series((cagr * 100).values, index=pd.to_datetime(equity_curve["date"]), name="rolling_cagr_pct")


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    if len(returns) < 20:
        return 0.0
    return float(-np.percentile(returns, (1 - confidence) * 100))


def historical_expected_shortfall(returns: pd.Series, confidence: float = 0.95) -> float:
    if len(returns) < 20:
        return 0.0
    threshold = np.percentile(returns, (1 - confidence) * 100)
    tail = returns[returns <= threshold]
    return float(-tail.mean()) if len(tail) else historical_var(returns, confidence)
