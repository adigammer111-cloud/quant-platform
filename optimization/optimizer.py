"""Parameter optimization: grid search and Optuna-based search.

Both operate strictly within a caller-supplied [start, end] window - this
module has no opinion about train/validation/test splits; that discipline
lives in `optimization/walk_forward.py`, which calls into this module once
per fold using only that fold's training window. Optimizing across an
entire dataset and reporting the in-sample result as if it were reliable is
exactly the mistake walk-forward analysis exists to avoid (see module
docstring there).
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from analytics.performance import PerformanceMetrics, compute_performance_metrics
from backtesting.engine import BacktestConfig, BacktestEngine
from strategies.registry import build_strategy

logger = logging.getLogger(__name__)


def _run_single(
    strategy_name: str,
    params: dict,
    data: dict[str, pd.DataFrame],
    start: date,
    end: date,
    config: BacktestConfig,
    risk_overrides: dict | None = None,
) -> PerformanceMetrics | None:
    strategy = build_strategy(strategy_name, params, risk_overrides=risk_overrides)
    engine = BacktestEngine(config)
    try:
        result = engine.run(strategy, data, start_date=start, end_date=end)
    except ValueError as exc:
        logger.warning("Skipping params %s: %s", params, exc)
        return None
    return compute_performance_metrics(result.equity_curve, result.trades, config.initial_capital)


@dataclass
class OptimizationResult:
    best_params: dict
    best_metric_value: float
    metric_name: str
    all_results: pd.DataFrame  # one row per parameter combination tried


def grid_search(
    strategy_name: str,
    param_grid: dict[str, list],
    data: dict[str, pd.DataFrame],
    start: date,
    end: date,
    config: BacktestConfig,
    metric: str = "sharpe_ratio",
    maximize: bool = True,
    risk_overrides: dict | None = None,
) -> OptimizationResult:
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    rows = []
    for combo in combos:
        params = dict(zip(keys, combo))
        metrics = _run_single(strategy_name, params, data, start, end, config, risk_overrides)
        row = dict(params)
        if metrics is None:
            row[metric] = float("-inf") if maximize else float("inf")
            row["num_trades"] = 0
        else:
            row.update(metrics.to_dict())
        rows.append(row)

    results_df = pd.DataFrame(rows)
    results_df = results_df.sort_values(metric, ascending=not maximize).reset_index(drop=True)
    best_idx = results_df.index[0]
    # Column-wise .at access (not row-wise .iloc[0]) - a row mixing int and
    # float columns (e.g. fast_period=5 alongside sharpe_ratio=1.87) gets
    # silently upcast to a single float64 Series by .iloc[0], turning
    # fast_period=5 into 5.0. pandas .rolling(min_periods=...) then rejects
    # that float when best_params is reused to build the next strategy run.
    best_params = {k: results_df.at[best_idx, k] for k in keys}
    best_params = {k: (v.item() if hasattr(v, "item") else v) for k, v in best_params.items()}

    return OptimizationResult(
        best_params=best_params,
        best_metric_value=float(results_df.at[best_idx, metric]),
        metric_name=metric,
        all_results=results_df,
    )


def optuna_search(
    strategy_name: str,
    param_space: dict[str, tuple],
    data: dict[str, pd.DataFrame],
    start: date,
    end: date,
    config: BacktestConfig,
    n_trials: int = 50,
    metric: str = "sharpe_ratio",
    maximize: bool = True,
    seed: int | None = None,
    risk_overrides: dict | None = None,
) -> OptimizationResult:
    """`param_space`: {name: (low, high)} for float/int ranges (int if both
    bounds are ints), or {name: [choice1, choice2, ...]} for categorical."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    rows: list[dict] = []

    def objective(trial: "optuna.Trial") -> float:
        params = {}
        for name, spec in param_space.items():
            if isinstance(spec, (list, tuple)) and len(spec) > 2:
                params[name] = trial.suggest_categorical(name, list(spec))
            elif isinstance(spec, tuple) and len(spec) == 2:
                low, high = spec
                if isinstance(low, int) and isinstance(high, int):
                    params[name] = trial.suggest_int(name, low, high)
                else:
                    params[name] = trial.suggest_float(name, low, high)
            else:
                raise ValueError(f"Unsupported param_space spec for '{name}': {spec}")

        metrics = _run_single(strategy_name, params, data, start, end, config, risk_overrides)
        row = dict(params)
        if metrics is None:
            value = float("-inf") if maximize else float("inf")
            row["num_trades"] = 0
        else:
            row.update(metrics.to_dict())
            value = getattr(metrics, metric)
        row[metric] = value
        rows.append(row)
        return value

    sampler = optuna.samplers.TPESampler(seed=seed)
    direction = "maximize" if maximize else "minimize"
    study = optuna.create_study(direction=direction, sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    results_df = pd.DataFrame(rows).sort_values(metric, ascending=not maximize).reset_index(drop=True)
    return OptimizationResult(
        best_params=study.best_params,
        best_metric_value=study.best_value,
        metric_name=metric,
        all_results=results_df,
    )
