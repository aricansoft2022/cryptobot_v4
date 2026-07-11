"""Tests for fill aggregation into RealizedEntry and realized PnL."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cryptobot.exchange.fills import Fill, aggregate_entry, realized_pnl


def test_aggregate_multiple_fills_weighted_average():
    fills = [Fill(Decimal("100"), Decimal("0.6")), Fill(Decimal("102"), Decimal("0.4"))]
    entry = aggregate_entry(fills, "BTC", "USDT")
    assert entry.filled_base_qty == Decimal("1.0")
    assert entry.true_entry_cost == Decimal("100.8")
    assert entry.avg_entry_price == Decimal("100.8")
    assert entry.entry_fees_quote == Decimal("0")
    assert entry.sellable_base_qty == Decimal("1.0")


def test_quote_commission_adds_to_fees_only():
    fills = [Fill(Decimal("100"), Decimal("1"), Decimal("0.1"), "USDT")]
    entry = aggregate_entry(fills, "BTC", "USDT")
    assert entry.entry_fees_quote == Decimal("0.1")
    assert entry.sellable_base_qty == Decimal("1")
    assert entry.invested_quote_cost == Decimal("100.1")


def test_base_commission_reduces_sellable_and_values_fee_at_avg():
    fills = [
        Fill(Decimal("100"), Decimal("0.6"), Decimal("0.0006"), "BTC"),
        Fill(Decimal("102"), Decimal("0.4"), Decimal("0.0004"), "BTC"),
    ]
    entry = aggregate_entry(fills, "BTC", "USDT")
    # base commission total 0.001 -> sellable 0.999; fee = 0.001 * avg(100.8)
    assert entry.sellable_base_qty == Decimal("0.999")
    assert entry.entry_fees_quote == Decimal("0.001") * Decimal("100.8")


def test_bnb_commission_requires_conversion_rate():
    fills = [Fill(Decimal("100"), Decimal("1"), Decimal("0.01"), "BNB")]
    with pytest.raises(ValueError):
        aggregate_entry(fills, "BTC", "USDT")
    entry = aggregate_entry(fills, "BTC", "USDT", commission_rates={"BNB": Decimal("500")})
    assert entry.entry_fees_quote == Decimal("5")  # 0.01 * 500


def test_empty_fills_raise():
    with pytest.raises(ValueError):
        aggregate_entry([], "BTC", "USDT")


def test_realized_pnl_from_real_fills():
    entry = aggregate_entry([Fill(Decimal("100"), Decimal("1"))], "BTC", "USDT")
    sell = [Fill(Decimal("110"), Decimal("1"), Decimal("0.11"), "USDT")]
    pnl = realized_pnl(entry, sell, "BTC", "USDT")
    assert pnl.gross_proceeds == Decimal("110")
    assert pnl.exit_fees_quote == Decimal("0.11")
    # net = 110 - 0.11 - invested(100) = 9.89
    assert pnl.net_pnl == Decimal("9.89")


def test_realized_slippage_vs_estimate():
    entry = aggregate_entry([Fill(Decimal("100"), Decimal("1"))], "BTC", "USDT")
    sell = [Fill(Decimal("105"), Decimal("1"))]
    pnl = realized_pnl(entry, sell, "BTC", "USDT")  # net = 5
    # Realized worse than an optimistic estimate of 7 -> negative slippage.
    assert pnl.slippage_vs_estimate(Decimal("7")) == Decimal("-2")
