"""Paper trading backend API.

Run standalone with:
    .venv\\Scripts\\python.exe -m uvicorn backend.main:app --reload --port 8000

This is a real, independently runnable HTTP server - not a mock. It sits
on top of the same `auth` and `paper_trading` modules the Streamlit
dashboard's Paper Trading page uses, backed by the same local DuckDB file
(free, no external service), so an account created here shows up in the
dashboard and vice versa. Interactive API docs are auto-generated at
/docs (Swagger UI) and /redoc once the server is running.

Auth: bearer token in the `Authorization: Bearer <token>` header, issued by
POST /auth/login. See auth/service.py's docstring for what this scheme
does and does not protect against - it's sized for a personal or small
private deployment, not a hardened multi-tenant production service.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from analytics.performance import compute_performance_metrics
from analytics.reporting import build_round_trip_trades
from auth import service as auth
from auth.service import AuthError
from backend.schemas import (
    AccountResponse,
    AuthResponse,
    CreateAccountRequest,
    ErrorResponse,
    LoginRequest,
    MeResponse,
    OrderRequest,
    OrderResponse,
    PositionResponse,
    QuoteResponse,
    RegisterRequest,
)
from data.providers.base import ProviderError
from data.providers.live_quotes import get_live_quote
from database.db import ensure_database
from logging_config import configure_logging
from paper_trading import engine
from paper_trading.engine import InsufficientFundsError, InsufficientSharesError

configure_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    ensure_database()
    yield


app = FastAPI(
    title="Quant Platform - Paper Trading API",
    description="Register, log in, open demo trading accounts, and trade any NSE/BSE symbol against live quotes.",
    version="1.0.0",
    lifespan=_lifespan,
)

# Permissive CORS since this is meant for localhost tools/dashboards during
# development, not a hardened public deployment (see module docstring).
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def get_current_user_id(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    user_id = auth.verify_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def _owned_account_or_404(account_id: str, user_id: str) -> dict:
    if not engine.account_belongs_to_user(account_id, user_id):
        raise HTTPException(status_code=404, detail="No such account")
    return engine.get_account(account_id)


def _json_safe_records(df) -> list[dict]:
    """DataFrame -> list[dict] with NaN replaced by None - `NaN` is not
    valid JSON, and pandas leaves it in place of Python's `None` for empty
    numeric cells (e.g. `realized_pnl` on a still-open position)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/register", response_model=AuthResponse, responses={400: {"model": ErrorResponse}})
def register(body: RegisterRequest) -> AuthResponse:
    try:
        user_id = auth.register(body.username, body.password)
        token = auth.login(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthResponse(token=token, user_id=user_id, username=body.username)


@app.post("/auth/login", response_model=AuthResponse, responses={401: {"model": ErrorResponse}})
def login(body: LoginRequest) -> AuthResponse:
    try:
        token = auth.login(body.username, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user_id = auth.verify_token(token)
    return AuthResponse(token=token, user_id=user_id, username=body.username.strip())


@app.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)) -> None:
    if authorization and authorization.lower().startswith("bearer "):
        auth.logout(authorization.split(" ", 1)[1].strip())


@app.get("/me", response_model=MeResponse)
def me(user_id: str = Depends(get_current_user_id)) -> MeResponse:
    return MeResponse(user_id=user_id, username=auth.get_username(user_id) or "")


@app.get("/quotes/{symbol}", response_model=QuoteResponse, responses={502: {"model": ErrorResponse}})
def get_quote(symbol: str, user_id: str = Depends(get_current_user_id)) -> QuoteResponse:
    try:
        quote = get_live_quote(symbol)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return QuoteResponse(
        symbol=quote.symbol, price=quote.price, prev_close=quote.prev_close, open=quote.open,
        day_high=quote.day_high, day_low=quote.day_low, volume=quote.volume,
        change=quote.change, change_pct=quote.change_pct, as_of=quote.as_of, source=quote.source,
    )


@app.post("/accounts", response_model=AccountResponse, status_code=201)
def create_account(body: CreateAccountRequest, user_id: str = Depends(get_current_user_id)) -> AccountResponse:
    account_id = engine.create_account(body.name, body.initial_capital, user_id=user_id)
    return AccountResponse(**engine.get_account(account_id))


@app.get("/accounts", response_model=list[AccountResponse])
def list_accounts(user_id: str = Depends(get_current_user_id)) -> list[AccountResponse]:
    df = engine.list_accounts(user_id=user_id)
    return [AccountResponse(**row) for row in df.to_dict(orient="records")]


@app.get("/accounts/{account_id}", response_model=AccountResponse, responses={404: {"model": ErrorResponse}})
def get_account(account_id: str, user_id: str = Depends(get_current_user_id)) -> AccountResponse:
    return AccountResponse(**_owned_account_or_404(account_id, user_id))


@app.get("/accounts/{account_id}/positions", response_model=list[PositionResponse])
def get_positions(account_id: str, user_id: str = Depends(get_current_user_id)) -> list[PositionResponse]:
    _owned_account_or_404(account_id, user_id)
    df = engine.get_positions(account_id)
    return [PositionResponse(symbol=r["symbol"], quantity=r["quantity"], avg_price=r["avg_price"]) for _, r in df.iterrows()]


@app.get("/accounts/{account_id}/trades")
def get_trades(account_id: str, user_id: str = Depends(get_current_user_id)) -> list[dict]:
    _owned_account_or_404(account_id, user_id)
    df = engine.get_trades(account_id)
    return _json_safe_records(df)


@app.post(
    "/accounts/{account_id}/orders", response_model=OrderResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
def place_order(account_id: str, body: OrderRequest, user_id: str = Depends(get_current_user_id)) -> OrderResponse:
    _owned_account_or_404(account_id, user_id)
    try:
        result = engine.place_order(account_id, body.symbol.upper(), body.side, body.quantity)
    except (InsufficientFundsError, InsufficientSharesError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch a live quote: {exc}") from exc
    return OrderResponse(**vars(result))


@app.get("/accounts/{account_id}/analysis", responses={404: {"model": ErrorResponse}})
def get_analysis(account_id: str, user_id: str = Depends(get_current_user_id)) -> dict:
    account = _owned_account_or_404(account_id, user_id)
    equity_curve = engine.get_equity_curve(account_id)
    trades = engine.get_trades(account_id)

    if equity_curve.empty:
        return {"has_data": False, "metrics": None, "equity_curve": [], "round_trip_trades": []}

    metrics = compute_performance_metrics(equity_curve, trades, float(account["initial_capital"]))
    round_trips = build_round_trip_trades(trades)
    return {
        "has_data": True,
        "metrics": metrics.to_dict(),
        "equity_curve": _json_safe_records(equity_curve),
        "round_trip_trades": _json_safe_records(round_trips),
    }
