"""Pydantic request/response models for the paper trading API. Kept
separate from `backend/main.py` so route handlers stay readable."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str


class MeResponse(BaseModel):
    user_id: str
    username: str


class CreateAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    initial_capital: float = Field(gt=0)


class AccountResponse(BaseModel):
    account_id: str
    name: str
    initial_capital: float
    cash: float
    created_at: datetime


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)


class OrderResponse(BaseModel):
    trade_id: str
    symbol: str
    side: str
    quantity: float
    execution_price: float
    costs: float
    realized_pnl: float | None
    quote_source: str
    cash_after: float


class QuoteResponse(BaseModel):
    symbol: str
    price: float
    prev_close: float
    open: float
    day_high: float
    day_low: float
    volume: int
    change: float
    change_pct: float
    as_of: datetime
    source: str


class PositionResponse(BaseModel):
    symbol: str
    quantity: float
    avg_price: float


class ErrorResponse(BaseModel):
    detail: str
