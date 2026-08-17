"""The consensus rule.

Direct mode runs the leader path only and never invokes validator_fn, so the
comparison logic is extracted into the pure `_agrees` helper specifically so it
can be covered here. This is the most important logic in the contract.

The property these tests exist to pin: `_agrees` accepting a validator result
must imply the stored price and the stored confidence are identical to what any
other accepted result would have stored. Consensus binds the output, it does not
merely bless a leader who was nearby.
"""

SCALE = 10**18
TOL = 200      # 2%
MIN_N = 3
QUANT = 50     # DEF_QUANT_BPS


def payload(median, n=6, confidence="HIGH"):
    """Shaped exactly like what _collect returns - medians as strings, since
    that is how they cross the calldata boundary."""
    return {"median": str(int(median)), "n": n, "confidence": confidence,
            "prices": {}, "failed": {}, "spread_bps": 10}


def agrees(mod, lead, val, tol=TOL, min_n=MIN_N, quant=QUANT):
    return mod._agrees(lead, val, tol, min_n, quant)


def stored(mod, median, quant=QUANT):
    """What request_price would write for this median - the same expression."""
    return mod._quantize(int(median), quant)


# --- FIX 1: the stored price is bound to the bucket, not to the leader ---

def test_identical_results_agree(mod):
    p = payload(1882 * SCALE)
    assert agrees(mod, p, p) is True


def test_same_bucket_agrees_and_pins_one_stored_price(mod):
    """Two different raw medians inside one bucket agree, and both store the
    identical number - the leader's raw value never reaches storage."""
    lead = payload(1877_600000000000000000)   # $1877.60
    val = payload(1877_100000000000000000)    # $1877.10, 2.7 bps apart
    assert agrees(mod, lead, val) is True
    assert stored(mod, 1877_600000000000000000) == stored(mod, 1877_100000000000000000)


def test_reviewers_example_now_disagrees(mod):
    """The reported hole: leader $1877.60, validator $1874.50. 16 bps apart, so
    the old +/-200 bps gate passed it and the leader's exact value was stored.
    They fall either side of a bucket edge, so they are now a disagreement."""
    lead = payload(1877_600000000000000000)
    val = payload(1874_500000000000000000)
    assert mod._bps(1874_500000000000000000, 1877_600000000000000000) < TOL
    assert agrees(mod, lead, val) is False


def test_drift_well_inside_tolerance_no_longer_agrees(mod):
    """1.9% used to pass on tolerance alone. Bucket equality is the gate now."""
    lead = payload(1000 * SCALE)
    assert agrees(mod, lead, payload(1019 * SCALE)) is False
    assert agrees(mod, lead, payload(1021 * SCALE)) is False
    assert agrees(mod, lead, payload(950 * SCALE)) is False


def test_every_accepted_pair_stores_the_same_price(mod):
    """THE property, swept rather than argued: across four magnitudes and a
    +/-3% band of validator medians, every pair `_agrees` accepts stores one
    identical value. Two accepted outputs cannot change a quote."""
    accepted = 0
    for lead_usd in (0.87, 42.5, 1877.6, 95000.0):
        lm = int(lead_usd * SCALE)
        lead = payload(lm)
        for i in range(-300, 301):
            vm = lm + (lm * i) // 10000  # i bps away
            if vm <= 0:
                continue
            if agrees(mod, lead, payload(vm)):
                assert stored(mod, vm) == stored(mod, lm), (
                    "accepted %d vs %d but they store different prices" % (vm, lm))
                accepted += 1
    assert accepted > 100, "sweep accepted too little to be meaningful"


def test_a_tighter_lattice_binds_harder(mod):
    """quant_bps is the knob: the same pair agrees on a wide lattice and
    disagrees on a narrow one, and never the other way round."""
    lead = payload(1877_600000000000000000)
    val = payload(1874_500000000000000000)
    assert agrees(mod, lead, val, quant=500) is True    # 5% buckets
    assert agrees(mod, lead, val, quant=10) is False    # 0.1% buckets


