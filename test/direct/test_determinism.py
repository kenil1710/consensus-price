"""FIX 3: two accepted outputs cannot change a quote.

test_consensus.py proves the rule in the abstract - that `_agrees` only accepts
pairs which store one identical value. These tests drive the whole
`request_price` path twice and compare what actually landed in storage, which is
the form the reviewer asked for: request ETH/USD twice, compare stored values.
"""

import pytest

from conftest import (TIER_A, mock_all, mock_page, mock_tier_a, quantized,
                      request)

SCALE = 10**18


@pytest.fixture
def open_oracle(oracle, direct_vm, direct_owner):
    """min_request_interval 0, so two requests can run back to back."""
    direct_vm.sender = direct_owner
    oracle.set_params(200, 1000, 900, 3, 0, 24)
    return oracle


def post(oracle, vm, sender, price, spread=0.0):
    vm.clear_mocks()
    mock_all(vm, price=price, spread=spread)
    return request(oracle, vm, sender)


def snapshot(rec):
    """Everything a downstream consumer can act on."""
    return (rec["price"], rec["confidence"], rec["bucket"], rec["quant_bps"])


def test_two_identical_requests_store_identical_values(open_oracle, direct_vm, direct_alice):
    post(open_oracle, direct_vm, direct_alice, 1877.60)
    first = snapshot(open_oracle.get_latest_price("ETH/USD"))

    post(open_oracle, direct_vm, direct_alice, 1877.60)
    second = snapshot(open_oracle.get_latest_price("ETH/USD"))

    assert first == second
    assert first[0] == quantized(1877.60)


def test_source_jitter_between_requests_does_not_move_the_quote(open_oracle, direct_vm, direct_alice):
    """The real case. Two requests seconds apart never see byte-identical source
    data; the sources drift and fan differently. Inside one bucket that must not
    reach storage, or every consumer re-quotes on noise."""
    post(open_oracle, direct_vm, direct_alice, 1877.60, spread=3.0)
    first = snapshot(open_oracle.get_latest_price("ETH/USD"))

    post(open_oracle, direct_vm, direct_alice, 1877.10, spread=2.5)
    second = snapshot(open_oracle.get_latest_price("ETH/USD"))

    assert first == second, "jitter inside one bucket changed the stored quote"
    assert open_oracle.get_latest_price("ETH/USD")["deviation_bps"] == 0


def test_a_leader_reporting_a_different_median_stores_the_same_price(open_oracle, direct_vm, direct_alice):
    """The reported hole, end to end. Two source sets whose medians differ by
    16 bps - the gap that used to pass on tolerance and store the leader's exact
    number - now produce byte-identical storage."""
    mock_tier_a(direct_vm, {sid: 1877.60 for sid in TIER_A})
    mock_page(direct_vm, page_price=1877.60)
    request(open_oracle, direct_vm, direct_alice)
    high = snapshot(open_oracle.get_latest_price("ETH/USD"))

    direct_vm.clear_mocks()
    mock_tier_a(direct_vm, {sid: 1876.10 for sid in TIER_A})
    mock_page(direct_vm, page_price=1876.10)
    request(open_oracle, direct_vm, direct_alice)
    low = snapshot(open_oracle.get_latest_price("ETH/USD"))

    assert high == low


def test_the_stored_price_is_never_a_source_value(open_oracle, direct_vm, direct_alice):
    """Storage holds the bucket midpoint. If any source's raw number could still
    reach storage the binding would be cosmetic."""
    mock_tier_a(direct_vm, {sid: 1877.60 for sid in TIER_A})
    mock_page(direct_vm, page_price=1877.60)
    request(open_oracle, direct_vm, direct_alice)

    rec = open_oracle.get_latest_price("ETH/USD")
    assert rec["price"] != 1877_600000000000000000
    assert rec["price"] == quantized(1877.60)
    # source_data is on the lattice too, so the record is self-consistent
    assert set(rec["sources"].values()) == {str(quantized(1877.60))}


def test_the_bucket_a_consumer_reads_back_is_the_bucket_consensus_agreed(open_oracle, direct_vm, direct_alice):
    post(open_oracle, direct_vm, direct_alice, 1877.60)
    rec = open_oracle.get_latest_price("ETH/USD")

    mod = __import__("sys").modules["_contract_ConsensusPrice"]
    step, idx = mod._bucket(mod._to_atto(1877.60), mod.DEF_QUANT_BPS)
    assert rec["bucket"] == "%d@%d" % (idx, step)
    assert rec["quant_bps"] == mod.DEF_QUANT_BPS
    # and the price sits inside the bucket it names
    assert idx * step <= rec["price"] < (idx + 1) * step


def test_a_real_move_still_moves_the_price(open_oracle, direct_vm, direct_alice):
    """Determinism must not mean deafness: a move larger than one bucket has to
    reach storage, or the oracle is just stale."""
    post(open_oracle, direct_vm, direct_alice, 1877.60)
    before = open_oracle.get_latest_price("ETH/USD")["price"]

    post(open_oracle, direct_vm, direct_alice, 1920.00)
    after = open_oracle.get_latest_price("ETH/USD")

    assert after["price"] > before
    assert after["price"] == quantized(1920.00)
    assert after["deviation_bps"] > 200


def test_repeated_requests_hold_one_quote_for_a_consumer(open_oracle, direct_vm, direct_alice):
    """Five requests across a sub-bucket drift: get_latest_price must answer with
    the same number every time, which is what makes it safe to price against."""
    seen = set()
    for p in (1877.60, 1877.10, 1878.40, 1876.90, 1879.20):
        post(open_oracle, direct_vm, direct_alice, p)
        rec = open_oracle.get_latest_price("ETH/USD")
        seen.add((rec["price"], rec["confidence"]))

    assert len(seen) == 1, "sub-bucket drift produced %d distinct quotes" % len(seen)
    assert open_oracle.get_price_checked("ETH/USD", 900, "HIGH")["price"] == quantized(1877.60)
