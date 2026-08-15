# ConsensusPrice

A decentralized price oracle primitive for GenLayer.

Any account requests a price for a pair. The leader fetches independent public sources,
computes the median, and every validator independently re-fetches and re-derives it. Only
the consensus-agreed median is written on-chain — where any other contract can read it for
free, forever.

The price is not reported by an operator. It is the number a majority of validators
independently arrived at, from their own network vantage points, within a 2% tolerance of
each other.

---

## Deployed

**Bradbury testnet**

| Contract | Address |
|---|---|
| `ConsensusPrice` | `0xF6d254596B58B8c3898e33FA871ee17f68e94fB2` |
| `PriceConsumer` | `0x68c97558e71A8E574d7E52018115312A696146FC` |

**Studionet**

| Contract | Address |
|---|---|
| `ConsensusPrice` | `0x6dc688b2F104FB124B2a3bd17F7374b68dF06C53` |
| `PriceConsumer` | `0x4dfBA3605eA958Cea3b5c67ED8Ff6BaAE75aD29A` |

Full transaction hashes in [`deployments.json`](deployments.json).

Real result from a live request, not a mock:

```
$ genlayer call 0x6dc688b2F104FB124B2a3bd17F7374b68dF06C53 get_latest_price --args "ETH/USD"

{
  pair: 'ETH/USD',
  price: '1877393480456408800000',    # $1,877.393480456408800
  decimals: 18,
  confidence: 'HIGH',
  n_sources: 6,                        # of 7 attempted
  spread_bps: 9,                       # widest source is 0.09% off the median
  flags: 'FIRST',
  is_stale: false,
  sources: {
    coinbase:  '1877330000000000000000',
    coingecko: '1877280000000000000000',
    gemini:    '1877500000000000000000',
    kucoin:    '1879220000000000000000',
    paprika:   '1877396960912817600000',
    yahoo:     '1877390000000000000000'
  }
}
```

Six independent venues agreed to within 0.09%, and the seventh — Binance — is recorded
on-chain as having failed with `[EXTERNAL] http 451`, geo-blocked from validator
infrastructure. That is the design working: one dead source is data, not an outage.

### The same price from two different networks

The same request ran on Bradbury minutes later, against a completely different validator set
on different infrastructure:

| | Studionet | Bradbury |
|---|---|---|
| ETH/USD | `$1,877.393480456408800` | `$1,877.599524608443050` |
| Sources used | 6 of 7 | 6 of 7 |
| Confidence | HIGH | HIGH |
| Spread | 9 bps | 9 bps |
| Source that failed | `binance` — `http 451` | `yahoo` — `ungrounded` |

**Different networks, different failing sources, prices 1.1 bps apart.** Binance is
geo-blocked from Studionet's infrastructure but reachable from Bradbury's. Yahoo is the
reverse: on Bradbury the model returned a number that did not literally appear in the
rendered page, and the grounding check discarded it rather than trusting it — the
prompt-injection defense rejecting a bad extraction in production, not in a test.

Neither failure moved the price. That is the entire point of the median.

---

## How it works

### 1. Deterministic preflight

Before any network call: normalize the pair, check paused, check the fee, enforce the
per-pair rate limit, resolve the enabled source list, and snapshot every tunable into
locals. Leader and validators therefore run against a byte-identical task definition, and
every cheap revert happens before a single byte crosses the network.

### 2. The nondeterministic block

**Tier A — six JSON endpoints, parsed deterministically, no model involved.**
Binance, Coinbase, Gemini, KuCoin, CoinGecko, Coinpaprika. Each source is wrapped in its
own `try`/`except`, so a 451, a timeout, or malformed JSON removes one source and never
aborts the block. Prices are parsed to 18-decimal integers by string manipulation — no
float arithmetic touches the money path.

**Tier B — rendered pages, extracted by a model.**
Yahoo Finance injects its price via JavaScript, so it is absent from raw HTML; this is
where `render()` earns its place. The extracted numeral must literally appear in the fetched
page text (grounding), and must sit within 5% of the Tier A median (cross-tier anchor). A
page that fully controls both its own content *and* the model's response still cannot move
the result while three Tier A sources are alive.

### 3. Consensus

Validators do not compare individual source prices — those legitimately differ between
nodes fetching different venues milliseconds apart, and comparing them would guarantee
permanent consensus failure. They compare two things:

- **Median tolerance** — leader and validator medians within 200 bps.
- **Confidence agreement** — the two nodes' independently computed confidence scores must
  not differ by more than one level.

The second gate is the one a pure median check misses. A leader claiming `HIGH` confidence
while a validator independently observes scattered sources means the leader saw a
suspiciously clean world. That disagreement forces leader rotation.

