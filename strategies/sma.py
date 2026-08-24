from __future__ import annotations

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import sma


class SmaCrossoverStrategy(Strategy):
    """Long while the fast SMA is above the slow SMA, flat otherwise.

    Equivalent to "buy on golden cross, sell on death cross" expressed as a
    target-position regime rather than discrete cross events.
    """

    name = "sma_crossover"
    default_params = {"fast_period": 20, "slow_period": 50}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        fast = sma(data["close"], self.params["fast_period"])
        slow = sma(data["close"], self.params["slow_period"])
        signal = (fast > slow).astype(int)
        return signal.where(fast.notna() & slow.notna(), 0)
