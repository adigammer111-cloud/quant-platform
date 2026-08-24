"""Walk-forward analysis: repeatedly optimize on a rolling training window
and evaluate the chosen parameters on the immediately-following, never-
optimized-on test window. This is what stands between "this strategy has a
great backtest" and "this strategy might actually hold up out of sample" -
see `analytics/overfitting.py` for the diagnostics run on the results.

Each fold:
    [train_start ............ train_end] -> optimize -> best_params
    [validation_start .. validation_end] -> evaluate best_params (reported only)
    [test_start ................ test_end] -> evaluate best_params (the fold's real OOS result)

The composite out-of-sample equity curve chains each fold's test-period
result together (fold N+1 starts with fold N's ending capital), giving one
continuous "what if you had actually traded this way" curve rather than
just an average of disconnected metrics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from analytics.performance import PerformanceMetrics, compute_performance_metrics
from backtesting.engine import BacktestConfig, BacktestEngine
from optimization.optimizer import _run_single, grid_search
from strategies.registry import build_strategy

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    train_start: date
    train_end: date
    validation_start: date | None
    validation_end: date | None
    test_start: date
    test_end: date
    best_params: dict
    train_metric_value: float
    validation_metric_value: float | None
    test_metrics: PerformanceMetrics
    test_equity_curve: pd.DataFrame
    test_trades: pd.DataFrame


@dataclass
class WalkForwardReport:
    folds: list[WalkForwardFold]
    combined_equity_curve: pd.DataFrame
    combined_metrics: PerformanceMetrics
    fold_summary: pd.DataFrame  # one row per fold, easy to inspect/export


def _shift_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def run_walk_forward(
    strategy_name: str,
    param_grid: dict[str, list],
    data: dict[str, pd.DataFrame],
    overall_start: date,
    overall_end: date,
    train_days: int,
    test_days: int,
    step_days: int,
    config: BacktestConfig,
    validation_days: int = 0,
    metric: str = "sharpe_ratio",
    maximize: bool = True,
    risk_overrides: dict | None = None,
) -> WalkForwardReport:
    folds: list[WalkForwardFold] = []
    running_capital = config.initial_capital
    cursor = overall_start

    while True:
        train_start = cursor
        train_end = _shift_days(train_start, train_days - 1)
        val_start = val_end = None
        if validation_days > 0:
            val_start = _shift_days(train_end, 1)
            val_end = _shift_days(val_start, validation_days - 1)
            test_start = _shift_days(val_end, 1)
        else:
            test_start = _shift_days(train_end, 1)
        test_end = _shift_days(test_start, test_days - 1)

        if test_end > overall_end:
            break

        fold_config = BacktestConfig(
            initial_capital=running_capital,
            cost_model=config.cost_model,
            execution_price_field=config.execution_price_field,
            benchmark_symbol=config.benchmark_symbol,
        )

        opt_result = grid_search(
            strategy_name, param_grid, data, train_start, train_end, fold_config,
            metric=metric, maximize=maximize, risk_overrides=risk_overrides,
        )
        best_params = opt_result.best_params

        val_metric_value = None
        if val_start:
            val_metrics = _run_single(
                strategy_name, best_params, data, val_start, val_end, fold_config, risk_overrides
            )
            val_metric_value = getattr(val_metrics, metric) if val_metrics else None

        strategy = build_strategy(strategy_name, best_params, risk_overrides=risk_overrides)
        engine = BacktestEngine(fold_config)
        try:
            test_result = engine.run(strategy, data, start_date=test_start, end_date=test_end)
        except ValueError as exc:
            logger.warning("Fold [%s -> %s] test period skipped: %s", test_start, test_end, exc)
            cursor = _shift_days(cursor, step_days)
            continue

        test_metrics = compute_performance_metrics(
            test_result.equity_curve, test_result.trades, fold_config.initial_capital
        )

        folds.append(
            WalkForwardFold(
                train_start=train_start, train_end=train_end,
                validation_start=val_start, validation_end=val_end,
                test_start=test_start, test_end=test_end,
                best_params=best_params,
                train_metric_value=opt_result.best_metric_value,
                validation_metric_value=val_metric_value,
                test_metrics=test_metrics,
                test_equity_curve=test_result.equity_curve,
                test_trades=test_result.trades,
            )
        )
        running_capital = float(test_result.equity_curve["total_value"].iloc[-1])
        cursor = _shift_days(cursor, step_days)

    if not folds:
        raise ValueError(
            "No walk-forward folds could be generated - check that "
            "overall_start/overall_end are wide enough for train_days + "
            "test_days (+ validation_days)."
        )

    combined_curve = _chain_equity_curves([f.test_equity_curve for f in folds], config.initial_capital)
    combined_trades = pd.concat([f.test_trades for f in folds], ignore_index=True) if folds else pd.DataFrame()
    combined_metrics = compute_performance_metrics(combined_curve, combined_trades, config.initial_capital)

    fold_summary = pd.DataFrame(
        [
            {
                "fold": i + 1,
                "train_start": f.train_start, "train_end": f.train_end,
                "test_start": f.test_start, "test_end": f.test_end,
                **{f"param_{k}": v for k, v in f.best_params.items()},
                "train_metric": f.train_metric_value,
                "validation_metric": f.validation_metric_value,
                "test_metric": getattr(f.test_metrics, metric),
                "test_cagr_pct": f.test_metrics.cagr_pct,
                "test_num_trades": f.test_metrics.num_trades,
            }
            for i, f in enumerate(folds)
        ]
    )

    return WalkForwardReport(
        folds=folds,
        combined_equity_curve=combined_curve,
        combined_metrics=combined_metrics,
        fold_summary=fold_summary,
    )


def _chain_equity_curves(curves: list[pd.DataFrame], initial_capital: float) -> pd.DataFrame:
    """Concatenate fold equity curves end-to-end. Each fold already starts
    from the previous fold's ending capital (see running_capital above), so
    this just stitches the date-indexed rows together without re-scaling."""
    chained = pd.concat([c for c in curves if not c.empty], ignore_index=True)
    chained = chained.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    prev_total = initial_capital
    daily_returns = []
    for total in chained["total_value"]:
        daily_returns.append((total / prev_total - 1) if prev_total else 0.0)
        prev_total = total
    chained["daily_return"] = daily_returns
    chained["cummax"] = chained["total_value"].cummax()
    chained["drawdown"] = chained["total_value"] / chained["cummax"] - 1
    return chained
