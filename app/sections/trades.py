from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.reporting import build_round_trip_trades
from app.components import empty_state, render_topbar
from database.backtest_repository import get_backtest_trades, list_backtest_runs


def render() -> None:
    render_topbar("Trades", "Every completed round-trip trade across your saved backtests")

    runs = list_backtest_runs()
    if runs.empty:
        empty_state("No saved backtests", "Run a backtest first (Backtesting → Backtests).")
        return

    labels = [f"{r.backtest_id} ({r.strategy_name})" for r in runs.itertuples()]
    label_to_id = dict(zip(labels, runs["backtest_id"]))
    selected_labels = st.multiselect("Backtests", labels, default=labels[: min(5, len(labels))])
    if not selected_labels:
        empty_state("Select at least one backtest", "Use the picker above.")
        return

    frames = []
    for label in selected_labels:
        bt_id = label_to_id[label]
        raw = get_backtest_trades(bt_id)
        rt = build_round_trip_trades(raw)
        if not rt.empty:
            rt.insert(0, "backtest_id", bt_id)
            frames.append(rt)

    if not frames:
        empty_state("No completed round-trip trades", "The selected backtests have no closed trades yet.")
        return

    all_trades = pd.concat(frames, ignore_index=True)

    f1, f2, f3, f4 = st.columns(4)
    symbol_filter = f1.multiselect("Symbol", sorted(all_trades["symbol"].unique()))
    side_filter = f2.multiselect("Side", sorted(all_trades["side"].unique()))
    min_pnl = f3.number_input("Min net P&L", value=float(all_trades["net_pnl"].min()))
    search = f4.text_input("Search exit reason")

    filtered = all_trades.copy()
    if symbol_filter:
        filtered = filtered[filtered["symbol"].isin(symbol_filter)]
    if side_filter:
        filtered = filtered[filtered["side"].isin(side_filter)]
    filtered = filtered[filtered["net_pnl"] >= min_pnl]
    if search:
        filtered = filtered[filtered["exit_reason"].str.contains(search, case=False, na=False)]

    st.write("")
    c1, c2, c3 = st.columns(3)
    c1.metric("Trades shown", len(filtered))
    c2.metric("Total Net P&L", f"₹{filtered['net_pnl'].sum():,.0f}")
    c3.metric("Win Rate", f"{(filtered['net_pnl'] > 0).mean() * 100:.1f}%" if len(filtered) else "—")

    display = filtered.rename(columns={
        "exit_date": "Date", "symbol": "Symbol", "side": "Side", "entry_price": "Entry",
        "exit_price": "Exit", "quantity": "Qty", "holding_period_days": "Holding",
        "costs": "Costs", "net_pnl": "Net P&L", "return_pct": "Return %",
    })
    st.dataframe(
        display[["backtest_id", "Date", "Symbol", "Side", "Entry", "Exit", "Qty", "Holding", "Costs", "Net P&L", "Return %", "exit_reason"]],
        width="stretch", hide_index=True,
        column_config={
            "Entry": st.column_config.NumberColumn(format="%.2f"),
            "Exit": st.column_config.NumberColumn(format="%.2f"),
            "Net P&L": st.column_config.NumberColumn(format="%.2f"),
            "Return %": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    st.download_button("Download CSV", display.to_csv(index=False).encode("utf-8"), "trades.csv", "text/csv")
