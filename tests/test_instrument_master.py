from __future__ import annotations

import pytest

from data.providers.instrument_master import (
    fetch_bse_equity_list,
    fetch_nse_equity_list,
    sync_full_instrument_master,
)

_FAKE_NSE_CSV = (
    "SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,29-JAN-1996,10,1,INE002A01018,10\n"
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    "SOMEBOND,Some Bond Series,BE,01-JAN-2020,10,1,INE000X00000,10\n"  # non-EQ series, should be filtered out
)


class _FakeResponse:
    def __init__(self, text: str = "", json_data=None, status_code: int = 200):
        self.text = text
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def test_fetch_nse_equity_list_parses_and_filters_series(monkeypatch):
    monkeypatch.setattr(
        "data.providers.instrument_master.requests.get",
        lambda *a, **k: _FakeResponse(text=_FAKE_NSE_CSV),
    )
    instruments = fetch_nse_equity_list()
    symbols = {i.symbol for i in instruments}
    assert symbols == {"RELIANCE.NS", "TCS.NS"}  # SOMEBOND (series BE) excluded

    reliance = next(i for i in instruments if i.symbol == "RELIANCE.NS")
    assert reliance.base_symbol == "RELIANCE"
    assert reliance.exchange == "NSE"
    assert reliance.isin == "INE002A01018"


def test_fetch_bse_equity_list_parses_json(monkeypatch):
    fake_payload = [
        {"SCRIP_CD": "500325", "Scrip_Name": "Reliance Industries Ltd"},
        {"SCRIP_CD": "532540", "Scrip_Name": "Tata Consultancy Services Ltd"},
    ]
    monkeypatch.setattr(
        "data.providers.instrument_master.requests.get",
        lambda *a, **k: _FakeResponse(json_data=fake_payload),
    )
    instruments = fetch_bse_equity_list()
    assert len(instruments) == 2
    assert instruments[0].symbol == "500325.BO"
    assert instruments[0].exchange == "BSE"


def test_fetch_bse_equity_list_raises_on_unexpected_shape(monkeypatch):
    monkeypatch.setattr(
        "data.providers.instrument_master.requests.get",
        lambda *a, **k: _FakeResponse(json_data={"not": "a list"}),
    )
    with pytest.raises(Exception):
        fetch_bse_equity_list()


def test_sync_writes_nse_instruments_to_db(temp_db, monkeypatch):
    monkeypatch.setattr(
        "data.providers.instrument_master.requests.get",
        lambda *a, **k: _FakeResponse(text=_FAKE_NSE_CSV),
    )
    from data.storage.repository import list_instruments

    result = sync_full_instrument_master()
    assert result.nse_count == 2

    df = list_instruments()
    assert set(df["symbol"]) == {"RELIANCE.NS", "TCS.NS"}


def test_sync_bse_failure_does_not_block_nse_sync(temp_db, monkeypatch):
    def fake_get(url, *a, **k):
        if "nseindia" in url:
            return _FakeResponse(text=_FAKE_NSE_CSV)
        return _FakeResponse(status_code=500)  # BSE fails

    monkeypatch.setattr("data.providers.instrument_master.requests.get", fake_get)

    result = sync_full_instrument_master()
    assert result.nse_count == 2
    assert result.bse_count == 0
    assert result.bse_error is not None
