from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analytics.overfitting import check_single_backtest
from app.auth_ui import log_out, require_login
from app.components import (
    empty_state,
    error_banner,
    fmt_currency,
    fmt_num,
    fmt_pct,
    performance_header,
    render_topbar,
    style_fig,
    ticker_hero,
    warning_banner,
)
from app.theme import COLORS
from data.providers.base import ProviderError
from data.providers.live_quotes import get_live_quote
from paper_trading import engine
from paper_trading.engine import InsufficientFundsError, InsufficientSharesError


def _account_switcher(user_id: str) -> str | None:
    accounts = engine.list_accounts(user_id=user_id)
    top = st.columns([3, 1, 1])

    account_id = None
    with top[0]:
        if not accounts.empty:
            labels = [f"{r['name']}  ·  {r['account_id'][-6:]}" for _, r in accounts.iterrows()]
            idx = st.selectbox("Account", range(len(labels)), format_func=lambda i: labels[i], label_visibility="collapsed")
            account_id = accounts.iloc[idx]["account_id"]
        else:
            st.markdown('<span class="qp-secondary">No accounts yet - create one →</span>', unsafe_allow_html=True)
    with top[1]:
        new_clicked = top[1].button("+ New Account", width="stretch")
    with top[2]:
        if top[2].button("Log Out", width="stretch"):
            log_out()
            st.rerun()

    if new_clicked or accounts.empty:
        with st.form("new_paper_account_form"):
            st.markdown("**New Demo Account**")
            name = st.text_input("Account name", "Demo Account")
            capital = st.number_input("Starting capital (INR)", value=100_000.0, step=10_000.0, min_value=1_000.0)
            if st.form_submit_button("Create", type="primary"):
                new_id = engine.create_account(name, capital, user_id=user_id)
                st.rerun()
        if accounts.empty:
            return None

    return account_id


