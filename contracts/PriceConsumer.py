# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# PriceConsumer - reference integration for ConsensusPrice.
#
# This contract exists to prove ConsensusPrice is infrastructure rather than a
# standalone tool, and to give other builders something to copy. It holds no
# price data of its own: every value it reports comes from a cross-contract read
# of the oracle, for free, with no transaction on the oracle side.
#
# The pattern that matters is get_price_checked(): it reverts on a missing,
# stale or low-confidence price instead of returning one. A consumer that uses
# it cannot silently act on a bad number, which is the usual way price oracles
# hurt the things built on them.

from genlayer import *

import typing


@gl.contract_interface
class IConsensusPrice:
    """Copy this block into your own contract to read ConsensusPrice."""

    class View:
        def get_price_checked(self, pair: str, max_age_seconds: int,
                              min_confidence: str) -> typing.Any: ...

        def get_latest_price(self, pair: str) -> typing.Any: ...

        def get_twap(self, pair: str, count: int) -> typing.Any: ...

        def decimals(self) -> int: ...

    class Write:
        pass


class PriceConsumer(gl.Contract):
    oracle: Address
    max_age: u256
    min_confidence: str
    quote_count: u256
    last_value_atto: u256

    def __init__(self, oracle: typing.Any, max_age_seconds: int, min_confidence: str):
        # A 40-hex-char argument arrives already decoded as an Address from the
        # CLI, and as a plain hex string from a contract caller. str() collapses
        # both to hex, so the constructor accepts either.
        self.oracle = Address(str(oracle))
        self.max_age = u256(int(max_age_seconds))
        self.min_confidence = str(min_confidence)
        self.quote_count = u256(0)
        self.last_value_atto = u256(0)

    def _oracle(self) -> typing.Any:
        return IConsensusPrice(self.oracle)

    @gl.public.view
    def quote(self, pair: str, amount_atto: int) -> typing.Any:
        """Value `amount_atto` of the base asset in USD.

        Reverts if the oracle price is missing, stale, or below the confidence
        this consumer requires - the caller never receives an unsafe number.
        """
        rec = self._oracle().view().get_price_checked(
            pair, int(self.max_age), self.min_confidence)
        price = int(rec["price"])
        amt = int(amount_atto)
        if amt < 0:
            raise gl.vm.UserError("[EXPECTED] negative amount")
        # both sides are 18-decimal, so one division keeps the result 18-decimal
        return {
            "pair": str(rec["pair"]),
            "amount_atto": amt,
            "value_usd_atto": (amt * price) // (10 ** 18),
            "price": price,
            "confidence": str(rec["confidence"]),
            "flags": str(rec["flags"]),
            "age_seconds": int(rec["age_seconds"]),
        }

    @gl.public.view
    def is_safe_to_trade(self, pair: str) -> typing.Any:
        """Non-reverting variant: report why a price is unusable rather than
        failing, for callers that want to degrade gracefully."""
        rec = self._oracle().view().get_latest_price(pair)
        if not rec["found"]:
            return {"safe": False, "reason": "no price for " + str(pair)}
        if rec["is_stale"]:
            return {"safe": False, "reason": "stale: " + str(rec["age_seconds"]) + "s"}
        if "HIGH_VOLATILITY" in str(rec["flags"]):
            return {"safe": False, "reason": "high volatility, wait for the next update"}
        if str(rec["confidence"]) == "LOW":
            return {"safe": False, "reason": "sources disagree, spread "
                    + str(rec["spread_bps"]) + " bps"}
        return {"safe": True, "reason": "", "price": int(rec["price"])}

    @gl.public.view
    def twap_quote(self, pair: str, count: int) -> typing.Any:
        """Time-weighted price, for consumers that want manipulation resistance
        across time rather than only across sources."""
        out = self._oracle().view().get_twap(pair, int(count))
        if not out["found"]:
            raise gl.vm.UserError("[EXPECTED] no history for " + str(pair))
        return out

    @gl.public.write
    def record_quote(self, pair: str, amount_atto: int) -> int:
        """Persist a quote, demonstrating that a write path can settle against
        the oracle inside its own transaction."""
        out = self.quote(pair, amount_atto)
        value = int(out["value_usd_atto"])
        self.last_value_atto = u256(value)
        self.quote_count = u256(int(self.quote_count) + 1)
        return value

    @gl.public.view
    def get_config(self) -> typing.Any:
        return {
            "oracle": self.oracle.as_hex,
            "max_age_seconds": int(self.max_age),
            "min_confidence": str(self.min_confidence),
            "quote_count": int(self.quote_count),
            "last_value_atto": int(self.last_value_atto),
        }
