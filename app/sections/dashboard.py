from __future__ import annotations

import streamlit as st

from analytics.benchmark import build_buy_and_hold_curve
from analytics.performance import compute_performance_metrics
from app.components import (
    data_health_card,
    empty_state,
    fmt_currency,
    fmt_num,
    fmt_pct,
    metric_row,
    render_topbar,
    signed_class,
    style_fig,
)
from data.storage.repository import get_daily_prices, get_data_status
from database.backtest_repository import (
    get_backtest_equity_curve,
    get_backtest_run,
    get_backtest_trades,
    list_backtest_runs,
)


def render() -> None:
    render_topbar("Dashboard", "Command center - latest run, data health, recent activity")

    status = get_data_status()
    runs = list_backtest_runs()

    if runs.empty:
        empty_state(
            "No backtests yet",
            "Head to System → Data to download a universe, then Backtesting → Backtests to run your first strategy.",
        )
        st.write("")
        c1, _ = st.columns([1, 2])
        with c1:
            data_health_card(status)
        return

    latest = runs.iloc[0]
    backtest_id = latest["backtest_id"]
    equity = get_backtest_equity_curve(backtest_id)
    trades = get_backtest_trades(backtest_id)
    run_detail = get_backtest_run(backtest_id)

    if equity.empty:
        empty_state("Latest backtest has no equity curve", "Try running a new backtest.")
        return

    metrics = compute_performance_metrics(equity, trades, float(run_detail["initial_capital"]))

    st.markdown(
        f'<div class="qp-secondary">Latest run &nbsp;·&nbsp; '
        f'<span class="qp-mono">{backtest_id}</span> &nbsp;·&nbsp; '
        f'{run_detail["strategy_name"]} &nbsp;·&nbsp; {run_detail["universe"]}</div>',
        unsafe_allow_html=True,
    )
    st.write("")

    metric_row(
        [
            ("Final Capital", fmt_currency(metrics.final_capital), fmt_pct(metrics.absolute_return_pct), metrics.absolute_return_pct >= 0),
            ("Total Return", fmt_pct(metrics.absolute_return_pct), None, None),
            ("CAGR", fmt_pct(metrics.cagr_pct), None, None),
            ("Sharpe", fmt_num(metrics.sharpe_ratio), None, None),
            ("Max Drawdown", fmt_pct(metrics.max_drawdown_pct), None, None),
            ("Trades", str(metrics.num_trades), None, None),
        ]
    )

    st.write("")
    left, right = st.columns([2.4, 1])

    with left:
        st.markdown("### Equity Curve")
        import plotly.graph_objects as go

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=equity["date"], y=equity["total_value"], name=run_detail["strategy_name"],
                mode="lines", line=dict(color="#4CC9F0", width=1.8),
                fill="tozeroy", fillcolor="rgba(76,201,240,0.06)",
            )
        )
        benchmark_symbol = run_detail.get("benchmark_symbol")
        if benchmark_symbol:
            bench_prices = get_daily_prices(benchmark_symbol)
            if not bench_prices.empty:
                bench_curve = build_buy_and_hold_curve(
                    bench_prices, float(run_detail["initial_capital"]),
                    equity["date"].min().date(), equity["date"].max().date(),
                )
                fig.add_trace(
                    go.Scatter(
                        x=bench_curve["date"], y=bench_curve["total_value"], name=benchmark_symbol,
                        mode="lines", line=dict(color="#8B98A8", width=1.3, dash="dot"),
                    )
                )
        style_fig(fig, height=380)
        st.plotly_chart(fig, width="stretch")

    with right:
        data_health_card(status)

    st.write("")
    st.markdown("### Recent Backtests")
    display_cols = ["backtest_id", "created_at", "strategy_name", "universe", "start_date", "end_date", "status"]
    st.dataframe(runs[display_cols].head(8), width="stretch", hide_index=True)
