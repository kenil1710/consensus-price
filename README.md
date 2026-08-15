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

**Reviewers: [start here](#testing-this-contract).** There is no frontend — this is an
Intelligent Contracts submission, and the contract itself is the deliverable. Every method
below can be called in the browser with no wallet and no install.

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
https://studio.genlayer.com/?import-contract=0x6dc688b2F104FB124B2a3bd17F7374b68dF06C53
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

Reads need no account. `request_price` needs an account with a little testnet GEN to cover
the consensus fee deposit.

### The Bradbury explorer

```
https://explorer-bradbury.genlayer.com/address/0xF6d254596B58B8c3898e33FA871ee17f68e94fB2
```

Useful for **verifying** the deployment — it shows the on-chain source, the balance, and
every transaction against the contract, including the price requests below. It is a
read-only browser: it has **no** interface for calling contract methods. Use Studio or the
CLI to actually call anything.

---

The five steps below are written as CLI commands against Bradbury. **In Studio, run the
same steps** by selecting the identical method name and arguments in the interaction panel —
the contract is the same and the fee is zeroed on both deployments. Substitute the Studionet
addresses (`0x6dc688b2…` oracle, `0x4dfBA360…` consumer) if you are reading along there.

### Step 1 — Current state (no wallet)

```bash
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_stats
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_config
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 decimals
```

`get_stats` shows total requests and unique pairs. `get_config` shows every tunable plus
`enabled_core: 7` — the live source count. `decimals` returns `18`.

Also worth calling, because it is the transparency claim made checkable:

```bash
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_sources
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_governance_log --args 20
```

`get_sources` reports per-source `ok_count`, `fail_count`, `reliability_pct`, and the real
`last_fail` string. `get_governance_log` lists every owner action ever taken, with address
and timestamp.

### Step 2 — Existing price data (no wallet)

```bash
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_latest_price --args "ETH/USD"
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_price_history --args "ETH/USD" 5
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_twap --args "ETH/USD" 5
```

Returns real prices from live requests, with the full per-source breakdown in `sources` and
the failure reason for any source that did not answer. `get_price_history` returns however
many records exist, newest first — it does not pad to the count you ask for.

Divide `price` by 10^18 for USD: `1877599524608443050000` is `$1,877.599524608443050`.

### Step 3 — Request a fresh price (needs an account)

```bash
genlayer write 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 request_price --args "ETH/USD"
```

**The fee is set to 0 on this deployment, so send no value.** The contract charges
`fee_wei` (default 0.001 GEN), but the CLI has no way to attach `msg.value` to a call —
`--fee-value` is the consensus fee deposit, not the value forwarded to the contract — so
the fee is zeroed here to keep the method reachable. The fee logic itself is covered by the
direct test suite. You still need a little GEN for the deposit.

This takes **30–60 seconds**: the leader fetches seven sources, then every validator
independently re-fetches and re-derives the median before agreeing. Watch for
`resultName: 'AGREE'`. Then:

```bash
genlayer call 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_latest_price --args "ETH/USD"
```

`timestamp` and `price_id` will have advanced, and `flags` will no longer read `FIRST`.

> **If it reverts with `[EXPECTED] fresh, retry in Ns`** — that is the 60-second per-pair
> rate limit working, not a failure. It rejects duplicate requests *before* any network
> fetch so the caller keeps their money. Wait it out, or request a different pair.

### Step 4 — A different pair, zero configuration

```bash
genlayer write 0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 request_price --args "BTC/USD"
genlayer call  0xF6d254596B58B8c3898e33FA871ee17f68e94fB2 get_latest_price --args "BTC/USD"
```

No setup was needed for BTC/USD, and none is needed for `SOL/USD`, `AVAX/USD`, or
`LINK/USD` either — exchange source symbols are derived mechanically from the pair string.
Try an invalid pair like `"NOTREAL/USD"` to watch it fail cleanly with `[TRANSIENT]` rather
than storing garbage.

### Step 5 — Composability

`PriceConsumer` is a separate contract that holds no price data of its own. Every number it
returns comes from a free cross-contract read of the oracle.

```bash
genlayer call 0x68c97558e71A8E574d7E52018115312A696146FC quote --args "ETH/USD" 2500000000000000000
```

Returns the USD value of 2.5 ETH — `value_usd_atto: '4693998811521107625000'`, about
`$4,693.99` — alongside the price, confidence, and age it used.

The more interesting call is the one that **refuses**:

```bash
genlayer call 0x68c97558e71A8E574d7E52018115312A696146FC quote --args "DOGE/USD" 1000000000000000000
# execution failed — no price stored for DOGE/USD

genlayer call 0x68c97558e71A8E574d7E52018115312A696146FC is_safe_to_trade --args "DOGE/USD"
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
       "params":[{"address":"0xF6d254596B58B8c3898e33FA871ee17f68e94fB2"}],"id":1}' \
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
pytest test/direct -q          # 132 passed
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

Commands under [Running the tests locally](#running-the-tests-locally).

132 direct-mode tests covering price parsing across all six response shapes, median and
basis-point math, confidence boundaries, TWAP, symbol substitution, the ring buffer,
volatility and staleness flags, prompt-injection defenses, governance access control and
bounds, cross-contract composability, and the consensus rule itself.

`test_consensus.py` matters disproportionately: direct mode runs the leader path only and
never exercises `validator_fn`, so the leader/validator comparison is extracted into a pure
function and tested directly. It is the single most important piece of logic in the
contract.
