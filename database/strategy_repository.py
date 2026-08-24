"""Persistence for user-built strategies (Strategy Builder → Strategy
Library). Built-in strategies (SMA crossover, RSI mean reversion, etc.) are
never stored here - they live in `strategies/registry.py` as code. This
table only holds rule-based and custom-code strategies assembled through
the dashboard.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

import pandas as pd

from database.db import get_connection


def generate_strategy_id(name: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in name.lower())[:30]
    return f"{slug}_{uuid.uuid4().hex[:6]}"


def save_strategy(name: str, kind: str, definition: dict, risk: dict | None = None, notes: str = "") -> str:
    strategy_id = generate_strategy_id(name)
    with get_connection() as con:
        con.execute(
            """
            INSERT INTO saved_strategies (strategy_id, name, kind, definition_json, risk_json, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [strategy_id, name, kind, json.dumps(definition, default=str), json.dumps(risk or {}), notes],
        )
    return strategy_id


def list_saved_strategies() -> pd.DataFrame:
    with get_connection(read_only=True) as con:
        return con.execute(
            "SELECT strategy_id, name, kind, created_at, notes FROM saved_strategies ORDER BY created_at DESC"
        ).fetchdf()


def get_saved_strategy(strategy_id: str) -> dict:
    with get_connection(read_only=True) as con:
        row = con.execute(
            "SELECT * FROM saved_strategies WHERE strategy_id = ?", [strategy_id]
        ).fetchdf()
    if row.empty:
        raise ValueError(f"No saved strategy with id {strategy_id}")
    record = row.iloc[0].to_dict()
    record["definition"] = json.loads(record["definition_json"])
    record["risk"] = json.loads(record["risk_json"]) if record["risk_json"] else {}
    return record


def delete_saved_strategy(strategy_id: str) -> None:
    with get_connection() as con:
        con.execute("DELETE FROM saved_strategies WHERE strategy_id = ?", [strategy_id])
