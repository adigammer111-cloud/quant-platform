"""Drawdown-specific helpers used by the reporting layer (underwater curve
chart). Headline drawdown *statistics* (max/avg drawdown) live in
`analytics/performance.py` alongside the rest of the summary metrics so
there is one source of truth for the numbers shown in a report; this module
is just the time series used to draw the chart.
"""
from __future__ import annotations

import pandas as pd


def underwater_curve(equity_curve: pd.DataFrame) -> pd.Series:
    """Return drawdown (%, <= 0) indexed by date - the 'underwater' chart."""
    cummax = equity_curve["total_value"].cummax()
    dd = (equity_curve["total_value"] / cummax - 1) * 100
    return pd.Series(dd.values, index=pd.to_datetime(equity_curve["date"]), name="drawdown_pct")


def drawdown_episodes(equity_curve: pd.DataFrame, threshold_pct: float = -1.0) -> pd.DataFrame:
    """Identify distinct peak-to-recovery drawdown episodes deeper than
    `threshold_pct`. Useful for a "worst drawdowns" table in a report."""
    dd = underwater_curve(equity_curve)
    episodes = []
    in_dd = False
    start = None
    trough = 0.0
    trough_date = None
    for d, value in dd.items():
        if value < 0 and not in_dd:
            in_dd = True
            start = d
            trough = value
            trough_date = d
        elif in_dd and value < trough:
            trough = value
            trough_date = d
        elif in_dd and value >= 0:
            if trough <= threshold_pct:
                episodes.append(
                    {
                        "start": start,
                        "trough_date": trough_date,
                        "recovery_date": d,
                        "max_drawdown_pct": trough,
                        "duration_days": (d - start).days,
                    }
                )
            in_dd = False
    if in_dd and trough <= threshold_pct:
        episodes.append(
            {
                "start": start,
                "trough_date": trough_date,
                "recovery_date": None,
                "max_drawdown_pct": trough,
                "duration_days": (dd.index[-1] - start).days,
            }
        )
    return pd.DataFrame(episodes).sort_values("max_drawdown_pct") if episodes else pd.DataFrame(
        columns=["start", "trough_date", "recovery_date", "max_drawdown_pct", "duration_days"]
    )
