from __future__ import annotations

import uuid

import streamlit as st

from app.components import render_topbar, warning_banner
from database.strategy_repository import save_strategy
from strategies.rule_based import Condition

SERIES_OPTIONS = ["price", "sma", "ema", "rsi", "bb_upper", "bb_mid", "bb_lower", "volume", "value"]
SERIES_LABELS = {
    "price": "Price", "sma": "SMA", "ema": "EMA", "rsi": "RSI",
    "bb_upper": "Bollinger Upper", "bb_mid": "Bollinger Mid", "bb_lower": "Bollinger Lower",
    "volume": "Volume", "value": "Fixed value",
}
WINDOWED = {"sma", "ema", "rsi"}
OPERATORS = [">", "<", ">=", "<=", "crosses_above", "crosses_below"]


def _default_condition(kind: str) -> dict:
    if kind == "entry":
        return {"id": str(uuid.uuid4()), "left": "price", "left_window": 200, "operator": ">", "right": "sma", "right_window": 200, "right_value": 0.0}
    return {"id": str(uuid.uuid4()), "left": "rsi", "left_window": 14, "operator": ">", "right": "value", "right_window": 20, "right_value": 50.0}


def _ensure_state() -> None:
    if "builder_entry" not in st.session_state:
        st.session_state["builder_entry"] = [_default_condition("entry")]
    if "builder_exit" not in st.session_state:
        st.session_state["builder_exit"] = [_default_condition("exit")]


def _condition_row(cond: dict, group: str) -> None:
    cols = st.columns([2, 1, 2, 2, 1, 0.6])
    cond["left"] = cols[0].selectbox(
        "Left", SERIES_OPTIONS, index=SERIES_OPTIONS.index(cond["left"]), key=f"{group}_left_{cond['id']}",
        format_func=lambda k: SERIES_LABELS[k], label_visibility="collapsed",
    )
    if cond["left"] in WINDOWED:
        cond["left_window"] = cols[1].number_input("Window", 2, 500, cond["left_window"], key=f"{group}_lw_{cond['id']}", label_visibility="collapsed")
    else:
        cols[1].markdown("&nbsp;", unsafe_allow_html=True)

    cond["operator"] = cols[2].selectbox(
        "Op", OPERATORS, index=OPERATORS.index(cond["operator"]), key=f"{group}_op_{cond['id']}", label_visibility="collapsed",
    )

    cond["right"] = cols[3].selectbox(
        "Right", SERIES_OPTIONS, index=SERIES_OPTIONS.index(cond["right"]), key=f"{group}_right_{cond['id']}",
        format_func=lambda k: SERIES_LABELS[k], label_visibility="collapsed",
    )

    if cond["right"] == "value":
        cond["right_value"] = cols[4].number_input("Value", value=float(cond["right_value"]), key=f"{group}_rv_{cond['id']}", label_visibility="collapsed")
    elif cond["right"] in WINDOWED:
        cond["right_window"] = cols[4].number_input("Window", 2, 500, cond["right_window"], key=f"{group}_rw_{cond['id']}", label_visibility="collapsed")
    else:
        cols[4].markdown("&nbsp;", unsafe_allow_html=True)

    if cols[5].button("✕", key=f"{group}_remove_{cond['id']}"):
        st.session_state[f"builder_{group}"] = [c for c in st.session_state[f"builder_{group}"] if c["id"] != cond["id"]]
        st.rerun()


def _conditions_to_objects(raw: list[dict]) -> list[Condition]:
    return [
        Condition(
            left=c["left"], operator=c["operator"], right=c["right"],
            left_window=c.get("left_window", 20), right_window=c.get("right_window", 20),
            right_value=c.get("right_value", 0.0),
        )
        for c in raw
    ]


