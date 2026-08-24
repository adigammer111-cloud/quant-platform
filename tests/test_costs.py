from __future__ import annotations

import pytest

from backtesting.costs import TransactionCostModel


def test_buy_costs_include_stamp_duty_sell_does_not():
    model = TransactionCostModel()
    buy = model.compute_costs("BUY", price=100.0, quantity=10)
    sell = model.compute_costs("SELL", price=100.0, quantity=10)
    assert buy.stamp_duty > 0
    assert sell.stamp_duty == 0


def test_stt_applies_both_sides():
    model = TransactionCostModel()
    buy = model.compute_costs("BUY", price=100.0, quantity=10)
    sell = model.compute_costs("SELL", price=100.0, quantity=10)
    assert buy.stt == pytest.approx(1000 * model.stt_pct_buy)
    assert sell.stt == pytest.approx(1000 * model.stt_pct_sell)


def test_brokerage_flat_cap_applied():
    model = TransactionCostModel(brokerage_pct=0.01, brokerage_flat_cap=20.0)
    # 1% of a 100,000 turnover would be 1000, way above the 20 cap.
    costs = model.compute_costs("BUY", price=1000.0, quantity=100)
    assert costs.brokerage == 20.0


def test_gst_applies_only_to_brokerage_exchange_sebi():
    model = TransactionCostModel(
        brokerage_pct=0.001, brokerage_flat_cap=None,
        exchange_txn_pct=0.0001, sebi_fee_pct=0.00001,
        stt_pct_buy=0.001, stamp_duty_pct_buy=0.0002, gst_pct=0.18,
    )
    costs = model.compute_costs("BUY", price=100.0, quantity=10)
    expected_gst_base = costs.brokerage + costs.exchange_txn_charge + costs.sebi_fee
    assert costs.gst == pytest.approx(expected_gst_base * 0.18)
    # STT and stamp duty must NOT be part of the GST base.
    assert costs.gst < (costs.brokerage + costs.exchange_txn_charge + costs.sebi_fee + costs.stt) * 0.18


def test_slippage_direction():
    model = TransactionCostModel(slippage_bps=100.0)  # 1%
    buy_price = model.apply_slippage("BUY", 100.0)
    sell_price = model.apply_slippage("SELL", 100.0)
    assert buy_price == pytest.approx(101.0)
    assert sell_price == pytest.approx(99.0)


def test_zero_cost_model_is_actually_zero():
    model = TransactionCostModel(
        brokerage_pct=0, brokerage_flat_cap=0, stt_pct_buy=0, stt_pct_sell=0,
        exchange_txn_pct=0, sebi_fee_pct=0, stamp_duty_pct_buy=0, gst_pct=0, slippage_bps=0,
    )
    costs = model.compute_costs("BUY", price=100.0, quantity=10)
    assert costs.total == 0.0
    assert model.apply_slippage("BUY", 100.0) == 100.0


def test_total_sums_all_components():
    model = TransactionCostModel()
    costs = model.compute_costs("BUY", price=250.0, quantity=40)
    assert costs.total == pytest.approx(
        costs.brokerage + costs.stt + costs.exchange_txn_charge
        + costs.sebi_fee + costs.stamp_duty + costs.gst
    )
