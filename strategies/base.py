"""Strategy interface.

A Strategy turns a single symbol's OHLCV history into a *target position*
series: -1 (short), 0 (flat), 1 (long), one value per bar, using only data
up to and including that bar. It does NOT decide execution price or
timing - the backtesting engine is solely responsible for turning a target
position at bar t into an order filled at bar t+1 (see
`backtesting/engine.py` for why, and how look-ahead bias is prevented).

Risk parameters (stop loss / take profit / trailing stop / position and
exposure limits) are declared per-strategy but *applied* by the engine,
because they require portfolio-level state (current cash, entry price,
running high-water-mark) that an individual `generate_signals` call does
not have visibility into.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class RiskParams:
    stop_loss_pct: float | None = None       # e.g. 0.05 = exit if -5% from entry
    take_profit_pct: float | None = None      # e.g. 0.10 = exit if +10% from entry
    trailing_stop_pct: float | None = None    # e.g. 0.08 = exit if -8% from running peak
    max_position_pct: float = 1.0             # max fraction of equity in one symbol
    max_portfolio_exposure_pct: float = 1.0    # max fraction of equity invested across all symbols


class Strategy(ABC):
    name: str = "unnamed_strategy"
    version: str = "1.0"
    allow_short: bool = False
    default_params: dict = {}
    risk: RiskParams = RiskParams()

    def __init__(self, **params):
        self.params = {**self.default_params, **params}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """`data` columns: open, high, low, close, adj_close, volume, indexed
        by ascending date. Must return a Series aligned to `data.index` with
        values in {-1, 0, 1} - the *target* position as of each bar's close.
        Implementations must only reference `data.loc[:t]` when computing the
        value for bar t (rolling/ewm/shift operations all satisfy this
        automatically; do not use centered windows or negative shifts).
        """
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "allow_short": self.allow_short,
            "parameters": dict(self.params),
            "risk": {
                "stop_loss_pct": self.risk.stop_loss_pct,
                "take_profit_pct": self.risk.take_profit_pct,
                "trailing_stop_pct": self.risk.trailing_stop_pct,
                "max_position_pct": self.risk.max_position_pct,
                "max_portfolio_exposure_pct": self.risk.max_portfolio_exposure_pct,
            },
        }
