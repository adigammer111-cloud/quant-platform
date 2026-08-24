from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analytics.performance import compute_performance_metrics
from app.components import empty_state, fmt_num, fmt_pct, render_topbar, style_fig
from app.theme import COLORS
from database.backtest_repository import get_backtest_equity_curve, get_backtest_run, get_backtest_trades, list_backtest_runs


def render() -> None:
    render_topbar("Performance", "Compare multiple saved backtests side by side")

    runs = list_backtest_runs()
    if runs.empty:
        empty_state("No saved backtests", "Run a backtest first (Backtesting → Backtests).")
        return

    labels = [f"{r.backtest_id}  ({r.strategy_name})" for r in runs.itertuples()]
    label_to_id = dict(zip(labels, runs["backtest_id"]))
    selected = st.multiselect("Backtests to compare", labels, default=labels[: min(3, len(labels))])

    if not selected:
        empty_state("Select at least one backtest", "Use the picker above.")
        return

    colors = [COLORS["accent_cyan"], COLORS["accent_purple"], COLORS["profit"], COLORS["warning"], COLORS["loss"], "#5B7A99"]
    fig = go.Figure()
    rows = []
    for i, label in enumerate(selected):
        bt_id = label_to_id[label]
        equity = get_backtest_equity_curve(bt_id)
        trades = get_backtest_trades(bt_id)
        run_detail = get_backtest_run(bt_id)
        if equity.empty:
            continue
        metrics = compute_performance_metrics(equity, trades, float(run_detail["initial_capital"]))
        fig.add_trace(go.Scatter(
            x=equity["date"], y=equity["total_value"] / equity["total_value"].iloc[0] * 100,
            name=run_detail["strategy_name"] + " · " + bt_id[-6:], mode="lines",
            line=dict(color=colors[i % len(colors)], width=1.6),
        ))
        rows.append({
            "backtest_id": bt_id, "strategy": run_detail["strategy_name"], "universe": run_detail["universe"],
            "cagr_pct": round(metrics.cagr_pct, 2), "sharpe": round(metrics.sharpe_ratio, 2),
            "max_dd_pct": round(metrics.max_drawdown_pct, 2), "win_rate_pct": round(metrics.win_rate_pct, 1),
            "trades": metrics.num_trades, "profit_factor": round(metrics.profit_factor, 2),
        })

    fig.update_layout(yaxis_title="Normalized Equity (start = 100)")
    style_fig(fig, height=420, title="Equity Curves (normalized)")
    st.plotly_chart(fig, width="stretch")

    st.write("")
    st.markdown("### Metrics Comparison")
    st.dataframe(rows, width="stretch", hide_index=True)
