"""Order/trade/position data structures shared by the execution simulator,
portfolio, and backtesting engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0          # positive = long, negative = short, 0 = flat
    entry_price: float = 0.0        # average entry price of the current open lot
    entry_date: date | None = None
    peak_price: float = 0.0         # highest (long) / lowest (short) price seen since entry, for trailing stops

    @property
    def is_open(self) -> bool:
        return self.quantity != 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


@dataclass
class Trade:
    symbol: str
    side: str                # BUY | SELL
    signal_date: date
    execution_date: date
    execution_price: float
    quantity: float
    gross_amount: float
    costs: float
    net_amount: float
    realized_pnl: float | None = None
    holding_period_days: int | None = None
    exit_reason: str | None = None   # SIGNAL | STOP_LOSS | TAKE_PROFIT | TRAILING_STOP | END_OF_BACKTEST
