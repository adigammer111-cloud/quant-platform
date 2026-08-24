from __future__ import annotations

from datetime import date

import pandas as pd

from data.calendar import trading_sessions
from data.validation.quality import validate_daily_prices


def _valid_row(d, o=100.0, h=105.0, l=95.0, c=102.0, v=1000):
    return {"date": d, "open": o, "high": h, "low": l, "close": c, "adj_close": c, "volume": v}


def test_clean_data_is_ok():
    df = pd.DataFrame(
        [_valid_row(date(2024, 1, 1)), _valid_row(date(2024, 1, 2))]
    )
    report = validate_daily_prices("X", df, check_calendar=False)
    assert report.status == "OK"
    assert report.duplicates == 0
    assert report.invalid_ohlc_rows == 0


def test_duplicate_dates_detected():
    df = pd.DataFrame(
        [_valid_row(date(2024, 1, 1)), _valid_row(date(2024, 1, 1))]
    )
    report = validate_daily_prices("X", df, check_calendar=False)
    assert report.duplicates == 1  # one distinct date duplicated
    assert report.status == "ERROR"


def test_negative_price_detected():
    df = pd.DataFrame(
        [_valid_row(date(2024, 1, 1), o=-5.0)]
    )
    report = validate_daily_prices("X", df, check_calendar=False)
    assert len(report.negative_or_zero_price_dates) == 1
    assert report.status == "ERROR"


def test_zero_price_detected():
    df = pd.DataFrame([_valid_row(date(2024, 1, 1), c=0.0)])
    report = validate_daily_prices("X", df, check_calendar=False)
    assert len(report.negative_or_zero_price_dates) == 1


def test_high_less_than_low_detected():
    df = pd.DataFrame([_valid_row(date(2024, 1, 1), h=90.0, l=95.0)])
    report = validate_daily_prices("X", df, check_calendar=False)
    assert date(2024, 1, 1) in report.invalid_ohlc_dates
    assert report.status == "ERROR"


def test_open_outside_high_low_detected():
    df = pd.DataFrame([_valid_row(date(2024, 1, 1), o=200.0, h=105.0, l=95.0)])
    report = validate_daily_prices("X", df, check_calendar=False)
    assert date(2024, 1, 1) in report.invalid_ohlc_dates


def test_close_outside_high_low_detected():
    df = pd.DataFrame([_valid_row(date(2024, 1, 1), c=1.0, h=105.0, l=95.0)])
    report = validate_daily_prices("X", df, check_calendar=False)
    assert date(2024, 1, 1) in report.invalid_ohlc_dates


def test_missing_volume_detected():
    row = _valid_row(date(2024, 1, 1))
    row["volume"] = None
    df = pd.DataFrame([row])
    report = validate_daily_prices("X", df, check_calendar=False)
    assert date(2024, 1, 1) in report.missing_volume_dates


def test_suspicious_price_jump_detected():
    df = pd.DataFrame(
        [
            _valid_row(date(2024, 1, 1), c=100.0),
            _valid_row(date(2024, 1, 2), o=148.0, h=155.0, l=145.0, c=150.0),  # +50% unexplained jump
        ]
    )
    report = validate_daily_prices("X", df, check_calendar=False)
    assert report.suspicious_moves == 1
    assert report.status == "WARNING"


def test_suspicious_jump_ignored_when_corp_action_present():
    df = pd.DataFrame(
        [
            _valid_row(date(2024, 1, 1), c=100.0),
            _valid_row(date(2024, 1, 2), c=50.0),  # -50%, matches a 2:1 split
        ]
    )
    corp_actions = pd.DataFrame(
        [
            {
                "ex_date": date(2024, 1, 2),
                "action_type": "SPLIT",
                "ratio_numerator": 2.0,
                "ratio_denominator": 1.0,
                "dividend_amount": None,
                "new_symbol": None,
                "notes": None,
            }
        ]
    )
    report = validate_daily_prices("X", df, corporate_actions=corp_actions, check_calendar=False)
    assert report.suspicious_moves == 0
    assert report.corporate_actions_detected == 1


def test_missing_sessions_detected_against_real_calendar():
    sessions = trading_sessions(date(2024, 1, 1), date(2024, 1, 31))
    assert len(sessions) > 5
    kept = [d.date() for d in sessions[:5]] + [d.date() for d in sessions[7:10]]
    df = pd.DataFrame([_valid_row(d) for d in kept])
    report = validate_daily_prices("X", df, check_calendar=True)
    assert report.missing_sessions == 2  # sessions[5], sessions[6] dropped


def test_empty_dataframe_is_error():
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "adj_close", "volume"])
    report = validate_daily_prices("X", df)
    assert report.status == "ERROR"
    assert report.row_count == 0
