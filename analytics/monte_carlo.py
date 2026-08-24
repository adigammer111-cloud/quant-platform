"""Monte Carlo analysis on a completed backtest's trade log: resample the
sequence of realized trade P&Ls (with replacement) to see how sensitive the
result is to the particular order/luck of trades that happened to occur,
rather than treating the single historical path as gospel.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MonteCarloResult:
    n_simulations: int
    final_capital_percentiles: dict[float, float]   # e.g. {5: ..., 50: ..., 95: ...}
    max_drawdown_percentiles: dict[float, float]
    probability_of_loss_pct: float
    median_final_capital: float
    worst_final_capital: float
    worst_max_drawdown_pct: float
    raw_final_capitals: np.ndarray
    raw_max_drawdowns: np.ndarray


def run_monte_carlo(
    trades: pd.DataFrame,
    initial_capital: float,
    n_simulations: int = 10_000,
    slippage_jitter_bps_std: float = 0.0,
    seed: int | None = None,
) -> MonteCarloResult:
    """Randomizes trade order (and optionally jitters each trade's P&L by
    extra simulated slippage noise) to build a distribution of outcomes.
    Only closed trades (non-null realized_pnl) are resampled - open/partial
    legs carry no standalone P&L to resample.
    """
    closed = trades[trades["realized_pnl"].notna()] if not trades.empty else pd.DataFrame()
    pnls = closed["realized_pnl"].to_numpy() if not closed.empty else np.array([])
    if len(pnls) == 0:
        raise ValueError("No closed trades available to run a Monte Carlo simulation on")

    rng = np.random.default_rng(seed)
    n_trades = len(pnls)

    final_capitals = np.empty(n_simulations)
    max_drawdowns = np.empty(n_simulations)

    for i in range(n_simulations):
        sampled = rng.choice(pnls, size=n_trades, replace=True)
        if slippage_jitter_bps_std > 0:
            gross_estimate = np.abs(sampled).mean() if len(sampled) else 0.0
            noise = rng.normal(0, slippage_jitter_bps_std / 10_000.0, size=n_trades) * gross_estimate
            sampled = sampled + noise

        equity = initial_capital + np.cumsum(sampled)
        equity_with_start = np.concatenate([[initial_capital], equity])
        running_max = np.maximum.accumulate(equity_with_start)
        drawdowns = equity_with_start / running_max - 1

        final_capitals[i] = equity_with_start[-1]
        max_drawdowns[i] = drawdowns.min() * 100

    percentiles = [5, 25, 50, 75, 95]
    final_capital_percentiles = {p: float(np.percentile(final_capitals, p)) for p in percentiles}
    max_drawdown_percentiles = {p: float(np.percentile(max_drawdowns, p)) for p in percentiles}
    probability_of_loss_pct = float((final_capitals < initial_capital).mean() * 100)

    return MonteCarloResult(
        n_simulations=n_simulations,
        final_capital_percentiles=final_capital_percentiles,
        max_drawdown_percentiles=max_drawdown_percentiles,
        probability_of_loss_pct=probability_of_loss_pct,
        median_final_capital=float(np.median(final_capitals)),
        worst_final_capital=float(final_capitals.min()),
        worst_max_drawdown_pct=float(max_drawdowns.min()),
        raw_final_capitals=final_capitals,
        raw_max_drawdowns=max_drawdowns,
    )
