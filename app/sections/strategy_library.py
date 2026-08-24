from __future__ import annotations

import streamlit as st

from app.components import empty_state, render_topbar, status_badge
from database.strategy_repository import delete_saved_strategy, get_saved_strategy, list_saved_strategies
from strategies.registry import STRATEGY_REGISTRY

BUILTIN_DESCRIPTIONS = {
    "sma_crossover": "Long while the fast SMA sits above the slow SMA - a trend-following crossover.",
    "rsi_mean_reversion": "Enter oversold (RSI below threshold), hold until RSI recovers past the exit level.",
    "ma_momentum": "Long when price and the medium SMA both confirm an established uptrend vs. the long SMA.",
    "bollinger_mean_reversion": "Enter when price closes below the lower Bollinger Band, exit at the middle band.",
    "breakout": "Donchian-channel breakout: enter on a new N-day high, exit on a new M-day low.",
}


def render() -> None:
    render_topbar("Strategy Library", "Built-in strategies and everything you've saved from the Strategy Builder")

    st.markdown("### Built-in Strategies")
    for name, cls in STRATEGY_REGISTRY.items():
        instance = cls()
        with st.container():
            c1, c2, c3 = st.columns([2.5, 4, 1.2])
            c1.markdown(f"**{name}**  {status_badge('built-in', 'neutral')}", unsafe_allow_html=True)
            c2.markdown(f'<span class="qp-secondary">{BUILTIN_DESCRIPTIONS.get(name, "")}</span>', unsafe_allow_html=True)
            if c3.button("Use →", key=f"use_builtin_{name}"):
                st.session_state["pending_strategy"] = {"kind": "builtin", "name": name, "params": instance.params, "risk": {}}
                st.session_state["current_page"] = "Backtests"
                st.rerun()
        st.markdown(f'<div class="qp-secondary" style="margin:-6px 0 10px 0;">Default params: {instance.params}</div>', unsafe_allow_html=True)

    st.write("")
    st.markdown("### Your Saved Strategies")
    saved = list_saved_strategies()
    if saved.empty:
        empty_state("No custom strategies yet", "Build one in Strategies → Strategy Builder and click Save to Library.")
        return

    for _, row in saved.iterrows():
        c1, c2, c3, c4 = st.columns([2.5, 1.5, 3, 1.5])
        c1.markdown(f"**{row['name']}**")
        c2.markdown(status_badge(row["kind"], "neutral"), unsafe_allow_html=True)
        c3.markdown(f'<span class="qp-secondary">{row["created_at"]}</span>', unsafe_allow_html=True)
        with c4:
            use_col, del_col = st.columns(2)
            if use_col.button("Use", key=f"use_saved_{row['strategy_id']}"):
                record = get_saved_strategy(row["strategy_id"])
                if record["kind"] == "rule_based":
                    from strategies.rule_based import Condition

                    entry = [Condition(**{k: v for k, v in c.items() if k != "id"}) for c in record["definition"]["entry"]]
                    exit_ = [Condition(**{k: v for k, v in c.items() if k != "id"}) for c in record["definition"]["exit"]]
                    st.session_state["pending_strategy"] = {"kind": "rule_based", "name": row["name"], "entry": entry, "exit": exit_, "risk": record["risk"]}
                else:
                    st.session_state["pending_strategy"] = {
                        "kind": "custom_code", "name": row["name"],
                        "source_code": record["definition"]["source_code"], "risk": record["risk"],
                    }
                st.session_state["current_page"] = "Backtests"
                st.rerun()
            if del_col.button("Delete", key=f"del_saved_{row['strategy_id']}"):
                delete_saved_strategy(row["strategy_id"])
                st.rerun()
