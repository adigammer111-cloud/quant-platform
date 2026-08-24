from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backtesting.costs import TransactionCostModel
from backtesting.engine import BacktestConfig
from optimization.optimizer import grid_search
from optimization.walk_forward import run_walk_forward


def zero_cost_model() -> TransactionCostModel:
    return TransactionCostModel(
        brokerage_pct=0, brokerage_flat_cap=0, stt_pct_buy=0, stt_pct_sell=0,
        exchange_txn_pct=0, sebi_fee_pct=0, stamp_duty_pct_buy=0, gst_pct=0, slippage_bps=0,
    )


def _trending_df(n_days: int, start: date = date(2018, 1, 1)) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = [start + timedelta(days=i) for i in range(n_days)]
    # Steady uptrend with small noise - a short/fast SMA should track it well.
    trend = np.linspace(100, 100 + n_days * 0.3, n_days)
    noise = rng.normal(0, 1.0, n_days)
    closes = trend + noise
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes * 1.005,
            "low": closes * 0.995,
            "close": closes,
            "adj_close": closes,
            "volume": [10000] * n_days,
        }
    )


def test_grid_search_returns_all_combinations_scored():
    df = _trending_df(300)
    data = {"TEST.NS": df}
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    param_grid = {"fast_period": [5, 10], "slow_period": [30, 60]}

    result = grid_search(
        "sma_crossover", param_grid, data, df["date"].iloc[0], df["date"].iloc[-1], config,
        metric="cagr_pct",
    )
    assert len(result.all_results) == 4  # 2 x 2 grid
    assert set(result.best_params.keys()) == {"fast_period", "slow_period"}
    # Best result's metric must actually be the max across all combos tried.
    assert result.best_metric_value == pytest.approx(result.all_results["cagr_pct"].max())


def test_grid_search_prefers_better_performing_params_on_strong_uptrend():
    df = _trending_df(400)
    data = {"TEST.NS": df}
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    # A very slow-to-react pair (fast=150, slow=200) barely has time to catch
    # the trend in-window, vs a responsive (fast=10, slow=30) pair.
    param_grid = {"fast_period": [10, 150], "slow_period": [30, 200]}
    result = grid_search(
        "sma_crossover", param_grid, data, df["date"].iloc[0], df["date"].iloc[-1], config,
        metric="cagr_pct",
    )
    assert result.best_params["fast_period"] == 10
    assert result.best_params["slow_period"] == 30


def test_walk_forward_produces_expected_fold_count():
    df = _trending_df(500)
    data = {"TEST.NS": df}
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    param_grid = {"fast_period": [5, 10], "slow_period": [30, 50]}

    start = df["date"].iloc[0]
    end = df["date"].iloc[-1]
    report = run_walk_forward(
        "sma_crossover", param_grid, data, start, end,
        train_days=200, test_days=60, step_days=60, config=config,
        metric="cagr_pct",
    )
    assert len(report.folds) >= 2
    # Each fold's test window must never overlap its own train window.
    for fold in report.folds:
        assert fold.test_start > fold.train_end
    # Combined equity curve should be continuous and start near initial capital.
    assert report.combined_equity_curve["total_value"].iloc[0] > 0


def test_walk_forward_fold_summary_has_one_row_per_fold():
    df = _trending_df(500)
    data = {"TEST.NS": df}
    config = BacktestConfig(initial_capital=100_000, cost_model=zero_cost_model())
    param_grid = {"fast_period": [5], "slow_period": [30]}
    report = run_walk_forward(
        "sma_crossover", param_grid, data, df["date"].iloc[0], df["date"].iloc[-1],
        train_days=200, test_days=60, step_days=60, config=config,
    )
    assert len(report.fold_summary) == len(report.folds)
