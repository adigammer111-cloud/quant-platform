from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.monte_carlo import run_monte_carlo
from analytics.overfitting import (
    check_parameter_stability,
    check_single_backtest,
    check_train_test_gap,
)
from analytics.performance import PerformanceMetrics


def _metrics(**overrides) -> PerformanceMetrics:
    base = dict(
        initial_capital=100_000, final_capital=110_000, absolute_return_pct=10,
        cagr_pct=10, annualized_return_pct=10, max_drawdown_pct=-5, avg_drawdown_pct=-2,
        volatility_annualized_pct=10, downside_deviation_pct=5, value_at_risk_95_pct=2,
        expected_shortfall_95_pct=3, sharpe_ratio=1.0, sortino_ratio=1.2, calmar_ratio=1.0,
        num_trades=50, winning_trades=25, losing_trades=25, win_rate_pct=50.0,
        avg_win=100, avg_loss=-80, profit_factor=1.5, expectancy=10,
        avg_holding_period_days=10, max_consecutive_wins=3, max_consecutive_losses=3,
        turnover_ratio=5.0,
    )
    base.update(overrides)
    return PerformanceMetrics(**base)


def test_monte_carlo_all_winning_trades_has_zero_loss_probability():
    trades = pd.DataFrame({"realized_pnl": [100.0, 200.0, 150.0, 300.0, 250.0] * 10})
    result = run_monte_carlo(trades, initial_capital=100_000, n_simulations=500, seed=1)
    assert result.probability_of_loss_pct == 0.0
    assert result.median_final_capital > 100_000


def test_monte_carlo_all_losing_trades_has_full_loss_probability():
    trades = pd.DataFrame({"realized_pnl": [-100.0, -200.0, -150.0] * 10})
    result = run_monte_carlo(trades, initial_capital=100_000, n_simulations=500, seed=1)
    assert result.probability_of_loss_pct == 100.0


def test_monte_carlo_mixed_trades_gives_percentile_spread():
    rng = np.random.default_rng(3)
    pnls = rng.normal(loc=20, scale=200, size=200)
    trades = pd.DataFrame({"realized_pnl": pnls})
    result = run_monte_carlo(trades, initial_capital=100_000, n_simulations=2000, seed=2)
    assert result.final_capital_percentiles[5] < result.final_capital_percentiles[50]
    assert result.final_capital_percentiles[50] < result.final_capital_percentiles[95]
    assert 0 < result.probability_of_loss_pct < 100


def test_monte_carlo_raises_on_no_closed_trades():
    trades = pd.DataFrame({"realized_pnl": [None, None]})
    with pytest.raises(ValueError):
        run_monte_carlo(trades, initial_capital=100_000, n_simulations=10)


def test_overfitting_flags_low_trade_count():
    metrics = _metrics(num_trades=5)
    warnings = check_single_backtest(metrics)
    assert any("closed trades" in w for w in warnings)


def test_overfitting_flags_unrealistic_sharpe():
    metrics = _metrics(sharpe_ratio=5.0)
    warnings = check_single_backtest(metrics)
    assert any("Sharpe" in w for w in warnings)


def test_overfitting_no_warnings_for_reasonable_metrics():
    metrics = _metrics()
    warnings = check_single_backtest(metrics)
    assert warnings == []


def test_train_test_gap_flags_degradation():
    train = _metrics(sharpe_ratio=2.0)
    test = _metrics(sharpe_ratio=-0.5)
    warnings = check_train_test_gap(train, test)
    assert any("non-positive" in w or "weaker" in w for w in warnings)


def test_train_test_gap_no_warning_when_consistent():
    train = _metrics(sharpe_ratio=1.0)
    test = _metrics(sharpe_ratio=0.9)
    warnings = check_train_test_gap(train, test)
    assert warnings == []


def test_parameter_stability_flags_high_variance():
    fold_summary = pd.DataFrame({"param_fast_period": [5, 50, 5, 90]})
    warnings = check_parameter_stability(fold_summary)
    assert len(warnings) == 1


def test_parameter_stability_no_warning_when_consistent():
    fold_summary = pd.DataFrame({"param_fast_period": [10, 11, 9, 10]})
    warnings = check_parameter_stability(fold_summary)
    assert warnings == []
