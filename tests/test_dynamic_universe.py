from __future__ import annotations

from data.providers.base import InstrumentInfo
from data.storage.repository import upsert_instruments
from data.universe import list_available_universes, universe_symbols


def test_nse_all_absent_before_any_instruments_synced(temp_db):
    assert "NSE_ALL" not in list_available_universes()


def test_nse_all_appears_after_sync_and_returns_symbols(temp_db):
    upsert_instruments([
        InstrumentInfo(symbol="RELIANCE.NS", base_symbol="RELIANCE", exchange="NSE", name="Reliance"),
        InstrumentInfo(symbol="TCS.NS", base_symbol="TCS", exchange="NSE", name="TCS"),
    ])
    assert "NSE_ALL" in list_available_universes()
    assert set(universe_symbols("NSE_ALL")) == {"RELIANCE.NS", "TCS.NS"}


def test_bse_all_independent_of_nse_all(temp_db):
    upsert_instruments([
        InstrumentInfo(symbol="500325.BO", base_symbol="500325", exchange="BSE", name="Reliance"),
    ])
    universes = list_available_universes()
    assert "BSE_ALL" in universes
    assert "NSE_ALL" not in universes  # no NSE instruments synced in this test
    assert universe_symbols("BSE_ALL") == ["500325.BO"]


def test_static_csv_universes_still_work_alongside_dynamic(temp_db):
    upsert_instruments([InstrumentInfo(symbol="RELIANCE.NS", base_symbol="RELIANCE", exchange="NSE", name="Reliance")])
    universes = list_available_universes()
    assert "NSE_ALL" in universes
    # At least one curated CSV universe should still be present (shipped in configs/universes).
    assert any(not u.endswith("_ALL") for u in universes)
