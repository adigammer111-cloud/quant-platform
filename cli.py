"""Command-line entry point for the quant platform.

Run from the project root (quant_platform/), e.g.:

    .venv\\Scripts\\python.exe cli.py update-data --universe sample_watchlist
    .venv\\Scripts\\python.exe cli.py data-status
"""
from __future__ import annotations

import logging

import typer

from logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, help="Quant research & backtesting platform CLI")


@app.command("update-data")
def update_data(
    universe: str = typer.Option(
        "sample_watchlist", help="Universe CSV name under configs/universes/"
    ),
    full_refresh: bool = typer.Option(
        False, help="Re-download full history instead of only the missing tail"
    ),
    history_days: int = typer.Option(
        3650, help="Lookback window (days) for symbols with no existing data"
    ),
):
    """Download/update daily OHLCV + corporate actions for a universe."""
    from data.providers.factory import get_provider
    from data.ingestion.downloader import update_universe
    from database.db import ensure_database

    ensure_database()
    provider = get_provider()
    logger.info("Using provider: %s", provider.name)
    results = update_universe(provider, universe, full_refresh=full_refresh, history_days=history_days)

    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    typer.echo(
        f"\nUpdate complete: {len(ok)} symbols OK, {len(failed)} failed, "
        f"{sum(r.rows_written for r in results)} rows written."
    )
    for r in failed:
        typer.echo(f"  FAILED {r.symbol}: {r.error}")


@app.command("data-status")
def data_status():
    """Show what's currently in the database."""
    from data.storage.repository import get_data_status
    from database.db import ensure_database

    ensure_database()
    df = get_data_status()
    if df.empty:
        typer.echo("No data in database yet. Run 'update-data' first.")
        return
    typer.echo(df.to_string(index=False))


@app.command("quality-report")
def quality_report(symbol: str):
    """Print a data-quality report for a single symbol already in the DB."""
    from data.storage.repository import get_daily_prices, get_corporate_actions
    from data.validation.quality import validate_daily_prices
    from database.db import ensure_database

    ensure_database()
    df = get_daily_prices(symbol)
    if df.empty:
        typer.echo(f"No data for {symbol}. Run 'update-data' first.")
        raise typer.Exit(code=1)
    corp_actions = get_corporate_actions(symbol)
    report = validate_daily_prices(symbol, df, corporate_actions=corp_actions)
    typer.echo(report.to_text())


@app.command("list-strategies")
def list_strategies():
    """List available strategy names and their default parameters."""
    from strategies.registry import STRATEGY_REGISTRY

    for name, cls in STRATEGY_REGISTRY.items():
        instance = cls()
        typer.echo(f"{name} (v{instance.version}): {instance.params}")


@app.command("backtest")
def backtest(
    config: str = typer.Option(
        None, "--config", help="Path to a YAML backtest config (see configs/strategies/*.yaml)"
    ),
    strategy: str = typer.Option(None, help="Strategy name (ignored if --config is given)"),
    universe: str = typer.Option(None, help="Universe CSV name, e.g. sample_watchlist"),
    symbol: list[str] = typer.Option(None, help="Symbol(s) to backtest, e.g. RELIANCE.NS (repeatable)"),
    start: str = typer.Option(None, help="Start date YYYY-MM-DD"),
    end: str = typer.Option(None, help="End date YYYY-MM-DD"),
    capital: float = typer.Option(100_000.0, help="Initial capital"),
    benchmark: str = typer.Option(None, help="Benchmark symbol, e.g. ^NSEI"),
    export_dir: str = typer.Option(None, help="Directory to export CSV/Excel/JSON reports to"),
    export_format: str = typer.Option("csv", help="csv | excel | json"),
):
    """Run a backtest and print a full performance report."""
    import datetime as dt

    from pathlib import Path

    from backtesting.engine import BacktestConfig
    from backtesting.runner import run_backtest
    from data.universe import universe_symbols
    from database.db import ensure_database
    from analytics.reporting import format_metrics_table, benchmark_comparison_text

    ensure_database()

    if config:
        from configs.loader import load_backtest_config

        loaded = load_backtest_config(config)
        strategy_name = loaded.strategy_name
        params = loaded.parameters
        symbols = loaded.symbols or (universe_symbols(loaded.universe) if loaded.universe else [])
        start_date = loaded.start_date
        end_date = loaded.end_date or dt.date.today()
        initial_capital = loaded.initial_capital
        cost_model = loaded.cost_model
        benchmark_symbol = loaded.benchmark_symbol
        exec_field = loaded.execution_price_field
        risk_cfg = loaded.risk
        index_bias_check = loaded.universe
    else:
        if not strategy:
            typer.echo("Error: either --config or --strategy is required.")
            raise typer.Exit(code=1)
        strategy_name = strategy
        params = {}
        symbols = list(symbol) if symbol else (universe_symbols(universe) if universe else [])
        start_date = dt.datetime.strptime(start, "%Y-%m-%d").date() if start else None
        end_date = dt.datetime.strptime(end, "%Y-%m-%d").date() if end else dt.date.today()
        initial_capital = capital
        from backtesting.costs import TransactionCostModel

        cost_model = TransactionCostModel()
        benchmark_symbol = benchmark
        exec_field = "open"
        risk_cfg = {}
        index_bias_check = universe

    if not symbols:
        typer.echo("Error: no symbols resolved. Pass --symbol, --universe, or a --config with a universe.")
        raise typer.Exit(code=1)
    if not start_date:
        typer.echo("Error: --start (or period.start in --config) is required.")
        raise typer.Exit(code=1)

    bt_config = BacktestConfig(
        initial_capital=initial_capital,
        cost_model=cost_model,
        execution_price_field=exec_field,
        benchmark_symbol=benchmark_symbol,
    )

    output = run_backtest(
        strategy_name=strategy_name,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        params=params,
        risk_overrides=risk_cfg,
        config=bt_config,
        benchmark_symbol=benchmark_symbol,
        index_name_for_bias_check=index_bias_check,
        export_dir=Path(export_dir) if export_dir else None,
        export_formats=(export_format,),
    )

    typer.echo(f"\nBacktest ID: {output.backtest_id}")
    if output.result.warnings:
        for w in output.result.warnings:
            typer.echo(f"WARNING: {w}")
    typer.echo(format_metrics_table(output.metrics, label=f"{strategy_name} on {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}"))
    if output.benchmark_metrics:
        typer.echo(benchmark_comparison_text(output.metrics, output.benchmark_metrics, benchmark_symbol))
    if output.exported_files:
        typer.echo(f"\nExported: {[str(p) for p in output.exported_files]}")


