from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import empty_state, render_topbar
from data.storage.repository import get_daily_prices
from data.universe import list_available_universes, universe_symbols
from strategies.indicators import momentum, rsi, sma


def render() -> None:
    render_topbar("Screener", "Rank a universe by real-time indicator values computed from stored price history")

    universe = st.selectbox("Universe", list_available_universes())
    if st.button("Scan", type="primary"):
        symbols = universe_symbols(universe)
        rows = []
        progress = st.progress(0.0, text="Scanning...")
        for i, symbol in enumerate(symbols):
            df = get_daily_prices(symbol)
            if len(df) < 210:
                progress.progress((i + 1) / len(symbols))
                continue
            close = df["close"]
            last_price = close.iloc[-1]
            sma_50 = sma(close, 50).iloc[-1]
            sma_200 = sma(close, 200).iloc[-1]
            rsi_14 = rsi(close, 14).iloc[-1]
            mom_63 = momentum(close, 63).iloc[-1] * 100  # ~3 month momentum
            prev_close = close.iloc[-2]
            daily_change = (last_price / prev_close - 1) * 100

            rows.append(
                {
                    "symbol": symbol,
                    "price": round(last_price, 2),
                    "chg_pct": round(daily_change, 2),
                    "rsi_14": round(rsi_14, 1),
                    "trend": "Above 200-SMA" if last_price > sma_200 else "Below 200-SMA",
                    "sma50_vs_sma200": "Bullish (50>200)" if sma_50 > sma_200 else "Bearish (50<200)",
                    "momentum_3m_pct": round(mom_63, 2),
                }
            )
            progress.progress((i + 1) / len(symbols))
        progress.empty()

        if not rows:
            empty_state("No symbols had enough history", "Symbols need 200+ days of data to compute a 200-SMA trend.")
            return

        st.session_state["screener_results"] = pd.DataFrame(rows)

    if "screener_results" in st.session_state:
        df = st.session_state["screener_results"]
        st.markdown(f"### Results ({len(df)} symbols)")

        sort_col = st.selectbox("Sort by", df.columns.tolist(), index=list(df.columns).index("momentum_3m_pct"))
        ascending = st.checkbox("Ascending", value=False)
        st.dataframe(
            df.sort_values(sort_col, ascending=ascending),
            width="stretch", hide_index=True,
            column_config={
                "chg_pct": st.column_config.NumberColumn("Chg %", format="%.2f%%"),
                "momentum_3m_pct": st.column_config.NumberColumn("3M Momentum %", format="%.2f%%"),
                "rsi_14": st.column_config.ProgressColumn("RSI 14", min_value=0, max_value=100),
            },
        )
    else:
        empty_state("No scan run yet", "Choose a universe and click Scan.")
