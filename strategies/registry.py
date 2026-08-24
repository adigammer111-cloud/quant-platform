"""Strategy name -> class registry, used by the CLI, config loader, and
Streamlit UI so strategies can be selected by name (e.g. from a YAML config)
without importing every module by hand.
"""
from __future__ import annotations

from strategies.base import RiskParams, Strategy
from strategies.bollinger import BollingerMeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.momentum import MaMomentumStrategy
from strategies.rsi import RsiMeanReversionStrategy
from strategies.sma import SmaCrossoverStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    SmaCrossoverStrategy.name: SmaCrossoverStrategy,
    RsiMeanReversionStrategy.name: RsiMeanReversionStrategy,
    MaMomentumStrategy.name: MaMomentumStrategy,
    BollingerMeanReversionStrategy.name: BollingerMeanReversionStrategy,
    BreakoutStrategy.name: BreakoutStrategy,
}


def get_strategy_class(name: str) -> type[Strategy]:
    try:
        return STRATEGY_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {list(STRATEGY_REGISTRY)}"
        ) from exc


def apply_risk_overrides(instance: Strategy, risk_overrides: dict | None) -> Strategy:
    """Mutates and returns `instance` with its `.risk` replaced by a
    RiskParams built from `risk_overrides` layered on top of whatever the
    strategy already had. Shared by registry-built strategies and
    dashboard-constructed ones (RuleBasedStrategy, CustomCodeStrategy) so
    there's one place that knows the override key names."""
    if not risk_overrides:
        return instance
    base = instance.risk
    instance.risk = RiskParams(
        stop_loss_pct=risk_overrides.get("stop_loss", base.stop_loss_pct),
        take_profit_pct=risk_overrides.get("take_profit", base.take_profit_pct),
        trailing_stop_pct=risk_overrides.get("trailing_stop", base.trailing_stop_pct),
        max_position_pct=risk_overrides.get("max_position_pct", base.max_position_pct),
        max_portfolio_exposure_pct=risk_overrides.get(
            "max_portfolio_exposure_pct", base.max_portfolio_exposure_pct
        ),
    )
    return instance


def build_strategy(
    name: str, params: dict | None = None, risk_overrides: dict | None = None
) -> Strategy:
    cls = get_strategy_class(name)
    instance = cls(**(params or {}))
    return apply_risk_overrides(instance, risk_overrides)