def render() -> None:
    render_topbar("Strategy Builder", "Compose entry/exit rules visually, or write Python directly")
    _ensure_state()

    mode = st.radio("Mode", ["Visual Builder", "Advanced Python"], horizontal=True, label_visibility="collapsed")

    if mode == "Visual Builder":
        st.markdown("### Entry Rules")
        st.caption("ALL conditions below must hold simultaneously to open a position.")
        for cond in st.session_state["builder_entry"]:
            _condition_row(cond, "entry")
            st.markdown(
                f'<div class="qp-secondary" style="margin:-6px 0 8px 4px;">{Condition(cond["left"], cond["operator"], cond["right"], cond.get("left_window",20), cond.get("right_window",20), cond.get("right_value",0.0)).describe()}</div>',
                unsafe_allow_html=True,
            )
        if st.button("+ Add entry condition"):
            st.session_state["builder_entry"].append(_default_condition("entry"))
            st.rerun()

        st.write("")
        st.markdown("### Exit Rules")
        st.caption("ANY ONE condition below triggers a close (first warning sign exits the position).")
        for cond in st.session_state["builder_exit"]:
            _condition_row(cond, "exit")
            st.markdown(
                f'<div class="qp-secondary" style="margin:-6px 0 8px 4px;">{Condition(cond["left"], cond["operator"], cond["right"], cond.get("left_window",20), cond.get("right_window",20), cond.get("right_value",0.0)).describe()}</div>',
                unsafe_allow_html=True,
            )
        if st.button("+ Add exit condition"):
            st.session_state["builder_exit"].append(_default_condition("exit"))
            st.rerun()

        st.write("")
        st.markdown("### Risk Management")
        r1, r2, r3, r4 = st.columns(4)
        max_position_pct = r1.slider("Max position size (%)", 5, 100, 20) / 100
        use_sl = r2.checkbox("Stop loss", value=True)
        stop_loss_pct = r2.slider("Stop loss %", 1, 30, 8, disabled=not use_sl) / 100 if use_sl else None
        use_tp = r3.checkbox("Take profit", value=False)
        take_profit_pct = r3.slider("Take profit %", 1, 60, 15, disabled=not use_tp) / 100 if use_tp else None
        use_ts = r4.checkbox("Trailing stop", value=False)
        trailing_stop_pct = r4.slider("Trailing stop %", 1, 30, 10, disabled=not use_ts) / 100 if use_ts else None

        definition = {
            "entry": st.session_state["builder_entry"],
            "exit": st.session_state["builder_exit"],
        }
        risk = {
            "max_position_pct": max_position_pct,
            "stop_loss": stop_loss_pct,
            "take_profit": take_profit_pct,
            "trailing_stop": trailing_stop_pct,
        }

        st.write("")
        strategy_name = st.text_input("Strategy name", "My Custom Strategy")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save to Library", type="primary"):
                if not st.session_state["builder_entry"]:
                    warning_banner("Add at least one entry condition before saving.")
                else:
                    sid = save_strategy(strategy_name, "rule_based", definition, risk)
                    st.success(f"Saved as '{strategy_name}' ({sid})")
        with c2:
            if st.button("Send to Backtests →"):
                st.session_state["pending_strategy"] = {
                    "kind": "rule_based", "name": strategy_name,
                    "entry": _conditions_to_objects(st.session_state["builder_entry"]),
                    "exit": _conditions_to_objects(st.session_state["builder_exit"]),
                    "risk": risk,
                }
                st.session_state["current_page"] = "Backtests"
                st.rerun()

    else:
        st.markdown("### Advanced Python Mode")
        st.caption(
            "Write the body of `generate_signals(data)`. `data` has columns open/high/low/close/volume, "
            "indexed by date. Return a pandas Series of -1/0/1 aligned to `data.index`. "
            "Available: `pd`, `np`, `sma`, `ema`, `rsi`, `bollinger_bands`. "
            "Runs locally with a restricted builtin set (no file/network/OS access)."
        )
        default_code = (
            "fast = sma(data['close'], 20)\n"
            "slow = sma(data['close'], 50)\n"
            "signal = (fast > slow).astype(int)\n"
            "return signal.where(fast.notna() & slow.notna(), 0)"
        )
        code = st.text_area("generate_signals(data):", value=st.session_state.get("builder_code", default_code), height=220)
        st.session_state["builder_code"] = code

        c1, c2 = st.columns(2)
        with c1:
            code_name = st.text_input("Strategy name", "My Python Strategy", key="code_name")
            if st.button("Save to Library", key="save_code", type="primary"):
                sid = save_strategy(code_name, "custom_code", {"source_code": code}, {})
                st.success(f"Saved as '{code_name}' ({sid})")
        with c2:
            if st.button("Send to Backtests →", key="send_code"):
                st.session_state["pending_strategy"] = {"kind": "custom_code", "name": code_name, "source_code": code, "risk": {}}
                st.session_state["current_page"] = "Backtests"
                st.rerun()
