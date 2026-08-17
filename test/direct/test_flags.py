"""Volatility flagging, staleness and the checked/TWAP consumer reads."""

import pytest

from conftest import TIER_A, mock_all, mock_tier_a, mock_page, quantized, request

SCALE = 10**18


@pytest.fixture
def open_oracle(oracle, direct_vm, direct_owner):
    """No rate limit, so a test can post several prices in sequence."""
    direct_vm.sender = direct_owner
    oracle.set_params(200, 1000, 900, 3, 0, 24)
    return oracle


def post(oracle, direct_vm, sender, price, pair="ETH/USD"):
    direct_vm.clear_mocks()
    mock_all(direct_vm, price=price)
    return request(oracle, direct_vm, sender, pair=pair)


def test_first_record_is_flagged_first(open_oracle, direct_vm, direct_alice):
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    rec = open_oracle.get_latest_price("ETH/USD")
    assert rec["flags"] == "FIRST"
    assert rec["deviation_bps"] == 0


def test_calm_move_is_not_flagged(open_oracle, direct_vm, direct_alice):
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    post(open_oracle, direct_vm, direct_alice, 1050.0)  # +5%
    rec = open_oracle.get_latest_price("ETH/USD")
    assert rec["flags"] == ""
    assert 490 <= rec["deviation_bps"] <= 510


def test_flash_move_is_flagged_but_still_stored(open_oracle, direct_vm, direct_alice):
    """A flash crash is real data. Flag it; refusing it would make the oracle lie
    during exactly the events it exists for."""
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    post(open_oracle, direct_vm, direct_alice, 700.0)  # -30%
    rec = open_oracle.get_latest_price("ETH/USD")
    assert rec["flags"] == "HIGH_VOLATILITY"
    assert 2990 <= rec["deviation_bps"] <= 3010
    assert rec["price"] == quantized(700.0)  # stored, not rejected


def test_volatility_threshold_is_configurable(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_params(200, 200, 900, 3, 0, 24)  # flag anything over 2%
    post(oracle, direct_vm, direct_alice, 1000.0)
    post(oracle, direct_vm, direct_alice, 1050.0)
    assert oracle.get_latest_price("ETH/USD")["flags"] == "HIGH_VOLATILITY"


def test_staleness_tracks_the_clock(open_oracle, direct_vm, direct_alice):
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    assert open_oracle.is_stale("ETH/USD") is False
    assert open_oracle.get_latest_price("ETH/USD")["is_stale"] is False

    direct_vm.warp("2026-06-01T12:10:00Z")  # +600s, under the 900s window
    assert open_oracle.is_stale("ETH/USD") is False

    direct_vm.warp("2026-06-01T12:20:00Z")  # +1200s, past it
    assert open_oracle.is_stale("ETH/USD") is True
    rec = open_oracle.get_latest_price("ETH/USD")
    assert rec["is_stale"] is True
    assert rec["age_seconds"] >= 1200


def test_get_price_checked_passes_a_good_price(open_oracle, direct_vm, direct_alice):
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    out = open_oracle.get_price_checked("ETH/USD", 900, "MEDIUM")
    assert out["found"] is True
    assert out["price"] == quantized(1000.0)


def test_get_price_checked_reverts_when_stale(open_oracle, direct_vm, direct_alice):
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    direct_vm.warp("2026-06-01T13:00:00Z")
    with direct_vm.expect_revert("stale"):
        open_oracle.get_price_checked("ETH/USD", 900, "MEDIUM")


def test_get_price_checked_reverts_below_required_confidence(open_oracle, direct_vm, direct_alice):
    direct_vm.clear_mocks()
    # sources scattered far apart -> LOW confidence
    mock_tier_a(direct_vm, {"binance": 1000.0, "coinbase": 2000.0, "gemini": 500.0})
    mock_page(direct_vm, page_price=1000.0)
    request(open_oracle, direct_vm, direct_alice)
    assert open_oracle.get_latest_price("ETH/USD")["confidence"] == "LOW"

    with direct_vm.expect_revert("confidence"):
        open_oracle.get_price_checked("ETH/USD", 0, "HIGH")
    # but a consumer willing to accept LOW can still read it
    assert open_oracle.get_price_checked("ETH/USD", 0, "LOW")["found"] is True


def test_get_price_checked_reverts_on_unknown_pair(open_oracle, direct_vm):
    with direct_vm.expect_revert("no price"):
        open_oracle.get_price_checked("DOGE/USD", 900, "LOW")


def test_get_price_checked_ignores_age_when_max_age_is_zero(open_oracle, direct_vm, direct_alice):
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    direct_vm.warp("2026-06-05T12:00:00Z")
    assert open_oracle.get_price_checked("ETH/USD", 0, "LOW")["found"] is True


def test_twap_weights_by_time_not_sample_count(open_oracle, direct_vm, direct_alice):
    """A price that stood for an hour must outweigh one that stood for a minute."""
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(open_oracle, direct_vm, direct_alice, 1000.0)
    direct_vm.warp("2026-06-01T13:00:00Z")   # 1000 stood for 3600s
    post(open_oracle, direct_vm, direct_alice, 2000.0)
    direct_vm.warp("2026-06-01T13:01:00Z")   # 2000 stood for 60s

    out = open_oracle.get_twap("ETH/USD", 10)
    assert out["samples"] == 2
    assert out["window_seconds"] == 3660
    # simple mean would be 1500; time weighting must land far nearer 1000
    assert out["twap"] < 1100 * SCALE
    expected = (quantized(1000.0) * 3600 + quantized(2000.0) * 60) // 3660
    assert out["twap"] == expected


def test_twap_on_unknown_pair_is_safe(open_oracle):
    assert open_oracle.get_twap("DOGE/USD", 5)["found"] is False
