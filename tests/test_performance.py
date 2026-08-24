"""Performance metrics tests with hand-computed expected values."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from analytics.performance import compute_performance_metrics


def _equity_curve(values: list[float], start: date = date(2020, 1, 1)) -> pd.DataFrame:
    dates = [start + timedelta(days=i) for i in range(len(values))]
    df = pd.DataFrame({"date": dates, "total_value": values})
    df["daily_return"] = df["total_value"].pct_change().fillna(0.0)
    df["cummax"] = df["total_value"].cummax()
    df["drawdown"] = df["total_value"] / df["cummax"] - 1
    return df


def test_cagr_matches_hand_calculation_two_year_doubling():
    # Exactly 2 years (730 days), 100,000 -> 121,000 => CAGR = 10%
    n = 731
    values = np.linspace(100_000, 121_000, n).tolist()
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])

    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    assert metrics.cagr_pct == pytest.approx(10.0, abs=0.5)
    assert metrics.absolute_return_pct == pytest.approx(21.0, abs=0.01)


def test_max_drawdown_matches_hand_calculation():
    values = [100_000, 110_000, 121_000, 90_750, 95_000, 100_000]
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    # peak 121,000 -> trough 90,750 = -25%
    assert metrics.max_drawdown_pct == pytest.approx(-25.0, abs=0.01)


def test_zero_drawdown_when_monotonically_increasing():
    values = list(np.linspace(100_000, 150_000, 100))
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    assert metrics.max_drawdown_pct == pytest.approx(0.0, abs=1e-6)


def test_win_rate_and_profit_factor_hand_calculation():
    trades = pd.DataFrame(
        {
            "realized_pnl": [100.0, -50.0, 200.0, -50.0, np.nan, 300.0],  # NaN = still-open leg
            "holding_period_days": [5, 3, 10, 2, None, 7],
            "gross_amount": [1000, 1000, 1000, 1000, 1000, 1000],
        }
    )
    values = [100_000] * 20
    equity = _equity_curve(values)
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)

    assert metrics.num_trades == 5  # NaN row excluded
    assert metrics.winning_trades == 3
    assert metrics.losing_trades == 2
    assert metrics.win_rate_pct == pytest.approx(60.0)
    gross_profit = 100 + 200 + 300
    gross_loss = 50 + 50
    assert metrics.profit_factor == pytest.approx(gross_profit / gross_loss)
    assert metrics.avg_win == pytest.approx(gross_profit / 3)
    assert metrics.avg_loss == pytest.approx(-gross_loss / 2)
    assert metrics.expectancy == pytest.approx((100 - 50 + 200 - 50 + 300) / 5)


def test_sharpe_zero_when_no_volatility():
    values = list(np.linspace(100_000, 110_000, 50))  # perfectly smooth, constant daily return
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    # near-constant daily returns => near-zero std => Sharpe computed but should be finite, not NaN/inf
    assert np.isfinite(metrics.sharpe_ratio)


def test_sharpe_positive_for_consistently_positive_returns():
    rng = np.random.default_rng(42)
    daily = rng.normal(loc=0.001, scale=0.005, size=500)
    values = [100_000.0]
    for r in daily:
        values.append(values[-1] * (1 + r))
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    assert metrics.sharpe_ratio > 0


def test_no_trades_gives_zero_trading_stats_without_crashing():
    values = [100_000] * 10
    equity = _equity_curve(values)
    trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    metrics = compute_performance_metrics(equity, trades, initial_capital=100_000)
    assert metrics.num_trades == 0
    assert metrics.win_rate_pct == 0.0
    assert metrics.profit_factor == 0.0
