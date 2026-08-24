from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.providers import live_quotes
from data.providers.base import ProviderError, Quote


def _quote(symbol: str, source: str) -> Quote:
    return Quote(
        symbol=symbol, price=100.0, prev_close=98.0, open=99.0, day_high=101.0,
        day_low=97.0, volume=1000, as_of=datetime.now(timezone.utc), source=source,
    )


class _StubProvider:
    def __init__(self, name: str, result=None, error: Exception | None = None):
        self.name = name
        self._result = result
        self._error = error
        self.calls = 0

    def get_quote(self, symbol: str) -> Quote:
        self.calls += 1
        if self._error:
            raise self._error
        return self._result


def test_uses_first_provider_when_it_succeeds(monkeypatch):
    primary = _StubProvider("nse_live", result=_quote("RELIANCE.NS", "nse_live"))
    fallback = _StubProvider("yfinance", result=_quote("RELIANCE.NS", "yfinance"))
    monkeypatch.setattr(live_quotes, "_LIVE_QUOTE_CHAIN", [primary, fallback])

    quote = live_quotes.get_live_quote("RELIANCE.NS")
    assert quote.source == "nse_live"
    assert fallback.calls == 0


def test_falls_back_when_first_provider_fails(monkeypatch):
    primary = _StubProvider("nse_live", error=ProviderError("blocked"))
    fallback = _StubProvider("yfinance", result=_quote("RELIANCE.NS", "yfinance"))
    monkeypatch.setattr(live_quotes, "_LIVE_QUOTE_CHAIN", [primary, fallback])

    quote = live_quotes.get_live_quote("RELIANCE.NS")
    assert quote.source == "yfinance"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_raises_when_every_provider_fails(monkeypatch):
    primary = _StubProvider("nse_live", error=ProviderError("blocked"))
    fallback = _StubProvider("yfinance", error=ProviderError("also down"))
    monkeypatch.setattr(live_quotes, "_LIVE_QUOTE_CHAIN", [primary, fallback])

    with pytest.raises(ProviderError, match="All live quote sources failed"):
        live_quotes.get_live_quote("RELIANCE.NS")


def test_quote_change_and_change_pct():
    q = _quote("RELIANCE.NS", "yfinance")
    assert q.change == pytest.approx(2.0)
    assert q.change_pct == pytest.approx(2.0 / 98.0 * 100)
