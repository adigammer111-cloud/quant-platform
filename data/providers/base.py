"""Provider-agnostic market data interface.

Every concrete data source (yfinance today; a direct NSE/BSE feed, a paid
vendor, or a broker API later) implements `MarketDataProvider`. Nothing
outside `data/providers/` should import a concrete provider directly -
the rest of the application talks to this interface so swapping or adding
a provider never touches ingestion, validation, storage, or backtesting
code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd

DAILY_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
INTRADAY_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
CORPORATE_ACTION_COLUMNS = [
    "ex_date",
    "action_type",
    "ratio_numerator",
    "ratio_denominator",
    "dividend_amount",
    "new_symbol",
    "notes",
]


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    base_symbol: str
    exchange: str
    name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    instrument_type: str = "EQUITY"
    first_listed_date: Optional[date] = None


class ProviderError(RuntimeError):
    """Raised when a provider cannot fulfil a request after retries."""


@dataclass(frozen=True)
class Quote:
    """A single point-in-time price snapshot, used by paper trading and the
    Market page's "live" price display. NSE/BSE data from free sources is
    exchange-delayed (typically ~15 minutes), never real-time tick data -
    this is a research/paper-trading tool, not a trading terminal."""

    symbol: str
    price: float
    prev_close: float
    open: float
    day_high: float
    day_low: float
    volume: int
    as_of: datetime
    source: str

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100) if self.prev_close else 0.0


class LiveQuoteProvider(ABC):
    """A source of current (delayed) price quotes. Separate from
    `MarketDataProvider` because not every historical-data source can offer
    a live quote, and vice versa - `get_live_quote()` in `live_quotes.py`
    tries a priority list of these and falls back automatically."""

    name: str = "base"

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        """Raises ProviderError if the symbol can't be quoted by this source."""


class MarketDataProvider(ABC):
    """Abstract interface every market data source must implement."""

    name: str = "base"

    @abstractmethod
    def get_daily_data(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return a DataFrame with columns DAILY_COLUMNS, one row per session,
        for `symbol` in the half-open... inclusive range [start, end].
        Empty DataFrame (correct columns, zero rows) if nothing is available.
        """

    @abstractmethod
    def get_intraday_data(
        self, symbol: str, start: date, end: date, interval: str = "5m"
    ) -> pd.DataFrame:
        """Return a DataFrame with columns INTRADAY_COLUMNS."""

    @abstractmethod
    def get_corporate_actions(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return a DataFrame with columns CORPORATE_ACTION_COLUMNS."""

    @abstractmethod
    def get_instruments(self, symbols: list[str]) -> list[InstrumentInfo]:
        """Best-effort metadata lookup for a list of symbols."""
