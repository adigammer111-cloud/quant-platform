"""Multi-source live quote lookup with automatic fallback. Tries NSE India's
own API first (authoritative when reachable), then falls back to yfinance
if NSE is blocked, rate-limited, or doesn't cover the symbol (e.g. BSE).
This is what paper trading and the Market page's live price display call -
nothing else should reach into a specific provider for a quote.
"""
from __future__ import annotations

import logging

from data.providers.base import ProviderError, Quote
from data.providers.nse_live import NseLiveProvider
from data.providers.twelve_data import TwelveDataProvider
from data.providers.yfinance_provider import YFinanceProvider

logger = logging.getLogger(__name__)

_nse_provider = NseLiveProvider()
_twelve_data_provider = TwelveDataProvider()
_yfinance_provider = YFinanceProvider()

# NSE first (authoritative when reachable), then Twelve Data if the user has
# configured a free API key (see data/providers/twelve_data.py), then
# yfinance as the always-available last resort. Twelve Data is skipped
# entirely (not even attempted) when unconfigured, rather than wasting a
# request on a call we already know will fail.
_LIVE_QUOTE_CHAIN = [
    _nse_provider,
    *([_twelve_data_provider] if _twelve_data_provider.is_configured else []),
    _yfinance_provider,
]


def get_live_quote(symbol: str) -> Quote:
    """Returns a Quote from the first provider in the priority chain that
    succeeds. Raises ProviderError only if every source fails."""
    errors = []
    for provider in _LIVE_QUOTE_CHAIN:
        try:
            return provider.get_quote(symbol)
        except Exception as exc:  # noqa: BLE001 - genuinely want to try the next source
            errors.append(f"{provider.name}: {exc}")
            logger.info("Live quote source %s failed for %s: %s", provider.name, symbol, exc)
    raise ProviderError(f"All live quote sources failed for {symbol}: " + " | ".join(errors))
