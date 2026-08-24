from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from data.providers.base import Quote
from paper_trading import engine


@pytest.fixture()
def client(temp_db):
    return TestClient(app)


@pytest.fixture()
def auth_headers(client):
    client.post("/auth/register", json={"username": "trader1", "password": "correcthorsebattery"})
    resp = client.post("/auth/login", json={"username": "trader1", "password": "correcthorsebattery"})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def mock_quotes(monkeypatch):
    prices = {"RELIANCE.NS": 1000.0, "TCS.NS": 3500.0}

    def fake_get_live_quote(symbol: str) -> Quote:
        if symbol not in prices:
            from data.providers.base import ProviderError

            raise ProviderError(f"no quote for {symbol}")
        p = prices[symbol]
        return Quote(symbol=symbol, price=p, prev_close=p, open=p, day_high=p, day_low=p,
                     volume=1000, as_of=datetime.now(timezone.utc), source="test")

    monkeypatch.setattr(engine, "get_live_quote", fake_get_live_quote)
    return prices


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_register_then_login(client):
    resp = client.post("/auth/register", json={"username": "alice", "password": "longenoughpassword"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["token"]

    resp2 = client.post("/auth/login", json={"username": "alice", "password": "longenoughpassword"})
    assert resp2.status_code == 200


def test_register_weak_password_rejected(client):
    resp = client.post("/auth/register", json={"username": "alice", "password": "short"})
    assert resp.status_code in (400, 422)  # 422 if pydantic min_length catches it first


def test_login_wrong_password(client):
    client.post("/auth/register", json={"username": "bob", "password": "longenoughpassword"})
    resp = client.post("/auth/login", json={"username": "bob", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_protected_endpoint_requires_auth(client):
    resp = client.get("/accounts")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_bad_token(client):
    resp = client.get("/accounts", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_create_and_list_account(client, auth_headers):
    resp = client.post("/accounts", json={"name": "My Demo", "initial_capital": 100000}, headers=auth_headers)
    assert resp.status_code == 201
    account_id = resp.json()["account_id"]

    resp2 = client.get("/accounts", headers=auth_headers)
    assert resp2.status_code == 200
    assert any(a["account_id"] == account_id for a in resp2.json())


def test_cannot_access_another_users_account(client):
    client.post("/auth/register", json={"username": "userA", "password": "longenoughpassword"})
    token_a = client.post("/auth/login", json={"username": "userA", "password": "longenoughpassword"}).json()["token"]
    account_id = client.post(
        "/accounts", json={"name": "A's account", "initial_capital": 50000},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()["account_id"]

    client.post("/auth/register", json={"username": "userB", "password": "longenoughpassword"})
    token_b = client.post("/auth/login", json={"username": "userB", "password": "longenoughpassword"}).json()["token"]

    resp = client.get(f"/accounts/{account_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404  # not leaked as 403 - see _owned_account_or_404


def test_place_order_end_to_end(client, auth_headers, mock_quotes):
    account_id = client.post(
        "/accounts", json={"name": "Trading", "initial_capital": 100000}, headers=auth_headers
    ).json()["account_id"]

    resp = client.post(
        f"/accounts/{account_id}/orders", json={"symbol": "RELIANCE.NS", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE.NS"
    assert body["quote_source"] == "test"

    positions = client.get(f"/accounts/{account_id}/positions", headers=auth_headers).json()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 10


def test_place_order_insufficient_funds_returns_400(client, auth_headers, mock_quotes):
    account_id = client.post(
        "/accounts", json={"name": "Tiny", "initial_capital": 100}, headers=auth_headers
    ).json()["account_id"]
    resp = client.post(
        f"/accounts/{account_id}/orders", json={"symbol": "RELIANCE.NS", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_order_unknown_symbol_returns_502(client, auth_headers, mock_quotes):
    account_id = client.post(
        "/accounts", json={"name": "Test", "initial_capital": 100000}, headers=auth_headers
    ).json()["account_id"]
    resp = client.post(
        f"/accounts/{account_id}/orders", json={"symbol": "NOPE.NS", "side": "BUY", "quantity": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 502


def test_analysis_endpoint_after_trades(client, auth_headers, mock_quotes):
    account_id = client.post(
        "/accounts", json={"name": "Test", "initial_capital": 100000}, headers=auth_headers
    ).json()["account_id"]
    client.post(
        f"/accounts/{account_id}/orders", json={"symbol": "RELIANCE.NS", "side": "BUY", "quantity": 10},
        headers=auth_headers,
    )
    resp_open = client.get(f"/accounts/{account_id}/analysis", headers=auth_headers)
    assert resp_open.json()["metrics"]["num_trades"] == 0  # still open, no completed round-trip yet

    mock_quotes["RELIANCE.NS"] = 1100.0
    client.post(
        f"/accounts/{account_id}/orders", json={"symbol": "RELIANCE.NS", "side": "SELL", "quantity": 10},
        headers=auth_headers,
    )

    resp = client.get(f"/accounts/{account_id}/analysis", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_data"] is True
    assert body["metrics"]["num_trades"] == 1  # now closed
    assert len(body["equity_curve"]) >= 1
    assert len(body["round_trip_trades"]) == 1


def test_analysis_with_no_trades_is_graceful(client, auth_headers):
    account_id = client.post(
        "/accounts", json={"name": "Empty", "initial_capital": 100000}, headers=auth_headers
    ).json()["account_id"]
    resp = client.get(f"/accounts/{account_id}/analysis", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["has_data"] is False
