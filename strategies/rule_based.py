"""Rule-based strategy engine backing the visual Strategy Builder.

A user composes entry conditions (all must hold - AND) and exit conditions
(any one triggers a close - OR) from a small vocabulary of price/indicator
comparisons. This is a real, working `Strategy` implementation - the
builder UI is not a mockup that produces a static picture; the conditions
you assemble are compiled into an actual `generate_signals` function run by
the same `BacktestEngine` every other strategy in this project uses.

Also provides `build_custom_strategy`, backing the "advanced Python mode":
the user supplies the body of a `generate_signals(data)` function directly,
which is executed in a namespace exposing only pandas/numpy and this
project's indicator helpers (no `os`, `subprocess`, filesystem, or network
access) - not a full sandbox, but enough to keep an accidental typo (or a
strategy snippet copied from somewhere) from doing anything beyond
computing a signal series. This tool runs entirely on your own machine
under your own account, so this is defense-in-depth, not a security
boundary against a hostile user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from strategies.base import Strategy
from strategies.indicators import bollinger_bands, ema, rsi, sma

SeriesKind = Literal["price", "sma", "ema", "rsi", "bb_upper", "bb_mid", "bb_lower", "volume", "value"]
Operator = Literal[">", "<", ">=", "<=", "crosses_above", "crosses_below"]

SERIES_LABELS: dict[str, str] = {
    "price": "Price (Close)",
    "sma": "SMA",
    "ema": "EMA",
    "rsi": "RSI",
    "bb_upper": "Bollinger Upper",
    "bb_mid": "Bollinger Mid",
    "bb_lower": "Bollinger Lower",
    "volume": "Volume",
    "value": "Fixed Value",
}
OPERATOR_LABELS: dict[str, str] = {
    ">": "greater than (>)",
    "<": "less than (<)",
    ">=": ">=",
    "<=": "<=",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}


@dataclass
class Condition:
    left: SeriesKind
    operator: Operator
    right: SeriesKind
    left_window: int = 20
    right_window: int = 20
    right_value: float = 0.0
    num_std: float = 2.0

    def describe(self) -> str:
        left_desc = f"{SERIES_LABELS[self.left]}({self.left_window})" if self.left in {"sma", "ema", "rsi"} else SERIES_LABELS[self.left]
        if self.right == "value":
            right_desc = f"{self.right_value:g}"
        elif self.right in {"sma", "ema", "rsi"}:
            right_desc = f"{SERIES_LABELS[self.right]}({self.right_window})"
        else:
            right_desc = SERIES_LABELS[self.right]
        return f"{left_desc} {OPERATOR_LABELS[self.operator]} {right_desc}"


def _resolve_series(data: pd.DataFrame, kind: str, window: int, num_std: float) -> pd.Series:
    close = data["close"]
    if kind == "price":
        return close
    if kind == "sma":
        return sma(close, window)
    if kind == "ema":
        return ema(close, window)
    if kind == "rsi":
        return rsi(close, window)
    if kind == "bb_upper":
        return bollinger_bands(close, window, num_std)[0]
    if kind == "bb_mid":
        return bollinger_bands(close, window, num_std)[1]
    if kind == "bb_lower":
        return bollinger_bands(close, window, num_std)[2]
    if kind == "volume":
        return data["volume"]
    raise ValueError(f"Unknown series kind: {kind}")


def evaluate_condition(data: pd.DataFrame, cond: Condition) -> pd.Series:
    left = _resolve_series(data, cond.left, cond.left_window, cond.num_std)
    right = cond.right_value if cond.right == "value" else _resolve_series(
        data, cond.right, cond.right_window, cond.num_std
    )

    if cond.operator == ">":
        return left > right
    if cond.operator == "<":
        return left < right
    if cond.operator == ">=":
        return left >= right
    if cond.operator == "<=":
        return left <= right

    right_prev = right.shift(1) if isinstance(right, pd.Series) else right
    if cond.operator == "crosses_above":
        return (left > right) & (left.shift(1) <= right_prev)
    if cond.operator == "crosses_below":
        return (left < right) & (left.shift(1) >= right_prev)
    raise ValueError(f"Unknown operator: {cond.operator}")


class RuleBasedStrategy(Strategy):
    """Built from user-assembled entry/exit condition lists. Entry requires
    ALL entry conditions to hold simultaneously; exit fires on ANY exit
    condition (the common convention: enter on confluence, exit on the
    first warning sign)."""

    name = "rule_based_builder"

    def __init__(self, entry_conditions: list[Condition], exit_conditions: list[Condition], **kwargs):
        super().__init__(**kwargs)
        self.entry_conditions = entry_conditions
        self.exit_conditions = exit_conditions

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        if not self.entry_conditions:
            return pd.Series(0, index=data.index)

        entry_mask = pd.Series(True, index=data.index)
        for cond in self.entry_conditions:
            entry_mask = entry_mask & evaluate_condition(data, cond).fillna(False)

        if self.exit_conditions:
            exit_mask = pd.Series(False, index=data.index)
            for cond in self.exit_conditions:
                exit_mask = exit_mask | evaluate_condition(data, cond).fillna(False)
        else:
            exit_mask = pd.Series(False, index=data.index)

        position = 0
        signals = []
        for enter, exit_ in zip(entry_mask, exit_mask):
            if position == 0 and enter:
                position = 1
            elif position == 1 and exit_:
                position = 0
            signals.append(position)
        return pd.Series(signals, index=data.index)


_ALLOWED_BUILTINS = {
    "len": len, "range": range, "min": min, "max": max, "abs": abs, "sum": sum,
    "round": round, "enumerate": enumerate, "zip": zip, "sorted": sorted,
    "int": int, "float": float, "bool": bool, "str": str,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "isinstance": isinstance, "print": print,
    "True": True, "False": False, "None": None,
}


class CustomCodeStrategy(Strategy):
    """Wraps a user-supplied `generate_signals(data)` function body (source
    text, not a callable) for the advanced Python mode. Executed in a
    namespace exposing pandas, numpy, and this project's indicator
    functions - not the OS, filesystem, or network."""

    name = "custom_code_strategy"

    def __init__(self, source_code: str, **kwargs):
        super().__init__(**kwargs)
        self.source_code = source_code
        self._compiled_fn = self._compile(source_code)

    @staticmethod
    def _compile(source_code: str):
        import numpy as np

        namespace: dict = {
            "pd": pd, "np": np,
            "sma": sma, "ema": ema, "rsi": rsi, "bollinger_bands": bollinger_bands,
            "__builtins__": _ALLOWED_BUILTINS,
        }
        wrapped = "def generate_signals(data):\n" + "\n".join(
            "    " + line for line in source_code.splitlines()
        )
        exec(wrapped, namespace)  # noqa: S102 - intentional, see module docstring
        return namespace["generate_signals"]

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        result = self._compiled_fn(data)
        if not isinstance(result, pd.Series):
            raise ValueError("generate_signals must return a pandas Series")
        return result.reindex(data.index).fillna(0).clip(-1, 1).astype(int)
