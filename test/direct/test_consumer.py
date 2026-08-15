"""Cross-contract composability: PriceConsumer reading ConsensusPrice.

Direct mode allocates every contract at the same root storage slot, so two
contracts cannot share one VM context. The oracle therefore gets its own
VMContext and a call hook swaps to it for the duration of a cross-contract read.
Calldata still round-trips through the real encoder, so this exercises the
genuine CallContract path rather than a plain Python method call.
"""

import pytest

from conftest import (CONSUMER, CONTRACT, FEE, allow_another_contract,
                      mock_all, mock_page, mock_tier_a)

SCALE = 10**18
ORACLE_ADDR = "0x" + "ab" * 20


class Stack:
    """A consumer in one VM, an oracle in another, wired by a call hook."""

    def __init__(self, oracle, oracle_vm, consumer, consumer_vm):
        self.oracle = oracle
        self.oracle_vm = oracle_vm
        self.consumer = consumer
        self.vm = consumer_vm

    def warp(self, ts):
        self.oracle_vm.warp(ts)
        self.vm.warp(ts)

    def post(self, sender, price=1882.0, pair="ETH/USD", scatter=None):
        """Drive a real request_price on the oracle, in the oracle's VM."""
        from gltest.direct import wasi_mock
        saved = _swap(self.oracle_vm)
        try:
            self.oracle_vm.clear_mocks()
            if scatter is None:
                mock_all(self.oracle_vm, price=price)
            else:
                mock_tier_a(self.oracle_vm, scatter)
                mock_page(self.oracle_vm, page_price=price)
            self.oracle_vm.sender = sender
            self.oracle_vm.value = FEE
            return self.oracle.request_price(pair)
        finally:
            _restore(saved)

    def read(self, fn, *args):
        from gltest.direct import wasi_mock
        saved = _swap(self.oracle_vm)
        try:
            return getattr(self.oracle, fn)(*args)
        finally:
            _restore(saved)


def _swap(vm):
    """Switch the active VM, preserving the caller's fd bookkeeping."""
    from gltest.direct import wasi_mock
    local = wasi_mock._local
    saved = (getattr(local, "vm", None),
             getattr(local, "fd_buffers", {}),
             getattr(local, "fd_counter", 100))
    wasi_mock.set_vm(vm)
    return saved


def _restore(saved):
    from gltest.direct import wasi_mock
    local = wasi_mock._local
    local.vm, local.fd_buffers, local.fd_counter = saved


@pytest.fixture
def stack(direct_vm, direct_owner, direct_alice):
    from gltest.direct.vm import VMContext
    from gltest.direct.loader import deploy_contract

    # --- oracle in its own context
    ovm = VMContext()
    ovm.sender = direct_owner
    saved = _swap(ovm)
    try:
        allow_another_contract()
        oracle = deploy_contract(CONTRACT, ovm)
        oracle.set_params(200, 1000, 900, 3, 0, 24)  # no rate limit in tests
    finally:
        _restore(saved)

    # --- consumer in the fixture context, reading the oracle through the hook
    def hook(_vm, req):
        cc = req.get("CallContract")
        if cc is None:
            return None
        from genlayer.py import calldata  # on sys.path once a contract loaded

        cd = cc.get("calldata", {})
        inner = _swap(ovm)
        try:
            result = getattr(oracle, cd["method"])(*list(cd.get("args", [])))
            return bytes([0]) + calldata.encode(result)      # ResultCode.RETURN
        except Exception as e:
            msg = getattr(e, "message", None) or str(e)
            return bytes([1]) + str(msg).encode("utf-8")     # ResultCode.USER_ERROR
        finally:
            _restore(inner)

    direct_vm._gl_call_hook = hook
    allow_another_contract()
    consumer = deploy_contract(CONSUMER, direct_vm, ORACLE_ADDR, 900, "MEDIUM")
    return Stack(oracle, ovm, consumer, direct_vm)


def test_consumer_reads_price_across_contracts(stack, direct_alice):
    stack.post(direct_alice, price=2000.0)

    out = stack.consumer.quote("ETH/USD", 3 * SCALE)
    assert out["pair"] == "ETH/USD"
    # 3 ETH at ~$2000 = ~$6000, carried at 18 decimals
    assert abs(out["value_usd_atto"] - 6000 * SCALE) < 5 * SCALE
    assert out["confidence"] in ("HIGH", "MEDIUM")
    assert out["price"] > 0


