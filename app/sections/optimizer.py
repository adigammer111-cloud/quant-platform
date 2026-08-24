from __future__ import annotations

import datetime as dt
import math

import plotly.graph_objects as go
import streamlit as st

from analytics.overfitting import check_single_backtest
from analytics.performance import compute_performance_metrics
from app.components import empty_state, fmt_num, parse_param_grid, render_topbar, style_fig, warning_banner
from app.theme import COLORS
from backtesting.costs import TransactionCostModel
from backtesting.engine import BacktestConfig, BacktestEngine
from data.storage.repository import get_daily_prices
from data.universe import list_available_universes, universe_symbols
from optimization.optimizer import grid_search
from strategies.registry import STRATEGY_REGISTRY, build_strategy


def render() -> None:
    render_topbar("Optimizer", "Grid-search parameters on a training window - always verify out-of-sample")

    c1, c2 = st.columns(2)
    strategy_name = c1.selectbox("Strategy", list(STRATEGY_REGISTRY.keys()))
    universe = c2.selectbox("Universe", list_available_universes())

    param_text = st.text_area(
        "Parameter grid (one per line: name=v1,v2,v3)",
        "fast_period=10,20,30\nslow_period=50,100,150",
    )

    c1, c2, c3 = st.columns(3)
    train_start = c1.date_input("Training start", dt.date(2018, 1, 1))
    train_end = c1.date_input("Training end", dt.date(2022, 12, 31))
    test_start = c2.date_input("Test start (optional OOS check)", dt.date(2023, 1, 1))
    test_end = c2.date_input("Test end", dt.date.today())
    metric = c3.selectbox("Objective", ["sharpe_ratio", "cagr_pct", "sortino_ratio", "calmar_ratio"])
    capital = c3.number_input("Initial capital", value=100_000.0, step=10_000.0)

    if st.button("Run Optimization", type="primary", width="stretch"):
        symbols = universe_symbols(universe)
        data = {s: df for s in symbols if not (df := get_daily_prices(s)).empty}
        if not data:
            empty_state("No data", "Download this universe from System → Data first.")
            return

        param_grid = parse_param_grid(param_text)
        config = BacktestConfig(initial_capital=capital, cost_model=TransactionCostModel())

        n_combos = math.prod(len(v) for v in param_grid.values()) if param_grid else 0
        with st.spinner(f"Testing {n_combos} parameter combinations..."):
            result = grid_search(strategy_name, param_grid, data, train_start, train_end, config, metric=metric)

        st.session_state["optimizer_result"] = {
            "result": result, "param_grid": param_grid, "data_keys": list(data.keys()),
            "strategy_name": strategy_name, "capital": capital, "metric": metric,
            "test_start": test_start, "test_end": test_end,
        }

    if "optimizer_result" not in st.session_state:
        empty_state("No optimization run yet", "Set a parameter grid and click Run Optimization.")
        return

    state = st.session_state["optimizer_result"]
    result = state["result"]
    param_names = list(state["param_grid"].keys())

    st.write("")
    st.markdown(f"### Best Parameters — {state['metric']} = `{result.best_metric_value:.4f}`")
    st.json(result.best_params)

    if len(param_names) == 2:
        st.markdown("### Parameter Heatmap")
        st.caption("Click a cell to load that exact configuration below.")
        p1, p2 = param_names
        pivot = result.all_results.pivot_table(index=p1, columns=p2, values=state["metric"])
        fig = go.Figure(data=go.Heatmap(
            z=pivot.values, x=[str(c) for c in pivot.columns], y=[str(i) for i in pivot.index],
            colorscale=[[0, COLORS["loss"]], [0.5, COLORS["surface"]], [1, COLORS["accent_cyan"]]],
            text=pivot.round(3).values, texttemplate="%{text}",
            hovertemplate=f"{p1}=%{{y}}<br>{p2}=%{{x}}<br>{state['metric']}=%{{z:.3f}}<extra></extra>",
        ))
        fig.update_layout(xaxis_title=p2, yaxis_title=p1)
        style_fig(fig, height=420)
        event = st.plotly_chart(fig, width="stretch", on_select="rerun", key="opt_heatmap")

        selected_params = None
        if event and event.get("selection", {}).get("points"):
            point = event["selection"]["points"][0]
            # Match by the clicked cell's x/y axis label text (always present
            # on a heatmap point) back to the original (possibly numeric) values.
            y_label, x_label = point.get("y"), point.get("x")
            row_val = pivot.index[[str(i) == y_label for i in pivot.index].index(True)]
            col_val = pivot.columns[[str(c) == x_label for c in pivot.columns].index(True)]
            selected_params = {p1: row_val, p2: col_val}

        if selected_params:
            st.markdown(f"**Inspecting:** {selected_params}")
            match = result.all_results
            for k, v in selected_params.items():
                match = match[match[k] == v]
            if not match.empty:
                row = match.iloc[0]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("CAGR", f"{row['cagr_pct']:.2f}%")
                m2.metric("Sharpe", f"{row['sharpe_ratio']:.2f}")
                m3.metric("Max DD", f"{row['max_drawdown_pct']:.2f}%")
                m4.metric("Trades", f"{int(row['num_trades'])}")

    st.write("")
    st.markdown("### All Combinations")
    st.dataframe(result.all_results, width="stretch", hide_index=True)

    if state["test_start"] and state["test_end"]:
        st.write("")
        st.markdown("### Out-of-Sample Test Window")
        symbols = state["data_keys"]
        data = {s: df for s in symbols if not (df := get_daily_prices(s)).empty}
        config = BacktestConfig(initial_capital=state["capital"], cost_model=TransactionCostModel())
        best_strategy = build_strategy(state["strategy_name"], result.best_params)
        test_result = BacktestEngine(config).run(best_strategy, data, start_date=state["test_start"], end_date=state["test_end"])
        test_metrics = compute_performance_metrics(test_result.equity_curve, test_result.trades, state["capital"])

        c1, c2 = st.columns(2)
        c1.metric(f"Training {state['metric']}", fmt_num(result.best_metric_value))
        c2.metric(f"Test {state['metric']}", fmt_num(getattr(test_metrics, state["metric"])))

        for w in check_single_backtest(test_metrics):
            warning_banner(w)
        train_value = result.best_metric_value
        test_value = getattr(test_metrics, state["metric"])
        if train_value > 0 and test_value <= 0:
            warning_banner(
                f"Out-of-sample {state['metric']} ({test_value:.2f}) is non-positive while training "
                f"{state['metric']} was {train_value:.2f}: this strategy appears highly optimized to the training period."
            )
