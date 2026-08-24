"""Provider factory - the only place that knows concrete provider classes."""
from __future__ import annotations

from config import settings
from data.providers.base import MarketDataProvider
from data.providers.yfinance_provider import YFinanceProvider

_PROVIDERS: dict[str, type[MarketDataProvider]] = {
    "yfinance": YFinanceProvider,
}


def get_provider(name: str | None = None) -> MarketDataProvider:
    provider_name = name or settings.data_provider
    try:
        cls = _PROVIDERS[provider_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown data provider '{provider_name}'. Available: {list(_PROVIDERS)}"
        ) from exc
    return cls()
