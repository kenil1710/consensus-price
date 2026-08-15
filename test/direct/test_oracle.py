"""End-to-end request_price flow, storage, reads and preflight reverts."""

import pytest

from conftest import FEE, TIER_A, addr_hex, mock_all, mock_tier_a, mock_page, request


def test_happy_path_stores_consensus_median(oracle, direct_vm, direct_alice):
    mock_all(direct_vm, price=1882.0, spread=6.0)
    pid = request(oracle, direct_vm, direct_alice)

    assert pid == "ETH/USD:1"
    rec = oracle.get_latest_price("ETH/USD")
    assert rec["found"] is True
    assert rec["pair"] == "ETH/USD"
    assert rec["decimals"] == 18
    # 6 Tier A + 1 page source all responded
    assert rec["n_sources"] == 7
    assert rec["n_attempted"] == 7
    # median of a symmetric fan sits on the centre
    assert abs(rec["price"] - 1882 * 10**18) < 2 * 10**18
    assert rec["confidence"] == "HIGH"
    assert rec["flags"] == "FIRST"
    assert rec["submitter"].lower() == addr_hex(direct_alice).lower()


def test_source_data_records_every_contributing_source(oracle, direct_vm, direct_alice):
    mock_all(direct_vm, price=1900.0)
    request(oracle, direct_vm, direct_alice)
    rec = oracle.get_latest_price("ETH/USD")
    assert set(rec["sources"].keys()) == set(TIER_A) | {"yahoo"}
    for v in rec["sources"].values():
        assert int(v) > 0


def test_median_is_not_moved_by_one_outlier(oracle, direct_vm, direct_alice):
    """The core anti-manipulation property: one wildly wrong source must not
    shift the stored price."""
    prices = {sid: 1880.0 for sid in TIER_A}
    prices["binance"] = 50000.0  # a single manipulated / broken venue
    mock_tier_a(direct_vm, prices)
    mock_page(direct_vm, page_price=1880.0)
    request(oracle, direct_vm, direct_alice)

    rec = oracle.get_latest_price("ETH/USD")
    assert abs(rec["price"] - 1880 * 10**18) < 10**18
    # but the disagreement is surfaced, not hidden
    assert rec["spread_bps"] > 20000
    assert rec["confidence"] in ("MEDIUM", "HIGH")


def test_partial_source_failure_still_produces_a_price(oracle, direct_vm, direct_alice):
    """Three sources down must not take the oracle down."""
    mock_tier_a(direct_vm, {
        "binance": 1881.0,
        "coinbase": (500, "upstream unavailable"),
        "gemini": 1883.0,
        "kucoin": (404, "not found"),
        "coingecko": 1882.0,
        # paprika deliberately unmocked -> behaves like a dead endpoint
    })
    mock_page(direct_vm, page_price=1882.0)
    request(oracle, direct_vm, direct_alice)

    rec = oracle.get_latest_price("ETH/USD")
    assert rec["n_sources"] == 4
    assert rec["n_attempted"] == 7
    assert abs(rec["price"] - 1882 * 10**18) < 2 * 10**18


def test_below_min_sources_reverts_as_transient(oracle, direct_vm, direct_alice):
    mock_tier_a(direct_vm, {"binance": 1881.0, "coinbase": 1882.0})
    with direct_vm.expect_revert("[TRANSIENT]"):
        request(oracle, direct_vm, direct_alice)
    # nothing partial was written
    assert oracle.get_latest_price("ETH/USD")["found"] is False


def test_underpayment_reverts_before_any_fetch(oracle, direct_vm, direct_alice):
    with direct_vm.expect_revert("[EXPECTED]"):
        request(oracle, direct_vm, direct_alice, value=FEE - 1)


def test_paused_reverts(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_paused(True)
    mock_all(direct_vm)
    with direct_vm.expect_revert("paused"):
        request(oracle, direct_vm, direct_alice)


def test_repeat_request_inside_interval_reverts(oracle, direct_vm, direct_alice):
    mock_all(direct_vm)
    request(oracle, direct_vm, direct_alice)
    with direct_vm.expect_revert("fresh"):
        request(oracle, direct_vm, direct_alice)


def test_pair_with_no_slug_skips_aggregator_sources(oracle, direct_vm, direct_alice):
    """Exchange sources derive symbols mechanically, so an unregistered pair
    still works - the two slug-dependent aggregators simply drop out."""
    mock_tier_a(direct_vm, {
        "binance": 42.0, "coinbase": 42.1, "gemini": 41.9, "kucoin": 42.05,
    })
    mock_page(direct_vm, page_price=42.0)
    request(oracle, direct_vm, direct_alice, pair="AVAX/USD")

    rec = oracle.get_latest_price("AVAX/USD")
    assert rec["found"] is True
    assert rec["n_attempted"] == 5  # 4 exchanges + page; no coingecko/paprika
    assert "coingecko" not in rec["sources"]


def test_supported_pairs_and_stats(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_params(200, 1000, 900, 3, 0, 24)  # interval 0 for back-to-back
    mock_all(direct_vm)
    request(oracle, direct_vm, direct_alice)
    direct_vm.clear_mocks()
    mock_all(direct_vm, price=61000.0, slug="bitcoin")
    request(oracle, direct_vm, direct_alice, pair="BTC/USD")

    assert oracle.get_supported_pairs() == ["ETH/USD", "BTC/USD"]
    stats = oracle.get_stats()
    assert stats["total_requests"] == 2
    assert stats["unique_pairs"] == 2
    assert stats["total_fees_wei"] == 2 * FEE


def test_history_ring_buffer_wraps_and_stays_newest_first(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_params(200, 10000, 900, 3, 0, 4)  # depth 4, volatility off
    for i in range(6):
        direct_vm.clear_mocks()
        mock_all(direct_vm, price=1000.0 + i)
        request(oracle, direct_vm, direct_alice)

    hist = oracle.get_price_history("ETH/USD", 0)
    assert len(hist) == 4  # capped at max_history
    seqs = [h["price_id"] for h in hist]
    assert seqs == ["ETH/USD:6", "ETH/USD:5", "ETH/USD:4", "ETH/USD:3"]
    assert hist[0]["price"] > hist[1]["price"] > hist[2]["price"]


def test_get_price_scaled_matches_decimals(oracle, direct_vm, direct_alice):
    mock_all(direct_vm, price=1882.0)
    request(oracle, direct_vm, direct_alice)

    assert oracle.decimals() == 18
    raw = oracle.get_latest_price("ETH/USD")["price"]
    assert oracle.get_price_scaled("ETH/USD", 18) == raw
    assert oracle.get_price_scaled("ETH/USD", 8) == raw // 10**10
    assert oracle.get_price_scaled("ETH/USD", 0) == raw // 10**18


def test_unknown_pair_reads_are_safe(oracle):
    assert oracle.get_latest_price("DOGE/USD")["found"] is False
    assert oracle.get_price_history("DOGE/USD", 5) == []
    assert oracle.is_stale("DOGE/USD") is True
