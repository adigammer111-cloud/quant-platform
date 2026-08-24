from __future__ import annotations

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import sma


class MaMomentumStrategy(Strategy):
    """Long when price is above its long-term SMA AND the medium SMA is
    above the long SMA (trend + momentum confirmation); flat otherwise."""

    name = "ma_momentum"
    default_params = {"fast_period": 50, "slow_period": 200}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        fast = sma(data["close"], self.params["fast_period"])
        slow = sma(data["close"], self.params["slow_period"])
        condition = (data["close"] > slow) & (fast > slow)
        signal = condition.astype(int)
        return signal.where(fast.notna() & slow.notna(), 0)
