"""Centralized design tokens for the dashboard: colors, spacing, typography,
borders, radii. Every page imports from here instead of hard-coding hex
values or px sizes, and `inject_css()` is the single place that reskins
Streamlit's default widgets to match. Base color theme (dark background,
primary color) is also set natively via .streamlit/config.toml - this
module layers typography, spacing, and custom component styling on top of
that, and provides a matching Plotly template so every chart in the app
shares one visual language.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------- palette
# Tighter, punchier, and closer to a real trading terminal's contrast level
# than the first pass - modeled on how TradingView actually reads (near-black
# blue-charcoal ground, a vivid electric-blue interactive accent, saturated
# up/down colors that pop hard against the ground) while keeping our own
# accent identity (cyan/purple) rather than cloning their exact blue.
COLORS = {
    "bg": "#0A0E14",
    "surface": "#10151D",
    "surface_elevated": "#161C26",
    "border": "#232B38",
    "text": "#E8EDF4",
    "text_secondary": "#7C8AA0",
    "accent_cyan": "#2DD4F5",
    "accent_purple": "#8B7CFF",
    "profit": "#00D68F",
    "loss": "#FF3D5A",
    "warning": "#FFB020",
}

FONT_SANS = "'Inter', 'Manrope', -apple-system, BlinkMacSystemFont, sans-serif"
FONT_MONO = "'JetBrains Mono', 'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace"

SPACE = {"xs": "4px", "sm": "8px", "md": "14px", "lg": "20px", "xl": "28px", "xxl": "40px"}
RADIUS = {"sm": "3px", "md": "5px", "lg": "8px"}


def _register_plotly_template() -> None:
    template = go.layout.Template()
    template.layout = go.Layout(
        paper_bgcolor=COLORS["surface"],
        plot_bgcolor=COLORS["surface"],
        font=dict(family=FONT_SANS, color=COLORS["text_secondary"], size=12),
        title=dict(font=dict(family=FONT_SANS, color=COLORS["text"], size=15)),
        colorway=[
            COLORS["accent_cyan"], COLORS["accent_purple"], COLORS["profit"],
            COLORS["warning"], COLORS["loss"], "#5B7A99", "#B892FF",
        ],
        xaxis=dict(
            gridcolor=COLORS["border"], zerolinecolor=COLORS["border"],
            linecolor=COLORS["border"], tickfont=dict(color=COLORS["text_secondary"]),
        ),
        yaxis=dict(
            gridcolor=COLORS["border"], zerolinecolor=COLORS["border"],
            linecolor=COLORS["border"], tickfont=dict(color=COLORS["text_secondary"]),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)", font=dict(color=COLORS["text_secondary"]),
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
        ),
        margin=dict(l=48, r=24, t=40, b=40),
        hoverlabel=dict(
            bgcolor=COLORS["surface_elevated"], font=dict(family=FONT_MONO, color=COLORS["text"]),
            bordercolor=COLORS["border"],
        ),
    )
    pio.templates["quant_dark"] = template
    pio.templates.default = "quant_dark"


_register_plotly_template()


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

        html, body, [class*="css"], .stApp {{
            font-family: {FONT_SANS};
        }}

        .stApp {{
            background: {COLORS["bg"]};
        }}

        /* ---- Numeric / monospace elements ---- */
        [data-testid="stMetricValue"], [data-testid="stMetricDelta"],
        .qp-mono, .stDataFrame, .stTable, code {{
            font-family: {FONT_MONO} !important;
        }}

        /* ---- Sidebar ---- */
        section[data-testid="stSidebar"] {{
            background: {COLORS["surface"]};
            border-right: 1px solid {COLORS["border"]};
        }}
        section[data-testid="stSidebar"] > div {{
            padding-top: 0.5rem;
        }}

        /* ---- Sidebar nav (buttons styled as a nav list - see
           render_sidebar_nav()'s docstring for why buttons, not radios) ---- */
        .qp-nav-group-label {{
            font-size: 0.66rem;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: {COLORS["text_secondary"]};
            font-weight: 600;
            margin: 14px 4px 4px 4px;
        }}
        section[data-testid="stSidebar"] .stButton {{
            margin: 0; padding: 0;
        }}
        section[data-testid="stSidebar"] .stButton > button {{
            display: flex; justify-content: flex-start; align-items: center;
            width: 100%; text-align: left;
            padding: 6px 10px; margin: 1px 0;
            background: transparent; border: 1px solid transparent; border-left: 2px solid transparent;
            border-radius: {RADIUS["sm"]};
            color: {COLORS["text_secondary"]}; font-size: 0.86rem; font-weight: 500;
            box-shadow: none;
        }}
        section[data-testid="stSidebar"] .stButton > button:hover {{
            background: {COLORS["surface_elevated"]};
            color: {COLORS["text"]};
            border-color: transparent;
            box-shadow: none;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: rgba(45,212,245,0.10);
            color: {COLORS["accent_cyan"]};
            font-weight: 600;
            border-left: 2px solid {COLORS["accent_cyan"]};
            box-shadow: none;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
            background: rgba(45,212,245,0.16);
            color: {COLORS["accent_cyan"]};
            box-shadow: none;
        }}
        section[data-testid="stSidebar"] hr {{
            margin: 10px 0; border-color: {COLORS["border"]};
        }}
        .qp-brand {{
            display: flex; align-items: center; gap: 8px;
            padding: 4px 4px 14px 4px; margin-bottom: 4px;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .qp-brand-mark {{
            width: 22px; height: 22px; border-radius: 6px;
            background: linear-gradient(135deg, {COLORS["accent_cyan"]}, {COLORS["accent_purple"]});
        }}
        .qp-brand-text {{ font-weight: 700; font-size: 0.95rem; color: {COLORS["text"]}; letter-spacing: -0.01em; }}

        /* ---- Metric cards (tighter, denser - terminal not brochure) ---- */
        [data-testid="stMetric"] {{
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: {RADIUS["sm"]};
            padding: 10px 12px 8px 12px;
        }}
        [data-testid="stMetricLabel"] {{
            color: {COLORS["text_secondary"]};
            font-size: 0.68rem;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }}
        [data-testid="stMetricValue"] {{
            color: {COLORS["text"]};
            font-size: 1.3rem;
            font-variant-numeric: tabular-nums;
        }}

        /* ---- Buttons ---- */
        .stButton > button {{
            background: {COLORS["surface_elevated"]};
            color: {COLORS["text"]};
            border: 1px solid {COLORS["border"]};
            border-radius: {RADIUS["sm"]};
            font-weight: 500;
            transition: border-color 150ms ease, color 150ms ease, box-shadow 150ms ease;
        }}
        .stButton > button:hover {{
            border-color: {COLORS["accent_cyan"]};
            color: {COLORS["accent_cyan"]};
        }}
        .stButton > button[kind="primary"] {{
            background: {COLORS["accent_cyan"]};
            color: {COLORS["bg"]};
            border: 1px solid {COLORS["accent_cyan"]};
            font-weight: 700;
            box-shadow: 0 0 0 rgba(45,212,245,0);
        }}
        .stButton > button[kind="primary"]:hover {{
            background: #52e0fc;
            color: {COLORS["bg"]};
            box-shadow: 0 0 14px rgba(45,212,245,0.35);
        }}

        /* ---- Buy / Sell action buttons (order tickets) ----
           Scoped via st.container(key="qpbuy_*"/"qpsell_*"), which Streamlit
           stamps onto the container element as class `st-key-qpbuy_*` etc. */
        div[class*="st-key-qpbuy_"] button {{
            background: {COLORS["profit"]} !important;
            border: 1px solid {COLORS["profit"]} !important;
            color: #04140F !important;
            font-weight: 700 !important;
        }}
        div[class*="st-key-qpbuy_"] button:hover {{ box-shadow: 0 0 14px rgba(0,214,143,0.4); }}
        div[class*="st-key-qpsell_"] button {{
            background: {COLORS["loss"]} !important;
            border: 1px solid {COLORS["loss"]} !important;
            color: #1A0508 !important;
            font-weight: 700 !important;
        }}
        div[class*="st-key-qpsell_"] button:hover {{ box-shadow: 0 0 14px rgba(255,61,90,0.4); }}

        /* ---- Tabs ---- */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px;
            border-bottom: 1px solid {COLORS["border"]};
        }}
        .stTabs [data-baseweb="tab"] {{
            color: {COLORS["text_secondary"]};
            font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            color: {COLORS["accent_cyan"]} !important;
        }}

        /* ---- Inputs ---- */
        .stTextInput input, .stNumberInput input, .stDateInput input,
        .stSelectbox [data-baseweb="select"], .stTextArea textarea {{
            background: {COLORS["surface"]} !important;
            border: 1px solid {COLORS["border"]} !important;
            color: {COLORS["text"]} !important;
            border-radius: {RADIUS["sm"]};
        }}

        /* ---- Headings tightened ---- */
        h1, h2, h3 {{
            font-weight: 700;
            letter-spacing: -0.01em;
        }}
        h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
        h2 {{ font-size: 1.15rem; color: {COLORS["text"]}; }}
        h3 {{ font-size: 0.95rem; color: {COLORS["text_secondary"]}; text-transform: uppercase; letter-spacing: 0.05em; }}

        /* ---- Custom components ---- */
        .qp-topbar {{
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 4px 18px 4px; border-bottom: 1px solid {COLORS["border"]};
            margin-bottom: 20px;
        }}
        .qp-topbar-left {{ display: flex; align-items: center; gap: 14px; }}
        .qp-topbar-title {{ font-size: 1.05rem; font-weight: 600; color: {COLORS["text"]}; }}
        .qp-topbar-right {{ display: flex; align-items: center; gap: 18px; }}
        .qp-pill {{
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 0.75rem; color: {COLORS["text_secondary"]};
            background: {COLORS["surface"]}; border: 1px solid {COLORS["border"]};
            border-radius: 999px; padding: 4px 12px;
            font-family: {FONT_MONO};
        }}
        .qp-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
        .qp-dot-green {{ background: {COLORS["profit"]}; box-shadow: 0 0 6px {COLORS["profit"]}; }}
        .qp-dot-red {{ background: {COLORS["loss"]}; box-shadow: 0 0 6px {COLORS["loss"]}; }}
        .qp-dot-amber {{ background: {COLORS["warning"]}; box-shadow: 0 0 6px {COLORS["warning"]}; }}
        .qp-dot-gray {{ background: {COLORS["text_secondary"]}; }}
        .qp-dot-live {{ animation: qp-pulse 1.6s ease-in-out infinite; }}
        @keyframes qp-pulse {{
            0%   {{ opacity: 1; transform: scale(1); }}
            50%  {{ opacity: 0.45; transform: scale(0.85); }}
            100% {{ opacity: 1; transform: scale(1); }}
        }}

        .qp-card {{
            background: {COLORS["surface"]};
            border: 1px solid {COLORS["border"]};
            border-radius: {RADIUS["sm"]};
            padding: 12px 14px;
        }}
        .qp-card-title {{
            font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
            color: {COLORS["text_secondary"]}; margin-bottom: 8px;
        }}

        .qp-badge {{
            display: inline-block; font-size: 0.7rem; font-weight: 600;
            padding: 2px 9px; border-radius: 999px; font-family: {FONT_MONO};
        }}
        .qp-badge-ok {{ background: rgba(0,214,143,0.12); color: {COLORS["profit"]}; border: 1px solid rgba(0,214,143,0.3); }}
        .qp-badge-warn {{ background: rgba(255,176,32,0.12); color: {COLORS["warning"]}; border: 1px solid rgba(255,176,32,0.3); }}
        .qp-badge-error {{ background: rgba(255,61,90,0.12); color: {COLORS["loss"]}; border: 1px solid rgba(255,61,90,0.3); }}
        .qp-badge-neutral {{ background: rgba(124,138,160,0.12); color: {COLORS["text_secondary"]}; border: 1px solid {COLORS["border"]}; }}

        .qp-warning-banner {{
            background: rgba(255,176,32,0.08);
            border: 1px solid rgba(255,176,32,0.35);
            border-left: 3px solid {COLORS["warning"]};
            border-radius: {RADIUS["sm"]};
            padding: 10px 14px; margin-bottom: 10px;
            color: #F4E4C1; font-size: 0.85rem;
        }}
        .qp-error-banner {{
            background: rgba(255,61,90,0.08);
            border: 1px solid rgba(255,61,90,0.35);
            border-left: 3px solid {COLORS["loss"]};
            border-radius: {RADIUS["sm"]};
            padding: 10px 14px; margin-bottom: 10px;
            color: #FFD7DB; font-size: 0.85rem;
        }}

        .qp-empty {{
            text-align: center; padding: 48px 20px; color: {COLORS["text_secondary"]};
            border: 1px dashed {COLORS["border"]}; border-radius: {RADIUS["md"]};
        }}
        .qp-empty-title {{ color: {COLORS["text"]}; font-weight: 600; margin-bottom: 4px; }}

        .qp-mono-pos {{ color: {COLORS["profit"]}; font-family: {FONT_MONO}; font-weight: 600; font-variant-numeric: tabular-nums; }}
        .qp-mono-neg {{ color: {COLORS["loss"]}; font-family: {FONT_MONO}; font-weight: 600; font-variant-numeric: tabular-nums; }}
        .qp-mono {{ color: {COLORS["text"]}; font-family: {FONT_MONO}; font-variant-numeric: tabular-nums; }}
        .qp-secondary {{ color: {COLORS["text_secondary"]}; font-size: 0.82rem; }}

        .qp-loading-row {{ display: flex; align-items: center; gap: 10px; padding: 4px 0; font-family: {FONT_MONO}; font-size: 0.85rem; }}

        [data-testid="stDataFrame"] {{
            border: 1px solid {COLORS["border"]};
            border-radius: {RADIUS["sm"]};
        }}

        /* ---- Ticker hero (big live price header - Market / Paper Trading) ---- */
        .qp-ticker {{
            display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
            padding: 2px 0 4px 0;
        }}
        .qp-ticker-symbol {{
            font-family: {FONT_MONO}; font-weight: 700; font-size: 1.1rem;
            color: {COLORS["text"]}; letter-spacing: 0.01em;
        }}
        .qp-ticker-price {{
            font-family: {FONT_MONO}; font-weight: 700; font-size: 2.1rem;
            color: {COLORS["text"]}; font-variant-numeric: tabular-nums; line-height: 1;
        }}
        .qp-ticker-change {{
            font-family: {FONT_MONO}; font-weight: 600; font-size: 1rem;
            font-variant-numeric: tabular-nums;
        }}

        /* ---- Watchlist strip (compact symbol rows, TradingView-style) ---- */
        .qp-watchrow {{
            display: flex; align-items: center; justify-content: space-between;
            padding: 7px 10px; border-radius: {RADIUS["sm"]};
            border: 1px solid transparent; cursor: default;
            transition: background 120ms ease, border-color 120ms ease;
        }}
        .qp-watchrow:hover {{ background: {COLORS["surface_elevated"]}; border-color: {COLORS["border"]}; }}
        .qp-watchrow-symbol {{ font-family: {FONT_MONO}; font-weight: 600; font-size: 0.82rem; color: {COLORS["text"]}; }}
        .qp-watchrow-price {{ font-family: {FONT_MONO}; font-size: 0.82rem; font-variant-numeric: tabular-nums; text-align: right; }}

        /* ---- Segmented control (timeframe / study pills) - override
           Streamlit's default selected-state red with our accent cyan. ---- */
        [data-testid="stSegmentedControl"] label[aria-checked="true"],
        [data-testid="stSegmentedControl"] label[data-checked="true"],
        [data-testid="stSegmentedControl"] button[aria-checked="true"] {{
            background: rgba(45,212,245,0.14) !important;
            color: {COLORS["accent_cyan"]} !important;
            border-color: {COLORS["accent_cyan"]} !important;
        }}
        [data-testid="stSegmentedControl"] * {{
            font-family: {FONT_MONO} !important;
        }}

        /* ---- Chips (indicator toggles etc.) ---- */
        div[data-testid="stCheckbox"] {{
            background: {COLORS["surface"]}; border: 1px solid {COLORS["border"]};
            border-radius: 999px; padding: 3px 12px 3px 8px;
            transition: border-color 120ms ease;
        }}
        div[data-testid="stCheckbox"]:has(input:checked) {{
            border-color: {COLORS["accent_cyan"]};
            background: rgba(45,212,245,0.08);
        }}

        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        </style>
        """,
        unsafe_allow_html=True,
    )