def test_tolerance_still_caps_a_widened_lattice(mod):
    """Even at the widest lattice, tolerance_bps remains an upper bound on how
    far apart two agreeing nodes may be."""
    lead = payload(1000 * SCALE)
    val = payload(1049 * SCALE)  # 490 bps away, still the same 5% bucket
    assert mod._bucket(1000 * SCALE, 500) == mod._bucket(1049 * SCALE, 500)
    assert agrees(mod, lead, val, quant=500) is False   # tolerance rejects it


# --- FIX 2: confidence must match exactly ---

def test_confidence_gap_of_two_levels_disagrees(mod):
    """A leader claiming a cleaner world than the validator independently saw is
    the manipulation signal a pure median check misses."""
    lead = payload(1000 * SCALE, confidence="HIGH")
    val = payload(1000 * SCALE, confidence="LOW")
    assert agrees(mod, lead, val) is False


def test_adjacent_confidence_levels_now_disagree(mod):
    """The second reported hole. HIGH and MEDIUM are different answers to "may I
    act on this?", so one rank of slack let two accepted outputs land either side
    of a consumer's min_confidence."""
    hi = payload(1000 * SCALE, confidence="HIGH")
    med = payload(1000 * SCALE, confidence="MEDIUM")
    low = payload(1000 * SCALE, confidence="LOW")
    assert agrees(mod, hi, med) is False
    assert agrees(mod, med, low) is False
    assert agrees(mod, med, med) is True


def test_no_accepted_pair_can_straddle_a_confidence_requirement(mod):
    """Swept form: for every confidence pairing `_agrees` accepts, every
    possible get_price_checked(min_confidence=...) gate answers identically."""
    levels = ["LOW", "MEDIUM", "HIGH"]
    for lc in levels:
        for vc in levels:
            if not agrees(mod, payload(1000 * SCALE, confidence=lc),
                          payload(1000 * SCALE, confidence=vc)):
                continue
            for want in levels:
                assert ((mod.CONF_RANK[lc] >= mod.CONF_RANK[want])
                        == (mod.CONF_RANK[vc] >= mod.CONF_RANK[want]))


def test_unknown_confidence_label_disagrees(mod):
    lead = payload(1000 * SCALE, confidence="TOTALLY_SURE")
    assert agrees(mod, lead, payload(1000 * SCALE, confidence="HIGH")) is False
    # and an unlabelled result is not silently downgraded into agreement
    assert agrees(mod, lead, lead) is False


# --- unchanged guards ---

def test_validator_below_min_sources_disagrees(mod):
    lead = payload(1000 * SCALE, n=6)
    val = payload(1000 * SCALE, n=2)
    assert agrees(mod, lead, val) is False


def test_leader_below_min_sources_disagrees(mod):
    assert agrees(mod, payload(1000 * SCALE, n=1), payload(1000 * SCALE, n=6)) is False


def test_zero_or_negative_medians_disagree(mod):
    good = payload(1000 * SCALE)
    assert agrees(mod, payload(0), good) is False
    assert agrees(mod, good, payload(0)) is False


def test_malformed_payloads_disagree(mod):
    good = payload(1000 * SCALE)
    assert agrees(mod, None, good) is False
    assert agrees(mod, "not a dict", good) is False
    assert agrees(mod, {}, good) is False
    assert agrees(mod, {"median": "abc", "n": 6, "confidence": "HIGH"}, good) is False


def test_tolerance_is_honoured_from_storage(mod):
    """tolerance_bps is read from state before the nondet block, so a tighter
    setting must actually tighten consensus."""
    lead = payload(1000 * SCALE)
    val = payload(1002 * SCALE)  # same bucket at quant=50, 20 bps apart
    assert agrees(mod, lead, val, tol=200) is True
    assert agrees(mod, lead, val, tol=10) is False