def test_consumer_config_points_at_the_oracle(stack):
    cfg = stack.consumer.get_config()
    assert cfg["oracle"].lower() == ORACLE_ADDR
    assert cfg["max_age_seconds"] == 900
    assert cfg["min_confidence"] == "MEDIUM"


def test_consumer_refuses_a_stale_price(stack, direct_alice):
    """The point of get_price_checked: a consumer cannot silently act on a bad
    number, because the oracle refuses to hand one over."""
    stack.warp("2026-06-01T12:00:00Z")
    stack.post(direct_alice, price=2000.0)
    assert stack.consumer.quote("ETH/USD", SCALE)["value_usd_atto"] > 0

    stack.warp("2026-06-01T13:00:00Z")  # an hour on, past the 900s window
    with stack.vm.expect_revert("stale"):
        stack.consumer.quote("ETH/USD", SCALE)


def test_consumer_refuses_a_low_confidence_price(stack, direct_alice):
    stack.post(direct_alice, price=1000.0,
               scatter={"binance": 1000.0, "coinbase": 2000.0, "gemini": 500.0})
    assert stack.read("get_latest_price", "ETH/USD")["confidence"] == "LOW"

    with stack.vm.expect_revert("confidence"):
        stack.consumer.quote("ETH/USD", SCALE)


def test_consumer_refuses_an_unknown_pair(stack):
    with stack.vm.expect_revert("no price"):
        stack.consumer.quote("DOGE/USD", SCALE)


def test_graceful_degradation_reports_a_reason(stack, direct_alice):
    """is_safe_to_trade is the non-reverting variant, for callers that want to
    degrade rather than fail."""
    out = stack.consumer.is_safe_to_trade("DOGE/USD")
    assert out["safe"] is False and "no price" in out["reason"]

    stack.post(direct_alice, price=2000.0)
    out = stack.consumer.is_safe_to_trade("ETH/USD")
    assert out["safe"] is True
    assert abs(out["price"] - 2000 * SCALE) < 5 * SCALE


def test_graceful_degradation_flags_volatility(stack, direct_alice):
    stack.post(direct_alice, price=2000.0)
    stack.post(direct_alice, price=1000.0)  # -50%
    assert stack.read("get_latest_price", "ETH/USD")["flags"] == "HIGH_VOLATILITY"

    out = stack.consumer.is_safe_to_trade("ETH/USD")
    assert out["safe"] is False
    assert "volatility" in out["reason"]


def test_graceful_degradation_flags_staleness(stack, direct_alice):
    stack.warp("2026-06-01T12:00:00Z")
    stack.post(direct_alice, price=2000.0)
    stack.warp("2026-06-01T14:00:00Z")
    out = stack.consumer.is_safe_to_trade("ETH/USD")
    assert out["safe"] is False and "stale" in out["reason"]


def test_consumer_twap_read(stack, direct_alice):
    stack.warp("2026-06-01T12:00:00Z")
    stack.post(direct_alice, price=1000.0)
    stack.warp("2026-06-01T13:00:00Z")
    stack.post(direct_alice, price=2000.0)
    stack.warp("2026-06-01T13:01:00Z")

    out = stack.consumer.twap_quote("ETH/USD", 10)
    assert out["samples"] == 2
    assert out["twap"] < 1100 * SCALE  # time-weighted, not a simple mean

    with stack.vm.expect_revert("no history"):
        stack.consumer.twap_quote("DOGE/USD", 10)


def test_consumer_write_path_settles_against_the_oracle(stack, direct_alice):
    stack.post(direct_alice, price=2000.0)
    stack.vm.sender = direct_alice

    value = stack.consumer.record_quote("ETH/USD", 2 * SCALE)
    assert abs(value - 4000 * SCALE) < 5 * SCALE
    cfg = stack.consumer.get_config()
    assert cfg["quote_count"] == 1
    assert cfg["last_value_atto"] == value


def test_oracle_needs_no_transaction_to_be_read(stack, direct_alice):
    """Reads are free: many consumer calls, no further oracle requests."""
    stack.post(direct_alice, price=2000.0)
    before = stack.read("get_stats")["total_requests"]
    for _ in range(5):
        stack.consumer.quote("ETH/USD", SCALE)
        stack.consumer.is_safe_to_trade("ETH/USD")
    assert stack.read("get_stats")["total_requests"] == before
