"""Hand-rolled technical indicators (pandas/numpy only - no TA-Lib / pandas-ta
dependency, both of which have Windows install friction and shaky support
for modern pandas). Every function is a pure, vectorized transform over a
single price Series and uses only backward-looking (`.rolling`, `.ewm`,
`.shift`) windows, so none of them can leak future information into bar t -
that invariant is what lets the backtesting engine trust
`generate_signals(data)` as of any row without re-checking each strategy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    return result.where(avg_loss != 0, 100.0)


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def rolling_high(series: pd.Series, window: int) -> pd.Series:
    """Highest value over the *prior* `window` bars, excluding the current
    bar - used for breakout signals so "today's high" can't trigger its own
    breakout (that would be look-ahead)."""
    return series.shift(1).rolling(window=window, min_periods=window).max()


def rolling_low(series: pd.Series, window: int) -> pd.Series:
    return series.shift(1).rolling(window=window, min_periods=window).min()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def daily_returns(series: pd.Series) -> pd.Series:
    return series.pct_change()


def momentum(series: pd.Series, window: int) -> pd.Series:
    """Total return over the trailing `window` bars (as of the current bar)."""
    return series / series.shift(window) - 1
