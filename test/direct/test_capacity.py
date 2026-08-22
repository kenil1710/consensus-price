"""Ring-buffer capacity: one width for reads and writes, fixed per feed.

Regression cover for the reviewer's finding. Changing max_history while a feed
already held records used to leave writes taking the new modulus while reads
still spanned the old array, so get_latest_price / get_price_history / get_twap
served records that were not the newest. Each feed now fixes its capacity when
it is born and both sides read that one number, so no governance call can move
which slot the readers treat as latest.
"""

import ast

import pytest

from conftest import CONTRACT, mock_all, quantized, request

SCALE = 10**18


def post(oracle, vm, sender, price, pair="ETH/USD"):
    vm.clear_mocks()
    mock_all(vm, price=price, slug=_slug(pair))
    return request(oracle, vm, sender, pair=pair)


def _slug(pair):
    return {"BTC/USD": "bitcoin", "SOL/USD": "solana"}.get(pair, "ethereum")


def set_depth(oracle, vm, owner, depth):
    """Only max_history moves; volatility is off so nothing gets flagged."""
    vm.sender = owner
    oracle.set_params(200, 10000, 900, 3, 0, depth)


def seqs(hist):
    return [int(h["price_id"].split(":")[1]) for h in hist]


def assert_consistent(oracle, pair, writes_done, capacity):
    """The whole contract of the ring, asserted from the outside.

    Reads must agree with what was actually written: the newest record is the
    last write, history is the tail of the write sequence in strict order, and
    depth never exceeds the feed's capacity.
    """
    hist = oracle.get_price_history(pair, 0)
    kept = min(writes_done, capacity)
    assert len(hist) == kept, f"{pair}: depth {len(hist)} != {kept}"

    got = seqs(hist)
    expected = list(range(writes_done, writes_done - kept, -1))
    assert got == expected, f"{pair}: history {got} != {expected}"

    latest = oracle.get_latest_price(pair)
    assert latest["price_id"] == f"{pair}:{writes_done}"
    assert latest["price"] == hist[0]["price"]

    info = oracle.get_feed_info(pair)
    assert info["capacity"] == capacity
    assert info["records_stored"] == kept
    assert info["update_count"] == writes_done

    # a checked read must serve the same record the raw read does
    checked = oracle.get_price_checked(pair, 0, "LOW")
    assert checked["price_id"] == latest["price_id"]

    # TWAP spans exactly the records history reports, oldest first
    twap = oracle.get_twap(pair, 0)
    assert twap["samples"] == kept
    assert twap["oldest_timestamp"] == hist[-1]["timestamp"]


# --- the reviewer's scenario, and its mirror image ---

def test_shrinking_max_history_cannot_corrupt_a_live_feed(
        oracle, direct_vm, direct_alice, direct_owner):
    """Owner shrinks the depth under a feed that already holds more records.

    Before the fix this was the reported bug: writes landed at count % 5 while
    reads still walked all 10 slots, so get_latest_price returned seq 10 with
    seqs 11-15 already written and invisible.
    """
    set_depth(oracle, direct_vm, direct_owner, 10)
    for i in range(10):
        post(oracle, direct_vm, direct_alice, 1000.0 + 20 * i)
    assert_consistent(oracle, "ETH/USD", 10, 10)

    set_depth(oracle, direct_vm, direct_owner, 5)   # shrink under a full feed
    assert_consistent(oracle, "ETH/USD", 10, 10)    # nothing moved on the read

    for i in range(5):
        post(oracle, direct_vm, direct_alice, 3000.0 + 20 * i)
        assert_consistent(oracle, "ETH/USD", 11 + i, 10)


def test_growing_max_history_cannot_corrupt_a_live_feed(
        oracle, direct_vm, direct_alice, direct_owner):
    """The mirror bug the report did not name: growing the depth under a feed
    that had already wrapped made the writer append past the ring while reads
    still rotated around the cursor, which returned history out of time order
    (seqs 3, 6, 5, 7, 4) and named seq 3 as latest with seq 7 written."""
    set_depth(oracle, direct_vm, direct_owner, 4)
    for i in range(6):                               # wrap it
        post(oracle, direct_vm, direct_alice, 1000.0 + 20 * i)
    assert_consistent(oracle, "ETH/USD", 6, 4)

    set_depth(oracle, direct_vm, direct_owner, 12)   # grow under a full feed
    assert_consistent(oracle, "ETH/USD", 6, 4)

    for i in range(6):
        post(oracle, direct_vm, direct_alice, 5000.0 + 20 * i)
        assert_consistent(oracle, "ETH/USD", 7 + i, 4)


