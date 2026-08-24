from __future__ import annotations

import streamlit as st

from app.components import data_health_card, empty_state, render_topbar, status_badge
from data.storage.repository import get_data_status


def render() -> None:
    render_topbar("Data Health", "Coverage, freshness, and validation status across every tracked symbol")

    status = get_data_status()
    if status.empty:
        empty_state("No data yet", "Go to System → Data to download a universe.")
        return

    c1, c2 = st.columns([1, 2.2])
    with c1:
        data_health_card(status)
    with c2:
        st.markdown("### Per-Symbol Status")
        if "status" in status.columns:
            warn_or_error = status[status["status"] != "OK"]
            if not warn_or_error.empty:
                st.markdown(
                    " ".join(
                        status_badge(f"{r.symbol}: {r.status}", "error" if r.status == "ERROR" else "warn")
                        for r in warn_or_error.itertuples()
                    ),
                    unsafe_allow_html=True,
                )
                st.write("")
        st.dataframe(status, width="stretch", hide_index=True)
