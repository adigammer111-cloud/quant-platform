"""Incremental data ingestion pipeline.

update_symbol() is the core building block: figure out what's already in the
database, download only the missing tail, validate it, and upsert it. This
is what backs `python cli.py update-data` - re-running it never re-downloads
history that's already present (unless `full_refresh=True` is passed).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from data.providers.base import MarketDataProvider, ProviderError
from data.storage import repository
from data.validation.quality import DataQualityReport, validate_daily_prices
from data.universe import load_universe

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DAYS = 10 * 365  # ~10 years for a brand-new symbol


@dataclass
class SymbolUpdateResult:
    symbol: str
    rows_downloaded: int
    rows_written: int
    quality_report: DataQualityReport | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def update_symbol(
    provider: MarketDataProvider,
    symbol: str,
    full_refresh: bool = False,
    history_days: int = DEFAULT_HISTORY_DAYS,
    end: date | None = None,
) -> SymbolUpdateResult:
    end = end or date.today()
    last_date = None if full_refresh else repository.get_last_daily_date(symbol)

    if last_date is None:
        start = end - timedelta(days=history_days)
    else:
        start = last_date + timedelta(days=1)

    rows_downloaded = 0
    rows_written = 0

    if start > end:
        logger.info("%s already up to date (last=%s)", symbol, last_date)
    else:
        logger.info("Downloading %s [%s -> %s]", symbol, start, end)
        try:
            df = provider.get_daily_data(symbol, start, end)
        except ProviderError as exc:
            logger.error("Download failed for %s: %s", symbol, exc)
            return SymbolUpdateResult(symbol, 0, 0, None, error=str(exc))

        rows_downloaded = len(df)
        logger.info("%d rows downloaded for %s", rows_downloaded, symbol)

        try:
            corp_actions = provider.get_corporate_actions(symbol, start, end)
        except ProviderError as exc:
            logger.warning("Corporate actions fetch failed for %s: %s", symbol, exc)
            corp_actions = None

        incremental_report = validate_daily_prices(symbol, df, corporate_actions=corp_actions)
        if incremental_report.status == "ERROR":
            logger.error("%s: data quality check FAILED - not writing to database", symbol)
            return SymbolUpdateResult(
                symbol, rows_downloaded, 0, incremental_report, error="data_quality_error"
            )

        rows_written = repository.upsert_daily_prices(symbol, df, source=provider.name)
        if corp_actions is not None and not corp_actions.empty:
            repository.upsert_corporate_actions(symbol, corp_actions, source=provider.name)

    # Always re-validate and refresh metadata against the full stored history,
    # so `data_metadata` (and hence `data-status`) stays accurate even when a
    # symbol was already up to date and nothing was downloaded this run.
    all_prices = repository.get_daily_prices(symbol)
    all_corp_actions = repository.get_corporate_actions(symbol)
    report = validate_daily_prices(symbol, all_prices, corporate_actions=all_corp_actions)
    if report.missing_sessions:
        logger.warning("%s: %d missing trading sessions", symbol, report.missing_sessions)
    repository.upsert_data_metadata(
        symbol,
        "daily",
        {
            "first_date": report.first_date,
            "last_date": report.last_date,
            "row_count": report.row_count,
            "missing_sessions": report.missing_sessions,
            "duplicate_rows": report.duplicates,
            "invalid_ohlc_rows": report.invalid_ohlc_rows,
            "suspicious_moves": report.suspicious_moves,
            "status": report.status,
            "notes": "; ".join(report.notes),
        },
    )
    logger.info("Validation complete for %s: status=%s", symbol, report.status)
    return SymbolUpdateResult(symbol, rows_downloaded, rows_written, report)


def update_universe(
    provider: MarketDataProvider,
    universe_name: str,
    full_refresh: bool = False,
    history_days: int = DEFAULT_HISTORY_DAYS,
) -> list[SymbolUpdateResult]:
    rows = load_universe(universe_name)
    symbols = [r["symbol"] for r in rows]

    instruments = provider.get_instruments(symbols)
    repository.upsert_instruments(instruments)

    results = []
    for symbol in symbols:
        result = update_symbol(
            provider, symbol, full_refresh=full_refresh, history_days=history_days
        )
        results.append(result)
    return results
