# Integrating ConsensusPrice

How to read the oracle from your own contract.

Reads are **free** — they are view calls, they cost no gas, they send no transaction, and
they do not require the oracle's fee. Your contract can read a price on every single call
without paying anything.

---

## 1. Copy the interface

Paste this into your contract. Declare only the methods you actually call.

```python
from genlayer import *
import typing


@gl.contract_interface
class IConsensusPrice:
    class View:
        def get_price_checked(self, pair: str, max_age_seconds: int,
                              min_confidence: str) -> typing.Any: ...

        def get_latest_price(self, pair: str) -> typing.Any: ...

        def get_twap(self, pair: str, count: int) -> typing.Any: ...

        def get_price_scaled(self, pair: str, decimals: int) -> int: ...

        def decimals(self) -> int: ...

    class Write:
        pass
```

## 2. Read a price

```python
class MyContract(gl.Contract):
    oracle: Address

    def __init__(self, oracle: typing.Any):
        # A 40-hex-char argument arrives already decoded as an Address from the
        # CLI, and as a plain hex string from a contract caller. str() collapses
        # both to hex, so the constructor accepts either.
        self.oracle = Address(str(oracle))

    @gl.public.view
    def value_of(self, amount_atto: int) -> int:
        rec = IConsensusPrice(self.oracle).view().get_price_checked(
            "ETH/USD", 900, "MEDIUM")
        price = int(rec["price"])
        return (int(amount_atto) * price) // (10 ** 18)
```

---

## 3. Which read method to use

### `get_price_checked(pair, max_age_seconds, min_confidence)` — start here

**Reverts** rather than returning a price you should not act on. This is the safe default
and what most integrations want.

```python
rec = oracle.view().get_price_checked("ETH/USD", 900, "MEDIUM")
```

| Argument | Meaning |
|---|---|
| `max_age_seconds` | Reverts if the stored price is older. `0` disables the age check. |
| `min_confidence` | `"LOW"`, `"MEDIUM"`, or `"HIGH"`. Reverts if the record scores below it. |

Recommended settings:

| Use case | `max_age_seconds` | `min_confidence` |
|---|---|---|
| Liquidation / settlement | `300` | `"HIGH"` |
| Lending, collateral valuation | `900` | `"MEDIUM"` |
| Display, analytics, non-financial | `3600` | `"LOW"` |

A revert is the correct outcome, not a failure to handle. The alternative is your contract
silently acting on a stale or contested number.

### `get_latest_price(pair)` — when you want to degrade gracefully

Never reverts on a missing price; returns `{"found": false, "pair": ...}`. Use it when you
want to inspect *why* a price is unusable and respond, rather than aborting the transaction.

```python
rec = oracle.view().get_latest_price("ETH/USD")
if not rec["found"]:
    return {"ok": False, "reason": "no price yet"}
if rec["is_stale"]:
    return {"ok": False, "reason": "stale"}
```

### `get_twap(pair, count)` — manipulation resistance across time

The median already gives resistance across *sources*. TWAP adds resistance across *time*,
weighting each record by how long it stood as the latest price rather than by sample count.
Use it for anything where a single-block price spike should not be actionable.

```python
out = oracle.view().get_twap("ETH/USD", 12)
if out["found"]:
    price = int(out["twap"])
```

### `get_price_scaled(pair, decimals)` — when you are not 18-decimal

```python
price_8dp = oracle.view().get_price_scaled("ETH/USD", 8)   # Chainlink-style
```

### `get_feed_info(pair)` — how deep this feed's history actually goes

Each feed's ring capacity is fixed when the feed is first created and never changes, so
`get_twap(pair, 0)` and `get_price_history(pair, 0)` span *that feed's* depth, not whatever
the oracle's current `max_history` parameter says. The two can legitimately differ, and this
is the read that tells you which is which:

```python
info = oracle.view().get_feed_info("ETH/USD")
depth = int(info["capacity"])           # what this feed will ever hold
have  = int(info["records_stored"])     # what it holds right now
```

