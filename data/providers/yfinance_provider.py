"""yfinance-backed implementation of MarketDataProvider.

yfinance is free and requires no API key, which makes it a practical default
for a personal research platform. It is not an official NSE/BSE feed and has
known quirks (occasional missing sessions, throttling by Yahoo's backend,
limited intraday history). All access here goes through retry/backoff and
throttling helpers, and every response is validated downstream by
`data/validation/quality.py` - nothing in this class should be trusted blindly
by the rest of the app.

Symbol convention: NSE symbols use the ".NS" suffix, BSE symbols use ".BO"
(this is Yahoo Finance's convention, e.g. "RELIANCE.NS", "RELIANCE.BO").
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from data.http_utils import retry_with_backoff
from data.providers.base import (
    CORPORATE_ACTION_COLUMNS,
    DAILY_COLUMNS,
    INTRADAY_COLUMNS,
    InstrumentInfo,
    LiveQuoteProvider,
    MarketDataProvider,
    ProviderError,
    Quote,
)

logger = logging.getLogger(__name__)

# yfinance enforces lookback limits on fine-grained intraday intervals.
_INTRADAY_MAX_LOOKBACK_DAYS = {
    "1m": 7,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "90m": 60,
    "1h": 730,
}


def _split_exchange(symbol: str) -> tuple[str, str]:
    if symbol.endswith(".NS"):
        return symbol[:-3], "NSE"
    if symbol.endswith(".BO"):
        return symbol[:-3], "BSE"
    return symbol, "UNKNOWN"


class YFinanceProvider(MarketDataProvider, LiveQuoteProvider):
    name = "yfinance"

    @retry_with_backoff(exceptions=(Exception,))
    def _download_history(
        self, symbol: str, start: date, end: date, interval: str
    ) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
            interval=interval,
            auto_adjust=False,
            actions=True,
            raise_errors=True,
        )
        return df

    def get_daily_data(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        try:
            raw = self._download_history(symbol, start, end, "1d")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Failed to download daily data for {symbol}: {exc}") from exc

        if raw is None or raw.empty:
            logger.warning("No daily data returned for %s in [%s, %s]", symbol, start, end)
            return pd.DataFrame(columns=DAILY_COLUMNS)

        raw = raw.reset_index()
        # yfinance uses "Date" for daily bars, tz-aware; normalize to naive date.
        date_col = "Date" if "Date" in raw.columns else "Datetime"
        out = pd.DataFrame(
            {
                "date": pd.to_datetime(raw[date_col]).dt.tz_localize(None).dt.date,
                "open": raw.get("Open"),
                "high": raw.get("High"),
                "low": raw.get("Low"),
                "close": raw.get("Close"),
                "adj_close": raw.get("Adj Close", raw.get("Close")),
                "volume": raw.get("Volume"),
            }
        )
        out = out.dropna(subset=["open", "high", "low", "close"], how="all")
        return out.reset_index(drop=True)

    def get_intraday_data(
        self, symbol: str, start: date, end: date, interval: str = "5m"
    ) -> pd.DataFrame:
        max_lookback = _INTRADAY_MAX_LOOKBACK_DAYS.get(interval)
        if max_lookback is not None:
            earliest_allowed = date.today() - timedelta(days=max_lookback)
            if start < earliest_allowed:
                logger.warning(
                    "Provider %s only supports %s data back to %s; clipping requested start %s",
                    self.name,
                    interval,
                    earliest_allowed,
                    start,
                )
                start = earliest_allowed

        try:
            raw = self._download_history(symbol, start, end, interval)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Failed to download intraday data for {symbol}: {exc}"
            ) from exc

        if raw is None or raw.empty:
            return pd.DataFrame(columns=INTRADAY_COLUMNS)

        raw = raw.reset_index()
        ts_col = "Datetime" if "Datetime" in raw.columns else "Date"
        out = pd.DataFrame(
            {
                "ts": pd.to_datetime(raw[ts_col]).dt.tz_localize(None),
                "open": raw.get("Open"),
                "high": raw.get("High"),
                "low": raw.get("Low"),
                "close": raw.get("Close"),
                "volume": raw.get("Volume"),
            }
        )
        return out.dropna(subset=["open", "high", "low", "close"], how="all").reset_index(
            drop=True
        )

    def get_corporate_actions(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            ticker = yf.Ticker(symbol)
            dividends = ticker.dividends
            splits = ticker.splits
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Failed to fetch corporate actions for {symbol}: {exc}"
            ) from exc

        rows = []
        for ts, amount in dividends.items():
            d = pd.Timestamp(ts).tz_localize(None).date()
            if start <= d <= end and amount:
                rows.append(
                    {
                        "ex_date": d,
                        "action_type": "DIVIDEND",
                        "ratio_numerator": None,
                        "ratio_denominator": None,
                        "dividend_amount": float(amount),
                        "new_symbol": None,
                        "notes": None,
                    }
                )
        for ts, ratio in splits.items():
            d = pd.Timestamp(ts).tz_localize(None).date()
            if start <= d <= end and ratio:
                rows.append(
                    {
                        "ex_date": d,
                        "action_type": "SPLIT",
                        "ratio_numerator": float(ratio),
                        "ratio_denominator": 1.0,
                        "dividend_amount": None,
                        "new_symbol": None,
                        "notes": "ratio_numerator:1 split/bonus (yfinance combines splits and bonuses)",
                    }
                )
        if not rows:
            return pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS)
        return pd.DataFrame(rows, columns=CORPORATE_ACTION_COLUMNS).sort_values("ex_date")

    def get_instruments(self, symbols: list[str]) -> list[InstrumentInfo]:
        results: list[InstrumentInfo] = []
        for symbol in symbols:
            base_symbol, exchange = _split_exchange(symbol)
            info: dict = {}
            try:
                info = self._get_info(symbol)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch metadata for %s: %s", symbol, exc)
            results.append(
                InstrumentInfo(
                    symbol=symbol,
                    base_symbol=base_symbol,
                    exchange=exchange,
                    name=info.get("longName") or info.get("shortName"),
                    isin=info.get("isin"),
                    sector=info.get("sector"),
                    industry=info.get("industry"),
                    instrument_type="INDEX" if symbol.startswith("^") else "EQUITY",
                )
            )
        return results

    @retry_with_backoff(exceptions=(Exception,))
    def _get_info(self, symbol: str) -> dict:
        return yf.Ticker(symbol).get_info()

    @retry_with_backoff(exceptions=(Exception,), max_retries=2)
    def get_quote(self, symbol: str) -> Quote:
        fast_info = yf.Ticker(symbol).fast_info
        try:
            return Quote(
                symbol=symbol,
                price=float(fast_info["lastPrice"]),
                prev_close=float(fast_info["previousClose"]),
                open=float(fast_info["open"]),
                day_high=float(fast_info["dayHigh"]),
                day_low=float(fast_info["dayLow"]),
                volume=int(fast_info["lastVolume"]),
                as_of=datetime.now(timezone.utc),
                source="yfinance",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"yfinance returned an incomplete quote for {symbol}: {exc}") from exc
