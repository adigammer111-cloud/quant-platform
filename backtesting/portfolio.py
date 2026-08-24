"""Portfolio state: cash, open positions, trade log, and the daily equity
curve. This class only tracks state - all trade *decisions* (sizing, risk
exits, signal timing) live in `backtesting/engine.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backtesting.orders import Position, Trade


@dataclass
class Portfolio:
    initial_capital: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    equity_history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.initial_capital

    def get_position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def invested_notional(self, prices: dict[str, float]) -> float:
        """Sum of |quantity * price| across open positions - used for
        portfolio exposure limits."""
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos.is_open and symbol in prices:
                total += abs(pos.quantity * prices[symbol])
        return total

    def holdings_value(self, prices: dict[str, float]) -> float:
        total = 0.0
        for symbol, pos in self.positions.items():
            if pos.is_open and symbol in prices:
                total += pos.quantity * prices[symbol]
        return total

    def total_equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.holdings_value(prices)

    def record_equity(self, as_of: date, prices: dict[str, float]) -> None:
        holdings = self.holdings_value(prices)
        total = self.cash + holdings
        prev_total = self.equity_history[-1]["total_value"] if self.equity_history else self.initial_capital
        daily_return = (total / prev_total - 1) if prev_total else 0.0
        self.equity_history.append(
            {
                "date": as_of,
                "cash": self.cash,
                "holdings_value": holdings,
                "total_value": total,
                "daily_return": daily_return,
            }
        )