If your strategy needs a minimum window, check `records_stored` before trusting a TWAP —
a feed three records old gives you a three-record average regardless of the count you pass.
`get_twap` already reports `samples` and `window_seconds` for exactly this reason; prefer
asserting on those over assuming a depth.

Governance cannot resize a live feed, so a capacity you read once will not move underneath
you. See "Ring capacity is per feed" in the README for why that guarantee exists.

---

## 4. The decimals contract

**Every price is an integer at 18 decimals (atto-USD).** `decimals()` returns `18` and this
will not change.

```
1902500000000000000000  ==  $1,902.50
```

Convert by dividing by `10 ** 18`. Do this at the display boundary only — keep integer math
end to end inside the contract.

Valuing an amount that is itself 18-decimal takes exactly one division:

```python
value_usd_atto = (amount_atto * price) // (10 ** 18)
```

Both operands are 18-decimal, so the single division returns an 18-decimal result. There is
no float anywhere in this path, and there should not be one in yours.

---

## 5. Confidence semantics

Computed independently by each node from its own source set, then required to match
**exactly** across consensus. An accepted round cannot have one node saying `HIGH` and
another `MEDIUM`, so a `min_confidence` gate you set can never be straddled by two outputs
the oracle would both have accepted.

| Value | Meaning |
|---|---|
| `HIGH` | ≥4 sources responded and ≥80% sit within 1% of the median |
| `MEDIUM` | ≥3 sources responded and ≥60% sit within 2.5% of the median |
| `LOW` | Neither threshold met, **or** the price came only from rendered pages with no deterministic source to anchor against |

`LOW` is not "probably fine." It means the sources materially disagreed, and you should
treat it as a signal that something is happening in the market or in the source set.

`spread_bps` on every record gives the number behind the label: the widest deviation from the
median, in basis points, measured over quantized source prices (see §5b). It reads `0` when
every source landed in the same bucket, which is the common case for a liquid pair.

---

## 5b. Prices are quantized — what that means for you

**The stored price is a bucket midpoint, not a raw median.** Every price snaps onto a lattice
before consensus, validators agree by landing in the *same* bucket, and the stored value is
derived from the bucket. This is what makes the number binding: two outputs the oracle would
both accept for one request cannot differ, so a second request cannot re-quote you on noise.

Two fields on every record expose it:

| Field | Example | Meaning |
|---|---|---|
| `quant_bps` | `50` | Lattice width, in bps of the price's scale anchor |
| `bucket` | `"380@5000000000000000000"` | `idx@step` — the price is the midpoint of `[idx*step, (idx+1)*step)` |

What this changes for an integrator:

- **Resolution.** At `quant_bps = 50` a bucket is 20–50 bps wide — about `$5` at ETH ≈
  `$1,900`. The stored price can sit up to half a bucket (≈13 bps) from the median that
  produced it. If your product needs finer resolution than that, this oracle is not the right
  input; do not paper over it with your own interpolation.
- **Stability is a feature.** Two requests inside one bucket return the identical `u256`, so
  quotes derived from it are stable across refreshes. Compare `bucket` between two reads to
  see whether the market actually moved or you simply re-read the same consensus.
- **Do not re-quantize.** The value you read is already on the lattice. Rounding it again
  only adds error.
- **`get_twap` is not on the lattice**, by design — it is a time-weighted average of
  lattice points, so it lands between them.

---

## 6. Flags

| Flag | Meaning | What to do |
|---|---|---|
| `FIRST` | First record for this pair; no previous price to compare against | Nothing. There is no deviation baseline yet. |
| `HIGH_VOLATILITY` | Moved more than 10% from the previous record | See below. |

### Handling `HIGH_VOLATILITY`

The oracle **flags** large moves; it never rejects them. A flash crash is real data, and an
oracle that suppresses it lies during exactly the events it exists for. The judgment call
belongs to you, so it is handed to you explicitly.

```python
rec = oracle.view().get_latest_price("ETH/USD")

if "HIGH_VOLATILITY" in str(rec["flags"]):
    # A 10%+ move is either a genuine market event or a source-set anomaly.
    # Do not liquidate on a single such record. Two reasonable responses:
    #
    #   1. Wait for the next update and confirm the move persists.
    #   2. Settle against get_twap() instead, which dampens a single spike.
    out = oracle.view().get_twap("ETH/USD", 12)
    price = int(out["twap"]) if out["found"] else None
else:
    price = int(rec["price"])
```

