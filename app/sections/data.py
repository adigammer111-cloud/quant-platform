from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.components import empty_state, error_banner, render_topbar
from app.theme import COLORS
from data.ingestion.downloader import update_symbol, update_universe
from data.providers.factory import get_provider
from data.providers.instrument_master import sync_full_instrument_master
from data.storage.repository import get_corporate_actions, get_daily_prices, get_data_status, list_instruments
from data.universe import list_available_universes
from data.validation.quality import validate_daily_prices


def render() -> None:
    render_topbar("Data", "Download and update NSE/BSE price history")

    tab_update, tab_search, tab_explore = st.tabs(["Update Data", "Search All NSE/BSE Tickers", "Explore a Symbol"])

    with tab_update:
        c1, c2 = st.columns(2)
        with c1:
            universe = st.selectbox("Universe", list_available_universes())
            full_refresh = st.checkbox("Full refresh (re-download entire history)", value=False)
            if st.button("Update Universe", type="primary", width="stretch"):
                with st.spinner(f"Downloading {universe}..."):
                    provider = get_provider()
                    results = update_universe(provider, universe, full_refresh=full_refresh)
                ok = sum(1 for r in results if r.ok)
                st.success(f"{ok}/{len(results)} symbols updated successfully.")
                for r in results:
                    if not r.ok:
                        error_banner(f"{r.symbol}: {r.error}")
        with c2:
            single_symbol = st.text_input("Update a single symbol", placeholder="e.g. RELIANCE.NS, ^NSEI")
            if st.button("Update Symbol", width="stretch") and single_symbol:
                with st.spinner(f"Downloading {single_symbol}..."):
                    provider = get_provider()
                    result = update_symbol(provider, single_symbol)
                if result.ok:
                    st.success(f"{single_symbol}: {result.rows_written} rows written.")
                else:
                    error_banner(f"{single_symbol}: {result.error}")

    with tab_search:
        instruments = list_instruments()
        st.markdown(
            f'<span class="qp-secondary">{len(instruments)} instruments in the local master list '
            f'(NSE + BSE combined). This is the full exchange listing - most won\'t have price '
            f'history downloaded yet; search, then download the ones you need.</span>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("↻ Sync Full NSE/BSE List", width="stretch", help="Pulls NSE's full published equity list (~2,300 symbols) and best-effort BSE. Slow-ish; run occasionally, not on every visit."):
                with st.spinner("Fetching NSE's published equity list (and attempting BSE)..."):
                    result = sync_full_instrument_master()
                st.success(f"Synced {result.nse_count} NSE instruments.")
                if result.bse_count:
                    st.success(f"Synced {result.bse_count} BSE instruments.")
                elif result.bse_error:
                    error_banner(f"BSE sync unavailable right now ({result.bse_error}) - NSE sync still succeeded. BSE symbols still work individually via Update Symbol / Paper Trading.")
                st.rerun()

        if instruments.empty:
            empty_state("No instrument master list yet", "Click 'Sync Full NSE/BSE List' above to pull NSE's full published ~2,300-symbol equity list.")
        else:
            with c2:
                search = st.text_input("Search by symbol or company name", placeholder="e.g. reliance, TCS, bank")
            filtered = instruments
            if search:
                mask = (
                    instruments["symbol"].str.contains(search, case=False, na=False)
                    | instruments["name"].str.contains(search, case=False, na=False)
                )
                filtered = instruments[mask]
            st.dataframe(
                filtered[["symbol", "name", "exchange", "isin"]].head(200),
                width="stretch", hide_index=True,
            )
            if len(filtered) > 200:
                st.caption(f"Showing first 200 of {len(filtered)} matches - narrow your search to see more.")

            pick = st.text_input("Symbol to download (paste from the table above)", placeholder="e.g. RELIANCE.NS")
            if st.button("Download this symbol's price history", width="stretch") and pick:
                with st.spinner(f"Downloading {pick}..."):
                    provider = get_provider()
                    result = update_symbol(provider, pick.strip().upper())
                if result.ok:
                    st.success(f"{pick}: {result.rows_written} rows written.")
                else:
                    error_banner(f"{pick}: {result.error}")

    with tab_explore:
        status = get_data_status()
        symbols = sorted(status["symbol"].tolist()) if not status.empty else []
        if not symbols:
            empty_state("No data yet", "Update a universe in the tab to the left first.")
            return

        symbol = st.selectbox("Symbol", symbols)
        df = get_daily_prices(symbol)
        fig = go.Figure(data=[go.Candlestick(
            x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            increasing_line_color=COLORS["profit"], decreasing_line_color=COLORS["loss"],
        )])
        fig.update_layout(title=f"{symbol} — Daily OHLC", height=420, xaxis_rangeslider_visible=False, template="quant_dark")
        st.plotly_chart(fig, width="stretch")

        corp_actions = get_corporate_actions(symbol)
        report = validate_daily_prices(symbol, df, corporate_actions=corp_actions)
        st.markdown("### Data Quality Report")
        st.code(report.to_text())

        st.download_button(
            "Download as CSV", df.to_csv(index=False).encode("utf-8"), f"{symbol}.csv", "text/csv"
        )
