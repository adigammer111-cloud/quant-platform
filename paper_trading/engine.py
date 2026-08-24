"""Paper (demo) trading: place simulated market orders against real,
live-fetched prices, with the same transaction-cost model used by the
backtester. No real money or brokerage account is ever involved - this is
a sandbox for practicing/observing strategy behavior against current
prices, not a live-trading connector.

Positions use weighted-average cost (not FIFO lots) since a human can add
to or trim a position freely here, unlike the backtester's discrete
signal-driven entries/exits. Trades are recorded in the same shape as
`backtest_trades` (symbol/side/execution_date/execution_price/quantity/
costs/realized_pnl/holding_period_days) specifically so the existing
`compute_performance_metrics` and `build_round_trip_trades` analytics -
already tested against the backtester - work unchanged here too.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from backtesting.costs import TransactionCostModel
from data.providers.live_quotes import get_live_quote
from database.db import get_connection

logger = logging.getLogger(__name__)

DEFAULT_COST_MODEL = TransactionCostModel()


def _utc_now_naive() -> datetime:
    """DuckDB TIMESTAMP columns are timezone-naive, so values round-tripped
    through the database lose their tzinfo. Using naive UTC everywhere in
    this module (rather than aware-in-Python, naive-after-a-DB-round-trip)
    avoids a can't-subtract-aware-and-naive-datetimes crash when computing
    holding periods from a previously stored `opened_at`."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InsufficientFundsError(RuntimeError):
    pass


class InsufficientSharesError(RuntimeError):
    pass


@dataclass
class OrderResult:
    trade_id: str
    symbol: str
    side: str
    quantity: float
    execution_price: float
    costs: float
    realized_pnl: float | None
    quote_source: str
    cash_after: float


def create_account(name: str, initial_capital: float, user_id: str | None = None) -> str:
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    account_id = f"paper_{uuid.uuid4().hex[:10]}"
    with get_connection() as con:
        con.execute(
            "INSERT INTO paper_accounts (account_id, user_id, name, initial_capital, cash) VALUES (?, ?, ?, ?, ?)",
            [account_id, user_id, name, initial_capital, initial_capital],
        )
    return account_id


def list_accounts(user_id: str | None = None) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        if user_id is not None:
            return con.execute(
                "SELECT * FROM paper_accounts WHERE user_id = ? ORDER BY created_at DESC", [user_id]
            ).fetchdf()
        return con.execute("SELECT * FROM paper_accounts ORDER BY created_at DESC").fetchdf()


def get_account(account_id: str) -> dict:
    with get_connection(read_only=True) as con:
        row = con.execute("SELECT * FROM paper_accounts WHERE account_id = ?", [account_id]).fetchdf()
    if row.empty:
        raise ValueError(f"No paper account with id {account_id}")
    return row.iloc[0].to_dict()


def delete_account(account_id: str) -> None:
    """Deletes a paper account and everything tied to it (positions, trade
    history, equity snapshots). Irreversible - callers should confirm with
    the user before calling this."""
    with get_connection() as con:
        con.execute("DELETE FROM paper_equity_snapshots WHERE account_id = ?", [account_id])
        con.execute("DELETE FROM paper_trades WHERE account_id = ?", [account_id])
        con.execute("DELETE FROM paper_positions WHERE account_id = ?", [account_id])
        con.execute("DELETE FROM paper_accounts WHERE account_id = ?", [account_id])


def account_belongs_to_user(account_id: str, user_id: str) -> bool:
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT 1 FROM paper_accounts WHERE account_id = ? AND user_id = ?", [account_id, user_id]
        ).fetchone()
    return row is not None


def get_positions(account_id: str) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND quantity > 0 ORDER BY symbol",
            [account_id],
        ).fetchdf()


def get_trades(account_id: str) -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            "SELECT * FROM paper_trades WHERE account_id = ? ORDER BY execution_date", [account_id]
        ).fetchdf()