The wrong response is ignoring the flag. It is set precisely when the number is least safe
to act on blindly.

---

## 7. Keeping the price fresh

The oracle is **pull-based**: it holds the last price someone paid to fetch. Nobody updates
it on your behalf.

```python
if oracle.view().is_stale("ETH/USD"):
    # someone must send a request_price transaction
```

Three ways to handle this:

1. **Let your users trigger it.** Call `is_stale()` in your UI and prompt for a refresh.
2. **Refresh in your own write path.** Call `request_price` from your contract before
   settling, paying the fee yourself.
3. **Run a keeper.** A cron job calling `request_price` on your pairs keeps the feed warm
   for every consumer at once.

Requests for a pair updated within the last 60 seconds revert *before* any network fetch, so
a redundant refresh returns the caller's money rather than buying a duplicate. Two keepers
racing is not an expensive mistake.

---

## 8. Reference implementation

`contracts/PriceConsumer.py` is a complete, deployed, working consumer — copy from it
directly. It is live on both networks:

| Network | PriceConsumer | reading oracle |
|---|---|---|
| Bradbury | `0xC20700C3021bd620f076967a04d916dBfB8F05cf` | `0x8c2Dd5E8B305F6B9659F058Ac86095bbc9733146` |
| Studionet | `0x3bAb00032b29Db9E14f12a3D975F6D4Add77F8F9` | `0xEB6FA760Ff86E50ef9089ed194d919ad0A155Fe0` |

It demonstrates both integration styles side by side:

- `quote(pair, amount)` — uses `get_price_checked`, reverts on anything unsafe
- `is_safe_to_trade(pair)` — uses `get_latest_price`, reports the reason instead
- `twap_quote(pair, count)` — time-weighted settlement
- `record_quote(pair, amount)` — a write path settling against the oracle in its own transaction

Verified live, against real prices:

```
$ genlayer call 0x3bAb0...F8F9 quote --args "ETH/USD" 2500000000000000000
{
  pair: 'ETH/USD',
  amount_atto:    '2500000000000000000',      # 2.5 ETH
  price:          '2425000000000000000000',   # bucket 242, a midpoint
  value_usd_atto: '6062500000000000000000',   # $6,062.50 — exact, not approximate
  confidence: 'HIGH',
  flags: 'FIRST',
  age_seconds: 410
}

$ genlayer call 0x3bAb0...F8F9 is_safe_to_trade --args "DOGE/USD"
{ safe: false, reason: 'no price for DOGE/USD' }

# and the same quote once that ETH record aged past the consumer's 900s max_age:
$ genlayer call 0x3bAb0...F8F9 quote --args "ETH/USD" 2500000000000000000
execution failed          # [EXPECTED] stale — correctly refused rather than served
```

The last two calls are the point. The graceful path explained why it had nothing for
`DOGE/USD`, and the strict path refused a real ETH price purely because it had aged past the
consumer's own freshness bar. Neither one invented a number, and neither one served a stale
one silently.

---

## 9. Errors you may see

All revert messages carry a class prefix.

| Prefix | Meaning | Retry? |
|---|---|---|
| `[EXPECTED]` | Business logic: bad pair, underpaid, paused, too soon, stale, below required confidence | No — fix the call |
| `[EXTERNAL]` | A source returned 4xx. Recorded per-source; does not fail the request unless too few survive | N/A |
| `[TRANSIENT]` | Fewer than `min_sources` responded, or a network-level failure | Yes |

`[TRANSIENT]` on `request_price` means the request failed cleanly and **no bad price was
stored**. Retry it.

Check which sources are actually healthy before assuming the oracle is at fault:

```bash
genlayer call <ORACLE> get_sources
```

Every source reports `ok_count`, `fail_count`, `reliability_pct`, and `last_fail` with the
real reason — for example `[EXTERNAL] http 451` for an endpoint geo-blocking validator
infrastructure.
