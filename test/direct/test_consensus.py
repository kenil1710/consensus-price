"""The consensus rule.

Direct mode runs the leader path only and never invokes validator_fn, so the
comparison logic is extracted into the pure `_agrees` helper specifically so it
can be covered here. This is the most important logic in the contract.
"""

SCALE = 10**18
TOL = 200      # 2%
MIN_N = 3


def payload(median, n=6, confidence="HIGH"):
    """Shaped exactly like what _collect returns - medians as strings, since
    that is how they cross the calldata boundary."""
    return {"median": str(int(median)), "n": n, "confidence": confidence,
            "prices": {}, "failed": {}, "spread_bps": 10}


def agrees(mod, lead, val, tol=TOL, min_n=MIN_N):
    return mod._agrees(lead, val, tol, min_n)


def test_identical_results_agree(mod):
    p = payload(1882 * SCALE)
    assert agrees(mod, p, p) is True


def test_drift_inside_tolerance_agrees(mod):
    lead = payload(1000 * SCALE)
    val = payload(1019 * SCALE)  # +1.9%
    assert agrees(mod, lead, val) is True


def test_drift_outside_tolerance_disagrees(mod):
    lead = payload(1000 * SCALE)
    val = payload(1021 * SCALE)  # +2.1%
    assert agrees(mod, lead, val) is False


def test_tolerance_boundary_is_inclusive(mod):
    lead = payload(1000 * SCALE)
    assert agrees(mod, lead, payload(1020 * SCALE)) is True   # exactly 200 bps
    assert agrees(mod, lead, payload(980 * SCALE)) is True    # exactly -200 bps


def test_drift_is_measured_in_both_directions(mod):
    lead = payload(1000 * SCALE)
    assert agrees(mod, lead, payload(950 * SCALE)) is False


def test_confidence_gap_of_two_levels_disagrees(mod):
    """A leader claiming a cleaner world than the validator independently saw is
    the manipulation signal a pure median check misses."""
    lead = payload(1000 * SCALE, confidence="HIGH")
    val = payload(1000 * SCALE, confidence="LOW")
    assert agrees(mod, lead, val) is False


def test_adjacent_confidence_levels_agree(mod):
    """One level of slack stops borderline spreads causing spurious failures."""
    lead = payload(1000 * SCALE, confidence="HIGH")
    val = payload(1000 * SCALE, confidence="MEDIUM")
    assert agrees(mod, lead, val) is True
    assert agrees(mod, payload(1000 * SCALE, confidence="MEDIUM"),
                  payload(1000 * SCALE, confidence="LOW")) is True


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


def test_unknown_confidence_label_is_treated_as_lowest(mod):
    lead = payload(1000 * SCALE, confidence="TOTALLY_SURE")
    val = payload(1000 * SCALE, confidence="HIGH")
    assert agrees(mod, lead, val) is False  # rank 0 vs 2


def test_tolerance_is_honoured_from_storage(mod):
    """tolerance_bps is read from state before the nondet block, so a tighter
    setting must actually tighten consensus."""
    lead = payload(1000 * SCALE)
    val = payload(1010 * SCALE)  # 1%
    assert agrees(mod, lead, val, tol=200) is True
    assert agrees(mod, lead, val, tol=50) is False
