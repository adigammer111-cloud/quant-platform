from __future__ import annotations

import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from analytics.overfitting import check_walk_forward_report
from app.components import empty_state, fmt_num, fmt_pct, parse_param_grid, render_topbar, style_fig, warning_banner
from app.theme import COLORS
from backtesting.costs import TransactionCostModel
from backtesting.engine import BacktestConfig
from data.storage.repository import get_daily_prices
from data.universe import list_available_universes, universe_symbols
from optimization.walk_forward import run_walk_forward


def _timeline_chart(report) -> go.Figure:
    fig = go.Figure()
    for i, fold in enumerate(report.folds):
        y = len(report.folds) - i
        fig.add_trace(go.Scatter(
            x=[fold.train_start, fold.train_end], y=[y, y], mode="lines",
            line=dict(color=COLORS["accent_purple"], width=10), name="Train" if i == 0 else None,
            showlegend=i == 0, hovertemplate=f"Train fold {i+1}: {fold.train_start} → {fold.train_end}<extra></extra>",
        ))
        if fold.validation_start:
            fig.add_trace(go.Scatter(
                x=[fold.validation_start, fold.validation_end], y=[y, y], mode="lines",
                line=dict(color=COLORS["warning"], width=10), name="Validate" if i == 0 else None,
                showlegend=i == 0, hovertemplate=f"Validate fold {i+1}<extra></extra>",
            ))
        fig.add_trace(go.Scatter(
            x=[fold.test_start, fold.test_end], y=[y, y], mode="lines",
            line=dict(color=COLORS["accent_cyan"], width=10), name="Test (OOS)" if i == 0 else None,
            showlegend=i == 0, hovertemplate=f"Test fold {i+1}: {fold.test_start} → {fold.test_end}<extra></extra>",
        ))
    fig.update_yaxes(showticklabels=False, title="Fold (newest at top)")
    fig.update_layout(height=max(200, 40 * len(report.folds)))
    style_fig(fig, height=max(200, 40 * len(report.folds)), title="Train / Validate / Test Timeline")
    return fig


def render() -> None:
    render_topbar("Walk Forward", "Rolling re-optimization with strictly out-of-sample evaluation per fold")

    c1, c2 = st.columns(2)
    strategy_name_input = c1.text_input("Strategy name (registry key)", "sma_crossover")
    universe = c2.selectbox("Universe", list_available_universes())
    param_text = st.text_area("Parameter grid (name=v1,v2,v3 per line)", "fast_period=10,20\nslow_period=50,100")

    c1, c2, c3 = st.columns(3)
    start = c1.date_input("Overall start", dt.date(2016, 1, 1))
    end = c1.date_input("Overall end", dt.date.today())
    train_days = c2.number_input("Train window (days)", value=730)
    test_days = c2.number_input("Test window (days)", value=180)
    step_days = c3.number_input("Step size (days)", value=180)
    metric = c3.selectbox("Metric", ["sharpe_ratio", "cagr_pct"])
    capital = st.number_input("Initial capital", value=100_000.0, step=10_000.0)

    if st.button("Run Walk-Forward", type="primary", width="stretch"):
        symbols = universe_symbols(universe)
        data = {s: df for s in symbols if not (df := get_daily_prices(s)).empty}
        if not data:
            empty_state("No data", "Download this universe from System → Data first.")
            return
        param_grid = parse_param_grid(param_text)
        config = BacktestConfig(initial_capital=capital, cost_model=TransactionCostModel())

        with st.spinner("Running walk-forward analysis (this runs many backtests, can take a while)..."):
            try:
                report = run_walk_forward(
                    strategy_name_input, param_grid, data, start, end,
                    train_days=int(train_days), test_days=int(test_days), step_days=int(step_days),
                    config=config, metric=metric,
                )
            except ValueError as exc:
                empty_state("Could not build any folds", str(exc))
                return
        st.session_state["walk_forward_report"] = report

    if "walk_forward_report" not in st.session_state:
        empty_state("No walk-forward run yet", "Configure the windows above and click Run Walk-Forward.")
        return

    report = st.session_state["walk_forward_report"]
    cm = report.combined_metrics

    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Combined OOS CAGR", fmt_pct(cm.cagr_pct))
    m2.metric("Combined OOS Sharpe", fmt_num(cm.sharpe_ratio))
    m3.metric("Combined OOS Max DD", fmt_pct(cm.max_drawdown_pct))
    m4.metric("Total OOS Trades", str(cm.num_trades))

    overfitting_warnings = check_walk_forward_report(report)
    if overfitting_warnings:
        st.markdown("### Overfitting Warnings")
        for w in overfitting_warnings:
            warning_banner(w)

    st.write("")
    st.plotly_chart(_timeline_chart(report), width="stretch")

    st.write("")
    st.markdown("### Per-Fold Comparison")
    fig = go.Figure()
    folds_x = [f"Fold {i+1}" for i in range(len(report.folds))]
    fig.add_trace(go.Bar(x=folds_x, y=[f.train_metric_value for f in report.folds], name="In-sample (train)", marker_color=COLORS["accent_purple"]))
    if any(f.validation_metric_value is not None for f in report.folds):
        fig.add_trace(go.Bar(x=folds_x, y=[f.validation_metric_value or 0 for f in report.folds], name="Validation", marker_color=COLORS["warning"]))
    fig.add_trace(go.Bar(x=folds_x, y=[getattr(f.test_metrics, metric) for f in report.folds], name="Out-of-sample (test)", marker_color=COLORS["accent_cyan"]))
    fig.update_layout(barmode="group")
    style_fig(fig, height=380, title=f"{metric} by fold")
    st.plotly_chart(fig, width="stretch")

    st.write("")
    st.markdown("### Fold Detail")
    st.dataframe(report.fold_summary, width="stretch", hide_index=True)

    st.write("")
    st.markdown("### Combined Out-of-Sample Equity Curve")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=report.combined_equity_curve["date"], y=report.combined_equity_curve["total_value"],
        mode="lines", line=dict(color=COLORS["accent_cyan"], width=1.6),
        fill="tozeroy", fillcolor="rgba(76,201,240,0.06)",
    ))
    style_fig(fig, height=340)
    st.plotly_chart(fig, width="stretch")
