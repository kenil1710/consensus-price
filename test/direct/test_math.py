"""Pure numeric helpers: median, basis points, confidence, atto parsing."""

import pytest

SCALE = 10**18


def test_median_odd_and_even(mod):
    assert mod._median([3, 1, 2]) == 2
    assert mod._median([4, 1, 3, 2]) == 2  # (2+3)//2
    assert mod._median([7]) == 7
    assert mod._median([]) == 0


def test_median_ignores_input_order(mod):
    assert mod._median([100, 5, 50]) == mod._median([5, 50, 100])


def test_bps_resolves_small_moves(mod):
    """The whole point of multiplying before dividing: sub-1% moves must not
    truncate to zero, or every tolerance gate in the contract silently opens."""
    assert mod._bps(101 * SCALE, 100 * SCALE) == 100        # 1%
    assert mod._bps(100_01 * SCALE // 100, 100 * SCALE) == 1  # 0.01%
    assert mod._bps(100 * SCALE, 100 * SCALE) == 0
    # symmetric in magnitude
    assert mod._bps(99 * SCALE, 100 * SCALE) == 100


def test_bps_guards_zero_reference(mod):
    assert mod._bps(5, 0) == 10**9
    assert mod._bps(5, -1) == 10**9


def test_bps_does_not_overflow_at_price_ceiling(mod):
    """Multiplying before dividing is only safe because prices are capped. This
    pins the bound the contract relies on."""
    hi = mod.MAX_PRICE_ATTO
    assert hi * 10000 < 2**256          # the widest possible intermediate
    # a full-range comparison stays well inside u256
    assert mod._bps(hi, 1) < 2**256
    # and at realistic magnitudes the result is an ordinary bps figure
    assert mod._bps(hi, hi // 2) == 10000


# --- the quantization lattice ---

Q = 50  # DEF_QUANT_BPS


def test_anchor_walks_the_1_2_5_ladder(mod):
    assert mod._anchor(1 * SCALE) == 1 * SCALE
    assert mod._anchor(1999 * SCALE // 1000) == 1 * SCALE
    assert mod._anchor(2 * SCALE) == 2 * SCALE
    assert mod._anchor(49 * SCALE // 10) == 2 * SCALE
    assert mod._anchor(5 * SCALE) == 5 * SCALE
    assert mod._anchor(99 * SCALE // 10) == 5 * SCALE
    assert mod._anchor(10 * SCALE) == 10 * SCALE


def test_bucket_width_stays_proportional_across_magnitudes(mod):
    """Without the 1-2-5 ladder a plain decade anchor collapses the bucket to
    ~5 bps at the top of a decade, and honest nodes would never agree there.
    Every realistic price must sit in a bucket of 20-50 bps."""
    for usd in (0.31, 0.99, 4.2, 42.5, 199.0, 1877.6, 4999.0, 62954.0, 95000.0):
        p = int(usd * SCALE)
        step, _ = mod._bucket(p, Q)
        width_bps = step * 10000 // p
        assert 19 <= width_bps <= Q, "%s -> %d bps" % (usd, width_bps)


def test_quantize_is_idempotent(mod):
    """The stored price must re-quantize to itself, or the bucket a consumer
    reads back would not be the bucket consensus agreed on."""
    for usd in (0.87, 42.5, 1877.6, 1999.99, 2000.0, 5000.01, 95000.0):
        p = int(usd * SCALE)
        q = mod._quantize(p, Q)
        assert mod._quantize(q, Q) == q
        assert mod._bucket(q, Q) == mod._bucket(p, Q)


def test_quantize_lands_inside_its_own_bucket(mod):
    """Midpoint, so the stored price is never more than half a bucket from the
    median that produced it."""
    for usd in (0.87, 42.5, 1877.6, 95000.0):
        p = int(usd * SCALE)
        step, idx = mod._bucket(p, Q)
        q = mod._quantize(p, Q)
        assert idx * step <= q < (idx + 1) * step
        assert abs(q - p) <= step // 2 + 1


def test_bucket_is_constant_across_a_bucket_and_changes_between(mod):
    p = 1877_600000000000000000
    step, idx = mod._bucket(p, Q)
    lo = idx * step
    # every point in the bucket quantizes to the identical stored value
    for off in (0, 1, step // 3, step // 2, step - 1):
        assert mod._quantize(lo + off, Q) == mod._quantize(p, Q)
    # and the neighbours do not
    assert mod._quantize(lo - 1, Q) != mod._quantize(p, Q)
    assert mod._quantize(lo + step, Q) != mod._quantize(p, Q)


def test_quantize_is_monotonic(mod):
    """A higher median can never store a lower price - including across the
    ladder steps at 2x and 5x, where the bucket width changes."""
    prev = -1
    p = 1 * SCALE // 10
    while p < 200000 * SCALE:
        q = mod._quantize(p, Q)
        assert q >= prev, "non-monotonic at %d" % p
        prev = q
        p = p + max(1, p // 2000)  # stays dense relative to the bucket width


def test_bucket_handles_degenerate_input(mod):
    assert mod._quantize(0, Q) == 0
    assert mod._quantize(-5, Q) == 0
    assert mod._bucket(0, Q) == (1, 0)
    # a dust price still gets a valid bucket rather than dividing by zero
    assert mod._quantize(1, Q) >= 0


def test_confidence_high_requires_four_tight_sources(mod):
    tight = [1000 * SCALE, 1001 * SCALE, 1000 * SCALE, 999 * SCALE, 1000 * SCALE]
    assert mod._confidence(tight, mod._median(tight)) == "HIGH"
    # same tightness, too few sources
    assert mod._confidence(tight[:3], mod._median(tight[:3])) == "MEDIUM"


def test_confidence_degrades_as_sources_disagree(mod):
    med = 1000 * SCALE
    loose = [1000 * SCALE, 1020 * SCALE, 980 * SCALE, 1015 * SCALE]
    assert mod._confidence(loose, mod._median(loose)) == "MEDIUM"
    wild = [1000 * SCALE, 2000 * SCALE, 500 * SCALE]
    assert mod._confidence(wild, mod._median(wild)) == "LOW"
    assert mod._confidence([], 0) == "LOW"
    assert mod._confidence([1], 0) == "LOW"


def test_spread_reports_worst_source(mod):
    vals = [1000 * SCALE, 1010 * SCALE, 1500 * SCALE]
    assert mod._spread(vals, 1000 * SCALE) == 5000  # 50%


@pytest.mark.parametrize("raw,expected", [
    ("1884.16000000", 1884_160000000000000000),
    ("1882.45", 1882_450000000000000000),
    (1882.12, 1882_120000000000000000),
    ("1,884.16", 1884_160000000000000000),
    ("$1884.16", 1884_160000000000000000),
    (" 1884.16 ", 1884_160000000000000000),
    ("+1884.16", 1884_160000000000000000),
    ("1884", 1884 * SCALE),
    (1884, 1884 * SCALE),
    ("0.00001234", 12340000000000),
    (".5", SCALE // 2),
])
def test_to_atto_parses_real_shapes(mod, raw, expected):
    assert mod._to_atto(raw) == expected


def test_to_atto_truncates_beyond_18_decimals(mod):
    assert mod._to_atto("1." + "1" * 25) == SCALE + int("1" * 18)


@pytest.mark.parametrize("raw", [
    "-5", "abc", "", "   ", "1e5", "1E5", True, False, "1.2.3", "12x",
])
def test_to_atto_rejects_bad_input(mod, raw):
    with pytest.raises(ValueError):
        mod._to_atto(raw)


def test_dig_walks_every_real_source_shape(mod):
    assert mod._dig({"price": "1"}, "price") == "1"
    assert mod._dig({"data": {"amount": "2"}}, "data.amount") == "2"
    assert mod._dig({"ethereum": {"usd": 3}}, "ethereum.usd") == 3
    assert mod._dig({"quotes": {"USD": {"price": 4}}}, "quotes.USD.price") == 4
    assert mod._dig({"data": [{"last": "5"}]}, "data.0.last") == "5"


def test_dig_raises_rather_than_guessing(mod):
    """A wrong-but-plausible value is worse than a failed source."""
    with pytest.raises((KeyError, ValueError, TypeError)):
        mod._dig({"price": "1"}, "nope")
    with pytest.raises((KeyError, ValueError, TypeError)):
        mod._dig({"a": {"b": 1}}, "a.b.c")
