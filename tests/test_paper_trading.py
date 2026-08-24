from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.providers.base import Quote
from paper_trading import engine
from paper_trading.engine import InsufficientFundsError, InsufficientSharesError


def _fake_quote(symbol: str, price: float) -> Quote:
    return Quote(
        symbol=symbol, price=price, prev_close=price, open=price, day_high=price,
        day_low=price, volume=1000, as_of=datetime.now(timezone.utc), source="test",
    )


@pytest.fixture()
def mock_quotes(monkeypatch):
    prices = {"RELIANCE.NS": 1000.0}

    def fake_get_live_quote(symbol: str) -> Quote:
        return _fake_quote(symbol, prices[symbol])

    monkeypatch.setattr(engine, "get_live_quote", fake_get_live_quote)
    return prices


def test_create_account_and_initial_cash(temp_db):
    account_id = engine.create_account("Test Account", 100_000.0)
    account = engine.get_account(account_id)
    assert account["cash"] == 100_000.0
    assert account["initial_capital"] == 100_000.0


def test_buy_reduces_cash_and_opens_position(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    result = engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)

    assert result.side == "BUY"
    assert result.realized_pnl is None
    positions = engine.get_positions(account_id)
    assert len(positions) == 1
    assert positions.iloc[0]["quantity"] == 10
    account = engine.get_account(account_id)
    assert account["cash"] < 100_000.0  # spent on shares + costs
    assert account["cash"] == pytest.approx(result.cash_after)


def test_buy_more_than_cash_allows_raises(temp_db, mock_quotes):
    account_id = engine.create_account("Small Account", 500.0)
    with pytest.raises(InsufficientFundsError):
        engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)  # needs ~10,000


def test_sell_more_than_held_raises(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 5)
    with pytest.raises(InsufficientSharesError):
        engine.place_order(account_id, "RELIANCE.NS", "SELL", 10)


def test_sell_realizes_pnl_on_price_move(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)  # @ ~1000

    mock_quotes["RELIANCE.NS"] = 1100.0  # price moves up 10%
    result = engine.place_order(account_id, "RELIANCE.NS", "SELL", 10)

    assert result.realized_pnl > 0  # profitable close
    positions = engine.get_positions(account_id)
    assert positions.empty  # fully closed, filtered out by quantity > 0


def test_weighted_average_cost_on_second_buy(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)  # @ 1000

    mock_quotes["RELIANCE.NS"] = 1200.0
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)  # @ 1200

    positions = engine.get_positions(account_id)
    row = positions.iloc[0]
    assert row["quantity"] == 20
    # BUY slippage (+5bps) nudges each fill price up slightly above the raw quote.
    expected_avg = (10 * 1000.0 * 1.0005 + 10 * 1200.0 * 1.0005) / 20
    assert row["avg_price"] == pytest.approx(expected_avg)


def test_equity_curve_reflects_snapshots(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)
    curve = engine.get_equity_curve(account_id)
    assert not curve.empty
    assert curve.iloc[-1]["total_value"] < 100_000.0  # costs paid, but still ~fully invested + cash

    # Marking to market at a new price changes holdings_value on a fresh snapshot.
    mock_quotes["RELIANCE.NS"] = 2000.0
    engine.snapshot_equity(account_id)
    curve2 = engine.get_equity_curve(account_id)
    assert curve2.iloc[-1]["total_value"] > curve.iloc[-1]["total_value"]


def test_list_accounts_filters_by_user(temp_db):
    a1 = engine.create_account("Alice's Account", 100_000.0, user_id="user_alice")
    engine.create_account("Bob's Account", 100_000.0, user_id="user_bob")

    alice_accounts = engine.list_accounts(user_id="user_alice")
    assert len(alice_accounts) == 1
    assert alice_accounts.iloc[0]["account_id"] == a1

    assert len(engine.list_accounts()) == 2  # unfiltered sees both


def test_account_belongs_to_user(temp_db):
    account_id = engine.create_account("Alice's Account", 100_000.0, user_id="user_alice")
    assert engine.account_belongs_to_user(account_id, "user_alice") is True
    assert engine.account_belongs_to_user(account_id, "user_bob") is False


def test_delete_account_removes_it_and_its_data(temp_db, mock_quotes):
    account_id = engine.create_account("Throwaway", 100_000.0, user_id="user_alice")
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 5)

    engine.delete_account(account_id)

    assert engine.list_accounts(user_id="user_alice").empty
    assert engine.get_positions(account_id).empty
    assert engine.get_trades(account_id).empty
    with pytest.raises(ValueError):
        engine.get_account(account_id)


def test_create_account_rejects_non_positive_capital(temp_db):
    with pytest.raises(ValueError):
        engine.create_account("Bad Account", 0)
    with pytest.raises(ValueError):
        engine.create_account("Bad Account", -100)


def test_trades_recorded_in_backtest_compatible_shape(temp_db, mock_quotes):
    account_id = engine.create_account("Test Account", 100_000.0)
    engine.place_order(account_id, "RELIANCE.NS", "BUY", 10)
    mock_quotes["RELIANCE.NS"] = 1100.0
    engine.place_order(account_id, "RELIANCE.NS", "SELL", 10)

    trades = engine.get_trades(account_id)
    assert len(trades) == 2
    for col in ["symbol", "side", "execution_date", "execution_price", "quantity", "costs", "realized_pnl", "holding_period_days", "exit_reason"]:
        assert col in trades.columns

    from analytics.performance import compute_performance_metrics
    from analytics.reporting import build_round_trip_trades

    equity = engine.get_equity_curve(account_id)
    metrics = compute_performance_metrics(equity, trades, 100_000.0)
    assert metrics.num_trades == 1

    round_trips = build_round_trip_trades(trades)
    assert len(round_trips) == 1
    assert round_trips.iloc[0]["exit_reason"] == "MANUAL"
