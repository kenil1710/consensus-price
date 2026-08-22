# ConsensusPrice

A decentralized price oracle primitive for GenLayer.

Any account requests a price for a pair. The leader fetches independent public sources,
computes the median, and every validator independently re-fetches and re-derives it. Only
the consensus-agreed median is written on-chain — where any other contract can read it for
free, forever.

The price is not reported by an operator. It is the number a majority of validators
independently arrived at, from their own network vantage points — and *exactly* that number:
validators agree by landing in the same quantization bucket, and the stored price is derived
from the bucket rather than from whatever the leader happened to measure. Two accepted
outputs for one request cannot differ. See [Consensus](#3-consensus).

---

## Deployed

**Bradbury testnet**

| Contract | Address |
|---|---|
| `ConsensusPrice` | `0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146` |
| `PriceConsumer` | `0xa67e231e29623ceeacd03A7314C273b0101F1490` |

**Studionet**

| Contract | Address |
|---|---|
| `ConsensusPrice` | `0xEB6FA760Ff86E50ef9089ed194d919ad0A155Fe0` |
| `PriceConsumer` | `0x3bAb00032b29Db9E14f12a3D975F6D4Add77F8F9` |

Full transaction hashes in [`deployments.json`](deployments.json).

**Reviewers: [start here](#testing-this-contract).** There is no frontend — this is an
Intelligent Contracts submission, and the contract itself is the deliverable. Every method
below can be called in the browser with no wallet and no install.

Real result from a live request, not a mock:

```
$ genlayer call 0xEB6FA760Ff86E50ef9089ed194d919ad0A155Fe0 get_latest_price --args "ETH/USD"

{
  pair: 'ETH/USD',
  price: '1897500000000000000000',     # $1,897.50 — the bucket midpoint
  decimals: 18,
  confidence: 'HIGH',
  quant_bps: 50,
  bucket: '379@5000000000000000000',   # bucket 379, $5 wide -> [$1895, $1900)
  n_sources: 6,                        # of 7 attempted
  spread_bps: 26,                      # worst source is one bucket away
  price_id: 'ETH/USD:4',
  sources: {
    coinbase:  '1897500000000000000000',
    coingecko: '1902500000000000000000',
    gemini:    '1897500000000000000000',
    kucoin:    '1902500000000000000000',
    paprika:   '1897500000000000000000',
    yahoo:     '1897500000000000000000'
  }
}
```

Six independent venues, each fetched at its own slightly different real price, snapped onto
the lattice: four landed in bucket 379 and two in bucket 380. The median is a **majority vote
over lattice points**, so the result is 379 — and every validator that agreed stored this
exact `u256`, not something near it. The seventh source is recorded on-chain with its failure
reason. That is the design working: one dead source is data, not an outage.

### The same price from two different networks

The same request ran on Bradbury, against a completely different validator set on different
infrastructure:

| | Studionet | Bradbury |
|---|---|---|
| ETH/USD | `1897500000000000000000` | `1897500000000000000000` |
| Bucket | `379@5000000000000000000` | `379@5000000000000000000` |
| Confidence | HIGH | HIGH |
| Sources used | 6 of 7 | 7 of 7, then 6 of 7 |

**Different networks, different validator sets, different source availability — same bucket,
same stored `u256`, to the wei.** Under the old tolerance rule these two would merely have
been "close"; now they are equal, and equal is what a downstream contract can price against.

### Determinism, checked live

Four consecutive `request_price("ETH/USD")` rounds on Studionet, rate limit set to `0`:

```
ETH/USD:1   1902500000000000000000   bucket 380@5e18   HIGH   6 sources   ts 1786944632
ETH/USD:2   1897500000000000000000   bucket 379@5e18   HIGH   6 sources   ts 1786944653
ETH/USD:3   1897500000000000000000   bucket 379@5e18   HIGH   5 sources   ts 1786944686
ETH/USD:4   1897500000000000000000   bucket 379@5e18   HIGH   6 sources   ts 1786944748
```

Rounds 2, 3 and 4 are byte-identical across 95 seconds and three independent consensus rounds
— including round 3, which ran on one fewer source. Round 1 → 2 moved exactly one bucket
because ETH itself moved 26 bps in those 21 seconds. **The oracle is deterministic, not deaf.**

Bradbury, three rounds spanning 1,706 seconds on three different source counts (7, 6, 6):

```
ETH/USD:1   1897500000000000000000   bucket 379@5e18   HIGH   7 sources   ts 1786944896
ETH/USD:2   1897500000000000000000   bucket 379@5e18   HIGH   6 sources   ts 1786945522
ETH/USD:3   1897500000000000000000   bucket 379@5e18   HIGH   6 sources   ts 1786946602
```

All three identical. Full records in [`deployments.json`](deployments.json).

---

## Testing this contract

Two ways in. **Option A needs nothing installed and no wallet** — start there.

| | Option A — GenLayer Studio | Option B — CLI |
|---|---|---|
| Network | Studionet | Bradbury |
| Install | none, runs in the browser | Node + `genlayer` CLI |
| Wallet | none, Studio provides funded accounts | keystore with testnet GEN |
| Reads | ✅ | ✅ |
| Writes (`request_price`) | ✅ | ✅ |

### Option A — GenLayer Studio (no install, no wallet)

**One-click import:**

```
https://studio.genlayer.com/?import-contract=0xEB6FA760Ff86E50ef9089ed194d919ad0A155Fe0
```

This loads the deployed Studionet instance: Studio fetches the on-chain source into the
editor and registers the live contract so every method is callable from the right-hand
panel. Pick a method, fill the arguments, and read the result.

> **Note on the address.** This link uses the **Studionet** address. Studio runs its own
> network (chain 61999) and cannot reach Bradbury (chain 4221), so importing the Bradbury
> address fails with "Contract not found". Both networks run identical code — see the
> cross-network comparison above. To exercise the Bradbury deployment, use Option B.

### Option B — CLI (Bradbury)

```bash
npm install -g genlayer
genlayer network set testnet-bradbury
```

Reads need no account. `request_price` needs an account with a little testnet GEN and an
explicit `--fee-value` deposit — see [Step 3](#step-3--request-a-fresh-price-needs-an-account).

### The Bradbury explorer

```
https://explorer-bradbury.genlayer.com/address/0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146
```

Useful for **verifying** the deployment — it shows the on-chain source, the balance, and
every transaction against the contract, including the price requests below. It is a
read-only browser: it has **no** interface for calling contract methods. Use Studio or the
CLI to actually call anything.

---

The five steps below are written as CLI commands against Bradbury. **In Studio, run the
same steps** by selecting the identical method name and arguments in the interaction panel —
the contract is the same and the fee is zeroed on both deployments. Substitute the Studionet
addresses (`0xEB6FA760…` oracle, `0x3bAb0003…` consumer) if you are reading along there.

### Step 1 — Current state (no wallet)

```bash
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_stats
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_config
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 decimals
```

`get_stats` shows total requests and unique pairs. `get_config` shows every tunable plus
`enabled_core: 7` — the live source count. `decimals` returns `18`.

Also worth calling, because it is the transparency claim made checkable:

```bash
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_sources
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_governance_log --args 20
```

`get_sources` reports per-source `ok_count`, `fail_count`, `reliability_pct`, and the real
`last_fail` string. `get_governance_log` lists every owner action ever taken, with address
and timestamp.

### Step 2 — Existing price data (no wallet)

```bash
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_latest_price --args "ETH/USD"
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_price_history --args "ETH/USD" 5
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_twap --args "ETH/USD" 5
```

Returns real prices from live requests, with the full per-source breakdown in `sources` and
the failure reason for any source that did not answer. `get_price_history` returns however
many records exist, newest first — it does not pad to the count you ask for.

At the time of writing the Bradbury oracle holds three ETH/USD records, all HIGH confidence:

```
ETH/USD:3   1897500000000000000000   bucket 379@5e18   ts 1786946602
ETH/USD:2   1897500000000000000000   bucket 379@5e18   ts 1786945522
ETH/USD:1   1897500000000000000000   bucket 379@5e18   ts 1786944896

get_twap("ETH/USD", 5) -> twap 1897500000000000000000, samples 3, window 2150s
```

Three independent consensus rounds spanning 28 minutes, on 7, 6 and 6 sources respectively —
byte-identical every time. Each was a fresh leader fetching seven live endpoints; none of
them could have stored a different number and still passed.

The TWAP equals spot here only because all three records share a bucket. In general it is
weighted by how long each record stood as the latest price, which is what makes it resistant
to a brief spike — and it is the one number in this contract that is deliberately *not* on
the lattice, since it is an average over time.

Divide `price` by 10^18 for USD: `1897500000000000000000` is `$1,897.50`.

### Step 3 — Request a fresh price (needs an account)

```bash
genlayer write 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 request_price \
  --args "ETH/USD" --fee-value 100000000000000000
```

> **`--fee-value` is required here — do not omit it.** Without it the CLI attaches a zero
> deposit and the transaction is reverted by the consensus contract within ~3 seconds,
> before it ever reaches consensus:
>
> ```
> Error: Transaction reverted: EVM tx 0x7065dc… to consensus contract 0x0112Bf6e… was reverted.
> ```
>
> `request_price` runs seven web fetches plus a model call across the leader and every
> validator, so the deposit the CLI derives automatically does not cover it. `0.1 GEN`
> (`100000000000000000` wei) is comfortably sufficient; unused deposit is not consumed.

**Note this is the consensus fee deposit, not the contract's own fee.** The contract's
`fee_wei` is set to **0** on this deployment, so no `msg.value` is needed — which is
necessary, because the CLI has no way to attach `msg.value` to a call at all. The contract's
fee logic is covered by the direct test suite instead.

This takes **1–7 minutes**: the leader fetches seven sources, then every validator
independently re-fetches and re-derives the median before agreeing. Observed runs on
Bradbury ranged from 56 seconds to 409 seconds depending on network load. Watch for
`resultName: 'AGREE'`. Then:

```bash
genlayer call 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_latest_price --args "ETH/USD"
```

`timestamp` and `price_id` will have advanced, and `flags` will no longer read `FIRST`.

> **If it reverts with `[EXPECTED] fresh, retry in Ns`** — that is the 60-second per-pair
> rate limit working, not a failure. It rejects duplicate requests *before* any network
> fetch so the caller keeps their money. Wait it out, or request a different pair.

### Step 4 — A different pair, zero configuration

```bash
genlayer write 0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 request_price \
  --args "BTC/USD" --fee-value 100000000000000000
genlayer call  0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146 get_latest_price --args "BTC/USD"
```

No setup was needed for BTC/USD, and none is needed for `SOL/USD`, `AVAX/USD`, or
`LINK/USD` either — exchange source symbols are derived mechanically from the pair string.
Try an invalid pair like `"NOTREAL/USD"` to watch it fail cleanly with `[TRANSIENT]` rather
than storing garbage.

### Step 5 — Composability

`PriceConsumer` is a separate contract that holds no price data of its own. Every number it
returns comes from a free cross-contract read of the oracle.

```bash
genlayer call 0xa67e231e29623ceeacd03A7314C273b0101F1490 quote --args "ETH/USD" 2500000000000000000
```

Returns the USD value of 2.5 ETH — `value_usd_atto: '4693998811521107625000'`, about
`$4,693.99` — alongside the price, confidence, and age it used.

The more interesting call is the one that **refuses**:

```bash
genlayer call 0xa67e231e29623ceeacd03A7314C273b0101F1490 quote --args "DOGE/USD" 1000000000000000000
# execution failed — no price stored for DOGE/USD

genlayer call 0xa67e231e29623ceeacd03A7314C273b0101F1490 is_safe_to_trade --args "DOGE/USD"
# { safe: false, reason: 'no price for DOGE/USD' }
```

`quote` uses `get_price_checked`, which reverts on a missing, stale, or low-confidence
price rather than returning one. `is_safe_to_trade` uses `get_latest_price` and reports the
reason instead. Neither invents a number. That contrast is the integration pattern the
project is arguing for — see [INTEGRATION.md](docs/INTEGRATION.md).

### Verifying the deployed code is this repo

Both deployments serve their source on-chain. This confirms the running contract is exactly
the file in this repository, byte for byte:

```bash
curl -s -X POST https://rpc-bradbury.genlayer.com -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"gen_getContractCode",
       "params":[{"address":"0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146"}],"id":1}' \
  | python3 -c "import json,sys,base64,hashlib; \
      print(hashlib.sha256(base64.b64decode(json.load(sys.stdin)['result'])).hexdigest())"

shasum -a 256 contracts/ConsensusPrice.py
```

Both print `757faa5d7d61a805…`. The Studionet instance hashes identically — the two networks
run the same 36,688 bytes.

### Running the tests locally

```bash
pip install genlayer-test[sim]
genvm-lint check contracts/ConsensusPrice.py
pytest test/direct -q          # 164 passed
```

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
permanent consensus failure. They compare three things, and **the two that decide what gets
stored are exact equality, not a tolerance**:

- **Same bucket** *(binding)* — every price snaps onto a quantization lattice, and the
  leader's median and the validator's median must land in the *same* bucket. The stored price
  is the bucket's midpoint, so agreeing on the bucket is agreeing on the exact `u256` stored.
- **Same confidence** *(binding)* — the two nodes' independently computed confidence labels
  must match exactly. `HIGH` and `MEDIUM` are different answers to "may I act on this?", so
  one rank of slack would let two accepted outputs land either side of a consumer's
  `min_confidence` gate.
- **Median tolerance** — leader and validator medians still within `tolerance_bps` (200), so
  widening the lattice through governance can never widen consensus past the tolerance.

Why this matters: a tolerance gate answers "was the leader close?", which is a different
question from "is the stored number agreed?". Under a pure tolerance the leader's exact
median still lands in storage, and a *different* leader with a different median would have
passed the same gate and stored a different number — two accepted outputs, two different
quotes. Deriving the stored price from the bucket closes that.

The confidence gate is also the one a pure median check misses. A leader claiming `HIGH`
confidence while a validator independently observes scattered sources means the leader saw a
suspiciously clean world. That disagreement forces leader rotation.

**The lattice**, in short: `step = anchor(p) * quant_bps / 10000`, where `anchor` is the
largest `c × 10^d ≤ p` for `c ∈ {1, 2, 5}`. At `quant_bps = 50` that is a bucket 20–50 bps
wide at every magnitude — about `$5` at ETH ≈ `$1,900`, about `$250` at BTC ≈ `$95,000`. The
cost is stated plainly in [DESIGN.md §3.6](docs/DESIGN.md): the stored price sits up to half a
bucket (≈13 bps) from the median that produced it, and a price sitting exactly on a bucket
edge can make two honest nodes disagree — in which case the round fails closed and the caller
retries, which is strictly better than storing a value two nodes never agreed on.

### 4. Post-consensus write

`_quantize(agreed_median)` — the bucket midpoint, not the leader's raw number — is written to
a per-pair ring buffer with its sequence number, bucket id, flags, spread, deviation from the
previous record, and the full per-source breakdown as JSON for transparency. The ring's width
is a property of the feed, not a global — see [Ring capacity](#ring-capacity-is-per-feed).

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
6. **Resize a live feed's history.** Each feed fixes its ring capacity when it is created and
   keeps it for life; `max_history` seeds new feeds only. No governance call can move which
   record readers treat as latest, and there is no migration hook to rewrite one — which is
   what keeps claim 1 literally true. See [Ring capacity](#ring-capacity-is-per-feed).

The owner **can** enable/disable seeded sources within those bounds, add capped non-core
sources, register slugs, tune parameters within hard-coded ranges, pause new requests, and
withdraw fees. Pausing cannot alter an already-stored price.

**Honest limit:** influence is bounded, public, and requires its own transaction — not zero.
At the floor of 3 core + 1 added source the owner still cannot determine the median (1 of 4
is no majority) and still needs validators to agree.

### Ring capacity is per feed

Every `PriceFeed` carries its own `capacity`, seeded from `max_history` on the transaction
that creates the feed and never assigned again. `_cap(feed)` is the one definition of how
wide that ring is, and the writer, `get_latest_price`, `get_price_history` and `get_twap`
all take their width from it.

This was a reported bug, and it was real. Reads used to derive the width from the stored
array length while the writer derived it from the mutable global `max_history`. Changing
`max_history` under a feed that already held records split those two apart, in both
directions:

| Change | State before | What reads returned afterwards |
|---|---|---|
| Shrink 10 → 5 | 10 records, seqs 1–10 | Writes landed at `count % 5`; reads still walked all 10 slots. `get_latest_price` returned **seq 10** with seqs 11–15 already written and unreachable |
| Grow 4 → 12 | 4 records, wrapped | Writer appended past the ring while reads rotated around the cursor. History came back **out of time order** (`3, 6, 5, 7, 4`) and seq 3 was named latest with seq 7 written |

Both fed stale or mis-ordered records to `get_price_checked` and `get_twap` — the two reads
a consumer is most likely to price against. Note the second row: rejecting only a *smaller*
`max_history` would have left the grow bug fully live.

**What `max_history` does now.** It sets the depth of feeds created after the call. A live
feed keeps the depth it was born with. `get_feed_info(pair)` reports both numbers, so the
difference is readable on-chain rather than implied:

```bash
genlayer call <ORACLE> get_feed_info --args "ETH/USD"
# {"found": true, "capacity": 24, "records_stored": 24, "new_feed_capacity": 48, ...}
```

**Why not migrate a live ring instead.** Compacting on resize means an owner-callable path
that rewrites stored price records, which contradicts claim 1 above. It is also unbounded
work — `pairs` grows with every pair ever requested, so an eager migration across all feeds
could exceed the block gas limit and brick the parameter permanently. Fixing the width per
feed costs one `u32` per pair, stays O(1), and keeps the trust model literally true.

**The trade, stated rather than hidden:** an existing feed cannot be deepened without
deploying a new contract. Both corruption scenarios, a sweep that resizes the global before
every single write, and AST checks that no governance method can reach feed history are in
`test/direct/test_capacity.py`.

---

## Usage

### Request a price (transaction)

```bash
genlayer write <ORACLE> request_price --args "ETH/USD" --fee-value 100000000000000000
```

Returns a `price_id` like `"ETH/USD:7"`. Costs the configured fee; requests for a pair
updated within the last 60 seconds revert *before* any fetch, so the caller keeps their
money instead of buying a duplicate.

`--fee-value` is the consensus deposit and is **required** for this method — see
[Step 3](#step-3--request-a-fresh-price-needs-an-account).

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
| `set_params(...)`, `set_quant_bps(...)`, `set_fee(...)`, `set_paused(...)` | owner |
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
| `get_feed_info(pair)` | This feed's ring `capacity`, records stored, update count |
| `get_supported_pairs()`, `get_sources()`, `get_config()`, `get_stats()` | Introspection |
| `get_governance_log(count)` | Every owner action, with address and timestamp |

---

## Repository layout

```
contracts/ConsensusPrice.py   the oracle
contracts/PriceConsumer.py    reference integration, deployed and live
test/direct/                  164 tests, no server required
docs/DESIGN.md                full design rationale
docs/INTEGRATION.md           how to read this oracle from your contract
deployments.json              live addresses and transaction hashes
```

## Tests

Commands under [Running the tests locally](#running-the-tests-locally).

164 direct-mode tests covering price parsing across all six response shapes, median and
basis-point math, confidence boundaries, TWAP, symbol substitution, the ring buffer,
volatility and staleness flags, prompt-injection defenses, governance access control and
bounds, cross-contract composability, and the consensus rule itself.

`test_consensus.py` matters disproportionately: direct mode runs the leader path only and
never exercises `validator_fn`, so the leader/validator comparison is extracted into a pure
function and tested directly. It is the single most important piece of logic in the
contract.