### 4. Post-consensus write

The median returned by `run_nondet_unsafe` is written to a per-pair ring buffer with its
sequence number, flags, spread, deviation from the previous record, and the full per-source
breakdown as JSON for transparency.

**The invariant:** a request either stores a price that ≥3 independent sources and a
majority of validators agreed on, or it stores nothing. There is no partial-credit path
into storage.

---

## Trust model — governance cannot manipulate prices

The owner **cannot**:

1. **Write a price.** No `set_price`, override, emergency write, or migration hook exists.
   Every stored price is assigned in the post-consensus block of `request_price()` from
   what validators independently agreed on.
2. **Repoint a seeded source.** All nine ship with `is_core=True`, and `add_source()`
   reverts on a core id. Core URLs are fixed at deploy.
3. **Starve the source set.** Disabling below 3 enabled core sources reverts.
4. **Outvote the median with added sources.** `add_source` and `set_source_enabled` enforce
   `2 × enabled_non_core ≤ enabled_core`, and moving a median requires a strict majority.
   Owner-added sources structurally cannot decide a price.
5. **Act invisibly.** Every governance call appends to `gov_log` with the caller address and
   timestamp, readable by anyone via `get_governance_log()`.

The owner **can** enable/disable seeded sources within those bounds, add capped non-core
sources, register slugs, tune parameters within hard-coded ranges, pause new requests, and
withdraw fees. Pausing cannot alter an already-stored price.

**Honest limit:** influence is bounded, public, and requires its own transaction — not zero.
At the floor of 3 core + 1 added source the owner still cannot determine the median (1 of 4
is no majority) and still needs validators to agree.

---

## Usage

### Request a price (transaction)

```bash
genlayer write <ORACLE> request_price --args "ETH/USD"
```

Returns a `price_id` like `"ETH/USD:7"`. Costs the configured fee; requests for a pair
updated within the last 60 seconds revert *before* any fetch, so the caller keeps their
money instead of buying a duplicate.

### Read a price (free, no transaction)

```bash
genlayer call <ORACLE> get_latest_price --args "ETH/USD"
```

All twelve view methods are free and callable by any contract. See
[INTEGRATION.md](docs/INTEGRATION.md) for the cross-contract pattern.

### Pairs

`ETH/USD`, `BTC/USD`, and `SOL/USD` ship with aggregator slugs registered. Any other pair
works immediately on the four exchange sources alone, because their symbols are derived
mechanically from the pair string — `AVAX/USD` and `LINK/USD` need zero configuration. The
two aggregator sources join in once the owner registers a slug via `set_pair_slugs`.

---

## Method surface

**Write**

| Method | Access |
|---|---|
| `request_price(pair)` | public, payable |
| `add_source(...)`, `set_source_enabled(...)`, `set_pair_slugs(...)` | owner |
| `set_params(...)`, `set_fee(...)`, `set_paused(...)` | owner |
| `transfer_ownership(...)`, `withdraw(...)` | owner |

**View — all free**

| Method | Returns |
|---|---|
| `get_latest_price(pair)` | Full record + `age_seconds` + `is_stale` |
| `get_price_checked(pair, max_age, min_confidence)` | **Reverts** if missing/stale/low-confidence |
| `get_price_history(pair, count)` | Last N records, newest first |
| `get_twap(pair, count)` | Time-weighted average |
| `get_price_scaled(pair, decimals)` | Median rescaled to your decimals |
| `is_stale(pair)`, `decimals()` | Freshness and scale |
| `get_supported_pairs()`, `get_sources()`, `get_config()`, `get_stats()` | Introspection |
| `get_governance_log(count)` | Every owner action, with address and timestamp |

---

## Repository layout

```
contracts/ConsensusPrice.py   the oracle
contracts/PriceConsumer.py    reference integration, deployed and live
test/direct/                  132 tests, no server required
docs/DESIGN.md                full design rationale
docs/INTEGRATION.md           how to read this oracle from your contract
deployments.json              live addresses and transaction hashes
```

## Tests

```bash
pip install genlayer-test[sim]
genvm-lint check contracts/ConsensusPrice.py
pytest test/direct -q
```

132 direct-mode tests covering price parsing across all six response shapes, median and
basis-point math, confidence boundaries, TWAP, symbol substitution, the ring buffer,
volatility and staleness flags, prompt-injection defenses, governance access control and
bounds, cross-contract composability, and the consensus rule itself.

`test_consensus.py` matters disproportionately: direct mode runs the leader path only and
never exercises `validator_fn`, so the leader/validator comparison is extracted into a pure
function and tested directly. It is the single most important piece of logic in the
contract.
