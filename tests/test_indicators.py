from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    momentum,
    rolling_high,
    rolling_low,
    rsi,
    sma,
)


def test_sma_matches_hand_calculation():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = sma(s, 3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)   # (1+2+3)/3
    assert result.iloc[3] == pytest.approx(3.0)   # (2+3+4)/3
    assert result.iloc[4] == pytest.approx(4.0)   # (3+4+5)/3


def test_ema_converges_toward_constant_series():
    s = pd.Series([100.0] * 30)
    result = ema(s, 10)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_100_for_pure_uptrend():
    s = pd.Series(np.linspace(100, 200, 30))
    result = rsi(s, 14)
    assert result.iloc[-1] == pytest.approx(100.0, abs=0.5)


def test_rsi_is_0_for_pure_downtrend():
    s = pd.Series(np.linspace(200, 100, 30))
    result = rsi(s, 14)
    assert result.iloc[-1] == pytest.approx(0.0, abs=0.5)


def test_bollinger_bands_ordering():
    s = pd.Series(np.random.default_rng(1).normal(100, 5, 60))
    upper, mid, lower = bollinger_bands(s, window=20, num_std=2.0)
    valid = upper.notna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_rolling_high_excludes_current_bar():
    s = pd.Series([1, 2, 3, 100, 4, 5])
    result = rolling_high(s, window=3)
    # At index 3 (value=100), rolling_high should reflect bars [0,1,2] = max(1,2,3)=3,
    # NOT include today's 100 - that would be look-ahead.
    assert result.iloc[3] == 3


def test_rolling_low_excludes_current_bar():
    s = pd.Series([10, 9, 8, 0, 7, 6])
    result = rolling_low(s, window=3)
    assert result.iloc[3] == 8  # min of [10,9,8], not today's 0


def test_macd_histogram_is_difference_of_lines():
    s = pd.Series(np.linspace(100, 150, 60))
    macd_line, signal_line, hist = macd(s, fast=12, slow=26, signal=9)
    valid = macd_line.notna() & signal_line.notna()
    diff = macd_line[valid] - signal_line[valid]
    pd.testing.assert_series_equal(hist[valid], diff, check_names=False)


def test_atr_nonnegative():
    high = pd.Series(np.random.default_rng(2).uniform(105, 110, 40))
    low = pd.Series(np.random.default_rng(3).uniform(95, 100, 40))
    close = pd.Series(np.random.default_rng(4).uniform(100, 105, 40))
    result = atr(high, low, close, window=14)
    assert (result.dropna() >= 0).all()


def test_momentum_matches_hand_calculation():
    s = pd.Series([100.0, 105.0, 110.0, 121.0])
    result = momentum(s, window=3)
    assert result.iloc[3] == pytest.approx(0.21)  # 121/100 - 1
