from __future__ import annotations

import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from analytics.drawdown import underwater_curve
from analytics.overfitting import check_single_backtest
from analytics.reporting import build_round_trip_trades, monthly_returns_table
from app.components import (
    empty_state,
    error_banner,
    fmt_currency,
    fmt_num,
    fmt_pct,
    performance_header,
    render_topbar,
    style_fig,
    warning_banner,
)
from app.theme import COLORS
from backtesting.costs import TransactionCostModel
from backtesting.engine import BacktestConfig
from backtesting.runner import run_backtest
from data.storage.repository import get_daily_prices
from data.universe import list_available_universes, universe_symbols
from strategies.registry import STRATEGY_REGISTRY, apply_risk_overrides
from strategies.rule_based import CustomCodeStrategy, RuleBasedStrategy


def _build_pending_strategy():
    pending = st.session_state.get("pending_strategy")
    if not pending:
        return None, None
    if pending["kind"] == "builtin":
        from strategies.registry import build_strategy

        strat = build_strategy(pending["name"], pending.get("params", {}), pending.get("risk"))
        return strat, pending["name"]
    if pending["kind"] == "rule_based":
        strat = RuleBasedStrategy(entry_conditions=pending["entry"], exit_conditions=pending["exit"])
        strat = apply_risk_overrides(strat, pending.get("risk"))
        return strat, pending["name"]
    if pending["kind"] == "custom_code":
        strat = CustomCodeStrategy(source_code=pending["source_code"])
        strat = apply_risk_overrides(strat, pending.get("risk"))
        return strat, pending["name"]
    return None, None


