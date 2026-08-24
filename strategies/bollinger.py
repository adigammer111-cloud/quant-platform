from __future__ import annotations

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import bollinger_bands


class BollingerMeanReversionStrategy(Strategy):
    """Enter long when close drops below (or touches) the lower Bollinger
    Band; hold until close recovers to the middle band (the SMA). Stateful
    for the same reason as the RSI strategy - the exit condition is not the
    mirror of the entry condition.
    """

    name = "bollinger_mean_reversion"
    default_params = {"window": 20, "num_std": 2.0}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        upper, mid, lower = bollinger_bands(
            data["close"], self.params["window"], self.params["num_std"]
        )
        close = data["close"]

        position = 0
        signals = []
        for c, m, lo in zip(close, mid, lower):
            if pd.isna(m) or pd.isna(lo):
                signals.append(0)
                continue
            if position == 0 and c <= lo:
                position = 1
            elif position == 1 and c >= m:
                position = 0
            signals.append(position)
        return pd.Series(signals, index=data.index)