@app.command("list-backtests")
def list_backtests():
    """List saved backtest runs."""
    from database.backtest_repository import list_backtest_runs
    from database.db import ensure_database

    ensure_database()
    df = list_backtest_runs()
    if df.empty:
        typer.echo("No backtests saved yet.")
        return
    typer.echo(df.to_string(index=False))


@app.command("show-backtest")
def show_backtest(backtest_id: str):
    """Show details and trades for a saved backtest run."""
    from database.backtest_repository import get_backtest_run, get_backtest_trades
    from database.db import ensure_database

    ensure_database()
    run = get_backtest_run(backtest_id)
    for k, v in run.items():
        typer.echo(f"{k}: {v}")
    trades = get_backtest_trades(backtest_id)
    typer.echo(f"\n{len(trades)} trades:")
    typer.echo(trades.to_string(index=False))


@app.command("optimize")
def optimize(
    strategy: str = typer.Option(..., help="Strategy name"),
    universe: str = typer.Option(None, help="Universe CSV name"),
    symbol: list[str] = typer.Option(None, help="Symbol(s) (repeatable), alternative to --universe"),
    param: list[str] = typer.Option(
        ..., help="Parameter grid entry as name=v1,v2,v3 (repeatable), e.g. fast_period=10,20,30"
    ),
    train_start: str = typer.Option(..., help="Training window start YYYY-MM-DD"),
    train_end: str = typer.Option(..., help="Training window end YYYY-MM-DD"),
    test_start: str = typer.Option(None, help="Optional out-of-sample test window start"),
    test_end: str = typer.Option(None, help="Optional out-of-sample test window end"),
    metric: str = typer.Option("sharpe_ratio", help="Metric to optimize (e.g. sharpe_ratio, cagr_pct)"),
    capital: float = typer.Option(100_000.0, help="Initial capital"),
):
    """Grid-search strategy parameters on a training window, then report
    out-of-sample performance on a separate test window if given."""
    import datetime as dt

    from analytics.overfitting import check_single_backtest
    from analytics.performance import compute_performance_metrics
    from analytics.reporting import format_metrics_table
    from backtesting.engine import BacktestConfig, BacktestEngine
    from backtesting.costs import TransactionCostModel
    from data.storage.repository import get_daily_prices
    from data.universe import universe_symbols
    from database.db import ensure_database
    from optimization.optimizer import grid_search
    from strategies.registry import build_strategy

    ensure_database()

    symbols = list(symbol) if symbol else (universe_symbols(universe) if universe else [])
    if not symbols:
        typer.echo("Error: pass --symbol or --universe.")
        raise typer.Exit(code=1)

    param_grid = {}
    for p in param:
        name, values = p.split("=", 1)
        parsed = []
        for v in values.split(","):
            try:
                parsed.append(int(v))
            except ValueError:
                try:
                    parsed.append(float(v))
                except ValueError:
                    parsed.append(v)
        param_grid[name] = parsed

    data = {s: df for s in symbols if not (df := get_daily_prices(s)).empty}
    if not data:
        typer.echo("Error: no data found for requested symbols. Run 'update-data' first.")
        raise typer.Exit(code=1)

    config = BacktestConfig(initial_capital=capital, cost_model=TransactionCostModel())
    train_start_d = dt.datetime.strptime(train_start, "%Y-%m-%d").date()
    train_end_d = dt.datetime.strptime(train_end, "%Y-%m-%d").date()

    result = grid_search(strategy, param_grid, data, train_start_d, train_end_d, config, metric=metric)
    typer.echo(f"\nBest params (by {metric} on training window): {result.best_params}")
    typer.echo(f"Training {metric}: {result.best_metric_value:.4f}")
    typer.echo(f"\nAll combinations tried (top 10):\n{result.all_results.head(10).to_string(index=False)}")

    if test_start and test_end:
        test_start_d = dt.datetime.strptime(test_start, "%Y-%m-%d").date()
        test_end_d = dt.datetime.strptime(test_end, "%Y-%m-%d").date()
        best_strategy = build_strategy(strategy, result.best_params)
        engine = BacktestEngine(config)
        test_result = engine.run(best_strategy, data, start_date=test_start_d, end_date=test_end_d)
        test_metrics = compute_performance_metrics(test_result.equity_curve, test_result.trades, capital)
        typer.echo(format_metrics_table(test_metrics, label="Out-of-sample test window"))

        train_value = result.best_metric_value
        test_value = getattr(test_metrics, metric)
        typer.echo(f"\nTraining {metric}: {train_value:.4f}  |  Test {metric}: {test_value:.4f}")

        warnings = check_single_backtest(test_metrics)
        if train_value > 0 and test_value <= 0:
            warnings.append(
                f"Out-of-sample {metric} ({test_value:.2f}) is non-positive while "
                f"training {metric} was {train_value:.2f}: this strategy appears "
                f"highly optimized to the training period."
            )
        for w in warnings:
            typer.echo(f"OVERFITTING WARNING: {w}")