def render() -> None:
    render_topbar("Backtests", "Configure, run, and inspect a strategy backtest")

    pending_strategy, pending_name = _build_pending_strategy()

    if pending_strategy:
        st.markdown(
            f'<div class="qp-card" style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">'
            f'<div><span class="qp-secondary">Using strategy from Builder/Library:</span> '
            f'<strong style="color:{COLORS["text"]};">{pending_name}</strong></div></div>',
            unsafe_allow_html=True,
        )
        clear = st.button("Clear and pick a built-in strategy instead")
        if clear:
            del st.session_state["pending_strategy"]
            st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Configuration")
        if not pending_strategy:
            strategy_name = st.selectbox("Strategy", list(STRATEGY_REGISTRY.keys()))
            default_strategy = STRATEGY_REGISTRY[strategy_name]()
            params = {}
            with st.expander("Strategy Parameters", expanded=True):
                for pname, pval in default_strategy.params.items():
                    if isinstance(pval, bool):
                        params[pname] = st.checkbox(pname, value=pval)
                    elif isinstance(pval, int):
                        params[pname] = st.number_input(pname, value=pval, step=1)
                    elif isinstance(pval, float):
                        params[pname] = st.number_input(pname, value=pval)
                    else:
                        params[pname] = st.text_input(pname, value=str(pval))
        else:
            strategy_name = pending_name
            params = {}

        universe = st.selectbox("Universe", list_available_universes())
        c1, c2 = st.columns(2)
        start_date = c1.date_input("Start date", dt.date(2018, 1, 1))
        end_date = c2.date_input("End date", dt.date.today())
        capital = st.number_input("Initial capital (INR)", value=100_000.0, step=10_000.0)
        benchmark = st.text_input("Benchmark symbol", "^NSEI")

    with col2:
        st.markdown("### Risk & Costs")
        with st.expander("Position Sizing", expanded=True):
            max_position_pct = st.slider("Max position size (% of equity)", 5, 100, 20) / 100
            max_exposure_pct = st.slider("Max portfolio exposure (%)", 5, 100, 100) / 100
            use_sl = st.checkbox("Stop loss", value=True)
            stop_loss_pct = st.slider("Stop loss %", 1, 30, 8, disabled=not use_sl) / 100 if use_sl else None
            use_tp = st.checkbox("Take profit", value=False)
            take_profit_pct = st.slider("Take profit %", 1, 60, 15, disabled=not use_tp) / 100 if use_tp else None

        with st.expander("Transaction Costs", expanded=False):
            brokerage_flat = st.number_input("Brokerage flat cap (INR/order)", value=20.0)
            slippage_bps = st.number_input("Slippage (bps)", value=5.0)
            stt_pct = st.number_input("STT % (each side)", value=0.10, format="%.3f") / 100
            stamp_duty_pct = st.number_input("Stamp duty % (buy side)", value=0.015, format="%.3f") / 100
            gst_pct = st.number_input("GST % on brokerage+exchange+SEBI", value=18.0) / 100

    st.write("")
    run_clicked = st.button("RUN BACKTEST", type="primary", width="stretch")

    if run_clicked:
        symbols = universe_symbols(universe)
        cost_model = TransactionCostModel(
            brokerage_flat_cap=brokerage_flat, slippage_bps=slippage_bps,
            stt_pct_buy=stt_pct, stt_pct_sell=stt_pct, stamp_duty_pct_buy=stamp_duty_pct, gst_pct=gst_pct,
        )
        config = BacktestConfig(initial_capital=capital, cost_model=cost_model, benchmark_symbol=benchmark or None)
        risk_overrides = {
            "max_position_pct": max_position_pct, "max_portfolio_exposure_pct": max_exposure_pct,
            "stop_loss": stop_loss_pct, "take_profit": take_profit_pct,
        }

        with st.status("Running backtest...", expanded=True) as status:
            st.write("Loading price data from database")
            try:
                if pending_strategy:
                    pending_strategy = apply_risk_overrides(pending_strategy, risk_overrides)
                    st.write("Simulating trades bar-by-bar (signal → next-bar execution)")
                    output = run_backtest(
                        strategy_name=strategy_name, symbols=symbols, start_date=start_date, end_date=end_date,
                        config=config, benchmark_symbol=benchmark or None, index_name_for_bias_check=universe,
                        strategy_instance=pending_strategy,
                    )
                else:
                    st.write("Simulating trades bar-by-bar (signal → next-bar execution)")
                    output = run_backtest(
                        strategy_name=strategy_name, symbols=symbols, start_date=start_date, end_date=end_date,
                        params=params, risk_overrides=risk_overrides, config=config,
                        benchmark_symbol=benchmark or None, index_name_for_bias_check=universe,
                    )
                st.write("Calculating performance metrics")
                status.update(label="Backtest complete", state="complete")
            except ValueError as exc:
                status.update(label="Backtest failed", state="error")
                error_banner(str(exc))
                return

        st.session_state["last_backtest"] = output

    if "last_backtest" not in st.session_state:
        empty_state("No backtest run yet", "Configure the strategy above and click RUN BACKTEST.")
        return

    output = st.session_state["last_backtest"]
    m = output.metrics

    for w in output.result.warnings:
        warning_banner(w)
    for w in check_single_backtest(m):
        warning_banner(f"Overfitting check: {w}")

    st.write("")
    st.markdown(f"### Results — `{output.backtest_id}`")
    performance_header(m)

    st.write("")
    tab_eq, tab_dd, tab_heat, tab_analysis, tab_bench, tab_trades = st.tabs(
        ["Equity Curve", "Drawdown", "Monthly Returns", "Trade Analysis", "Benchmark", "Trade Table"]
    )

    with tab_eq:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=output.result.equity_curve["date"], y=output.result.equity_curve["total_value"],
            name="Strategy", mode="lines", line=dict(color=COLORS["accent_cyan"], width=1.8),
            fill="tozeroy", fillcolor="rgba(76,201,240,0.06)",
        ))
        if output.benchmark_result is not None:
            fig.add_trace(go.Scatter(
                x=output.benchmark_result["date"], y=output.benchmark_result["total_value"],
                name="Benchmark", mode="lines", line=dict(color=COLORS["text_secondary"], width=1.3, dash="dot"),
            ))
        style_fig(fig, height=420)
        st.plotly_chart(fig, width="stretch")

    with tab_dd:
        dd = underwater_curve(output.result.equity_curve)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", name="Drawdown %",
                                  line=dict(color=COLORS["loss"], width=1.2), fillcolor="rgba(255,92,108,0.12)"))
        style_fig(fig, height=340)
        st.plotly_chart(fig, width="stretch")

    with tab_heat:
        table = monthly_returns_table(output.result.equity_curve)
        fig = go.Figure(data=go.Heatmap(
            z=table.values, x=list(table.columns), y=[str(y) for y in table.index],
            colorscale=[[0, COLORS["loss"]], [0.5, COLORS["surface"]], [1, COLORS["profit"]]],
            zmid=0, text=table.round(1).values, texttemplate="%{text}",
            hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>",
        ))
        style_fig(fig, height=340)
        st.plotly_chart(fig, width="stretch")

    with tab_analysis:
        rt = build_round_trip_trades(output.result.trades)
        if rt.empty:
            empty_state("No completed trades", "This backtest had no round-trip trades to analyze.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure()
                colors = [COLORS["profit"] if v >= 0 else COLORS["loss"] for v in rt["net_pnl"]]
                fig.add_trace(go.Bar(x=list(range(len(rt))), y=rt["net_pnl"], marker_color=colors, name="Net P&L per trade"))
                style_fig(fig, height=300, title="Trade P&L Sequence")
                st.plotly_chart(fig, width="stretch")
            with c2:
                fig = go.Figure()
                fig.add_trace(go.Histogram(x=rt["return_pct"], marker_color=COLORS["accent_purple"], nbinsx=30))
                style_fig(fig, height=300, title="Return % Distribution")
                st.plotly_chart(fig, width="stretch")
            exit_reason_counts = rt["exit_reason"].value_counts()
            st.markdown("**Exit reasons:** " + ", ".join(f"{k}: {v}" for k, v in exit_reason_counts.items()))

    with tab_bench:
        if output.benchmark_metrics is None:
            empty_state("No benchmark configured", "Set a benchmark symbol above and re-run.")
        else:
            bm = output.benchmark_metrics
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Strategy**")
                st.markdown(
                    f'CAGR: <span class="qp-mono">{fmt_pct(m.cagr_pct)}</span><br>'
                    f'Max DD: <span class="qp-mono">{fmt_pct(m.max_drawdown_pct)}</span><br>'
                    f'Sharpe: <span class="qp-mono">{fmt_num(m.sharpe_ratio)}</span><br>'
                    f'Return: <span class="qp-mono">{fmt_pct(m.absolute_return_pct)}</span>',
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(f"**Benchmark ({benchmark})**")
                st.markdown(
                    f'CAGR: <span class="qp-mono">{fmt_pct(bm.cagr_pct)}</span><br>'
                    f'Max DD: <span class="qp-mono">{fmt_pct(bm.max_drawdown_pct)}</span><br>'
                    f'Sharpe: <span class="qp-mono">{fmt_num(bm.sharpe_ratio)}</span><br>'
                    f'Return: <span class="qp-mono">{fmt_pct(bm.absolute_return_pct)}</span>',
                    unsafe_allow_html=True,
                )

    with tab_trades:
        rt = build_round_trip_trades(output.result.trades)
        if rt.empty:
            empty_state("No trades", "This backtest produced no round-trip trades.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            symbol_filter = fc1.multiselect("Symbol", sorted(rt["symbol"].unique()))
            side_filter = fc2.multiselect("Side", sorted(rt["side"].unique()))
            search = fc3.text_input("Search exit reason")

            filtered = rt.copy()
            if symbol_filter:
                filtered = filtered[filtered["symbol"].isin(symbol_filter)]
            if side_filter:
                filtered = filtered[filtered["side"].isin(side_filter)]
            if search:
                filtered = filtered[filtered["exit_reason"].str.contains(search, case=False, na=False)]

            display = filtered.rename(columns={
                "exit_date": "Date", "symbol": "Symbol", "side": "Side", "entry_price": "Entry",
                "exit_price": "Exit", "quantity": "Qty", "holding_period_days": "Holding",
                "costs": "Costs", "net_pnl": "Net P&L", "return_pct": "Return %",
            })[["Date", "Symbol", "Side", "Entry", "Exit", "Qty", "Holding", "Costs", "Net P&L", "Return %", "entry_date", "exit_reason"]]

            st.dataframe(
                display, width="stretch", hide_index=True,
                column_config={
                    "Entry": st.column_config.NumberColumn(format="%.2f"),
                    "Exit": st.column_config.NumberColumn(format="%.2f"),
                    "Costs": st.column_config.NumberColumn(format="%.2f"),
                    "Net P&L": st.column_config.NumberColumn(format="%.2f"),
                    "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )
            st.download_button(
                "Download trade table CSV", display.to_csv(index=False).encode("utf-8"),
                f"{output.backtest_id}_trades.csv", "text/csv",
            )