@pytest.mark.parametrize("depths", [
    [2, 128, 2],          # floor -> ceiling -> floor
    [24, 5, 24],          # the default, shrunk and restored
    [6, 7, 6, 5, 6],      # off-by-one either side of the live depth
    [3, 3, 3],            # no-op resizes
])
def test_resizing_between_every_write_keeps_reads_consistent(
        oracle, direct_vm, direct_alice, direct_owner, depths):
    """Sweep: resize the global depth before every single write and assert the
    full read contract after each one. The feed's capacity is whatever was set
    when it was born; nothing after that may reach it."""
    set_depth(oracle, direct_vm, direct_owner, depths[0])
    post(oracle, direct_vm, direct_alice, 1000.0)     # feed born at depths[0]
    birth = depths[0]
    assert_consistent(oracle, "ETH/USD", 1, birth)

    n = 1
    for round_ in range(3):
        for d in depths[1:]:
            set_depth(oracle, direct_vm, direct_owner, d)
            post(oracle, direct_vm, direct_alice, 1000.0 + 20 * n)
            n += 1
            assert_consistent(oracle, "ETH/USD", n, birth)


# --- what max_history does now ---

def test_a_live_feed_keeps_the_capacity_it_was_born_with(
        oracle, direct_vm, direct_alice, direct_owner):
    set_depth(oracle, direct_vm, direct_owner, 8)
    post(oracle, direct_vm, direct_alice, 1000.0)
    assert oracle.get_feed_info("ETH/USD")["capacity"] == 8

    for d in (2, 128, 24):
        set_depth(oracle, direct_vm, direct_owner, d)
        info = oracle.get_feed_info("ETH/USD")
        assert info["capacity"] == 8            # untouched
        assert info["new_feed_capacity"] == d   # the knob still reports itself


def test_new_feeds_take_the_current_max_history(
        oracle, direct_vm, direct_alice, direct_owner):
    """The knob is not dead - it still sets the depth of everything created
    after it, which is the whole of its remaining job."""
    set_depth(oracle, direct_vm, direct_owner, 4)
    post(oracle, direct_vm, direct_alice, 1000.0, pair="ETH/USD")

    set_depth(oracle, direct_vm, direct_owner, 16)
    post(oracle, direct_vm, direct_alice, 61000.0, pair="BTC/USD")

    assert oracle.get_feed_info("ETH/USD")["capacity"] == 4
    assert oracle.get_feed_info("BTC/USD")["capacity"] == 16

    # and each honours its own depth as it fills
    for i in range(6):
        post(oracle, direct_vm, direct_alice, 1000.0 + 20 * i, pair="ETH/USD")
        post(oracle, direct_vm, direct_alice, 61000.0 + 500 * i, pair="BTC/USD")
    assert_consistent(oracle, "ETH/USD", 7, 4)
    assert_consistent(oracle, "BTC/USD", 7, 16)


def test_unknown_pair_feed_info_is_safe(oracle, direct_vm, direct_owner):
    set_depth(oracle, direct_vm, direct_owner, 9)
    info = oracle.get_feed_info("DOGE/USD")
    assert info["found"] is False
    assert info["capacity_if_created_now"] == 9


def test_default_count_spans_the_feeds_own_depth(
        oracle, direct_vm, direct_alice, direct_owner):
    """count<=0 means "all of it". That has to mean all of THIS feed, not
    however wide the global happens to be right now."""
    set_depth(oracle, direct_vm, direct_owner, 10)
    for i in range(10):
        post(oracle, direct_vm, direct_alice, 1000.0 + 20 * i)

    set_depth(oracle, direct_vm, direct_owner, 3)     # global far below the feed
    assert len(oracle.get_price_history("ETH/USD", 0)) == 10
    assert oracle.get_twap("ETH/USD", 0)["samples"] == 10

    set_depth(oracle, direct_vm, direct_owner, 128)   # global far above the feed
    assert len(oracle.get_price_history("ETH/USD", 0)) == 10
    assert oracle.get_twap("ETH/USD", 0)["samples"] == 10


