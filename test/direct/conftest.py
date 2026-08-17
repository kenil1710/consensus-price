"""Shared fixtures and source mocks for ConsensusPrice direct-mode tests."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "ConsensusPrice.py"
CONSUMER = ROOT / "contracts" / "PriceConsumer.py"

FEE = 10**15

# URL fragments the contract will actually request, per source id.
SOURCE_URL = {
    "binance": r"api\.binance\.com",
    "coinbase": r"api\.coinbase\.com",
    "gemini": r"api\.gemini\.com",
    "kucoin": r"api\.kucoin\.com",
    "coingecko": r"api\.coingecko\.com",
    "paprika": r"api\.coinpaprika\.com",
    "yahoo": r"finance\.yahoo\.com",
}

# Response shapes captured from the live endpoints during design.
def _binance(p, slug):
    return json.dumps({"symbol": "ETHUSDT", "price": "%.8f" % p})


def _coinbase(p, slug):
    return json.dumps({"data": {"amount": "%.2f" % p, "base": "ETH", "currency": "USD"}})


def _gemini(p, slug):
    return json.dumps({"bid": "%.5f" % p, "ask": "%.5f" % p, "last": "%.5f" % p})


def _kucoin(p, slug):
    return json.dumps({"code": "200000", "data": {"time": 1, "price": "%.2f" % p}})


def _coingecko(p, slug):
    return json.dumps({slug: {"usd": p}})


def _paprika(p, slug):
    return json.dumps({"id": slug, "quotes": {"USD": {"price": p, "volume_24h": 1.0}}})


SOURCE_BODY = {
    "binance": _binance,
    "coinbase": _coinbase,
    "gemini": _gemini,
    "kucoin": _kucoin,
    "coingecko": _coingecko,
    "paprika": _paprika,
}

TIER_A = ["binance", "coinbase", "gemini", "kucoin", "coingecko", "paprika"]

PAGE_TEMPLATE = (
    "Ethereum USD (ETH-USD)\nCCC - CoinMarketCap. Currency in USD\n"
    "{price}\n+12.40 (+0.66%)\nAs of 10:15AM UTC. Market open.\n"
    "Previous Close 1,870.00\nOpen 1,871.20\nDay's Range 1,860.11 - 1,890.45\n"
)


def allow_another_contract():
    """The SDK registers one contract class per process. Loading a second
    contract (or reloading the first) needs that guard cleared; each class keeps
    its own generated storage, so this only lifts the process-wide limit."""
    try:
        import genlayer.gl.genvm_contracts as gc
        gc.__known_contract__ = None
    except ImportError:
        pass  # SDK not on sys.path until the first deploy sets it up


@pytest.fixture
def oracle(direct_vm, direct_deploy, direct_owner):
    allow_another_contract()
    direct_vm.sender = direct_owner
    return direct_deploy(str(CONTRACT))


def contract_mod():
    """The loaded contract module - usable from any test that has deployed the
    oracle, including the cross-contract stack which has no `mod` fixture."""
    return sys.modules["_contract_ConsensusPrice"]


@pytest.fixture
def mod(oracle):
    """The loaded contract module, for testing the pure helpers directly."""
    return contract_mod()


def quantized(price):
    """The exact price the contract stores for a source fan mocked at `price`.

    Every source snaps to the same lattice point, so the median is that point.
    Tests assert against this rather than against the raw mock: the whole point
    of the consensus fix is that storage holds a bucket midpoint, not whatever
    number a source happened to return.
    """
    m = contract_mod()
    return m._quantize(m._to_atto(price), m.DEF_QUANT_BPS)


def mock_tier_a(vm, prices, slug="ethereum"):
    """Mock Tier A sources. `prices` maps source id -> float price, or -> an
    (status, body) tuple to simulate a specific failure. Omitted sources are
    left unmocked, which surfaces as a source failure just like a dead endpoint.
    """
    for sid, val in prices.items():
        if isinstance(val, tuple):
            status, body = val
        else:
            status, body = 200, SOURCE_BODY[sid](val, slug)
        vm.mock_web(SOURCE_URL[sid], {"status": status, "body": body})


def mock_page(vm, page_price=None, page_text=None, llm_reply=None):
    """Mock the yahoo page render plus the extraction prompt."""
    if page_text is None:
        page_text = PAGE_TEMPLATE.format(price="%.2f" % page_price)
    vm.mock_web(SOURCE_URL["yahoo"], {"status": 200, "body": page_text})
    if llm_reply is None:
        llm_reply = json.dumps({"price": "%.2f" % page_price})
    vm.mock_llm(r"untrusted_page_content", llm_reply)


def mock_all(vm, price=1882.0, spread=0.0, slug="ethereum", with_page=True):
    """Six Tier A sources fanned evenly around `price`, plus the page source."""
    prices = {}
    n = len(TIER_A)
    for i, sid in enumerate(TIER_A):
        offset = 0.0 if n == 1 else (spread * (i - (n - 1) / 2.0) / ((n - 1) / 2.0))
        prices[sid] = price + offset
    mock_tier_a(vm, prices, slug=slug)
    if with_page:
        mock_page(vm, page_price=price)
    return prices


def request(contract, vm, sender, pair="ETH/USD", value=FEE):
    vm.sender = sender
    vm.value = value
    return contract.request_price(pair)


def addr_hex(a):
    """Test addresses come through as raw bytes; normalize for comparison."""
    if isinstance(a, bytes):
        return "0x" + a.hex()
    return str(a)
