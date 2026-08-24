"""Full NSE/BSE instrument master list - every listed equity symbol, not
just a hand-picked universe. Backed by NSE's own published archive (a
static CSV, not the bot-guarded live API, so it works even where
`nse_live.py`'s quote endpoint gets blocked) and a best-effort BSE source.

This only populates the `instruments` table (symbol/name/ISIN/exchange) so
symbol search and universe selection can cover the whole market - it does
NOT download price history for every symbol (that would be ~2,500+ full
downloads and is left to the existing on-demand `update_symbol`/
`update_universe` flow). Call `sync_full_instrument_master()` from the
Data page or CLI; it's a slow-ish one-time (or occasional refresh)
operation, not something to run on every app load.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import pandas as pd
import requests

from data.http_utils import retry_with_backoff
from data.providers.base import InstrumentInfo, ProviderError

logger = logging.getLogger(__name__)

_NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_BSE_SCRIP_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripCodes/w"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


@dataclass
class SyncResult:
    nse_count: int
    bse_count: int
    bse_error: str | None = None


@retry_with_backoff(exceptions=(requests.RequestException,), max_retries=3)
def fetch_nse_equity_list() -> list[InstrumentInfo]:
    """NSE publishes this as a static archive file (not behind the same
    Akamai bot-check as the live quote API), so it's reachable from most
    networks including ones where nse_live.py gets a 403."""
    resp = requests.get(_NSE_EQUITY_LIST_URL, headers=_HEADERS, timeout=20)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = df.columns.str.strip()
    df = df[df["SERIES"].str.strip() == "EQ"]

    instruments = []
    for _, row in df.iterrows():
        base_symbol = str(row["SYMBOL"]).strip()
        instruments.append(
            InstrumentInfo(
                symbol=f"{base_symbol}.NS",
                base_symbol=base_symbol,
                exchange="NSE",
                name=str(row["NAME OF COMPANY"]).strip(),
                isin=str(row["ISIN NUMBER"]).strip() or None,
                instrument_type="EQUITY",
            )
        )
    return instruments


@retry_with_backoff(exceptions=(requests.RequestException,), max_retries=2)
def fetch_bse_equity_list() -> list[InstrumentInfo]:
    """BSE's scrip-list API sits behind bot protection that (unlike NSE's
    static archive) this project has not found a reliable way around from
    every network - it may simply fail here. Callers should treat a
    failure as "BSE sync unavailable right now", not a fatal error: BSE
    symbols (.BO) still work individually via on-demand quotes/downloads,
    they just won't be pre-populated in the searchable instrument list.
    """
    resp = requests.get(
        _BSE_SCRIP_LIST_URL,
        headers={**_HEADERS, "Referer": "https://www.bseindia.com/corporates/List_Scrips.aspx"},
        params={"Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": "Active"},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        raise ProviderError(f"Unexpected BSE scrip list response shape: {type(payload)}")

    instruments = []
    for row in payload:
        base_symbol = str(row.get("SCRIP_CD") or row.get("scrip_cd") or "").strip()
        name = str(row.get("Scrip_Name") or row.get("scrip_name") or "").strip()
        if not base_symbol:
            continue
        instruments.append(
            InstrumentInfo(
                symbol=f"{base_symbol}.BO", base_symbol=base_symbol, exchange="BSE",
                name=name or None, instrument_type="EQUITY",
            )
        )
    return instruments


def sync_full_instrument_master() -> SyncResult:
    from data.storage.repository import upsert_instruments

    nse_instruments = fetch_nse_equity_list()
    upsert_instruments(nse_instruments)
    logger.info("Synced %d NSE equity instruments", len(nse_instruments))

    bse_count = 0
    bse_error = None
    try:
        bse_instruments = fetch_bse_equity_list()
        upsert_instruments(bse_instruments)
        bse_count = len(bse_instruments)
        logger.info("Synced %d BSE equity instruments", bse_count)
    except Exception as exc:  # noqa: BLE001 - BSE is best-effort, see fetch_bse_equity_list docstring
        bse_error = str(exc)
        logger.warning("BSE instrument sync failed (NSE sync still succeeded): %s", bse_error)

    return SyncResult(nse_count=len(nse_instruments), bse_count=bse_count, bse_error=bse_error)
