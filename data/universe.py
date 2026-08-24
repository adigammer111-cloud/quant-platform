"""Static universe definitions loaded from configs/universes/*.csv.

These CSVs are *current-constituent snapshots* maintained by hand (Yahoo
Finance/yfinance does not expose point-in-time NSE index membership). Using
one of these to backtest further back than the date the snapshot was taken
is survivorship-biased: stocks that were delisted, merged, or dropped from
the index are absent. `analytics/bias.py` and the backtest report label
every run that relies on a 'current_snapshot' universe accordingly.

For a genuinely unbiased historical universe, populate `index_membership`
with verified start/end dates per symbol (source='historical_verified') and
use `load_point_in_time_universe` instead.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from config import PROJECT_ROOT
from database.db import get_connection

UNIVERSE_DIR = PROJECT_ROOT / "configs" / "universes"

# Whole-market universes backed by the `instruments` table (see
# data/providers/instrument_master.py) rather than a curated CSV - only
# appear once synced, since there's nothing to list before that. Using one
# of these for a backtest/optimizer run is naturally limited to whichever
# symbols actually have downloaded price history: the runner already skips
# symbols with no data (data/storage/repository.get_daily_prices returns
# empty), so selecting "NSE_ALL" before downloading anything just does
# nothing rather than erroring - but it will also silently return few or
# no results, which is worth knowing before assuming a wide backtest ran.
_DYNAMIC_UNIVERSES = {"NSE_ALL": "NSE", "BSE_ALL": "BSE"}


def list_available_universes() -> list[str]:
    static = sorted(p.stem for p in UNIVERSE_DIR.glob("*.csv"))
    with get_connection(read_only=True) as con:
        exchanges_present = {
            row[0] for row in con.execute("SELECT DISTINCT exchange FROM instruments").fetchall()
        }
    dynamic = sorted(name for name, exch in _DYNAMIC_UNIVERSES.items() if exch in exchanges_present)
    return static + dynamic


def load_universe(name: str) -> list[dict]:
    """Load a CSV universe definition. Returns list of dict rows with
    symbol/base_symbol/exchange/name.
    """
    path = UNIVERSE_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Universe '{name}' not found in {UNIVERSE_DIR}. "
            f"Available: {list_available_universes()}"
        )
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def universe_symbols(name: str) -> list[str]:
    if name in _DYNAMIC_UNIVERSES:
        with get_connection(read_only=True) as con:
            rows = con.execute(
                "SELECT symbol FROM instruments WHERE exchange = ? ORDER BY symbol",
                [_DYNAMIC_UNIVERSES[name]],
            ).fetchall()
        return [r[0] for r in rows]
    return [row["symbol"] for row in load_universe(name)]


def seed_index_membership(index_name: str, universe_csv_name: str, as_of: date) -> int:
    """Register a CSV universe as a 'current_snapshot' index membership as of
    a given date. Explicitly NOT a historical reconstruction - see module
    docstring. Returns the number of symbols registered.
    """
    symbols = universe_symbols(universe_csv_name)
    with get_connection() as con:
        for symbol in symbols:
            con.execute(
                """
                INSERT INTO index_membership
                    (index_name, symbol, start_date, end_date, source)
                VALUES (?, ?, ?, NULL, 'current_snapshot')
                ON CONFLICT (index_name, symbol, start_date) DO NOTHING
                """,
                [index_name, symbol, as_of],
            )
    return len(symbols)


def load_point_in_time_universe(index_name: str, as_of: date) -> list[str]:
    """Return symbols that were members of `index_name` on `as_of`, based on
    whatever is recorded in index_membership (verified or snapshot)."""
    with get_connection(read_only=True) as con:
        rows = con.execute(
            """
            SELECT symbol FROM index_membership
            WHERE index_name = ?
              AND start_date <= ?
              AND (end_date IS NULL OR end_date >= ?)
            """,
            [index_name, as_of, as_of],
        ).fetchall()
    return [r[0] for r in rows]


def universe_is_survivorship_biased(index_name: str) -> bool:
    """True if the only membership records we have for this index are
    'current_snapshot' entries (i.e. no verified historical membership)."""
    with get_connection(read_only=True) as con:
        sources = con.execute(
            "SELECT DISTINCT source FROM index_membership WHERE index_name = ?",
            [index_name],
        ).fetchall()
    sources = {s[0] for s in sources}
    if not sources:
        return True
    return sources == {"current_snapshot"}
