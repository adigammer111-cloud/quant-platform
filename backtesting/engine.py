"""The backtesting engine.

Look-ahead bias prevention (the single most important property of this
module): `strategy.generate_signals(data)` returns a target position for
each bar computed from information available *as of that bar's close*. The
engine then shifts that series forward by `signal_lag_bars` (1 by default)
before ever comparing it to a price - so the position the strategy decided
on using bar t's close is only ever acted on starting at bar t+1, and it is
filled at bar t+1's `execution_price_field` (the opening price by default).
There is no code path in this engine that reads today's signal and trades
at today's price; the only same-day intrabar activity is stop-loss /
take-profit / trailing-stop checks, which are explicitly modeled as
intraday risk triggers (not signal-driven decisions) and are filled at the
trigger level, clipped to that day's actual [low, high] range.

Position sizing uses the *prior* day's closing equity, not same-day
mark-to-market equity, for the same reason: sizing off information that
only becomes known during today's session would itself be a subtle form of
look-ahead.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from backtesting.costs import TransactionCostModel
from backtesting.data_prep import prepare_ohlcv
from backtesting.execution import ExecutionSimulator
from backtesting.portfolio import Portfolio
from strategies.base import RiskParams, Strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    cost_model: TransactionCostModel = field(default_factory=TransactionCostModel)
    execution_price_field: str = "open"   # 'open' or 'close' of the execution bar
    use_adjusted_prices: bool = True
    signal_lag_bars: int = 1               # must stay >= 1 to avoid look-ahead; see module docstring
    benchmark_symbol: str | None = None
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if self.signal_lag_bars < 1:
            raise ValueError(
                "signal_lag_bars must be >= 1: executing on the same bar the "
                "signal was generated on is look-ahead bias by definition."
            )


@dataclass
class BacktestResult:
    strategy_name: str
    strategy_version: str
    parameters: dict
    universe: list[str]
    start_date: date
    end_date: date
    config: BacktestConfig
    portfolio: Portfolio
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    survivorship_biased: bool = True
    warnings: list[str] = field(default_factory=list)


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()
        self.execution = ExecutionSimulator(self.config.cost_model)

    def run(
        self,
        strategy: Strategy,
        data: dict[str, pd.DataFrame],
        start_date: date | None = None,
        end_date: date | None = None,
        survivorship_biased: bool = True,
    ) -> BacktestResult:
        prepared = {
            symbol: prepare_ohlcv(df, use_adjusted=self.config.use_adjusted_prices)
            for symbol, df in data.items()
            if not df.empty
        }
        if not prepared:
            raise ValueError("No non-empty price data supplied to the backtest engine")

        raw_signals = {symbol: strategy.generate_signals(df) for symbol, df in prepared.items()}
        # Shift by signal_lag_bars: the decision made using bar t's data is
        # only actionable starting bar t + signal_lag_bars.
        target_positions = {
            symbol: sig.shift(self.config.signal_lag_bars).fillna(0)
            for symbol, sig in raw_signals.items()
        }

        all_dates = sorted(set().union(*(df.index for df in prepared.values())))
        if start_date:
            all_dates = [d for d in all_dates if d.date() >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d.date() <= end_date]
        if not all_dates:
            raise ValueError("No trading dates fall within the requested backtest window")

        portfolio = Portfolio(initial_capital=self.config.initial_capital)
        risk = strategy.risk
        prior_day_equity = self.config.initial_capital
        exec_field = self.config.execution_price_field

        for current_ts in all_dates:
            current_date = current_ts.date()
            day_prices: dict[str, float] = {}
            for symbol, df in prepared.items():
                if current_ts in df.index:
                    day_prices[symbol] = float(df.loc[current_ts, "close"])

            for symbol, df in prepared.items():
                if current_ts not in df.index:
                    continue
                bar = df.loc[current_ts]
                position = portfolio.get_position(symbol)

                risk_exit_price, risk_exit_reason = self._check_risk_exits(
                    position, bar, risk
                )
                if risk_exit_reason is not None:
                    side = "SELL" if position.is_long else "BUY"
                    self.execution.execute(
                        portfolio,
                        symbol,
                        side,
                        risk_exit_price,
                        abs(position.quantity),
                        signal_date=current_date,
                        execution_date=current_date,
                        exit_reason=risk_exit_reason,
                    )
                    continue  # no signal-driven trade the same day a risk exit fires

                if position.is_open and position.is_long:
                    position.peak_price = max(position.peak_price, bar["high"])
                elif position.is_open and position.is_short:
                    position.peak_price = (
                        min(position.peak_price, bar["low"]) if position.peak_price else bar["low"]
                    )

                target_series = target_positions[symbol]
                target_dir = int(target_series.loc[current_ts]) if current_ts in target_series.index else 0
                self._apply_signal(
                    portfolio, symbol, target_dir, bar, risk, prior_day_equity,
                    day_prices, current_date, exec_field,
                )

            portfolio.record_equity(current_date, day_prices)
            prior_day_equity = portfolio.equity_history[-1]["total_value"]

        self._close_all_open_positions(portfolio, prepared, all_dates[-1].date())
        if portfolio.equity_history:
            prior_total = (
                portfolio.equity_history[-2]["total_value"]
                if len(portfolio.equity_history) > 1
                else portfolio.initial_capital
            )
            final_total = portfolio.cash
            portfolio.equity_history[-1] = {
                "date": all_dates[-1].date(),
                "cash": portfolio.cash,
                "holdings_value": 0.0,
                "total_value": final_total,
                "daily_return": (final_total / prior_total - 1) if prior_total else 0.0,
            }

        equity_df = pd.DataFrame(portfolio.equity_history)
        if not equity_df.empty:
            equity_df["cummax"] = equity_df["total_value"].cummax()
            equity_df["drawdown"] = equity_df["total_value"] / equity_df["cummax"] - 1
        trades_df = pd.DataFrame([t.__dict__ for t in portfolio.trades])

        warnings: list[str] = []
        if survivorship_biased:
            warnings.append(
                "SURVIVORSHIP-BIASED BACKTEST: universe membership was not "
                "reconstructed point-in-time; delisted/dropped constituents "
                "are absent from the simulated universe."
            )

        return BacktestResult(
            strategy_name=strategy.name,
            strategy_version=strategy.version,
            parameters=dict(strategy.params),
            universe=sorted(prepared.keys()),
            start_date=all_dates[0].date(),
            end_date=all_dates[-1].date(),
            config=self.config,
            portfolio=portfolio,
            equity_curve=equity_df,
            trades=trades_df,
            survivorship_biased=survivorship_biased,
            warnings=warnings,
        )

    @staticmethod
    def _check_risk_exits(position, bar, risk: RiskParams) -> tuple[float | None, str | None]:
        if not position.is_open:
            return None, None

        low, high = bar["low"], bar["high"]
        if position.is_long:
            if risk.stop_loss_pct is not None:
                stop_price = position.entry_price * (1 - risk.stop_loss_pct)
                if low <= stop_price:
                    return min(stop_price, high), "STOP_LOSS"
            if risk.take_profit_pct is not None:
                target_price = position.entry_price * (1 + risk.take_profit_pct)
                if high >= target_price:
                    return max(target_price, low), "TAKE_PROFIT"
            if risk.trailing_stop_pct is not None and position.peak_price:
                trail_price = position.peak_price * (1 - risk.trailing_stop_pct)
                if low <= trail_price:
                    return min(trail_price, high), "TRAILING_STOP"
        elif position.is_short:
            if risk.stop_loss_pct is not None:
                stop_price = position.entry_price * (1 + risk.stop_loss_pct)
                if high >= stop_price:
                    return max(stop_price, low), "STOP_LOSS"
            if risk.take_profit_pct is not None:
                target_price = position.entry_price * (1 - risk.take_profit_pct)
                if low <= target_price:
                    return min(target_price, high), "TAKE_PROFIT"
            if risk.trailing_stop_pct is not None and position.peak_price:
                trail_price = position.peak_price * (1 + risk.trailing_stop_pct)
                if high >= trail_price:
                    return max(trail_price, low), "TRAILING_STOP"
        return None, None

    def _apply_signal(
        self, portfolio, symbol, target_dir, bar, risk, prior_day_equity,
        day_prices, current_date, exec_field,
    ) -> None:
        position = portfolio.get_position(symbol)
        exec_price = float(bar[exec_field])

        already_holding_same_direction = position.quantity != 0 and (
            (position.quantity > 0) == (target_dir > 0) and target_dir != 0
        )
        if already_holding_same_direction:
            # Position already matches the target direction: hold as-is.
            # Re-sizing every bar off drifting mark-to-market equity would
            # generate spurious rebalancing trades for a strategy that just
            # wants to stay long/short, so sizing only happens on open,
            # close, or direction flip.
            return

        if target_dir == 0:
            target_qty = 0.0
        else:
            max_alloc = risk.max_position_pct * prior_day_equity
            if position.quantity == 0:
                invested = portfolio.invested_notional(day_prices)
                if prior_day_equity > 0 and (invested + max_alloc) / prior_day_equity > risk.max_portfolio_exposure_pct + 1e-9:
                    return  # opening this position would breach portfolio exposure limit
            shares = math.floor(max_alloc / exec_price) if exec_price > 0 else 0
            target_qty = float(shares) * (1 if target_dir > 0 else -1)

        delta = target_qty - position.quantity
        if abs(delta) < 1e-9:
            return

        side = "BUY" if delta > 0 else "SELL"
        self.execution.execute(
            portfolio, symbol, side, exec_price, abs(delta),
            signal_date=current_date, execution_date=current_date, exit_reason="SIGNAL",
        )

    def _close_all_open_positions(self, portfolio: Portfolio, prepared, as_of: date) -> None:
        for symbol, position in list(portfolio.positions.items()):
            if not position.is_open:
                continue
            df = prepared[symbol]
            last_ts = df.index[-1]
            price = float(df.loc[last_ts, "close"])
            side = "SELL" if position.is_long else "BUY"
            self.execution.execute(
                portfolio, symbol, side, price, abs(position.quantity),
                signal_date=as_of, execution_date=last_ts.date(), exit_reason="END_OF_BACKTEST",
            )
