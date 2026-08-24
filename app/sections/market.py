from __future__ import annotations

import datetime as dt

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app.components import empty_state, render_topbar, style_fig, ticker_hero, watchlist_panel
from app.theme import COLORS
from data.storage.repository import get_daily_prices, get_data_status
from strategies.indicators import bollinger_bands, ema, macd, rsi, sma

TIMEFRAMES = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "Max": None}
STUDIES = ["SMA", "EMA", "Bollinger", "RSI", "MACD"]


def render() -> None:
    render_topbar("Market", "Price action, volume, and technical studies")

    status = get_data_status()
    if status.empty:
        empty_state("No symbols available", "Download a universe from System → Data first.")
        return

    symbols = sorted(status["symbol"].tolist())
    watchlist_col, chart_col = st.columns([1, 4], gap="medium")

    with watchlist_col:
        st.markdown('<div class="qp-card-title">Watchlist</div>', unsafe_allow_html=True)
        selected = st.session_state.get("market_symbol", symbols[0])
        watch_rows = []
        for sym in symbols[:25]:
            df_sym = get_daily_prices(sym)
            if len(df_sym) < 2:
                continue
            watch_rows.append((sym, float(df_sym["close"].iloc[-1]), float(df_sym["close"].iloc[-2])))
        watchlist_panel(watch_rows)

        symbol = st.selectbox("Symbol", symbols, index=symbols.index(selected) if selected in symbols else 0, label_visibility="collapsed")
        st.session_state["market_symbol"] = symbol

    with chart_col:
        df_full = get_daily_prices(symbol)
        if df_full.empty:
            empty_state("No price data", f"No data found for {symbol}.")
            return

        top_row = st.columns([3, 2])
        with top_row[0]:
            last_close = float(df_full["close"].iloc[-1])
            prev_close = float(df_full["close"].iloc[-2]) if len(df_full) > 1 else last_close
            ticker_hero(symbol, last_close, prev_close, as_of=str(df_full["date"].max().date()), source="stored EOD", live=False)
        with top_row[1]:
            timeframe = st.segmented_control("Timeframe", list(TIMEFRAMES.keys()), default="1Y", label_visibility="collapsed")
            timeframe = timeframe or "1Y"

        studies = st.segmented_control("Studies", STUDIES, selection_mode="multi", default=["SMA", "RSI"], label_visibility="collapsed")
        studies = studies or []

        df = df_full
        lookback_days = TIMEFRAMES[timeframe]
        if lookback_days:
            cutoff = df["date"].max() - dt.timedelta(days=lookback_days)
            df = df[df["date"] >= cutoff]

        show_sma, show_ema, show_bb = "SMA" in studies, "EMA" in studies, "Bollinger" in studies
        show_rsi, show_macd = "RSI" in studies, "MACD" in studies

        specs_rows = 2 + int(show_rsi) + int(show_macd)
        heights = {2: [0.72, 0.28], 3: [0.56, 0.2, 0.24], 4: [0.48, 0.16, 0.18, 0.18]}[specs_rows]

        fig = make_subplots(rows=specs_rows, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=heights)

        fig.add_trace(
            go.Candlestick(
                x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                name=symbol, increasing_line_color=COLORS["profit"], decreasing_line_color=COLORS["loss"],
                increasing_fillcolor=COLORS["profit"], decreasing_fillcolor=COLORS["loss"],
            ),
            row=1, col=1,
        )
        # Floating last-price line, TradingView-style.
        fig.add_hline(
            y=last_close, line=dict(color=COLORS["profit"] if last_close >= prev_close else COLORS["loss"], width=0.8, dash="dot"),
            row=1, col=1,
        )

        if show_sma:
            for window, color in [(20, COLORS["accent_cyan"]), (50, COLORS["accent_purple"])]:
                fig.add_trace(
                    go.Scatter(x=df["date"], y=sma(df["close"], window), name=f"SMA {window}", line=dict(width=1.1, color=color)),
                    row=1, col=1,
                )
        if show_ema:
            fig.add_trace(
                go.Scatter(x=df["date"], y=ema(df["close"], 21), name="EMA 21", line=dict(width=1.1, color=COLORS["warning"])),
                row=1, col=1,
            )
        if show_bb:
            upper, mid, lower = bollinger_bands(df["close"], 20, 2.0)
            for series, name in [(upper, "BB Upper"), (lower, "BB Lower")]:
                fig.add_trace(
                    go.Scatter(x=df["date"], y=series, name=name, line=dict(width=0.9, color="#5B7A99", dash="dot")),
                    row=1, col=1,
                )

        vol_colors = [COLORS["profit"] if c >= o else COLORS["loss"] for o, c in zip(df["open"], df["close"])]
        fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color=vol_colors, opacity=0.5), row=2, col=1)

        current_row = 3
        if show_rsi:
            fig.add_trace(
                go.Scatter(x=df["date"], y=rsi(df["close"], 14), name="RSI 14", line=dict(width=1.2, color=COLORS["accent_cyan"])),
                row=current_row, col=1,
            )
            fig.add_hline(y=70, line=dict(color=COLORS["loss"], width=0.7, dash="dot"), row=current_row, col=1)
            fig.add_hline(y=30, line=dict(color=COLORS["profit"], width=0.7, dash="dot"), row=current_row, col=1)
            fig.update_yaxes(range=[0, 100], row=current_row, col=1)
            current_row += 1

        if show_macd:
            macd_line, signal_line, hist = macd(df["close"])
            hist_colors = [COLORS["profit"] if v >= 0 else COLORS["loss"] for v in hist.fillna(0)]
            fig.add_trace(go.Bar(x=df["date"], y=hist, name="Histogram", marker_color=hist_colors, opacity=0.6), row=current_row, col=1)
            fig.add_trace(go.Scatter(x=df["date"], y=macd_line, name="MACD", line=dict(width=1.1, color=COLORS["accent_cyan"])), row=current_row, col=1)
            fig.add_trace(go.Scatter(x=df["date"], y=signal_line, name="Signal", line=dict(width=1.1, color=COLORS["accent_purple"])), row=current_row, col=1)

        fig.update_layout(xaxis_rangeslider_visible=False, showlegend=True, legend=dict(orientation="h", y=1.02))
        # Price axis on the right, TradingView convention - the crosshair
        # reads more naturally when the numbers sit under the cursor's exit side.
        fig.update_yaxes(side="right")
        style_fig(fig, height=640)
        st.plotly_chart(fig, width="stretch")