@app.command("walk-forward")
def walk_forward_cmd(
    strategy: str = typer.Option(..., help="Strategy name"),
    universe: str = typer.Option(None, help="Universe CSV name"),
    symbol: list[str] = typer.Option(None, help="Symbol(s) (repeatable)"),
    param: list[str] = typer.Option(..., help="Parameter grid entry name=v1,v2,v3 (repeatable)"),
    start: str = typer.Option(..., help="Overall window start YYYY-MM-DD"),
    end: str = typer.Option(..., help="Overall window end YYYY-MM-DD"),
    train_days: int = typer.Option(756, help="Training window length in days (~3 years default)"),
    test_days: int = typer.Option(126, help="Test window length in days (~6 months default)"),
    step_days: int = typer.Option(126, help="Step size between folds"),
    metric: str = typer.Option("sharpe_ratio", help="Metric to optimize per fold"),
    capital: float = typer.Option(100_000.0, help="Initial capital"),
):
    """Run walk-forward analysis: repeatedly optimize on a rolling training
    window and evaluate out-of-sample on the following test window."""
    import datetime as dt

    from analytics.overfitting import check_walk_forward_report
    from backtesting.costs import TransactionCostModel
    from backtesting.engine import BacktestConfig
    from data.storage.repository import get_daily_prices
    from data.universe import universe_symbols
    from database.db import ensure_database
    from optimization.walk_forward import run_walk_forward

    ensure_database()
    symbols = list(symbol) if symbol else (universe_symbols(universe) if universe else [])
    if not symbols:
        typer.echo("Error: pass --symbol or --universe.")
        raise typer.Exit(code=1)

    param_grid = {}
    for p in param:
        name, values = p.split("=", 1)
        parsed = []
        for v in values.split(","):
            try:
                parsed.append(int(v))
            except ValueError:
                try:
                    parsed.append(float(v))
                except ValueError:
                    parsed.append(v)
        param_grid[name] = parsed

    data = {s: df for s in symbols if not (df := get_daily_prices(s)).empty}
    if not data:
        typer.echo("Error: no data found. Run 'update-data' first.")
        raise typer.Exit(code=1)

    config = BacktestConfig(initial_capital=capital, cost_model=TransactionCostModel())
    start_d = dt.datetime.strptime(start, "%Y-%m-%d").date()
    end_d = dt.datetime.strptime(end, "%Y-%m-%d").date()

    report = run_walk_forward(
        strategy, param_grid, data, start_d, end_d,
        train_days=train_days, test_days=test_days, step_days=step_days,
        config=config, metric=metric,
    )

    typer.echo(f"\n{len(report.folds)} walk-forward folds:")
    typer.echo(report.fold_summary.to_string(index=False))
    typer.echo(f"\nCombined out-of-sample CAGR: {report.combined_metrics.cagr_pct:.2f}%")
    typer.echo(f"Combined out-of-sample Sharpe: {report.combined_metrics.sharpe_ratio:.2f}")
    typer.echo(f"Combined out-of-sample Max Drawdown: {report.combined_metrics.max_drawdown_pct:.2f}%")

    for w in check_walk_forward_report(report):
        typer.echo(f"OVERFITTING WARNING: {w}")


if __name__ == "__main__":
    app()
