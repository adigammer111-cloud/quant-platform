from __future__ import annotations

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import rsi


class RsiMeanReversionStrategy(Strategy):
    """Enter long when RSI drops below `oversold`; hold until RSI rises
    above `exit_level`. This needs bar-by-bar state (a position opened on
    an oversold reading must persist even if RSI wobbles back above
    `oversold` before reaching `exit_level`), so it is not a pure threshold
    snapshot like the SMA crossover strategy.
    """

    name = "rsi_mean_reversion"
    default_params = {"period": 14, "oversold": 30, "exit_level": 50}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        r = rsi(data["close"], self.params["period"])
        oversold = self.params["oversold"]
        exit_level = self.params["exit_level"]

        position = 0
        signals = []
        for value in r:
            if pd.isna(value):
                signals.append(0)
                continue
            if position == 0 and value < oversold:
                position = 1
            elif position == 1 and value > exit_level:
                position = 0
            signals.append(position)
        return pd.Series(signals, index=data.index)
