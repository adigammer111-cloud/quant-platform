"""Transaction cost model for Indian equity delivery trades.

All default rates are illustrative approximations of publicly documented
NSE/SEBI charges and typical discount-broker pricing as of early 2025. They
are NOT guaranteed to be current - brokerage plans, STT, exchange charges,
SEBI fees, stamp duty, and GST all change via regulatory circulars and
broker pricing updates. Every field is a constructor argument specifically
so a user can override them with today's actual rates rather than trusting
a hard-coded assumption. Nothing here is investment or tax advice.

Cost components modeled (delivery/CNC equity trades on NSE):
- Brokerage: `min(brokerage_pct * turnover, brokerage_flat_cap)` if a flat
  cap is set (0 disables brokerage entirely, e.g. many brokers today offer
  zero-brokerage delivery trading).
- STT (Securities Transaction Tax): charged on both buy and sell for
  delivery equity.
- Exchange transaction charges: NSE turnover charge.
- SEBI turnover fee.
- Stamp duty: buy-side only, state-level but centrally capped for demat
  delivery trades.
- GST: 18% on (brokerage + exchange transaction charges + SEBI fee) only -
  NOT applied to STT or stamp duty.
- Slippage: modeled separately (see `apply_slippage`), not a regulatory
  charge but a realistic execution-cost assumption.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class CostBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange_txn_charge: float
    sebi_fee: float
    stamp_duty: float
    gst: float

    @property
    def total(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_txn_charge
            + self.sebi_fee
            + self.stamp_duty
            + self.gst
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        return d


@dataclass
class TransactionCostModel:
    brokerage_pct: float = 0.0            # e.g. 0.0003 = 0.03% of turnover
    brokerage_flat_cap: float = 20.0       # per-order cap in INR; 0 = no brokerage at all, None = uncapped
    stt_pct_buy: float = 0.001            # 0.1% delivery buy-side STT
    stt_pct_sell: float = 0.001           # 0.1% delivery sell-side STT
    exchange_txn_pct: float = 0.0000345   # NSE transaction charge (approx)
    sebi_fee_pct: float = 0.000001        # SEBI turnover fee (₹10 per crore)
    stamp_duty_pct_buy: float = 0.00015   # 0.015% buy-side only, capped by state rules
    gst_pct: float = 0.18                 # applied to brokerage + exchange charge + SEBI fee
    slippage_bps: float = 5.0             # basis points, applied against execution price

    def compute_costs(self, side: Side, price: float, quantity: float) -> CostBreakdown:
        turnover = price * quantity

        brokerage = turnover * self.brokerage_pct
        if self.brokerage_flat_cap is not None:
            brokerage = min(brokerage, self.brokerage_flat_cap)

        stt = turnover * (self.stt_pct_buy if side == "BUY" else self.stt_pct_sell)
        exchange_txn_charge = turnover * self.exchange_txn_pct
        sebi_fee = turnover * self.sebi_fee_pct
        stamp_duty = turnover * self.stamp_duty_pct_buy if side == "BUY" else 0.0
        gst = (brokerage + exchange_txn_charge + sebi_fee) * self.gst_pct

        return CostBreakdown(
            turnover=turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charge=exchange_txn_charge,
            sebi_fee=sebi_fee,
            stamp_duty=stamp_duty,
            gst=gst,
        )

    def apply_slippage(self, side: Side, price: float) -> float:
        """Slippage always works against the trader: buys fill higher,
        sells fill lower."""
        factor = self.slippage_bps / 10_000.0
        if side == "BUY":
            return price * (1 + factor)
        return price * (1 - factor)

    def to_dict(self) -> dict:
        return asdict(self)
