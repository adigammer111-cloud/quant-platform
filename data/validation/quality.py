"""Data quality engine.

Downloaded data is never trusted blindly. `validate_daily_prices` runs a
battery of checks (missing sessions, duplicates, invalid OHLC relationships,
suspicious price jumps, corporate-action discontinuities) and returns a
`DataQualityReport`. Callers (the ingestion pipeline, the CLI, the dashboard)
decide what to do with WARNING/ERROR statuses; this module never silently
drops or "fixes" data - it only reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from data.calendar import missing_sessions

SUSPICIOUS_MOVE_THRESHOLD = 0.20  # 20% single-session move, unexplained by a corp action


@dataclass
class DataQualityReport:
    symbol: str
    row_count: int = 0
    first_date: date | None = None
    last_date: date | None = None
    missing_session_dates: list[date] = field(default_factory=list)
    duplicate_dates: list[date] = field(default_factory=list)
    invalid_ohlc_dates: list[date] = field(default_factory=list)
    negative_or_zero_price_dates: list[date] = field(default_factory=list)
    missing_volume_dates: list[date] = field(default_factory=list)
    suspicious_move_dates: list[tuple[date, float]] = field(default_factory=list)
    corporate_actions_detected: int = 0
    corp_action_discontinuities: list[date] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def missing_sessions(self) -> int:
        return len(self.missing_session_dates)

    @property
    def duplicates(self) -> int:
        return len(self.duplicate_dates)

    @property
    def invalid_ohlc_rows(self) -> int:
        return len(self.invalid_ohlc_dates) + len(self.negative_or_zero_price_dates)

    @property
    def suspicious_moves(self) -> int:
        return len(self.suspicious_move_dates)

    @property
    def status(self) -> str:
        if self.row_count == 0:
            return "ERROR"
        if self.invalid_ohlc_rows > 0 or self.duplicates > 0:
            return "ERROR"
        if self.missing_sessions > 0 or self.suspicious_moves > 0 or self.corp_action_discontinuities:
            return "WARNING"
        return "OK"

    def to_text(self) -> str:
        lines = [
            self.symbol,
            "",
            f"Rows: {self.row_count:,}",
            f"Missing sessions: {self.missing_sessions}",
            f"Duplicates: {self.duplicates}",
            f"Invalid OHLC rows: {self.invalid_ohlc_rows}",
            f"Suspicious price movements: {self.suspicious_moves}",
            f"Corporate actions detected: {self.corporate_actions_detected}",
            f"Status: {self.status}",
        ]
        if self.notes:
            lines.append("Notes: " + "; ".join(self.notes))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "row_count": self.row_count,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "missing_sessions": self.missing_sessions,
            "duplicates": self.duplicates,
            "invalid_ohlc_rows": self.invalid_ohlc_rows,
            "suspicious_moves": self.suspicious_moves,
            "corporate_actions_detected": self.corporate_actions_detected,
            "status": self.status,
            "notes": "; ".join(self.notes),
        }


def validate_daily_prices(
    symbol: str,
    df: pd.DataFrame,
    corporate_actions: pd.DataFrame | None = None,
    check_calendar: bool = True,
) -> DataQualityReport:
    """`df` columns: date, open, high, low, close, adj_close, volume."""
    report = DataQualityReport(symbol=symbol, row_count=len(df))
    if df.empty:
        report.notes.append("No data returned by provider")
        return report

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date")

    report.first_date = df["date"].min()
    report.last_date = df["date"].max()

    # Duplicates
    dup_mask = df.duplicated(subset=["date"], keep=False)
    report.duplicate_dates = sorted(set(df.loc[dup_mask, "date"]))

    # Missing sessions (against NSE calendar)
    if check_calendar:
        try:
            report.missing_session_dates = missing_sessions(
                df["date"], report.first_date, report.last_date
            )
        except Exception as exc:  # noqa: BLE001
            report.notes.append(f"Calendar check skipped: {exc}")

    # Negative / zero prices
    price_cols = [c for c in ["open", "high", "low", "close", "adj_close"] if c in df.columns]
    neg_or_zero = df[(df[price_cols] <= 0).any(axis=1)]
    report.negative_or_zero_price_dates = sorted(neg_or_zero["date"].tolist())

    # OHLC relationship checks: high must be >= low, open/close within [low, high]
    valid = df.dropna(subset=["open", "high", "low", "close"])
    bad_hl = valid["high"] < valid["low"]
    bad_open = (valid["open"] > valid["high"]) | (valid["open"] < valid["low"])
    bad_close = (valid["close"] > valid["high"]) | (valid["close"] < valid["low"])
    invalid_mask = bad_hl | bad_open | bad_close
    report.invalid_ohlc_dates = sorted(valid.loc[invalid_mask, "date"].tolist())

    # Missing volume
    if "volume" in df.columns:
        report.missing_volume_dates = sorted(df.loc[df["volume"].isna(), "date"].tolist())

    # Suspicious single-session moves not explained by a corporate action ex-date
    corp_action_dates: set = set()
    if corporate_actions is not None and not corporate_actions.empty:
        report.corporate_actions_detected = len(corporate_actions)
        corp_action_dates = set(pd.to_datetime(corporate_actions["ex_date"]).dt.date)

    price_series = df.set_index("date")["close"].dropna()
    pct_change = price_series.pct_change().abs()
    for d, chg in pct_change.items():
        if pd.notna(chg) and chg > SUSPICIOUS_MOVE_THRESHOLD and d not in corp_action_dates:
            report.suspicious_move_dates.append((d, round(float(chg), 4)))

    # Corporate-action discontinuity sanity check: for SPLIT/BONUS actions,
    # the close-to-close return on the ex-date should be roughly explained by
    # the ratio; flag if it deviates by more than 50% of the expected magnitude
    # (a loose sanity check, not a precise reconciliation).
    if corporate_actions is not None and not corporate_actions.empty:
        splits = corporate_actions[corporate_actions["action_type"] == "SPLIT"]
        for _, row in splits.iterrows():
            ex_date = pd.Timestamp(row["ex_date"]).date()
            if ex_date not in price_series.index:
                continue
            ratio = row.get("ratio_numerator") or 1.0
            if ratio and ratio > 1 and ex_date in pct_change.index:
                observed = pct_change.get(ex_date, 0.0)
                expected = 1 - (1 / ratio)
                if pd.notna(observed) and abs(observed - expected) > 0.5 * expected:
                    report.corp_action_discontinuities.append(ex_date)

    return report
