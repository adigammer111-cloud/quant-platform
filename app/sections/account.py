from __future__ import annotations

import streamlit as st

from app.auth_ui import log_out, require_login
from app.components import empty_state, fmt_currency, fmt_pct, render_topbar
from auth import service as auth
from data.providers.base import ProviderError
from data.providers.live_quotes import get_live_quote
from paper_trading import engine


def _account_summary_row(account_row) -> dict:
    account_id = account_row["account_id"]
    positions = engine.get_positions(account_id)
    holdings_value = 0.0
    for _, pos in positions.iterrows():
        try:
            quote = get_live_quote(pos["symbol"])
            holdings_value += quote.price * pos["quantity"]
        except ProviderError:
            holdings_value += pos["avg_price"] * pos["quantity"]  # conservative fallback

    total_value = float(account_row["cash"]) + holdings_value
    pnl_pct = (total_value / float(account_row["initial_capital"]) - 1) * 100
    return {
        "Account": account_row["name"],
        "ID": account_id,
        "Cash": fmt_currency(account_row["cash"]),
        "Positions": len(positions),
        "Total Value": fmt_currency(total_value),
        "P&L": fmt_pct(pnl_pct),
        "Created": str(account_row["created_at"])[:10],
    }


def render() -> None:
    if not require_login("Account", "Your profile and paper trading accounts"):
        return

    user_id = st.session_state["user_id"]
    info = auth.get_user_info(user_id)
    render_topbar("Account", f"Signed in as {info['username']}")

    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(
            f"""
            <div class="qp-card">
                <div class="qp-card-title">Profile</div>
                <div class="qp-mono" style="font-size:1.1rem;font-weight:600;">{info['username']}</div>
                <div class="qp-secondary">Member since {str(info['created_at'])[:10]}</div>
                <div class="qp-secondary" style="margin-top:6px;">User ID: {info['user_id']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Log Out", width="stretch"):
            log_out()
            st.rerun()

    with c2:
        st.markdown('<div class="qp-card-title">Your Paper Trading Accounts</div>', unsafe_allow_html=True)
        accounts = engine.list_accounts(user_id=user_id)
        if accounts.empty:
            empty_state("No accounts yet", "Open one from Paper Trading → Paper Trading.")
        else:
            with st.spinner("Marking positions to market..."):
                rows = [_account_summary_row(row) for _, row in accounts.iterrows()]
            st.dataframe(rows, width="stretch", hide_index=True)

            st.write("")
            st.markdown("##### Delete an account")
            st.caption("Irreversible - removes the account, its positions, and its full trade/equity history.")
            labels = [f"{r['name']} ({r['account_id'][-6:]})" for _, r in accounts.iterrows()]
            del_idx = st.selectbox("Account to delete", range(len(labels)), format_func=lambda i: labels[i])
            confirm = st.checkbox("I understand this cannot be undone")
            if st.button("Delete Account", disabled=not confirm):
                engine.delete_account(accounts.iloc[del_idx]["account_id"])
                st.success("Account deleted.")
                st.rerun()
