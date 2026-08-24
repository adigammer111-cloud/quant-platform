"""Reusable UI components for the dashboard. Everything here is a plain
function that renders HTML/Streamlit widgets using the tokens in
`app.theme` - no page should hard-code a hex color or write ad-hoc HTML for
something already covered here.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.theme import COLORS

StatusKind = Literal["ok", "warn", "error", "neutral"]


# --------------------------------------------------------------- formatting
def fmt_currency(value: float, symbol: str = "₹", decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.{decimals}f}"


def fmt_pct(value: float, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.{decimals}f}%"


def fmt_num(value: float, decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{decimals}f}"


def signed_class(value: float) -> str:
    if value is None or pd.isna(value):
        return "qp-mono"
    return "qp-mono-pos" if value >= 0 else "qp-mono-neg"


# ---------------------------------------------------------------- metric card
def metric_card(label: str, value: str, delta: str | None = None, delta_positive: bool | None = None) -> None:
    delta_html = ""
    if delta is not None:
        cls = "qp-mono" if delta_positive is None else ("qp-mono-pos" if delta_positive else "qp-mono-neg")
        delta_html = f'<div class="{cls}" style="font-size:0.78rem;margin-top:4px;">{delta}</div>'
    st.markdown(
        f"""
        <div class="qp-card">
            <div class="qp-card-title">{label}</div>
            <div class="qp-mono" style="font-size:1.45rem;font-weight:600;color:{COLORS['text']};">{value}</div>
            {delta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_row(metrics: list[tuple[str, str, str | None, bool | None]]) -> None:
    cols = st.columns(len(metrics))
    for col, (label, value, delta, positive) in zip(cols, metrics):
        with col:
            metric_card(label, value, delta, positive)


# ---------------------------------------------------------------- badges
_BADGE_CLASS = {"ok": "qp-badge-ok", "warn": "qp-badge-warn", "error": "qp-badge-error", "neutral": "qp-badge-neutral"}


def status_badge(text: str, status: StatusKind = "neutral") -> str:
    return f'<span class="qp-badge {_BADGE_CLASS[status]}">{text}</span>'


def status_dot(status: StatusKind = "neutral") -> str:
    dot_class = {"ok": "qp-dot-green", "warn": "qp-dot-amber", "error": "qp-dot-red", "neutral": "qp-dot-gray"}[status]
    return f'<span class="qp-dot {dot_class}"></span>'


# ---------------------------------------------------------------- banners
def warning_banner(text: str) -> None:
    st.markdown(f'<div class="qp-warning-banner">⚠ {text}</div>', unsafe_allow_html=True)


def error_banner(text: str) -> None:
    st.markdown(f'<div class="qp-error-banner">✕ {text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- empty/loading
def empty_state(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="qp-empty">
            <div class="qp-empty-title">{title}</div>
            <div>{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def loading_checklist(steps: list[str], active_index: int) -> None:
    """Renders a checklist where steps before `active_index` are done (✓),
    the step at `active_index` is active (●), and later steps are pending (○)."""
    rows = []
    for i, step in enumerate(steps):
        if i < active_index:
            icon, color = "✓", COLORS["profit"]
        elif i == active_index:
            icon, color = "●", COLORS["accent_cyan"]
        else:
            icon, color = "○", COLORS["text_secondary"]
        rows.append(
            f'<div class="qp-loading-row"><span style="color:{color};">{icon}</span>'
            f'<span style="color:{color if i <= active_index else COLORS["text_secondary"]};">{step}</span></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar nav
NAV_GROUPS: dict[str, list[str]] = {
    "Research": ["Dashboard", "Market", "Screener"],
    "Strategies": ["Strategy Library", "Strategy Builder"],
    "Backtesting": ["Backtests", "Optimizer", "Walk Forward", "Monte Carlo"],
    "Paper Trading": ["Paper Trading", "Account"],
    "Analytics": ["Performance", "Risk", "Trades"],
    "System": ["Data", "Data Health", "Settings"],
}


def render_sidebar_nav() -> str:
    """Renders the grouped sidebar nav as buttons, not radio widgets.

    An earlier version used one st.radio per group with a dynamically
    computed `index` (None for inactive groups). That doesn't work:
    Streamlit's radio persists its checked state on the frontend by widget
    key across reruns, and neither passing `index=None` nor deleting the
    key from session_state on the *next* render reliably un-checks an
    already-rendered radio - so switching groups left the previous group's
    item stuck looking selected. Buttons have no such persistent "checked"
    visual state to fight: the active item is just recomputed from
    `current_page` and given `type="primary"` fresh on every render.
    """
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "Dashboard"

    st.sidebar.markdown(
        '<div class="qp-brand"><div class="qp-brand-mark"></div>'
        '<div class="qp-brand-text">Quant Platform</div></div>',
        unsafe_allow_html=True,
    )

    current = st.session_state["current_page"]
    for group, items in NAV_GROUPS.items():
        st.sidebar.markdown(f'<div class="qp-nav-group-label">{group.upper()}</div>', unsafe_allow_html=True)
        for item in items:
            is_active = item == current
            if st.sidebar.button(
                item, key=f"navbtn_{item}", type="primary" if is_active else "secondary", width="stretch"
            ):
                st.session_state["current_page"] = item
                st.rerun()
    return st.session_state["current_page"]


# ---------------------------------------------------------------- topbar
def render_topbar(page_title: str, subtitle: str = "") -> None:
    now = dt.datetime.now().strftime("%H:%M:%S")
    st.markdown(
        f"""
        <div class="qp-topbar">
            <div class="qp-topbar-left">
                <div class="qp-topbar-title">{page_title}</div>
                <div class="qp-secondary">{subtitle}</div>
            </div>
            <div class="qp-topbar-right">
                <span class="qp-pill">{status_dot('ok')} NSE Session</span>
                <span class="qp-pill">{now} IST</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- performance header
def performance_header(metrics) -> None:
    """`metrics`: an analytics.performance.PerformanceMetrics instance."""
    metric_row(
        [
            ("Final Capital", fmt_currency(metrics.final_capital), fmt_pct(metrics.absolute_return_pct), metrics.absolute_return_pct >= 0),
            ("CAGR", fmt_pct(metrics.cagr_pct), None, None),
            ("Sharpe", fmt_num(metrics.sharpe_ratio), None, None),
            ("Sortino", fmt_num(metrics.sortino_ratio), None, None),
            ("Max Drawdown", fmt_pct(metrics.max_drawdown_pct), None, None),
            ("Win Rate", fmt_pct(metrics.win_rate_pct, 1), None, None),
        ]
    )
    st.write("")
    metric_row(
        [
            ("Profit Factor", fmt_num(metrics.profit_factor), None, None),
            ("Trades", str(metrics.num_trades), None, None),
            ("Avg Holding (days)", fmt_num(metrics.avg_holding_period_days, 1), None, None),
            ("Expectancy", fmt_currency(metrics.expectancy), None, None),
            ("Turnover", f"{metrics.turnover_ratio:.1f}x", None, None),
            ("Volatility (ann.)", fmt_pct(metrics.volatility_annualized_pct, 1), None, None),
        ]
    )


# ---------------------------------------------------------------- data health card
def data_health_card(status_df: pd.DataFrame) -> None:
    if status_df.empty:
        empty_state("No data yet", "Go to System → Data to download a universe.")
        return

    total_rows = int(status_df["row_count"].sum()) if "row_count" in status_df else 0
    n_symbols = len(status_df)
    last_update = pd.to_datetime(status_df["last_updated_at"]).max() if "last_updated_at" in status_df else None
    warn_count = int((status_df["status"] == "WARNING").sum()) if "status" in status_df else 0
    error_count = int((status_df["status"] == "ERROR").sum()) if "status" in status_df else 0

    if last_update is not None:
        age_min = int((pd.Timestamp.now() - last_update).total_seconds() // 60)
        age_str = f"{age_min} min ago" if age_min < 60 else f"{age_min // 60}h {age_min % 60}m ago"
    else:
        age_str = "—"

    overall_status: StatusKind = "error" if error_count else ("warn" if warn_count else "ok")

    st.markdown(
        f"""
        <div class="qp-card">
            <div class="qp-card-title">Data Health</div>
            <table style="width:100%; font-family:{'JetBrains Mono'}; font-size:0.85rem; color:{COLORS['text']}; border-collapse:collapse;">
                <tr><td class="qp-secondary" style="padding:4px 0;">NSE</td><td style="text-align:right;">{status_dot(overall_status)} {"Operational" if overall_status=="ok" else ("Attention" if overall_status=="warn" else "Error")}</td></tr>
                <tr><td class="qp-secondary" style="padding:4px 0;">Last update</td><td style="text-align:right;">{age_str}</td></tr>
                <tr><td class="qp-secondary" style="padding:4px 0;">Symbols tracked</td><td style="text-align:right;">{n_symbols}</td></tr>
                <tr><td class="qp-secondary" style="padding:4px 0;">Total rows</td><td style="text-align:right;">{total_rows:,}</td></tr>
                <tr><td class="qp-secondary" style="padding:4px 0;">Warnings</td><td style="text-align:right;">{warn_count}</td></tr>
                <tr><td class="qp-secondary" style="padding:4px 0;">Errors</td><td style="text-align:right;">{error_count}</td></tr>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------- ticker / watchlist
def ticker_hero(symbol: str, price: float, prev_close: float, as_of: str = "", source: str = "", live: bool = True) -> None:
    """Big TradingView-style price header: symbol, huge tabular price,
    colored change, and a pulsing 'live' dot when `live` is True."""
    change = price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0
    color_class = "qp-mono-pos" if change >= 0 else "qp-mono-neg"
    dot_html = '<span class="qp-dot qp-dot-green qp-dot-live" style="margin-right:6px;"></span>' if live else ""
    meta = f'<span class="qp-secondary">{symbol}{" &middot; " + source if source else ""}{" &middot; " + as_of if as_of else ""}</span>'
    # Deliberately a single line with no embedded newlines/indentation: a
    # multi-line indented f-string here can trip CommonMark's indented-code-
    # block rule (most reliably when an interpolated part is empty, leaving
    # a blank-looking indented line) and render as literal escaped text
    # instead of HTML, even with unsafe_allow_html=True.
    html = (
        f'<div class="qp-ticker">{dot_html}'
        f'<span class="qp-ticker-price">{price:,.2f}</span>'
        f'<span class="{color_class} qp-ticker-change">{change:+,.2f} ({change_pct:+.2f}%)</span>'
        f"{meta}</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def watchlist_row(symbol: str, price: float, prev_close: float) -> str:
    """Returns HTML for one compact watchlist row - caller wraps a batch of
    these in a single st.markdown call for performance."""
    change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
    cls = "qp-mono-pos" if change_pct >= 0 else "qp-mono-neg"
    return (
        f'<div class="qp-watchrow">'
        f'<span class="qp-watchrow-symbol">{symbol}</span>'
        f'<span class="qp-watchrow-price {cls}">{price:,.2f}&nbsp;&nbsp;{change_pct:+.2f}%</span>'
        f"</div>"
    )


def watchlist_panel(rows: list[tuple[str, float, float]]) -> None:
    """`rows`: list of (symbol, price, prev_close)."""
    st.markdown("".join(watchlist_row(*r) for r in rows), unsafe_allow_html=True)


def buy_button(label: str = "BUY", key: str = "default") -> bool:
    # Separate st.markdown() calls render as DOM *siblings*, not parents, so
    # wrapping a button between two markdown calls does not actually nest it
    # for CSS purposes. st.container(key=...) is the real scoping mechanism:
    # Streamlit stamps that container's element with a `st-key-{key}` class,
    # which theme.py targets via an attribute-substring selector.
    with st.container(key=f"qpbuy_{key}"):
        return st.button(label, key=f"qpbuy_btn_{key}", width="stretch")


def sell_button(label: str = "SELL", key: str = "default") -> bool:
    with st.container(key=f"qpsell_{key}"):
        return st.button(label, key=f"qpsell_btn_{key}", width="stretch")


# ---------------------------------------------------------------- misc
def parse_param_grid(text: str) -> dict[str, list]:
    """Parses lines like 'fast_period=10,20,30' into a param grid dict."""
    grid: dict[str, list] = {}
    for line in text.strip().splitlines():
        if not line.strip() or "=" not in line:
            continue
        name, values = line.split("=", 1)
        parsed = []
        for v in values.split(","):
            v = v.strip()
            try:
                parsed.append(int(v))
            except ValueError:
                try:
                    parsed.append(float(v))
                except ValueError:
                    parsed.append(v)
        grid[name.strip()] = parsed
    return grid


# ---------------------------------------------------------------- chart helpers
def style_fig(fig: go.Figure, height: int = 380, title: str | None = None) -> go.Figure:
    fig.update_layout(template="quant_dark", height=height)
    if title:
        fig.update_layout(title=title)
    return fig
