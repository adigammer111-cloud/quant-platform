from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analytics.monte_carlo import run_monte_carlo
from app.components import empty_state, fmt_currency, fmt_pct, render_topbar, style_fig, warning_banner
from app.theme import COLORS
from database.backtest_repository import get_backtest_run, get_backtest_trades, list_backtest_runs


def render() -> None:
    render_topbar("Monte Carlo", "Resample completed trades to see how much of the result is luck")

    runs = list_backtest_runs()
    if runs.empty:
        empty_state("No saved backtests", "Run a backtest first (Backtesting → Backtests).")
        return

    backtest_id = st.selectbox("Backtest to analyze", runs["backtest_id"])
    c1, c2, c3 = st.columns(3)
    n_sims = c1.number_input("Simulations", value=5000, step=1000, min_value=100, max_value=50_000)
    slippage_jitter = c2.number_input("Extra slippage noise (bps std)", value=0.0)
    seed = c3.number_input("Random seed", value=42, step=1)

    if st.button("Run Monte Carlo", type="primary", width="stretch"):
        trades = get_backtest_trades(backtest_id)
        run_detail = get_backtest_run(backtest_id)
        try:
            result = run_monte_carlo(
                trades, initial_capital=float(run_detail["initial_capital"]),
                n_simulations=int(n_sims), slippage_jitter_bps_std=slippage_jitter, seed=int(seed),
            )
        except ValueError as exc:
            empty_state("Cannot run Monte Carlo", str(exc))
            return
        st.session_state["mc_result"] = (result, run_detail)

    if "mc_result" not in st.session_state:
        empty_state("No simulation run yet", "Pick a backtest and click Run Monte Carlo.")
        return

    result, run_detail = st.session_state["mc_result"]
    capital = float(run_detail["initial_capital"])

    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Probability of Loss", fmt_pct(result.probability_of_loss_pct, 1))
    m2.metric("Median Final Capital", fmt_currency(result.median_final_capital))
    m3.metric("Worst Final Capital", fmt_currency(result.worst_final_capital))
    m4.metric("Worst Max Drawdown", fmt_pct(result.worst_max_drawdown_pct))

    if result.probability_of_loss_pct > 30:
        warning_banner(
            f"{result.probability_of_loss_pct:.1f}% of simulated trade-order permutations ended below the "
            f"starting capital - this strategy's historical edge may not be robust."
        )

    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=result.raw_final_capitals, marker_color=COLORS["accent_cyan"], nbinsx=60))
        fig.add_vline(x=capital, line=dict(color=COLORS["text_secondary"], dash="dash"), annotation_text="Start")
        style_fig(fig, height=340, title="Distribution of Final Capital")
        st.plotly_chart(fig, width="stretch")
    with c2:
        fig = go.Figure()
        fig.add_trace(go.Histogram(x=result.raw_max_drawdowns, marker_color=COLORS["loss"], nbinsx=60))
        style_fig(fig, height=340, title="Distribution of Max Drawdown (%)")
        st.plotly_chart(fig, width="stretch")

    st.write("")
    st.markdown("### Percentiles")
    pct_rows = []
    for p in [5, 25, 50, 75, 95]:
        pct_rows.append({
            "Percentile": f"P{p}",
            "Final Capital": fmt_currency(result.final_capital_percentiles[p]),
            "Max Drawdown": fmt_pct(result.max_drawdown_percentiles[p]),
        })
    st.dataframe(pct_rows, width="stretch", hide_index=True)
