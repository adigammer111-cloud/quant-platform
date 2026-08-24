from __future__ import annotations

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import rolling_high, rolling_low


class BreakoutStrategy(Strategy):
    """Donchian-channel breakout: enter long when close breaks above the
    prior `entry_window`-day high; exit when close breaks below the prior
    `exit_window`-day low. `rolling_high`/`rolling_low` are shifted by one
    bar internally, so "today's high" can never trigger its own breakout.
    """

    name = "breakout"
    default_params = {"entry_window": 20, "exit_window": 10}

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        entry_level = rolling_high(data["close"], self.params["entry_window"])
        exit_level = rolling_low(data["close"], self.params["exit_window"])
        close = data["close"]

        position = 0
        signals = []
        for c, entry, exit_ in zip(close, entry_level, exit_level):
            if pd.isna(entry) or pd.isna(exit_):
                signals.append(0)
                continue
            if position == 0 and c > entry:
                position = 1
            elif position == 1 and c < exit_:
                position = 0
            signals.append(position)
        return pd.Series(signals, index=data.index)
