"""Performance metrics computed from a backtest's equity curve and trade
log. Every number here is derived from the actual simulated equity_curve /
trades DataFrames produced by `backtesting.engine.BacktestEngine` - nothing
is hard-coded or estimated.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class PerformanceMetrics:
    # Returns
    initial_capital: float
    final_capital: float
    absolute_return_pct: float
    cagr_pct: float
    annualized_return_pct: float
    # Risk
    max_drawdown_pct: float
    avg_drawdown_pct: float
    volatility_annualized_pct: float
    downside_deviation_pct: float
    value_at_risk_95_pct: float
    expected_shortfall_95_pct: float
    # Risk-adjusted
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    # Trading
    num_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    avg_holding_period_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    turnover_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)


def _max_consecutive(mask: pd.Series) -> int:
    best = current = 0
    for v in mask:
        if v:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def compute_performance_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
    risk_free_rate_annual: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> PerformanceMetrics:
    if equity_curve.empty:
        raise ValueError("Cannot compute performance metrics from an empty equity curve")

    equity_curve = equity_curve.sort_values("date").reset_index(drop=True)
    final_capital = float(equity_curve["total_value"].iloc[-1])
    absolute_return_pct = (final_capital / initial_capital - 1) * 100

    n_days = len(equity_curve)
    date_span_days = max(
        (pd.Timestamp(equity_curve["date"].iloc[-1]) - pd.Timestamp(equity_curve["date"].iloc[0])).days,
        1,
    )
    date_span_years = date_span_days / 365.25
    try:
        cagr = (final_capital / initial_capital) ** (1 / date_span_years) - 1 if final_capital > 0 else -1.0
    except OverflowError:
        # Annualizing an extreme return over a very short window (e.g. a
        # single day of paper trading) can overflow float64 well before it
        # becomes a meaningful number - fall back to the plain (still large)
        # absolute return rather than crashing the whole report.
        cagr = absolute_return_pct / 100
    cagr_pct = cagr * 100

    daily_returns = equity_curve["daily_return"].fillna(0.0)
    mean_daily = daily_returns.mean()
    annualized_return_pct = ((1 + mean_daily) ** periods_per_year - 1) * 100

    if "drawdown" in equity_curve.columns:
        drawdown = equity_curve["drawdown"]
    else:
        cummax = equity_curve["total_value"].cummax()
        drawdown = equity_curve["total_value"] / cummax - 1
    max_drawdown_pct = float(drawdown.min()) * 100
    avg_drawdown_pct = float(drawdown[drawdown < 0].mean()) * 100 if (drawdown < 0).any() else 0.0

    daily_vol = daily_returns.std(ddof=1) if n_days > 1 else 0.0
    volatility_annualized_pct = daily_vol * np.sqrt(periods_per_year) * 100

    downside_returns = daily_returns[daily_returns < 0]
    downside_deviation = downside_returns.std(ddof=1) if len(downside_returns) > 1 else 0.0
    downside_deviation_pct = downside_deviation * np.sqrt(periods_per_year) * 100

    if len(daily_returns) >= 20:
        var_95 = -float(np.percentile(daily_returns, 5))
        tail = daily_returns[daily_returns <= np.percentile(daily_returns, 5)]
        es_95 = -float(tail.mean()) if len(tail) else var_95
    else:
        var_95 = 0.0
        es_95 = 0.0

    daily_rf = (1 + risk_free_rate_annual) ** (1 / periods_per_year) - 1
    excess_returns = daily_returns - daily_rf
    sharpe = (
        (excess_returns.mean() / daily_returns.std(ddof=1)) * np.sqrt(periods_per_year)
        if daily_returns.std(ddof=1) > 0
        else 0.0
    )
    sortino = (
        (excess_returns.mean() / downside_deviation) * np.sqrt(periods_per_year)
        if downside_deviation > 0
        else 0.0
    )
    calmar = cagr / abs(drawdown.min()) if drawdown.min() < 0 else 0.0

    if trades.empty or "realized_pnl" not in trades.columns:
        closed = pd.DataFrame(columns=["realized_pnl", "holding_period_days", "gross_amount"])
    else:
        closed = trades[trades["realized_pnl"].notna()].copy()
    num_trades = len(closed)
    wins = closed[closed["realized_pnl"] > 0]
    losses = closed[closed["realized_pnl"] < 0]
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate_pct = (winning_trades / num_trades * 100) if num_trades else 0.0
    avg_win = float(wins["realized_pnl"].mean()) if winning_trades else 0.0
    avg_loss = float(losses["realized_pnl"].mean()) if losing_trades else 0.0
    gross_profit = float(wins["realized_pnl"].sum()) if winning_trades else 0.0
    gross_loss = float(-losses["realized_pnl"].sum()) if losing_trades else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = float(closed["realized_pnl"].mean()) if num_trades else 0.0
    avg_holding_period_days = float(closed["holding_period_days"].mean()) if num_trades else 0.0

    win_mask = closed["realized_pnl"] > 0 if num_trades else pd.Series(dtype=bool)
    loss_mask = closed["realized_pnl"] < 0 if num_trades else pd.Series(dtype=bool)
    max_consecutive_wins = _max_consecutive(win_mask) if num_trades else 0
    max_consecutive_losses = _max_consecutive(loss_mask) if num_trades else 0

    avg_equity = equity_curve["total_value"].mean()
    total_traded_value = float(trades["gross_amount"].sum()) if not trades.empty else 0.0
    turnover_ratio = (total_traded_value / avg_equity) if avg_equity else 0.0

    return PerformanceMetrics(
        initial_capital=initial_capital,
        final_capital=final_capital,
        absolute_return_pct=absolute_return_pct,
        cagr_pct=cagr_pct,
        annualized_return_pct=annualized_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        avg_drawdown_pct=avg_drawdown_pct,
        volatility_annualized_pct=volatility_annualized_pct,
        downside_deviation_pct=downside_deviation_pct,
        value_at_risk_95_pct=var_95 * 100,
        expected_shortfall_95_pct=es_95 * 100,
        sharpe_ratio=float(sharpe),
        sortino_ratio=float(sortino),
        calmar_ratio=float(calmar),
        num_trades=num_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=win_rate_pct,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_holding_period_days=avg_holding_period_days,
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
        turnover_ratio=turnover_ratio,
    )
