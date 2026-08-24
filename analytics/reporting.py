"""Text/table report generation and CSV/Excel/JSON export for a completed
backtest. Keeps presentation logic separate from `performance.py` (metric
math) and `engine.py` (simulation).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analytics.performance import PerformanceMetrics


def monthly_returns_table(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Year x Month table of % returns - the 'monthly returns heatmap' data."""
    df = equity_curve.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    monthly = df["total_value"].resample("ME").last()
    monthly_returns = monthly.pct_change() * 100
    # First month's return should be measured from the starting equity, not NaN.
    if len(monthly) > 0:
        first_start_value = df["total_value"].iloc[0]
        monthly_returns.iloc[0] = (monthly.iloc[0] / first_start_value - 1) * 100

    table = monthly_returns.to_frame("return_pct")
    table["year"] = table.index.year
    table["month"] = table.index.strftime("%b")
    pivot = table.pivot_table(index="year", columns="month", values="return_pct")
    month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot = pivot.reindex(columns=[m for m in month_order if m in pivot.columns])
    return pivot


def build_round_trip_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Pairs each opening fill with its closing fill to produce one row per
    completed round-trip trade (entry date/price, exit date/price, holding
    period, total costs, net P&L after costs, return %) - the format used
    by the trade table UI. `realized_pnl` on the closing fill is
    price-only (see backtesting/execution.py); this adds transaction costs
    from both legs to get the true net P&L.
    """
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "symbol", "side", "entry_date", "entry_price", "exit_date", "exit_price",
                "quantity", "holding_period_days", "costs", "net_pnl", "return_pct", "exit_reason",
            ]
        )

    rows = []
    for symbol, group in trades.sort_values("execution_date").groupby("symbol"):
        open_trade = None
        for _, trade in group.iterrows():
            if pd.isna(trade["realized_pnl"]):
                open_trade = trade
                continue
            if open_trade is None:
                continue  # closing fill with no matching open in this slice - skip defensively
            total_costs = float(open_trade["costs"]) + float(trade["costs"])
            net_pnl = float(trade["realized_pnl"]) - total_costs
            notional = float(open_trade["execution_price"]) * float(open_trade["quantity"])
            rows.append(
                {
                    "symbol": symbol,
                    "side": "LONG" if open_trade["side"] == "BUY" else "SHORT",
                    "entry_date": open_trade["execution_date"],
                    "entry_price": open_trade["execution_price"],
                    "exit_date": trade["execution_date"],
                    "exit_price": trade["execution_price"],
                    "quantity": open_trade["quantity"],
                    "holding_period_days": trade["holding_period_days"],
                    "costs": total_costs,
                    "net_pnl": net_pnl,
                    "return_pct": (net_pnl / notional * 100) if notional else 0.0,
                    "exit_reason": trade["exit_reason"],
                }
            )
            open_trade = None

    return pd.DataFrame(rows).sort_values("exit_date").reset_index(drop=True) if rows else pd.DataFrame(
        columns=[
            "symbol", "side", "entry_date", "entry_price", "exit_date", "exit_price",
            "quantity", "holding_period_days", "costs", "net_pnl", "return_pct", "exit_reason",
        ]
    )


def format_metrics_table(metrics: PerformanceMetrics, label: str = "Strategy") -> str:
    d = metrics.to_dict()
    lines = [f"{label} Performance", "=" * 40]
    groups = {
        "Returns": ["initial_capital", "final_capital", "absolute_return_pct", "cagr_pct", "annualized_return_pct"],
        "Risk": [
            "max_drawdown_pct", "avg_drawdown_pct", "volatility_annualized_pct",
            "downside_deviation_pct", "value_at_risk_95_pct", "expected_shortfall_95_pct",
        ],
        "Risk-Adjusted": ["sharpe_ratio", "sortino_ratio", "calmar_ratio"],
        "Trading": [
            "num_trades", "winning_trades", "losing_trades", "win_rate_pct",
            "avg_win", "avg_loss", "profit_factor", "expectancy",
            "avg_holding_period_days", "max_consecutive_wins",
            "max_consecutive_losses", "turnover_ratio",
        ],
    }
    for group, keys in groups.items():
        lines.append(f"\n{group}:")
        for k in keys:
            v = d[k]
            if isinstance(v, float):
                v = round(v, 4)
            lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def benchmark_comparison_text(strategy: PerformanceMetrics, benchmark: PerformanceMetrics, benchmark_label: str) -> str:
    lines = [
        f"\nBenchmark Comparison ({benchmark_label}):",
        "=" * 40,
        f"  Strategy CAGR:      {strategy.cagr_pct:.2f}%   Benchmark CAGR:      {benchmark.cagr_pct:.2f}%",
        f"  Strategy Max DD:    {strategy.max_drawdown_pct:.2f}%   Benchmark Max DD:    {benchmark.max_drawdown_pct:.2f}%",
        f"  Strategy Sharpe:    {strategy.sharpe_ratio:.2f}     Benchmark Sharpe:    {benchmark.sharpe_ratio:.2f}",
        f"  Strategy Return:    {strategy.absolute_return_pct:.2f}%   Benchmark Return:    {benchmark.absolute_return_pct:.2f}%",
    ]
    return "\n".join(lines)


def export_backtest_results(
    output_dir: Path,
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: PerformanceMetrics,
    monthly_table: pd.DataFrame,
    fmt: str = "csv",
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if fmt == "csv":
        p1 = output_dir / "equity_curve.csv"
        equity_curve.to_csv(p1, index=False)
        written.append(p1)
        p2 = output_dir / "trades.csv"
        trades.to_csv(p2, index=False)
        written.append(p2)
        p3 = output_dir / "metrics.csv"
        pd.DataFrame([metrics.to_dict()]).to_csv(p3, index=False)
        written.append(p3)
        p4 = output_dir / "monthly_returns.csv"
        monthly_table.to_csv(p4)
        written.append(p4)
    elif fmt == "excel":
        p = output_dir / "backtest_report.xlsx"
        with pd.ExcelWriter(p, engine="xlsxwriter") as writer:
            equity_curve.to_excel(writer, sheet_name="equity_curve", index=False)
            trades.to_excel(writer, sheet_name="trades", index=False)
            pd.DataFrame([metrics.to_dict()]).to_excel(writer, sheet_name="metrics", index=False)
            monthly_table.to_excel(writer, sheet_name="monthly_returns")
        written.append(p)
    elif fmt == "json":
        p = output_dir / "backtest_report.json"
        payload = {
            "metrics": metrics.to_dict(),
            "equity_curve": json.loads(equity_curve.to_json(orient="records", date_format="iso")),
            "trades": json.loads(trades.to_json(orient="records", date_format="iso")),
            "monthly_returns": json.loads(monthly_table.reset_index().to_json(orient="records")),
        }
        p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        written.append(p)
    else:
        raise ValueError(f"Unknown export format: {fmt}")

    return written
