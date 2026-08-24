"""Live (exchange-delayed) quotes straight from NSE India's public quote
API - free, no API key. NSE fronts this with bot-detection (Akamai) that
blocks many datacenter/cloud IPs outright; it tends to work fine from an
ordinary residential connection (i.e. most users actually running this app
locally) but may 403 in some hosted environments. `data/providers/live_quotes.py`
treats this as the preferred source and automatically falls back to
`YFinanceProvider.get_quote` when it fails, so a block here never breaks
paper trading - it just quietly uses the other source.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from data.http_utils import retry_with_backoff
from data.providers.base import LiveQuoteProvider, ProviderError, Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class NseLiveProvider(LiveQuoteProvider):
    name = "nse_live"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._warmed_up = False

    def _warm_up(self) -> None:
        """NSE requires a prior visit to the site to receive the cookies
        its API checks for - a bare API request without this is rejected."""
        resp = self._session.get(_BASE_URL, timeout=10)
        resp.raise_for_status()
        self._warmed_up = True

    @retry_with_backoff(exceptions=(requests.RequestException, ProviderError), max_retries=2)
    def get_quote(self, symbol: str) -> Quote:
        if symbol.endswith(".BO"):
            raise ProviderError("NSE India's API only covers NSE-listed symbols, not BSE (.BO)")
        base_symbol = symbol[:-3] if symbol.endswith(".NS") else symbol.lstrip("^")

        if not self._warmed_up:
            self._warm_up()

        resp = self._session.get(
            f"{_BASE_URL}/api/quote-equity",
            params={"symbol": base_symbol},
            headers={"Referer": f"{_BASE_URL}/get-quotes/equity?symbol={base_symbol}"},
            timeout=10,
        )
        if resp.status_code != 200:
            raise ProviderError(f"NSE API returned HTTP {resp.status_code} for {symbol}")

        payload = resp.json()
        price_info = payload.get("priceInfo", {})
        if not price_info or price_info.get("lastPrice") is None:
            raise ProviderError(f"NSE API returned no price data for {symbol}")

        return Quote(
            symbol=symbol,
            price=float(price_info["lastPrice"]),
            prev_close=float(price_info["previousClose"]),
            open=float(price_info["open"]),
            day_high=float(price_info["intraDayHighLow"]["max"]),
            day_low=float(price_info["intraDayHighLow"]["min"]),
            volume=int(payload.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume", 0)),
            as_of=datetime.now(timezone.utc),
            source="nse_live",
        )
