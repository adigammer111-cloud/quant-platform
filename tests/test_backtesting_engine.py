"""Backtesting engine tests, with a strong focus on the two properties that
matter most: (1) no look-ahead bias - a signal computed from bar t's data
can never be executed at bar t's price, and (2) cash/position accounting is
exactly correct (no phantom money created or destroyed).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backtesting.costs import TransactionCostModel
from backtesting.engine import BacktestConfig, BacktestEngine
from strategies.base import RiskParams, Strategy


def zero_cost_model() -> TransactionCostModel:
    return TransactionCostModel(
        brokerage_pct=0.0,
        brokerage_flat_cap=0.0,
        stt_pct_buy=0.0,
        stt_pct_sell=0.0,
        exchange_txn_pct=0.0,
        sebi_fee_pct=0.0,
        stamp_duty_pct_buy=0.0,
        gst_pct=0.0,
        slippage_bps=0.0,
    )


def _bars(prices: list[tuple[float, float, float, float]], start: date) -> pd.DataFrame:
    """prices: list of (open, high, low, close) tuples, one per day."""
    rows = []
    d = start
    for o, h, l, c in prices:
        rows.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "adj_close": c,
                "volume": 1000,
            }
        )
        d += timedelta(days=1)
    return pd.DataFrame(rows)


class FixedSignalStrategy(Strategy):
    """Test double: returns a hand-specified signal sequence regardless of
    price data, so tests can control exactly when a signal fires."""

    name = "fixed_signal_test_strategy"

    def __init__(self, signal_sequence: list[int], **kwargs):
        super().__init__(**kwargs)
        self._signal_sequence = signal_sequence

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        assert len(self._signal_sequence) == len(data)
        return pd.Series(self._signal_sequence, index=data.index)


def test_no_lookahead_entry_price_is_next_bar_open_not_signal_bar_close():
    """Signal fires (goes to 1) at day3 based on day3's close. There's then
    a large overnight gap up between day3 close and day4 open. If the engine
    had a look-ahead bug, it would fill at day3's close (100) and instantly
    mark a huge gain. The correct behavior is to fill at day4's open (200),
    i.e. AFTER the gap - capturing none of the jump the strategy could not
    have known about in time to trade.
    """
    prices = [
        (100, 101, 99, 100),   # day1
        (100, 101, 99, 100),   # day2
        (100, 101, 99, 100),   # day3 - signal computed here, target=1
        (200, 205, 195, 200),  # day4 - overnight gap gap up; execution happens here
        (200, 201, 199, 200),  # day5
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 1])

    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    engine = BacktestEngine(config)
    result = engine.run(strategy, {"TEST.NS": df})

    trades = result.trades
    buy_trades = trades[trades["side"] == "BUY"]
    assert len(buy_trades) == 1
    entry_trade = buy_trades.iloc[0]
    assert entry_trade["execution_date"] == start + timedelta(days=3)  # day4
    assert entry_trade["execution_price"] == 200.0  # NOT 100 (day3's close)


def test_signal_at_bar_t_shifted_and_never_executes_same_bar():
    """More direct check: for every BUY/SELL trade with exit_reason=SIGNAL,
    execution_date must be strictly after the date the underlying signal
    value changed (never equal to it)."""
    prices = [(100, 101, 99, 100)] * 6
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    # Signal flips to 1 on day3 (index 2), back to 0 on day5 (index 4).
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 0, 0])
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    signal_trades = result.trades[result.trades["exit_reason"] == "SIGNAL"]
    assert len(signal_trades) == 2  # one entry, one exit
    entry = signal_trades.iloc[0]
    exit_ = signal_trades.iloc[1]
    # signal changed on day3 (idx2) -> execution on day4 (idx3)
    assert entry["execution_date"] == start + timedelta(days=3)
    # signal changed back on day5 (idx4) -> execution on day6 (idx5)
    assert exit_["execution_date"] == start + timedelta(days=5)


def test_cash_accounting_buy_then_sell_no_costs():
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),  # signal -> 1
        (110, 111, 109, 110),  # entry here at open=110
        (120, 121, 119, 120),  # exit here (signal -> 0) at open=120
        (120, 121, 119, 120),
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 0, 0])
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    trades = result.trades
    buy = trades[trades["side"] == "BUY"].iloc[0]
    sell = trades[trades["side"] == "SELL"].iloc[0]

    shares = buy["quantity"]
    assert shares == 100_000 // 110  # floor(alloc / entry price)
    expected_final_cash = 100_000 - shares * 110 + shares * 120
    assert result.portfolio.cash == pytest.approx(expected_final_cash)
    assert sell["realized_pnl"] == pytest.approx(shares * (120 - 110))


def test_transaction_costs_reduce_pnl():
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (110, 111, 109, 110),
        (120, 121, 119, 120),
        (120, 121, 119, 120),
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 0, 0])

    cost_model = TransactionCostModel(
        brokerage_pct=0.0, brokerage_flat_cap=0.0,
        stt_pct_buy=0.001, stt_pct_sell=0.001,
        exchange_txn_pct=0.0, sebi_fee_pct=0.0,
        stamp_duty_pct_buy=0.0, gst_pct=0.0, slippage_bps=0.0,
    )
    config = BacktestConfig(initial_capital=100_000, cost_model=cost_model)
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    trades = result.trades
    buy = trades[trades["side"] == "BUY"].iloc[0]
    sell = trades[trades["side"] == "SELL"].iloc[0]
    assert buy["costs"] == pytest.approx(buy["gross_amount"] * 0.001)
    assert sell["costs"] == pytest.approx(sell["gross_amount"] * 0.001)
    # realized pnl is price-based only; costs are reflected in cash, not realized_pnl
    no_cost_pnl = buy["quantity"] * (120 - 110)
    assert sell["realized_pnl"] == pytest.approx(no_cost_pnl)


def test_stop_loss_triggers_and_exits_at_stop_price():
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),  # signal -> 1
        (100, 101, 99, 100),  # entry at open=100
        (95, 96, 90, 92),      # low breaches 5% stop (95) intraday
        (92, 93, 91, 92),
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 1, 1])
    strategy.risk = RiskParams(stop_loss_pct=0.05)

    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    stop_trades = result.trades[result.trades["exit_reason"] == "STOP_LOSS"]
    assert len(stop_trades) == 1
    assert stop_trades.iloc[0]["execution_price"] == pytest.approx(95.0)
    assert stop_trades.iloc[0]["execution_date"] == start + timedelta(days=4)


def test_take_profit_triggers_and_exits_at_target_price():
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),  # signal -> 1
        (100, 101, 99, 100),  # entry at open=100
        (108, 112, 107, 110),  # high breaches 10% target (110) intraday
        (110, 111, 109, 110),
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 1, 1])
    strategy.risk = RiskParams(take_profit_pct=0.10)

    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    tp_trades = result.trades[result.trades["exit_reason"] == "TAKE_PROFIT"]
    assert len(tp_trades) == 1
    assert tp_trades.iloc[0]["execution_price"] == pytest.approx(110.0)


def test_end_of_backtest_force_closes_open_positions():
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),  # signal -> 1, stays 1 through the end
        (100, 101, 99, 100),
        (105, 106, 104, 105),
        (110, 111, 109, 110),
    ]
    start = date(2024, 1, 1)
    df = _bars(prices, start)
    strategy = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 1, 1])

    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"TEST.NS": df})

    assert result.portfolio.get_position("TEST.NS").quantity == 0
    end_trades = result.trades[result.trades["exit_reason"] == "END_OF_BACKTEST"]
    assert len(end_trades) == 1
    assert result.equity_curve.iloc[-1]["holdings_value"] == 0.0


def test_single_position_sizing_respects_max_position_pct():
    start = date(2024, 1, 1)
    prices_common = [(100, 101, 99, 100)] * 6
    df_a = _bars(prices_common, start)

    strat_a = FixedSignalStrategy(signal_sequence=[0, 0, 1, 1, 1, 1])
    strat_a.risk = RiskParams(max_position_pct=0.6, max_portfolio_exposure_pct=0.6)

    engine = BacktestEngine(BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model()))
    result_a = engine.run(strat_a, {"A.NS": df_a})
    shares_a = result_a.trades[result_a.trades["side"] == "BUY"].iloc[0]["quantity"]
    assert shares_a == (100_000 * 0.6) // 100


def test_multi_symbol_single_run_respects_shared_cash_and_exposure():
    start = date(2024, 1, 1)
    prices = [(100, 101, 99, 100)] * 3 + [(100, 101, 99, 100)] * 3
    df_a = _bars(prices, start)
    df_b = _bars(prices, start)

    class TwoSymbolStrategy(Strategy):
        name = "two_symbol_test"
        risk = RiskParams(max_position_pct=0.6, max_portfolio_exposure_pct=0.6)

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            return pd.Series([0, 0, 1, 1, 1, 1], index=data.index)

    strategy = TwoSymbolStrategy()
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(strategy, {"A.NS": df_a, "B.NS": df_b})

    buys = result.trades[result.trades["side"] == "BUY"]
    # Both A and B want 60% each (120% total) but the 60% exposure cap means
    # only the first-processed symbol should actually open a position.
    assert len(buys) == 1


def test_short_position_pnl_is_correct_direction():
    start = date(2024, 1, 1)
    prices = [
        (100, 101, 99, 100),
        (100, 101, 99, 100),
        (100, 101, 99, 100),  # signal -> -1
        (100, 101, 99, 100),  # entry (short) at open=100
        (95, 96, 94, 95),      # price falls -> short position gains
        (90, 91, 89, 90),      # signal -> 0, cover here at open=90
    ]
    df = _bars(prices, start)

    class ShortStrategy(Strategy):
        name = "short_test"
        allow_short = True

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            # shifted by 1 bar by the engine: entry takes effect day4, exit day6
            return pd.Series([0, 0, -1, -1, 0, 0], index=data.index)

    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    result = BacktestEngine(config).run(ShortStrategy(), {"TEST.NS": df})

    trades = result.trades
    sell_open = trades[(trades["side"] == "SELL") & (trades["exit_reason"] == "SIGNAL")].iloc[0]
    buy_cover = trades[(trades["side"] == "BUY") & (trades["exit_reason"] == "SIGNAL")].iloc[0]
    assert sell_open["execution_price"] == 100.0
    assert buy_cover["execution_price"] == 90.0
    assert buy_cover["realized_pnl"] == pytest.approx(sell_open["quantity"] * (100 - 90))
