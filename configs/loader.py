"""Loads a YAML strategy/backtest configuration file (see
configs/strategies/*.yaml for examples) into the pieces `backtesting.runner`
needs, without touching engine code. This is what lets a strategy be
reconfigured (parameters, risk limits, capital, costs, universe, dates)
without editing Python.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from backtesting.costs import TransactionCostModel


@dataclass
class LoadedBacktestConfig:
    strategy_name: str
    parameters: dict
    risk: dict
    initial_capital: float
    cost_model: TransactionCostModel
    symbols: list[str] = field(default_factory=list)
    universe: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    benchmark_symbol: str | None = None
    execution_price_field: str = "open"


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def load_backtest_config(path: str | Path) -> LoadedBacktestConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    strategy = raw.get("strategy", {})
    parameters = raw.get("parameters", {}) or {}
    risk = raw.get("risk", {}) or {}
    capital = raw.get("capital", {}) or {}
    costs = raw.get("costs", {}) or {}
    period = raw.get("period", {}) or {}
    universe_cfg = raw.get("universe", {}) or {}

    cost_model = TransactionCostModel(**costs) if costs else TransactionCostModel()

    symbols = []
    universe_name = None
    if isinstance(universe_cfg, dict):
        symbols = universe_cfg.get("symbols", []) or []
        universe_name = universe_cfg.get("name")
    elif isinstance(universe_cfg, list):
        symbols = universe_cfg
    elif isinstance(universe_cfg, str):
        universe_name = universe_cfg

    return LoadedBacktestConfig(
        strategy_name=strategy["name"],
        parameters=parameters,
        risk=risk,
        initial_capital=float(capital.get("initial", 100_000)),
        cost_model=cost_model,
        symbols=symbols,
        universe=universe_name,
        start_date=_parse_date(period.get("start")),
        end_date=_parse_date(period.get("end")),
        benchmark_symbol=raw.get("benchmark"),
        execution_price_field=raw.get("execution_price_field", "open"),
    )
