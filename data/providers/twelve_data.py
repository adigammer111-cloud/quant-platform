"""Twelve Data (twelvedata.com) live quotes - a third, independent free
source. Unlike NSE India (blocked on some networks) and yfinance (delayed,
best-effort), Twelve Data requires a free API key
(https://twelvedata.com/pricing - the free tier covers this app's needs:
800 requests/day, NSE/BSE coverage) but gives more explicit rate-limit
behavior and doesn't depend on scraping a consumer-facing site.

Optional by design: `live_quotes.py` only adds this to the fallback chain
when `settings.twelve_data_api_key` is set. No key, no problem - NSE +
yfinance already cover every symbol on their own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from config import settings
from data.http_utils import retry_with_backoff
from data.providers.base import LiveQuoteProvider, ProviderError, Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/quote"


def _to_twelve_data_symbol(symbol: str) -> str:
    """Our internal convention is Yahoo-style (RELIANCE.NS / RELIANCE.BO);
    Twelve Data expects SYMBOL:EXCHANGE (RELIANCE:NSE / RELIANCE:BSE)."""
    if symbol.endswith(".NS"):
        return f"{symbol[:-3]}:NSE"
    if symbol.endswith(".BO"):
        return f"{symbol[:-3]}:BSE"
    return symbol  # US tickers etc. pass through unchanged (e.g. "AAPL")


class TwelveDataProvider(LiveQuoteProvider):
    name = "twelve_data"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.twelve_data_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @retry_with_backoff(exceptions=(requests.RequestException, ProviderError), max_retries=2)
    def get_quote(self, symbol: str) -> Quote:
        if not self._api_key:
            raise ProviderError("Twelve Data is not configured - set TWELVE_DATA_API_KEY to enable it")

        resp = requests.get(
            _BASE_URL,
            params={"symbol": _to_twelve_data_symbol(symbol), "apikey": self._api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            raise ProviderError(f"Twelve Data returned HTTP {resp.status_code} for {symbol}")

        payload = resp.json()
        if payload.get("status") == "error" or "close" not in payload:
            raise ProviderError(f"Twelve Data error for {symbol}: {payload.get('message', payload)}")

        return Quote(
            symbol=symbol,
            price=float(payload["close"]),
            prev_close=float(payload["previous_close"]),
            open=float(payload["open"]),
            day_high=float(payload["high"]),
            day_low=float(payload["low"]),
            volume=int(float(payload.get("volume") or 0)),
            as_of=datetime.now(timezone.utc),
            source="twelve_data",
        )
