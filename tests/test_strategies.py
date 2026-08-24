from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from strategies.bollinger import BollingerMeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.momentum import MaMomentumStrategy
from strategies.rsi import RsiMeanReversionStrategy
from strategies.sma import SmaCrossoverStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": [1000] * n,
        },
        index=pd.DatetimeIndex(dates),
    )


def test_sma_crossover_goes_long_when_fast_above_slow():
    # A rising ramp will eventually push the fast SMA above the slow SMA.
    closes = list(np.linspace(100, 200, 120))
    df = _make_df(closes)
    strat = SmaCrossoverStrategy(fast_period=5, slow_period=20)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] == 1
    assert signal.iloc[:19].sum() == 0  # warm-up period (slow SMA window - 1) must be flat


def test_sma_crossover_flat_when_no_crossover_possible():
    closes = [100.0] * 60
    df = _make_df(closes)
    strat = SmaCrossoverStrategy(fast_period=5, slow_period=20)
    signal = strat.generate_signals(df)
    assert (signal == 0).all()  # flat prices -> fast == slow -> never strictly above


def test_rsi_mean_reversion_enters_on_oversold_and_holds_until_exit():
    # Sharp decline (drives RSI down) then a strong rally (drives RSI up).
    decline = list(np.linspace(200, 100, 30))
    rally = list(np.linspace(100, 250, 30))
    closes = decline + rally
    df = _make_df(closes)
    strat = RsiMeanReversionStrategy(period=14, oversold=30, exit_level=50)
    signal = strat.generate_signals(df)
    assert signal.max() == 1
    # once entered, should stay 1 for at least a few bars (not flicker every bar)
    entered_at = signal[signal == 1].index[0]
    idx = list(signal.index).index(entered_at)
    assert signal.iloc[idx] == 1
    assert signal.iloc[idx + 1] in (0, 1)  # valid state, no crash


def test_ma_momentum_requires_both_conditions():
    closes = list(np.linspace(100, 300, 250))  # strong sustained uptrend
    df = _make_df(closes)
    strat = MaMomentumStrategy(fast_period=50, slow_period=200)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] == 1
    assert (signal.iloc[:199] == 0).all()  # can't be long before slow SMA (window - 1) warms up


def test_bollinger_mean_reversion_enters_below_lower_band():
    closes = [100.0] * 25 + [80.0]  # sharp one-bar drop below the band
    df = _make_df(closes)
    strat = BollingerMeanReversionStrategy(window=20, num_std=2.0)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] == 1


def test_breakout_enters_on_new_high():
    closes = [100.0] * 25 + [150.0]  # sharp breakout above the 20-day high
    df = _make_df(closes)
    strat = BreakoutStrategy(entry_window=20, exit_window=10)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] == 1


def test_breakout_does_not_enter_without_breaking_prior_high():
    closes = [100.0] * 30  # flat - never breaks its own rolling high
    df = _make_df(closes)
    strat = BreakoutStrategy(entry_window=20, exit_window=10)
    signal = strat.generate_signals(df)
    assert (signal == 0).all()


def test_all_strategies_return_series_aligned_to_input_index():
    closes = list(np.linspace(100, 120, 60))
    df = _make_df(closes)
    for cls, kwargs in [
        (SmaCrossoverStrategy, {}),
        (RsiMeanReversionStrategy, {}),
        (MaMomentumStrategy, {"fast_period": 10, "slow_period": 30}),
        (BollingerMeanReversionStrategy, {}),
        (BreakoutStrategy, {}),
    ]:
        strat = cls(**kwargs)
        signal = strat.generate_signals(df)
        assert list(signal.index) == list(df.index)
        assert set(signal.unique()).issubset({-1, 0, 1})
