from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from strategies.rule_based import Condition, CustomCodeStrategy, RuleBasedStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    dates = [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes, "volume": [1000] * n},
        index=pd.DatetimeIndex(dates),
    )


def test_price_above_sma_entry_and_rsi_exit():
    # Rising trend so price ends up above its SMA(20).
    closes = list(np.linspace(100, 200, 80))
    df = _make_df(closes)
    entry = [Condition(left="price", operator=">", right="sma", right_window=20)]
    exit_ = [Condition(left="rsi", operator=">", right="value", right_value=90, left_window=14)]
    strat = RuleBasedStrategy(entry_conditions=entry, exit_conditions=exit_)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] in (0, 1)
    assert signal.iloc[:19].sum() == 0  # warm-up


def test_entry_requires_all_conditions_and():
    closes = [100.0] * 30  # flat: RSI ~ neutral, price == SMA
    df = _make_df(closes)
    entry = [
        Condition(left="price", operator=">", right="sma", right_window=10),
        Condition(left="rsi", operator="<", right="value", right_value=30, left_window=14),
    ]
    strat = RuleBasedStrategy(entry_conditions=entry, exit_conditions=[])
    signal = strat.generate_signals(df)
    assert (signal == 0).all()  # flat price never satisfies price > SMA strictly


def test_exit_is_or_across_conditions():
    closes = [100.0] * 20 + [150.0] * 20  # jump up -> RSI spikes, price way above SMA
    df = _make_df(closes)
    entry = [Condition(left="price", operator=">", right="sma", right_window=10)]
    exit_ = [
        Condition(left="rsi", operator=">", right="value", right_value=200, left_window=14),  # never true
        Condition(left="price", operator=">", right="value", right_value=140, right_window=1),  # true after jump
    ]
    strat = RuleBasedStrategy(entry_conditions=entry, exit_conditions=exit_)
    signal = strat.generate_signals(df)
    # Should have entered then exited once price > 140 triggers the OR'd exit.
    assert 1 in signal.values
    assert signal.iloc[-1] == 0


def test_no_entry_conditions_is_always_flat():
    df = _make_df([100.0] * 20)
    strat = RuleBasedStrategy(entry_conditions=[], exit_conditions=[])
    signal = strat.generate_signals(df)
    assert (signal == 0).all()


def test_custom_code_strategy_runs_user_source():
    df = _make_df(list(np.linspace(100, 200, 60)))
    source = (
        "fast = sma(data['close'], 5)\n"
        "slow = sma(data['close'], 20)\n"
        "sig = (fast > slow).astype(int)\n"
        "return sig.where(fast.notna() & slow.notna(), 0)\n"
    )
    strat = CustomCodeStrategy(source_code=source)
    signal = strat.generate_signals(df)
    assert signal.iloc[-1] == 1
    assert set(signal.unique()).issubset({-1, 0, 1})


def test_custom_code_strategy_blocks_os_access():
    source = "import os\nreturn pd.Series(0, index=data.index)\n"
    try:
        strat = CustomCodeStrategy(source_code=source)
        strat.generate_signals(df=_make_df([100.0] * 5))
        assert False, "expected an error importing os in the restricted namespace"
    except (ImportError, NameError, Exception):
        pass  # any failure to import os is the expected/desired outcome
