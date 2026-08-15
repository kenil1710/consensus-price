"""Pair normalization, symbol whitelisting and URL template substitution."""

import pytest


def test_sub_replaces_all_occurrences(mod):
    assert mod._sub("{A}/{A}", "{A}", "X") == "X/X"
    assert mod._sub("no token here", "{A}", "X") == "no token here"
    assert mod._sub("{BASE}-{QUOTE}", "{BASE}", "ETH") == "ETH-{QUOTE}"


def test_strip_removes_every_occurrence(mod):
    assert mod._strip("1,234,567", ",") == "1234567"
    assert mod._strip("<a><b>", "<") == "a>b>"


@pytest.mark.parametrize("raw,expected", [
    ("ETH/USD", "ETH/USD"),
    ("eth/usd", "ETH/USD"),
    ("  eth / usd  ", "ETH/USD"),
    ("BtC/UsD", "BTC/USD"),
])
def test_norm_pair_normalizes(mod, raw, expected):
    assert mod._norm_pair(raw) == expected


@pytest.mark.parametrize("raw", [
    "ETHUSD",           # no separator
    "ETH/USD/EUR",      # too many parts
    "/USD",             # empty base
    "ETH/",             # empty quote
    "ETH USD",          # no separator
    "",
])
def test_norm_pair_rejects_malformed(mod, raw):
    with pytest.raises(Exception):
        mod._norm_pair(raw)


@pytest.mark.parametrize("raw", [
    "ETH/US D",
    "ET-H/USD",
    "ETH/US;D",
    "../../etc/USD",
    "ETH/USD?x=1",
    "VERYLONGSYMBOL1/USD",
])
def test_norm_pair_refuses_url_unsafe_symbols(mod, raw):
    """Symbols are interpolated straight into source URLs, so this is the
    injection boundary, not just input hygiene."""
    with pytest.raises(Exception):
        mod._norm_pair(raw)


def test_sym_ok_bounds(mod):
    assert mod._sym_ok("E") is True
    assert mod._sym_ok("A" * 12) is True
    assert mod._sym_ok("A" * 13) is False
    assert mod._sym_ok("") is False
    assert mod._sym_ok("ET H") is False


def test_resolved_urls_are_well_formed(oracle, mod):
    """Every enabled source must produce a usable https URL for a mapped pair."""
    tasks = oracle._resolve("ETH/USD") if hasattr(oracle, "_resolve") else None
    if tasks is None:
        pytest.skip("internal method not exposed through the proxy")
    ids = {t["id"] for t in tasks}
    assert "binance" in ids and "coingecko" in ids
    for t in tasks:
        assert t["url"].startswith("https://")
        assert "{" not in t["url"], t["url"]


def test_quote_alias_maps_usd_to_usdt(oracle, direct_vm, direct_alice):
    """Venues with no USD book are quoted in USDT; the contract must request the
    aliased symbol, not a pair that does not exist."""
    seen = {}

    def capture(pattern, price):
        return None

    from conftest import mock_tier_a, mock_page, request
    mock_tier_a(direct_vm, {"binance": 1880.0, "coinbase": 1881.0,
                            "gemini": 1882.0, "kucoin": 1883.0})
    mock_page(direct_vm, page_price=1881.0)
    request(oracle, direct_vm, direct_alice, pair="ETH/USD")
    rec = oracle.get_latest_price("ETH/USD")
    # binance/kucoin only resolve if {QALIAS} produced USDT
    assert "binance" in rec["sources"]
    assert "kucoin" in rec["sources"]
