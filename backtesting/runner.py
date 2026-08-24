"""High-level orchestration: load data from the database, run a backtest,
score it against a benchmark, persist the run, and (optionally) export
reports. This is the function both the CLI and the Streamlit dashboard call
- neither should talk to the engine or the database directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from analytics.benchmark import build_buy_and_hold_curve
from analytics.performance import PerformanceMetrics, compute_performance_metrics
from analytics.reporting import export_backtest_results, monthly_returns_table
from backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from data.storage.repository import get_daily_prices
from data.universe import universe_is_survivorship_biased
from database.backtest_repository import generate_backtest_id, save_backtest_run
from strategies.base import Strategy
from strategies.registry import build_strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestRunOutput:
    backtest_id: str
    result: BacktestResult
    metrics: PerformanceMetrics
    monthly_table: pd.DataFrame
    benchmark_result: pd.DataFrame | None = None
    benchmark_metrics: PerformanceMetrics | None = None
    exported_files: list[Path] | None = None


def run_backtest(
    strategy_name: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
    params: dict | None = None,
    risk_overrides: dict | None = None,
    config: BacktestConfig | None = None,
    benchmark_symbol: str | None = None,
    index_name_for_bias_check: str | None = None,
    save_to_db: bool = True,
    export_dir: Path | None = None,
    export_formats: tuple[str, ...] = ("csv",),
    strategy_instance: Strategy | None = None,
) -> BacktestRunOutput:
    """`strategy_instance`: pass an already-constructed `Strategy` (e.g. a
    `RuleBasedStrategy` or `CustomCodeStrategy` from the Strategy Builder)
    to bypass the `strategies.registry` name lookup entirely - `strategy_name`
    is then used only for labeling (backtest id, saved-run metadata)."""
    strategy = strategy_instance or build_strategy(strategy_name, params, risk_overrides=risk_overrides)
    config = config or BacktestConfig()
    if benchmark_symbol:
        config.benchmark_symbol = benchmark_symbol

    data = {}
    for symbol in symbols:
        df = get_daily_prices(symbol)
        if df.empty:
            logger.warning("No data in database for %s - skipping. Run 'update-data' first.", symbol)
            continue
        data[symbol] = df
    if not data:
        raise ValueError(
            f"No data available in the database for any of {symbols}. "
            f"Run 'python cli.py update-data' first."
        )

    survivorship_biased = True
    if index_name_for_bias_check:
        survivorship_biased = universe_is_survivorship_biased(index_name_for_bias_check)

    engine = BacktestEngine(config)
    result = engine.run(strategy, data, start_date=start_date, end_date=end_date, survivorship_biased=survivorship_biased)
    metrics = compute_performance_metrics(result.equity_curve, result.trades, config.initial_capital)
    monthly_table = monthly_returns_table(result.equity_curve)

    benchmark_result = None
    benchmark_metrics = None
    if benchmark_symbol:
        bench_df = get_daily_prices(benchmark_symbol)
        if bench_df.empty:
            logger.warning("No data for benchmark %s - skipping benchmark comparison", benchmark_symbol)
        else:
            benchmark_result = build_buy_and_hold_curve(
                bench_df, config.initial_capital, result.start_date, result.end_date
            )
            empty_trades = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
            benchmark_metrics = compute_performance_metrics(
                benchmark_result, empty_trades, config.initial_capital
            )

    backtest_id = generate_backtest_id(strategy_name)
    if save_to_db:
        save_backtest_run(backtest_id, result)

    exported_files = None
    if export_dir:
        exported_files = export_backtest_results(
            export_dir, result.equity_curve, result.trades, metrics, monthly_table,
            fmt=export_formats[0] if export_formats else "csv",
        )
        for fmt in export_formats[1:]:
            exported_files += export_backtest_results(
                export_dir, result.equity_curve, result.trades, metrics, monthly_table, fmt=fmt
            )

    return BacktestRunOutput(
        backtest_id=backtest_id,
        result=result,
        metrics=metrics,
        monthly_table=monthly_table,
        benchmark_result=benchmark_result,
        benchmark_metrics=benchmark_metrics,
        exported_files=exported_files,
    )
