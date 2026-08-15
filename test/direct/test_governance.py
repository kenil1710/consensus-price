"""Governance limits.

These tests are the executable form of the trust model in the contract header:
the owner manages the source registry and parameters, and cannot reach a price.
"""

import ast
import json

import pytest

from conftest import CONTRACT, FEE, TIER_A, addr_hex, mock_all, request

CORE_ENABLED_AT_DEPLOY = 7   # binance coinbase gemini kucoin coingecko paprika yahoo


def _public_writes(tree):
    """Every method decorated @gl.public.write or @gl.public.write.payable."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            src = ast.unparse(dec)
            if src.startswith("gl.public.write"):
                out[node.name] = node
    return out


def test_only_request_price_can_write_a_price():
    """The trust model's first claim, asserted structurally against the source
    rather than trusted as prose: no governance method can reach a stored price.
    """
    tree = ast.parse(CONTRACT.read_text())
    writes = _public_writes(tree)
    # sanity: the governance surface really is present
    assert "set_params" in writes and "add_source" in writes
    assert "request_price" in writes

    offenders = []
    for name, fn in writes.items():
        for node in ast.walk(fn):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr in ("price", "timestamp"):
                    offenders.append(name)
                if isinstance(t, ast.Subscript) and "feeds" in ast.unparse(t):
                    offenders.append(name)
    assert sorted(set(offenders)) == ["request_price"]


def test_price_writes_are_downstream_of_consensus():
    """Inside request_price, the stored value must come from run_nondet_unsafe."""
    tree = ast.parse(CONTRACT.read_text())
    callers = [
        fn.name for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
        for c in ast.walk(fn)
        if isinstance(c, ast.Call) and "run_nondet_unsafe" in ast.unparse(c.func)
    ]
    assert callers == ["request_price"]

    fn = _public_writes(tree)["request_price"]
    body = ast.unparse(fn)
    consensus_at = body.index("run_nondet_unsafe")
    price_at = body.index("rec.price =")
    assert price_at > consensus_at, "price assigned before consensus returned"


@pytest.mark.parametrize("call", [
    lambda c: c.set_paused(True),
    lambda c: c.set_fee(1),
    lambda c: c.set_params(200, 1000, 900, 3, 60, 24),
    lambda c: c.set_source_enabled("binance", False),
    lambda c: c.add_source("x1", "https://e.com/{BASE}", "json", "p", "", False),
    lambda c: c.set_pair_slugs("ETH/USD", '{"coingecko":"ethereum"}'),
    lambda c: c.transfer_ownership("0x" + "11" * 20),
    lambda c: c.withdraw("0x" + "11" * 20, 1),
])
def test_governance_is_owner_only(oracle, direct_vm, direct_bob, call):
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("owner only"):
        call(oracle)


def test_core_sources_are_immutable(oracle, direct_vm, direct_owner):
    """Core URLs are fixed at deploy - this is what makes the trust model
    structural rather than a promise."""
    direct_vm.sender = direct_owner
    for sid in TIER_A + ["yahoo"]:
        with direct_vm.expect_revert("core source is immutable"):
            oracle.add_source(sid, "https://evil.example/{BASE}", "json", "p", "", True)

    srcs = {s["id"]: s for s in oracle.get_sources()}
    assert srcs["binance"]["url_template"].startswith("https://api.binance.com")
    assert srcs["binance"]["is_core"] is True


def test_core_sources_cannot_be_starved_below_the_floor(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    # 7 enabled core -> may disable down to 3
    for sid in ["yahoo", "paprika", "coingecko", "kucoin"]:
        oracle.set_source_enabled(sid, False)
    assert oracle.get_config()["enabled_core"] == 3

    with direct_vm.expect_revert("core sources enabled"):
        oracle.set_source_enabled("gemini", False)


def test_owner_added_sources_cannot_become_a_majority(oracle, direct_vm, direct_owner):
    """Moving a median needs a strict majority of inputs. The cap keeps
    owner-added sources structurally incapable of reaching one."""
    direct_vm.sender = direct_owner
    cfg = oracle.get_config()
    assert cfg["enabled_core"] == CORE_ENABLED_AT_DEPLOY

    # 2 * non_core <= core, so with 7 core the owner gets at most 3
    for i in range(3):
        oracle.add_source("mine%d" % i, "https://e%d.com/{BASE}" % i, "json", "p", "", True)
    assert oracle.get_config()["enabled_non_core"] == 3

    with direct_vm.expect_revert("non-core cap"):
        oracle.add_source("mine3", "https://e3.com/{BASE}", "json", "p", "", True)


def test_disabling_core_cannot_smuggle_non_core_into_a_majority(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    for i in range(3):
        oracle.add_source("mine%d" % i, "https://e%d.com/{BASE}" % i, "json", "p", "", True)
    # core 7, non-core 3. Dropping to core 5 would leave 2*3 > 5.
    oracle.set_source_enabled("yahoo", False)
    with direct_vm.expect_revert("non-core cap"):
        oracle.set_source_enabled("paprika", False)


def test_added_source_can_be_registered_disabled_without_cap(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    for i in range(6):
        oracle.add_source("off%d" % i, "https://e%d.com/{BASE}" % i, "json", "p", "", False)
    assert oracle.get_config()["enabled_non_core"] == 0
    # but enabling past the cap still fails
    for i in range(3):
        oracle.set_source_enabled("off%d" % i, True)
    with direct_vm.expect_revert("non-core cap"):
        oracle.set_source_enabled("off3", True)


def test_add_source_validates_input(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("url must be https"):
        oracle.add_source("bad1", "http://insecure.com/{BASE}", "json", "p", "", False)
    with direct_vm.expect_revert("kind must be"):
        oracle.add_source("bad2", "https://e.com/{BASE}", "wat", "p", "", False)
    with direct_vm.expect_revert("bad source id"):
        oracle.add_source("bad id!", "https://e.com/{BASE}", "json", "p", "", False)


def test_non_core_source_can_be_repointed(oracle, direct_vm, direct_owner):
    """Non-core sources are mutable - that is the point of the registry."""
    direct_vm.sender = direct_owner
    oracle.add_source("mine", "https://a.com/{BASE}", "json", "p", "", False)
    oracle.add_source("mine", "https://b.com/{BASE}", "json", "q", "", False)
    srcs = {s["id"]: s for s in oracle.get_sources()}
    assert srcs["mine"]["url_template"] == "https://b.com/{BASE}"
    assert srcs["mine"]["is_core"] is False


def test_set_params_enforces_bounds(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("tolerance_bps"):
        oracle.set_params(9, 1000, 900, 3, 60, 24)
    with direct_vm.expect_revert("tolerance_bps"):
        oracle.set_params(2001, 1000, 900, 3, 60, 24)
    with direct_vm.expect_revert("min_sources"):
        oracle.set_params(200, 1000, 900, 1, 60, 24)
    with direct_vm.expect_revert("max_history"):
        oracle.set_params(200, 1000, 900, 3, 60, 129)
    oracle.set_params(200, 1000, 900, 3, 60, 24)  # valid


def test_set_pair_slugs_validates(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("JSON"):
        oracle.set_pair_slugs("ETH/USD", "not json")
    with direct_vm.expect_revert("bad slug"):
        oracle.set_pair_slugs("ETH/USD", '{"coingecko":"../etc/passwd"}')
    oracle.set_pair_slugs("AVAX/USD", '{"coingecko":"avalanche-2"}')


def test_every_governance_call_is_logged(oracle, direct_vm, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_fee(2 * FEE)
    oracle.set_paused(True)
    oracle.set_source_enabled("yahoo", False)

    log = oracle.get_governance_log(0)
    actions = [json.loads(e)["action"] for e in log]
    assert actions == ["set_fee", "set_paused", "set_source_enabled"]
    entry = json.loads(log[0])
    assert entry["by"].lower() == addr_hex(direct_owner).lower()
    assert entry["ts"] > 0


def test_disabled_source_drops_out_of_the_next_request(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_source_enabled("binance", False)
    mock_all(direct_vm, price=1882.0)
    request(oracle, direct_vm, direct_alice)

    rec = oracle.get_latest_price("ETH/USD")
    assert "binance" not in rec["sources"]
    assert rec["n_attempted"] == 6


def test_source_reliability_is_tracked(oracle, direct_vm, direct_alice, direct_owner):
    direct_vm.sender = direct_owner
    oracle.set_params(200, 1000, 900, 3, 0, 24)
    from conftest import mock_tier_a, mock_page
    mock_tier_a(direct_vm, {
        "binance": 1882.0, "coinbase": (500, "down"), "gemini": 1883.0,
        "kucoin": 1881.0, "coingecko": 1882.0, "paprika": 1882.0,
    })
    mock_page(direct_vm, page_price=1882.0)
    request(oracle, direct_vm, direct_alice)

    srcs = {s["id"]: s for s in oracle.get_sources()}
    assert srcs["binance"]["ok_count"] == 1
    assert srcs["binance"]["reliability_pct"] == 100
    assert srcs["coinbase"]["fail_count"] == 1
    assert srcs["coinbase"]["reliability_pct"] == 0
    assert "500" in srcs["coinbase"]["last_fail"]


def test_ownership_transfer_moves_control(oracle, direct_vm, direct_owner, direct_bob):
    direct_vm.sender = direct_owner
    oracle.transfer_ownership(str(direct_bob))
    with direct_vm.expect_revert("owner only"):
        oracle.set_paused(True)
    direct_vm.sender = direct_bob
    oracle.set_paused(True)
    assert oracle.get_stats()["paused"] is True