def test_explicit_count_still_truncates_to_the_newest(
        oracle, direct_vm, direct_alice, direct_owner):
    set_depth(oracle, direct_vm, direct_owner, 10)
    for i in range(10):
        post(oracle, direct_vm, direct_alice, 1000.0 + 20 * i)
    set_depth(oracle, direct_vm, direct_owner, 2)

    assert seqs(oracle.get_price_history("ETH/USD", 3)) == [10, 9, 8]
    assert oracle.get_twap("ETH/USD", 3)["samples"] == 3


# --- TWAP is the read that a wrong order corrupts silently ---

def test_twap_stays_time_ordered_across_a_resize(
        oracle, direct_vm, direct_alice, direct_owner):
    """A mis-ordered ring still returns a number, so TWAP has to be checked
    against a hand-computed weighting rather than just for plausibility."""
    set_depth(oracle, direct_vm, direct_owner, 3)
    direct_vm.warp("2026-06-01T12:00:00Z")
    post(oracle, direct_vm, direct_alice, 1000.0)     # dropped once the ring wraps
    direct_vm.warp("2026-06-01T12:30:00Z")
    post(oracle, direct_vm, direct_alice, 2000.0)     # stands 1800s

    set_depth(oracle, direct_vm, direct_owner, 64)    # resize mid-window
    direct_vm.warp("2026-06-01T13:00:00Z")
    post(oracle, direct_vm, direct_alice, 3000.0)     # stands 1800s
    direct_vm.warp("2026-06-01T13:30:00Z")
    post(oracle, direct_vm, direct_alice, 4000.0)     # stands 600s
    direct_vm.warp("2026-06-01T13:40:00Z")

    out = oracle.get_twap("ETH/USD", 0)
    assert out["samples"] == 3                        # capacity 3, seq 1 evicted
    assert out["window_seconds"] == 1800 + 1800 + 600
    expected = (quantized(2000.0) * 1800
                + quantized(3000.0) * 1800
                + quantized(4000.0) * 600) // 4200
    assert out["twap"] == expected

    hist = oracle.get_price_history("ETH/USD", 0)
    stamps = [h["timestamp"] for h in hist]
    assert stamps == sorted(stamps, reverse=True)     # newest first, no wobble


# --- structural: the fix cannot be undone by a later edit ---

def _public_writes(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
                ast.unparse(d).startswith("gl.public.write")
                for d in node.decorator_list):
            out[node.name] = node
    return out


def test_capacity_is_assigned_exactly_once_and_only_on_the_write_path():
    """The trust model's sixth claim, asserted against the source: nothing the
    owner can call assigns a feed's ring width."""
    tree = ast.parse(CONTRACT.read_text())
    writers = []
    for name, fn in _public_writes(tree).items():
        for node in ast.walk(fn):
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
            for t in targets:
                if isinstance(t, ast.Attribute) and t.attr in ("capacity", "cursor"):
                    writers.append(name)
    assert sorted(set(writers)) == ["request_price"]

    body = ast.unparse(_public_writes(tree)["request_price"])
    assert body.count("feed.capacity = ") == 1


def test_no_governance_method_can_touch_stored_history():
    """No migration hook, by construction: the only public write that reaches
    feed history at all is request_price."""
    tree = ast.parse(CONTRACT.read_text())
    offenders = []
    for name, fn in _public_writes(tree).items():
        if name == "request_price":
            continue
        src = ast.unparse(fn)
        for token in ("self.feeds", ".history", "_ordered", "_latest", "_indices"):
            if token in src:
                offenders.append((name, token))
    assert offenders == []


SEED_STMT = "feed.capacity = u32(self.max_history)"

# Reporting the knob is fine; using it as a ring modulus is the bug.
REPORTERS = ("_cap", "set_params", "get_config", "get_feed_info", "__init__")


def test_reads_and_writes_take_the_width_from_one_helper():
    """Every ring width in the contract comes from _cap(feed). The mutable
    global is allowed exactly one appearance on the ring path - seeding a brand
    new feed - and must never be a modulus or a read depth."""
    tree = ast.parse(CONTRACT.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name in REPORTERS:
            continue
        src = ast.unparse(node)
        uses = len(src.split("self.max_history")) - 1
        if node.name == "request_price":
            assert uses == 1 and SEED_STMT in src, (
                "request_price may touch max_history only to seed a new feed")
            continue
        assert uses == 0, (
            f"{node.name} reads the mutable global instead of _cap(feed)")
