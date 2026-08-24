"""Order execution simulator: turns a desired trade (symbol, side, quantity,
raw market price) into a filled `Trade`, applying slippage and transaction
costs, and mutates the portfolio's cash/position accordingly.

This module is purely mechanical - it does not decide *whether* to trade
(that's the engine's job via signals + risk rules) or *what size* to trade
(also the engine, via position sizing). It only answers "given this order,
what actually happens to cash and the position."
"""
from __future__ import annotations

from datetime import date

from backtesting.costs import TransactionCostModel
from backtesting.orders import Trade
from backtesting.portfolio import Portfolio


class ExecutionSimulator:
    def __init__(self, cost_model: TransactionCostModel):
        self.cost_model = cost_model

    def execute(
        self,
        portfolio: Portfolio,
        symbol: str,
        side: str,
        raw_price: float,
        quantity: float,
        signal_date: date,
        execution_date: date,
        exit_reason: str | None = None,
    ) -> Trade:
        """`quantity` is always positive. BUY increases the position
        (opening/adding to long, or covering a short); SELL decreases it
        (closing/trimming a long, or opening/adding to a short)."""
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")

        fill_price = self.cost_model.apply_slippage(side, raw_price)
        breakdown = self.cost_model.compute_costs(side, fill_price, quantity)
        gross = fill_price * quantity

        position = portfolio.get_position(symbol)
        prior_qty = position.quantity

        if side == "BUY":
            portfolio.cash -= gross + breakdown.total
            new_qty = prior_qty + quantity
        elif side == "SELL":
            portfolio.cash += gross - breakdown.total
            new_qty = prior_qty - quantity
        else:
            raise ValueError(f"side must be BUY or SELL, got {side}")

        realized_pnl, holding_days = self._update_position_and_pnl(
            position, prior_qty, new_qty, fill_price, execution_date
        )

        net_amount = (gross - breakdown.total) if side == "SELL" else -(gross + breakdown.total)
        trade = Trade(
            symbol=symbol,
            side=side,
            signal_date=signal_date,
            execution_date=execution_date,
            execution_price=fill_price,
            quantity=quantity,
            gross_amount=gross,
            costs=breakdown.total,
            net_amount=net_amount,
            realized_pnl=realized_pnl,
            holding_period_days=holding_days,
            exit_reason=exit_reason,
        )
        portfolio.trades.append(trade)
        return trade

    @staticmethod
    def _update_position_and_pnl(position, prior_qty, new_qty, fill_price, execution_date):
        realized_pnl = None
        holding_days = None

        was_long_or_short = prior_qty != 0
        direction_flipped = was_long_or_short and (prior_qty > 0) != (new_qty > 0) and new_qty != 0
        fully_closing = was_long_or_short and new_qty == 0
        reducing = was_long_or_short and abs(new_qty) < abs(prior_qty) and not direction_flipped

        if fully_closing or reducing or direction_flipped:
            closed_qty = abs(prior_qty) - abs(new_qty) if not direction_flipped else abs(prior_qty)
            sign = 1 if prior_qty > 0 else -1
            realized_pnl = (fill_price - position.entry_price) * closed_qty * sign
            if position.entry_date:
                holding_days = (execution_date - position.entry_date).days

        if new_qty == 0:
            position.quantity = 0.0
            position.entry_price = 0.0
            position.entry_date = None
            position.peak_price = 0.0
        elif prior_qty == 0 or direction_flipped:
            # Opening a fresh position (possibly after flipping direction).
            position.quantity = new_qty
            position.entry_price = fill_price
            position.entry_date = execution_date
            position.peak_price = fill_price
        else:
            # Adding to an existing position: blend the average entry price.
            total_cost_basis = position.entry_price * abs(prior_qty) + fill_price * abs(
                new_qty - prior_qty
            )
            position.quantity = new_qty
            position.entry_price = total_cost_basis / abs(new_qty)
            # entry_date / peak_price unchanged when adding to a position

        return realized_pnl, holding_days
