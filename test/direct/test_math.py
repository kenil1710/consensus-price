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