def place_order(
    account_id: str,
    symbol: str,
    side: str,
    quantity: float,
    cost_model: TransactionCostModel | None = None,
) -> OrderResult:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    cost_model = cost_model or DEFAULT_COST_MODEL

    quote = get_live_quote(symbol)
    execution_price = cost_model.apply_slippage(side, quote.price)
    costs = cost_model.compute_costs(side, execution_price, quantity).total
    now = _utc_now_naive()

    with get_connection() as con:
        account = con.execute("SELECT cash FROM paper_accounts WHERE account_id = ?", [account_id]).fetchdf()
        if account.empty:
            raise ValueError(f"No paper account with id {account_id}")
        cash = float(account.iloc[0]["cash"])

        position = con.execute(
            "SELECT quantity, avg_price, opened_at FROM paper_positions WHERE account_id = ? AND symbol = ?",
            [account_id, symbol],
        ).fetchdf()
        held_qty = float(position.iloc[0]["quantity"]) if not position.empty else 0.0
        held_avg = float(position.iloc[0]["avg_price"]) if not position.empty else 0.0
        opened_at = position.iloc[0]["opened_at"] if not position.empty else None

        realized_pnl = None
        holding_period_days = None

        if side == "BUY":
            gross = execution_price * quantity
            if gross + costs > cash:
                raise InsufficientFundsError(
                    f"Order needs {gross + costs:,.2f} but account only has {cash:,.2f} cash"
                )
            new_qty = held_qty + quantity
            new_avg = (held_qty * held_avg + execution_price * quantity) / new_qty
            new_opened_at = opened_at if held_qty > 0 else now
            cash -= gross + costs
            net_amount = -(gross + costs)

        elif side == "SELL":
            if quantity > held_qty + 1e-9:
                raise InsufficientSharesError(
                    f"Order sells {quantity} shares but account only holds {held_qty} of {symbol}"
                )
            gross = execution_price * quantity
            realized_pnl = (execution_price - held_avg) * quantity
            if opened_at is not None:
                opened_dt = pd.Timestamp(opened_at).to_pydatetime()
                holding_period_days = (now - opened_dt).total_seconds() / 86400
            new_qty = held_qty - quantity
            new_avg = held_avg if new_qty > 1e-9 else 0.0
            new_opened_at = opened_at if new_qty > 1e-9 else None
            cash += gross - costs
            net_amount = gross - costs
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        con.execute(
            """
            INSERT INTO paper_positions (account_id, symbol, quantity, avg_price, opened_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (account_id, symbol) DO UPDATE SET
                quantity = excluded.quantity, avg_price = excluded.avg_price, opened_at = excluded.opened_at
            """,
            [account_id, symbol, new_qty, new_avg, new_opened_at],
        )
        con.execute("UPDATE paper_accounts SET cash = ? WHERE account_id = ?", [cash, account_id])

        trade_id = f"pt_{uuid.uuid4().hex[:12]}"
        # exit_reason is only meaningful on the closing (SELL) leg, but is
        # populated on every row (as "OPEN" for a still-open BUY) because
        # `analytics.reporting.build_round_trip_trades` - shared with the
        # backtester, whose trades always carry this column - reads it
        # unconditionally when pairing entries with exits.
        exit_reason = "MANUAL" if side == "SELL" else "OPEN"
        con.execute(
            """
            INSERT INTO paper_trades (
                trade_id, account_id, symbol, side, execution_date, execution_price, quantity,
                gross_amount, costs, net_amount, realized_pnl, holding_period_days, exit_reason, quote_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trade_id, account_id, symbol, side, now, execution_price, quantity,
                execution_price * quantity, costs, net_amount, realized_pnl, holding_period_days,
                exit_reason, quote.source,
            ],
        )

    snapshot_equity(account_id)

    return OrderResult(
        trade_id=trade_id, symbol=symbol, side=side, quantity=quantity, execution_price=execution_price,
        costs=costs, realized_pnl=realized_pnl, quote_source=quote.source, cash_after=cash,
    )


def snapshot_equity(account_id: str) -> float:
    """Marks every open position to its current live price and records a
    snapshot. Returns total account value. Positions whose live quote can't
    be fetched right now are valued at their average cost as a conservative
    fallback (logged, not silently ignored)."""
    account = get_account(account_id)
    cash = float(account["cash"])
    positions = get_positions(account_id)

    holdings_value = 0.0
    for _, pos in positions.iterrows():
        try:
            quote = get_live_quote(pos["symbol"])
            holdings_value += quote.price * pos["quantity"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not mark %s to market, using avg cost: %s", pos["symbol"], exc)
            holdings_value += pos["avg_price"] * pos["quantity"]

    total_value = cash + holdings_value
    now = _utc_now_naive()
    with get_connection() as con:
        con.execute(
            """
            INSERT INTO paper_equity_snapshots (account_id, snapshot_at, cash, holdings_value, total_value)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (account_id, snapshot_at) DO UPDATE SET
                cash = excluded.cash, holdings_value = excluded.holdings_value, total_value = excluded.total_value
            """,
            [account_id, now, cash, holdings_value, total_value],
        )
    return total_value


def get_equity_curve(account_id: str) -> pd.DataFrame:
    """One row per calendar date (the last snapshot that day), shaped like
    `backtest_equity_curve` (date/cash/holdings_value/total_value/
    daily_return/drawdown) so `compute_performance_metrics` works unchanged."""
    with get_connection(read_only=True) as con:
        raw = con.execute(
            "SELECT * FROM paper_equity_snapshots WHERE account_id = ? ORDER BY snapshot_at", [account_id]
        ).fetchdf()
    if raw.empty:
        return pd.DataFrame(columns=["date", "cash", "holdings_value", "total_value", "daily_return", "drawdown"])

    raw["date"] = pd.to_datetime(raw["snapshot_at"]).dt.date
    daily = raw.groupby("date", as_index=False).last()[["date", "cash", "holdings_value", "total_value"]]
    daily["date"] = pd.to_datetime(daily["date"])
    daily["daily_return"] = daily["total_value"].pct_change()
    running_max = daily["total_value"].cummax()
    daily["drawdown"] = (daily["total_value"] - running_max) / running_max * 100
    return daily
