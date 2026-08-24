"""Persistence for backtest results: backtest_runs, backtest_trades,
backtest_equity_curve, strategy_parameters. Kept separate from
data/storage/repository.py (market data) since the two have unrelated write
patterns and callers.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

import pandas as pd

from backtesting.engine import BacktestResult
from database.db import get_connection

logger = logging.getLogger(__name__)


def generate_backtest_id(strategy_name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{strategy_name}_{uuid.uuid4().hex[:6]}"


def save_backtest_run(
    backtest_id: str,
    result: BacktestResult,
    software_version: str = "0.1.0",
) -> None:
    with get_connection() as con:
        con.execute(
            """
            INSERT INTO backtest_runs
                (backtest_id, strategy_name, strategy_version, parameters_json,
                 universe, start_date, end_date, initial_capital, cost_model_json,
                 slippage_bps, benchmark_symbol, random_seed, software_version,
                 dataset_snapshot_at, survivorship_biased, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                backtest_id,
                result.strategy_name,
                result.strategy_version,
                json.dumps(result.parameters, default=str),
                ",".join(result.universe),
                result.start_date,
                result.end_date,
                result.config.initial_capital,
                json.dumps(result.config.cost_model.to_dict()),
                result.config.cost_model.slippage_bps,
                result.config.benchmark_symbol,
                result.config.random_seed,
                software_version,
                datetime.now(),
                result.survivorship_biased,
                "COMPLETED",
                "; ".join(result.warnings),
            ],
        )

        if not result.trades.empty:
            trades = result.trades.copy()
            trades.insert(0, "backtest_id", backtest_id)
            con.register("trades_df", trades)
            con.execute(
                """
                INSERT INTO backtest_trades
                    (backtest_id, symbol, side, signal_date, execution_date,
                     execution_price, quantity, gross_amount, costs, net_amount,
                     realized_pnl, holding_period_days, exit_reason)
                SELECT backtest_id, symbol, side, signal_date, execution_date,
                       execution_price, quantity, gross_amount, costs, net_amount,
                       realized_pnl, holding_period_days, exit_reason
                FROM trades_df
                """
            )
            con.unregister("trades_df")

        if not result.equity_curve.empty:
            eq = result.equity_curve.copy()
            eq.insert(0, "backtest_id", backtest_id)
            eq = eq[["backtest_id", "date", "cash", "holdings_value", "total_value", "daily_return", "drawdown"]]
            con.register("eq_df", eq)
            con.execute(
                """
                INSERT INTO backtest_equity_curve
                    (backtest_id, date, cash, holdings_value, total_value, daily_return, drawdown)
                SELECT * FROM eq_df
                ON CONFLICT (backtest_id, date) DO NOTHING
                """
            )
            con.unregister("eq_df")

        param_rows = [
            (backtest_id, result.strategy_name, k, str(v), type(v).__name__)
            for k, v in result.parameters.items()
        ]
        if param_rows:
            con.executemany(
                """
                INSERT INTO strategy_parameters
                    (backtest_id, strategy_name, param_name, param_value, param_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                param_rows,
            )
    logger.info("Saved backtest run %s (%d trades)", backtest_id, len(result.trades))


def list_backtest_runs() -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            """
            SELECT backtest_id, created_at, strategy_name, universe, start_date,
                   end_date, initial_capital, survivorship_biased, status
            FROM backtest_runs ORDER BY created_at DESC
            """
        ).fetchdf()


def get_backtest_run(backtest_id: str) -> dict:
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT * FROM backtest_runs WHERE backtest_id = ?", [backtest_id]
        ).fetchdf()
    if row.empty:
        raise ValueError(f"No backtest run found with id {backtest_id}")
    return row.iloc[0].to_dict()


def get_backtest_trades(backtest_id: str) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            "SELECT * FROM backtest_trades WHERE backtest_id = ? ORDER BY execution_date",
            [backtest_id],
        ).fetchdf()


def get_backtest_equity_curve(backtest_id: str) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            "SELECT * FROM backtest_equity_curve WHERE backtest_id = ? ORDER BY date",
            [backtest_id],
        ).fetchdf()
