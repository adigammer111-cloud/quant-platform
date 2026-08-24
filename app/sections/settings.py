from __future__ import annotations

import streamlit as st

from app.components import render_topbar
from backtesting.costs import TransactionCostModel
from config import settings
from database.db import get_connection


def render() -> None:
    render_topbar("Settings", "Environment, database, and default cost-model configuration")

    st.markdown("### Environment")
    st.markdown(
        f"""
        <div class="qp-card">
        <table style="width:100%; font-family:'JetBrains Mono'; font-size:0.85rem;">
            <tr><td class="qp-secondary" style="padding:5px 0;">Data provider</td><td style="text-align:right;">{settings.data_provider}</td></tr>
            <tr><td class="qp-secondary" style="padding:5px 0;">Data directory</td><td style="text-align:right;">{settings.data_dir}</td></tr>
            <tr><td class="qp-secondary" style="padding:5px 0;">DuckDB path</td><td style="text-align:right;">{settings.duckdb_path}</td></tr>
            <tr><td class="qp-secondary" style="padding:5px 0;">Log level</td><td style="text-align:right;">{settings.log_level}</td></tr>
            <tr><td class="qp-secondary" style="padding:5px 0;">HTTP max retries</td><td style="text-align:right;">{settings.http_max_retries}</td></tr>
            <tr><td class="qp-secondary" style="padding:5px 0;">HTTP min interval (s)</td><td style="text-align:right;">{settings.http_min_interval_seconds}</td></tr>
        </table>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    st.markdown("### Database Tables")
    with get_connection(read_only=True) as con:
        table_rows = con.execute("SHOW TABLES").fetchdf()
        counts = []
        for t in table_rows["name"]:
            try:
                n = con.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()[0]
            except Exception:
                n = None
            counts.append({"table": t, "row_count": n})
    st.dataframe(counts, width="stretch", hide_index=True)

    st.write("")
    st.markdown("### Default Transaction Cost Model")
    st.caption("These are the defaults applied when a backtest doesn't override them. Indian equity charges change over time - verify against your broker before trusting results for capital allocation.")
    default_costs = TransactionCostModel()
    st.json(
        {
            "brokerage_pct": default_costs.brokerage_pct,
            "brokerage_flat_cap": default_costs.brokerage_flat_cap,
            "stt_pct_buy": default_costs.stt_pct_buy,
            "stt_pct_sell": default_costs.stt_pct_sell,
            "exchange_txn_pct": default_costs.exchange_txn_pct,
            "sebi_fee_pct": default_costs.sebi_fee_pct,
            "stamp_duty_pct_buy": default_costs.stamp_duty_pct_buy,
            "gst_pct": default_costs.gst_pct,
            "slippage_bps": default_costs.slippage_bps,
        }
    )
