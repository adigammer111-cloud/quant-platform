from __future__ import annotations

import pytest

from data.providers.base import ProviderError
from data.providers.twelve_data import TwelveDataProvider, _to_twelve_data_symbol


def test_symbol_conversion_nse():
    assert _to_twelve_data_symbol("RELIANCE.NS") == "RELIANCE:NSE"


def test_symbol_conversion_bse():
    assert _to_twelve_data_symbol("RELIANCE.BO") == "RELIANCE:BSE"


def test_symbol_conversion_passthrough_for_non_indian_tickers():
    assert _to_twelve_data_symbol("AAPL") == "AAPL"


def test_is_configured_false_without_key():
    provider = TwelveDataProvider(api_key=None)
    assert provider.is_configured is False


def test_is_configured_true_with_key():
    provider = TwelveDataProvider(api_key="fake-key")
    assert provider.is_configured is True


def test_get_quote_raises_when_not_configured():
    provider = TwelveDataProvider(api_key=None)
    with pytest.raises(ProviderError, match="not configured"):
        provider.get_quote("RELIANCE.NS")


def test_get_quote_parses_successful_response(monkeypatch):
    provider = TwelveDataProvider(api_key="fake-key")

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "close": "1316.00", "previous_close": "1313.20", "open": "1314.00",
                "high": "1320.00", "low": "1308.00", "volume": "5434871",
            }

    monkeypatch.setattr("data.providers.twelve_data.requests.get", lambda *a, **k: _FakeResponse())
    quote = provider.get_quote("RELIANCE.NS")
    assert quote.price == 1316.00
    assert quote.source == "twelve_data"


def test_get_quote_raises_on_api_error_payload(monkeypatch):
    provider = TwelveDataProvider(api_key="fake-key")

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "error", "message": "invalid api key"}

    monkeypatch.setattr("data.providers.twelve_data.requests.get", lambda *a, **k: _FakeResponse())
    with pytest.raises(ProviderError, match="invalid api key"):
        provider.get_quote("RELIANCE.NS")
