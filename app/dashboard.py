"""Streamlit dashboard for the quant platform.

Run from the project root:
    .venv\\Scripts\\python.exe -m streamlit run app/dashboard.py

Every number shown here comes from a real query against the DuckDB database
or a real backtest run through the same engine the CLI uses - nothing is
hard-coded. This file only wires up page config, theming, and navigation;
each page's actual logic lives in app/sections/.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit adds this script's own directory (app/) to sys.path, not the
# project root, so sibling packages (config, data, backtesting, ...) need
# the root added explicitly before any of them can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from logging_config import configure_logging

configure_logging()

from app.components import NAV_GROUPS, render_sidebar_nav
from app.sections import (
    account,
    backtests,
    dashboard as dashboard_page,
    data as data_page,
    data_health,
    market,
    monte_carlo,
    optimizer,
    paper_trading,
    performance,
    risk,
    screener,
    settings as settings_page,
    strategy_builder,
    strategy_library,
    trades,
    walk_forward,
)
from app.theme import inject_css
from database.db import ensure_database

st.set_page_config(page_title="Quant Platform", layout="wide", initial_sidebar_state="expanded")
ensure_database()
inject_css()

PAGES = {
    "Dashboard": dashboard_page.render,
    "Market": market.render,
    "Screener": screener.render,
    "Strategy Library": strategy_library.render,
    "Strategy Builder": strategy_builder.render,
    "Backtests": backtests.render,
    "Optimizer": optimizer.render,
    "Walk Forward": walk_forward.render,
    "Monte Carlo": monte_carlo.render,
    "Paper Trading": paper_trading.render,
    "Account": account.render,
    "Performance": performance.render,
    "Risk": risk.render,
    "Trades": trades.render,
    "Data": data_page.render,
    "Data Health": data_health.render,
    "Settings": settings_page.render,
}

current_page = render_sidebar_nav()
PAGES[current_page]()
