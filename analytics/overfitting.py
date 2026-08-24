"""Heuristic overfitting / data-mining-bias warnings. None of these are
proof a strategy is broken - they are the standard "smell tests" a
quant researcher runs before trusting a backtest, surfaced automatically
instead of relying on the user to remember to check.
"""
from __future__ import annotations

import pandas as pd

from analytics.performance import PerformanceMetrics

MIN_RELIABLE_TRADES = 30
UNREALISTIC_SHARPE = 3.0
UNREALISTIC_WIN_RATE_PCT = 80.0
HIGH_TURNOVER_RATIO = 50.0
TRAIN_TEST_DEGRADATION_RATIO = 0.5   # test metric below 50% of train metric -> flag
PARAM_INSTABILITY_CV = 0.5            # coefficient of variation threshold


def check_single_backtest(metrics: PerformanceMetrics) -> list[str]:
    warnings: list[str] = []
    if metrics.num_trades < MIN_RELIABLE_TRADES:
        warnings.append(
            f"Only {metrics.num_trades} closed trades - performance statistics "
            f"(win rate, profit factor, Sharpe) are not statistically reliable "
            f"below ~{MIN_RELIABLE_TRADES} trades."
        )
    if metrics.sharpe_ratio > UNREALISTIC_SHARPE:
        warnings.append(
            f"Sharpe ratio of {metrics.sharpe_ratio:.2f} is unusually high for a "
            f"daily-bar equity strategy - double-check for look-ahead bias or "
            f"an unrealistic cost/slippage assumption before trusting this."
        )
    if metrics.win_rate_pct > UNREALISTIC_WIN_RATE_PCT and metrics.num_trades >= 10:
        warnings.append(
            f"Win rate of {metrics.win_rate_pct:.1f}% is unusually high - verify "
            f"trade timing and exit logic are not accidentally peeking ahead."
        )
    if metrics.turnover_ratio > HIGH_TURNOVER_RATIO:
        warnings.append(
            f"Turnover ratio of {metrics.turnover_ratio:.1f}x is very high - "
            f"transaction costs and slippage will dominate returns at this "
            f"trading frequency; verify the cost model is realistic."
        )
    return warnings


def check_train_test_gap(
    train_metrics: PerformanceMetrics, test_metrics: PerformanceMetrics, metric_name: str = "sharpe_ratio"
) -> list[str]:
    warnings: list[str] = []
    train_value = getattr(train_metrics, metric_name)
    test_value = getattr(test_metrics, metric_name)
    if train_value > 0 and test_value <= 0:
        warnings.append(
            f"Out-of-sample {metric_name} ({test_value:.2f}) is non-positive while "
            f"in-sample {metric_name} was {train_value:.2f}: this strategy appears "
            f"highly optimized to the training period, with out-of-sample "
            f"performance significantly weaker."
        )
    elif train_value > 0 and test_value < train_value * TRAIN_TEST_DEGRADATION_RATIO:
        warnings.append(
            f"Out-of-sample {metric_name} ({test_value:.2f}) is less than "
            f"{TRAIN_TEST_DEGRADATION_RATIO:.0%} of in-sample {metric_name} "
            f"({train_value:.2f}) - possible overfitting to the training window."
        )
    return warnings


def check_parameter_stability(fold_summary: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    param_cols = [c for c in fold_summary.columns if c.startswith("param_")]
    for col in param_cols:
        series = pd.to_numeric(fold_summary[col], errors="coerce").dropna()
        if len(series) < 2 or series.mean() == 0:
            continue
        cv = series.std() / abs(series.mean())
        if cv > PARAM_INSTABILITY_CV:
            warnings.append(
                f"Optimal '{col.replace('param_', '')}' varies substantially across "
                f"walk-forward folds (coefficient of variation {cv:.2f}) - the "
                f"'best' parameter value may just be noise rather than a stable edge."
            )
    return warnings


def check_walk_forward_report(report) -> list[str]:
    """`report`: an optimization.walk_forward.WalkForwardReport."""
    warnings: list[str] = []
    warnings.extend(check_single_backtest(report.combined_metrics))
    warnings.extend(check_parameter_stability(report.fold_summary))
    positive_folds = (report.fold_summary["test_metric"] > 0).sum()
    total_folds = len(report.fold_summary)
    if total_folds > 0 and positive_folds / total_folds < 0.5:
        warnings.append(
            f"Only {positive_folds}/{total_folds} walk-forward test folds were "
            f"profitable on the chosen metric - performance is inconsistent "
            f"across time periods."
        )
    return warnings
