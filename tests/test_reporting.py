from __future__ import annotations

from datetime import date

import pandas as pd

from analytics.reporting import monthly_returns_table


def test_monthly_returns_table_basic_two_months():
    dates = pd.date_range("2024-01-01", "2024-02-29", freq="D")
    # Jan: flat at 100,000. Feb: rises to 110,000 (a +10% month).
    values = []
    for d in dates:
        if d.month == 1:
            values.append(100_000)
        else:
            frac = (d.day - 1) / 28
            values.append(100_000 * (1 + 0.10 * frac))
    equity = pd.DataFrame({"date": dates, "total_value": values})

    table = monthly_returns_table(equity)
    assert 2024 in table.index
    assert "Jan" in table.columns and "Feb" in table.columns
    assert table.loc[2024, "Jan"] == 0.0
    assert round(table.loc[2024, "Feb"], 1) == 10.0
