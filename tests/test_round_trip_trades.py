from __future__ import annotations

from datetime import date

import pandas as pd

from analytics.reporting import build_round_trip_trades


def test_pairs_buy_and_sell_into_one_round_trip():
    trades = pd.DataFrame(
        [
            {
                "symbol": "TEST.NS", "side": "BUY", "signal_date": date(2024, 1, 1),
                "execution_date": date(2024, 1, 2), "execution_price": 100.0, "quantity": 10.0,
                "gross_amount": 1000.0, "costs": 5.0, "net_amount": -1005.0,
                "realized_pnl": None, "holding_period_days": None, "exit_reason": "SIGNAL",
            },
            {
                "symbol": "TEST.NS", "side": "SELL", "signal_date": date(2024, 1, 10),
                "execution_date": date(2024, 1, 11), "execution_price": 120.0, "quantity": 10.0,
                "gross_amount": 1200.0, "costs": 6.0, "net_amount": 1194.0,
                "realized_pnl": 200.0, "holding_period_days": 9, "exit_reason": "SIGNAL",
            },
        ]
    )
    result = build_round_trip_trades(trades)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["side"] == "LONG"
    assert row["entry_price"] == 100.0
    assert row["exit_price"] == 120.0
    assert row["costs"] == 11.0
    assert row["net_pnl"] == 189.0  # 200 realized - 11 total costs
    assert row["return_pct"] == 18.9  # 189 / 1000 * 100


def test_multiple_symbols_paired_independently():
    trades = pd.DataFrame(
        [
            {"symbol": "A.NS", "side": "BUY", "signal_date": date(2024, 1, 1), "execution_date": date(2024, 1, 2),
             "execution_price": 50.0, "quantity": 20.0, "gross_amount": 1000.0, "costs": 2.0, "net_amount": -1002.0,
             "realized_pnl": None, "holding_period_days": None, "exit_reason": "SIGNAL"},
            {"symbol": "B.NS", "side": "BUY", "signal_date": date(2024, 1, 1), "execution_date": date(2024, 1, 2),
             "execution_price": 200.0, "quantity": 5.0, "gross_amount": 1000.0, "costs": 2.0, "net_amount": -1002.0,
             "realized_pnl": None, "holding_period_days": None, "exit_reason": "SIGNAL"},
            {"symbol": "A.NS", "side": "SELL", "signal_date": date(2024, 1, 5), "execution_date": date(2024, 1, 6),
             "execution_price": 55.0, "quantity": 20.0, "gross_amount": 1100.0, "costs": 2.0, "net_amount": 1098.0,
             "realized_pnl": 100.0, "holding_period_days": 4, "exit_reason": "SIGNAL"},
            {"symbol": "B.NS", "side": "SELL", "signal_date": date(2024, 1, 8), "execution_date": date(2024, 1, 9),
             "execution_price": 190.0, "quantity": 5.0, "gross_amount": 950.0, "costs": 2.0, "net_amount": 948.0,
             "realized_pnl": -50.0, "holding_period_days": 7, "exit_reason": "STOP_LOSS"},
        ]
    )
    result = build_round_trip_trades(trades)
    assert len(result) == 2
    assert set(result["symbol"]) == {"A.NS", "B.NS"}
    b_row = result[result["symbol"] == "B.NS"].iloc[0]
    assert b_row["exit_reason"] == "STOP_LOSS"
    assert b_row["net_pnl"] == -54.0


def test_empty_trades_returns_empty_with_correct_columns():
    result = build_round_trip_trades(pd.DataFrame())
    assert result.empty
    assert "net_pnl" in result.columns