def render() -> None:
    if not require_login("Paper Trading", "Sign in to trade any NSE/BSE security against live prices"):
        return

    user_id = st.session_state["user_id"]
    render_topbar("Paper Trading", f"Signed in as {st.session_state['username']}")

    account_id = _account_switcher(user_id)
    if account_id is None:
        return

    account = engine.get_account(account_id)
    positions = engine.get_positions(account_id)

    st.write("")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cash", fmt_currency(account["cash"]))
    m2.metric("Initial Capital", fmt_currency(account["initial_capital"]))
    m3.metric("Open Positions", str(len(positions)))
    unrealized_estimate = sum(
        (row["quantity"] * row["avg_price"]) for _, row in positions.iterrows()
    )
    m4.metric("Invested (at cost)", fmt_currency(unrealized_estimate))

    st.write("")
    order_col, watch_col = st.columns([2, 1], gap="large")

    with order_col:
        st.markdown('<div class="qp-card-title">Order Ticket</div>', unsafe_allow_html=True)
        sc1, sc2 = st.columns([3, 1])
        symbol = sc1.text_input(
            "Symbol", value=st.session_state.get("pt_last_symbol", "RELIANCE.NS"),
            placeholder="Any NSE (.NS), BSE (.BO), or global ticker - e.g. RELIANCE.NS, TCS.NS, AAPL",
            label_visibility="collapsed",
        ).strip().upper()
        fetch_clicked = sc2.button("Get Quote", width="stretch")

        if fetch_clicked and symbol:
            st.session_state["pt_last_symbol"] = symbol
            try:
                st.session_state["pt_quote"] = get_live_quote(symbol)
            except ProviderError as exc:
                st.session_state["pt_quote"] = None
                error_banner(f"Could not fetch a quote for {symbol}: {exc}")

        quote = st.session_state.get("pt_quote")
        if quote and quote.symbol == symbol:
            ticker_hero(quote.symbol, quote.price, quote.prev_close, source=quote.source, live=True)
            st.caption(f"Day range {quote.day_low:,.2f} - {quote.day_high:,.2f}  ·  Volume {quote.volume:,}")

            qc1, qc2, qc3 = st.columns([1, 1, 1])
            quantity = qc1.number_input("Quantity", min_value=1, value=1, step=1, key=f"qty_{symbol}")
            est_cost = quantity * quote.price
            qc2.markdown(f'<div class="qp-secondary" style="margin-top:1.9rem;">Est. value</div><div class="qp-mono">{fmt_currency(est_cost)}</div>', unsafe_allow_html=True)

            from app.components import buy_button, sell_button

            bc1, bc2 = st.columns(2)
            with bc1:
                if buy_button("BUY", key=f"buy_{account_id}_{symbol}"):
                    try:
                        result = engine.place_order(account_id, symbol, "BUY", quantity)
                        st.success(f"Bought {quantity} {symbol} @ {fmt_currency(result.execution_price)} (costs {fmt_currency(result.costs)}, source: {result.quote_source})")
                        st.rerun()
                    except (InsufficientFundsError, ValueError) as exc:
                        error_banner(str(exc))
                    except ProviderError as exc:
                        error_banner(f"Order failed - could not get a live quote: {exc}")
            with bc2:
                if sell_button("SELL", key=f"sell_{account_id}_{symbol}"):
                    try:
                        result = engine.place_order(account_id, symbol, "SELL", quantity)
                        pnl_note = f", P&L {fmt_currency(result.realized_pnl)}" if result.realized_pnl is not None else ""
                        st.success(f"Sold {quantity} {symbol} @ {fmt_currency(result.execution_price)}{pnl_note}")
                        st.rerun()
                    except (InsufficientSharesError, ValueError) as exc:
                        error_banner(str(exc))
                    except ProviderError as exc:
                        error_banner(f"Order failed - could not get a live quote: {exc}")
        else:
            empty_state("No quote loaded", "Enter a symbol and click Get Quote before trading.")

    with watch_col:
        st.markdown('<div class="qp-card-title">Positions</div>', unsafe_allow_html=True)
        if positions.empty:
            empty_state("Flat", "No open positions.")
        else:
            refresh = st.button("↻ Refresh live P&L", width="stretch")
            rows_html = []
            for _, pos in positions.iterrows():
                try:
                    q = get_live_quote(pos["symbol"]) if refresh or f"mtm_{pos['symbol']}" not in st.session_state else st.session_state[f"mtm_{pos['symbol']}"]
                    if refresh or f"mtm_{pos['symbol']}" not in st.session_state:
                        st.session_state[f"mtm_{pos['symbol']}"] = q
                    unrealized = (q.price - pos["avg_price"]) * pos["quantity"]
                    unrealized_pct = (q.price / pos["avg_price"] - 1) * 100
                    cls = "qp-mono-pos" if unrealized >= 0 else "qp-mono-neg"
                    rows_html.append(
                        f'<div class="qp-watchrow"><span class="qp-watchrow-symbol">{pos["symbol"]}<br>'
                        f'<span class="qp-secondary">{pos["quantity"]:g} @ {pos["avg_price"]:,.2f}</span></span>'
                        f'<span class="{cls} qp-watchrow-price">{unrealized:+,.0f}<br>{unrealized_pct:+.2f}%</span></div>'
                    )
                except ProviderError:
                    rows_html.append(
                        f'<div class="qp-watchrow"><span class="qp-watchrow-symbol">{pos["symbol"]}</span>'
                        f'<span class="qp-secondary">quote unavailable</span></div>'
                    )
            st.markdown("".join(rows_html), unsafe_allow_html=True)

    st.write("")
    tab_positions, tab_history, tab_analysis = st.tabs(["Positions Detail", "Order History", "Full Analysis"])

    with tab_positions:
        if positions.empty:
            empty_state("No open positions")
        else:
            st.dataframe(positions[["symbol", "quantity", "avg_price"]], width="stretch", hide_index=True)

    with tab_history:
        trades = engine.get_trades(account_id)
        if trades.empty:
            empty_state("No orders yet", "Place your first order above.")
        else:
            display = trades[["execution_date", "symbol", "side", "execution_price", "quantity", "costs", "realized_pnl", "quote_source"]]
            st.dataframe(display.sort_values("execution_date", ascending=False), width="stretch", hide_index=True)

    with tab_analysis:
        equity = engine.get_equity_curve(account_id)
        trades = engine.get_trades(account_id)
        if equity.empty:
            empty_state("No analysis yet", "Place at least one order to start building an equity curve.")
        else:
            from analytics.performance import compute_performance_metrics
            from analytics.reporting import build_round_trip_trades

            metrics = compute_performance_metrics(equity, trades, float(account["initial_capital"]))
            performance_header(metrics)

            for w in check_single_backtest(metrics):
                warning_banner(w)

            st.write("")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=equity["date"], y=equity["total_value"], mode="lines",
                line=dict(color=COLORS["accent_cyan"], width=1.8), fill="tozeroy", fillcolor="rgba(45,212,245,0.06)",
            ))
            style_fig(fig, height=340, title="Account Equity Curve")
            st.plotly_chart(fig, width="stretch")

            round_trips = build_round_trip_trades(trades)
            if not round_trips.empty:
                st.markdown("### Closed Trades")
                st.dataframe(round_trips, width="stretch", hide_index=True)
