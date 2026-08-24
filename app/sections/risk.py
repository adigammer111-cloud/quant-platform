from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analytics.drawdown import drawdown_episodes, underwater_curve
from analytics.performance import compute_performance_metrics
from analytics.risk import historical_expected_shortfall, historical_var, rolling_cagr, rolling_sharpe
from app.components import empty_state, fmt_currency, fmt_num, fmt_pct, render_topbar, style_fig
from app.theme import COLORS
from database.backtest_repository import get_backtest_equity_curve, get_backtest_run, get_backtest_trades, list_backtest_runs


def render() -> None:
    render_topbar("Risk", "Rolling risk metrics, drawdown episodes, and tail-loss estimates")

    runs = list_backtest_runs()
    if runs.empty:
        empty_state("No saved backtests", "Run a backtest first (Backtesting → Backtests).")
        return

    backtest_id = st.selectbox("Backtest", runs["backtest_id"])
    equity = get_backtest_equity_curve(backtest_id)
    trades = get_backtest_trades(backtest_id)
    run_detail = get_backtest_run(backtest_id)
    if equity.empty:
        empty_state("No equity curve", "This backtest has no stored equity curve.")
        return

    metrics = compute_performance_metrics(equity, trades, float(run_detail["initial_capital"]))
    daily_returns = equity["daily_return"].dropna()
    var_95 = historical_var(daily_returns, 0.95)
    es_95 = historical_expected_shortfall(daily_returns, 0.95)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Volatility (ann.)", fmt_pct(metrics.volatility_annualized_pct, 1))
    m2.metric("Downside Deviation (ann.)", fmt_pct(metrics.downside_deviation_pct, 1))
    m3.metric("1-day VaR (95%)", fmt_pct(var_95 * 100, 2))
    m4.metric("1-day Expected Shortfall (95%)", fmt_pct(es_95 * 100, 2))

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        rs = rolling_sharpe(equity, window=63)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity["date"], y=rs, line=dict(color=COLORS["accent_cyan"], width=1.4)))
        fig.add_hline(y=0, line=dict(color=COLORS["text_secondary"], width=0.8, dash="dot"))
        style_fig(fig, height=300, title="Rolling 63-day Sharpe")
        st.plotly_chart(fig, width="stretch")
    with c2:
        rc = rolling_cagr(equity, window=252)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity["date"], y=rc, line=dict(color=COLORS["accent_purple"], width=1.4)))
        fig.add_hline(y=0, line=dict(color=COLORS["text_secondary"], width=0.8, dash="dot"))
        style_fig(fig, height=300, title="Rolling 252-day CAGR (%)")
        st.plotly_chart(fig, width="stretch")

    st.write("")
    dd = underwater_curve(equity)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", line=dict(color=COLORS["loss"], width=1.2), fillcolor="rgba(255,92,108,0.12)"))
    style_fig(fig, height=300, title="Underwater Curve")
    st.plotly_chart(fig, width="stretch")

    st.write("")
    st.markdown("### Drawdown Episodes")
    episodes = drawdown_episodes(equity, threshold_pct=-3.0)
    if episodes.empty:
        empty_state("No material drawdowns", "No episode exceeded the -3% threshold.")
    else:
        st.dataframe(episodes, width="stretch", hide_index=True)
