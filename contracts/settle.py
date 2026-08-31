# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
A reference consumer for QUORUM, and an argument for why dissent belongs in
the output at all.

An oracle nobody calls is a library. This is the smallest honest thing that
depends on one: a settlement that pays out on an agreed figure and refuses
when the sources disagree.

The point it exists to make is the counterfactual. Every settlement records
both what it decided and what it *would* have decided given only a single
source's number, which is what an ordinary oracle would have handed it. When
those two differ, the difference is the entire value of the dissent record,
stated in the one place a reader cannot argue with: a stored decision that
went the other way.

There is no nondeterminism here. Reading another contract's view is exact,
so this needs no consensus block, no model, and no web access. That is
deliberate. The judgement already happened in QUORUM under consensus, and a
consumer should be able to act on it cheaply.
"""

from dataclasses import dataclass

from genlayer import *

# Ordered from weakest to strongest. A caller sets the bar it needs, and
# anything below that bar refuses.
_STRENGTH = {
    "no_data": 0,
    "contested": 1,
    "majority": 2,
    "corroborated": 3,
}

_DEFAULT_MINIMUM = "majority"


@allow_storage
@dataclass
class Settlement:
    check_id: str
    claim: str
    settled: bool
    reason: str
    value: str
    verdict: str
    agreement_percent: u256
    dissenting: DynArray[str]
    # What a single-source oracle would have returned, and whether acting on
    # it alone would have produced a different outcome.
    naive_value: str
    naive_would_settle: bool
    decided_by: Address


class Settle(gl.Contract):
    quorum: str
    minimum: str
    settlements: TreeMap[str, Settlement]
    ids: DynArray[str]

    def __init__(self, quorum_address: str, minimum_verdict: str = _DEFAULT_MINIMUM):
        wanted = minimum_verdict.strip().lower()
        if wanted not in _STRENGTH:
            raise gl.vm.UserError(
                "minimum_verdict must be one of: " + ", ".join(sorted(_STRENGTH))
            )
        # Stored as text rather than an Address because the calldata layer
        # decodes address-shaped arguments unpredictably, and this only ever
        # needs to be handed back to get_contract_at.
        self.quorum = str(quorum_address).strip()
        self.minimum = wanted

    @gl.public.write
    def settle(self, settlement_id: str, check_id: str) -> dict:
        """
        Act on a check that QUORUM has already settled.

        Refuses rather than guessing when the sources disagree. The refusal
        is the product: an oracle that returns one number gives a consumer
        nothing to refuse on.
        """
        key = settlement_id.strip().lower()
        if key in self.settlements:
            raise gl.vm.UserError(f"already settled: {key}")

        check_key = check_id.strip().lower()
        record = gl.get_contract_at(Address(self.quorum)).view().get_check(check_key)

        verdict = str(record["verdict"])
        value = str(record["consensus_value"])
        percent = int(record["agreement_percent"])
        dissenting = [str(d) for d in (record["dissenting"] or [])]

        strength = _STRENGTH.get(verdict, 0)
        required = _STRENGTH[self.minimum]
        settled = strength >= required

        if settled:
            reason = f"{verdict} at {percent}% meets the {self.minimum} bar"
        elif verdict == "no_data":
            reason = "no source answered, so there is nothing to settle on"
        else:
            reason = (
                f"{verdict} at {percent}% is below the {self.minimum} bar; "
                f"{len(dissenting)} source(s) disagreed"
            )

        # The counterfactual. A single-source oracle hands back one figure
        # with no spread, and a consumer holding only that would have acted.
        # Recording it makes the cost of not knowing legible.
        naive_value = _first_answer(record)
        naive_would_settle = bool(naive_value)

        outcome = Settlement(
            check_id=check_key,
            claim=str(record["claim"]),
            settled=settled,
            reason=reason,
            value=value if settled else "",
            verdict=verdict,
            agreement_percent=percent,
            dissenting=sorted(dissenting),
            naive_value=naive_value,
            naive_would_settle=naive_would_settle,
            decided_by=gl.message.sender_address,
        )
        self.settlements[key] = outcome
        self.ids.append(key)
        return _as_dict(key, outcome)

    @gl.public.view
    def get_settlement(self, settlement_id: str) -> dict:
        key = settlement_id.strip().lower()
        return _as_dict(key, self.settlements[key])

    @gl.public.view
    def settlement_ids(self) -> list:
        return [sid for sid in self.ids]

    @gl.public.view
    def count(self) -> int:
        return len(self.ids)

    @gl.public.view
    def oracle(self) -> str:
        """Which QUORUM deployment this consumer trusts, and to what bar."""
        return self.quorum

    @gl.public.view
    def minimum_verdict(self) -> str:
        return self.minimum

    @gl.public.view
    def divergences(self) -> list:
        """
        Every settlement where knowing the dissent changed the decision.

        This is the list that justifies the whole design. Each entry is a
        case where a single-source oracle would have been acted on and this
        consumer refused, because it could see that the sources did not
        agree.
        """
        out = []
        for sid in self.ids:
            s = self.settlements[sid]
            if s.naive_would_settle and not s.settled:
                out.append(
                    {
                        "settlement_id": sid,
                        "claim": s.claim,
                        "verdict": s.verdict,
                        "agreement_percent": s.agreement_percent,
                        "naive_value": s.naive_value,
                        "dissenting": len(s.dissenting),
                        "reason": s.reason,
                    }
                )
        return out


def _first_answer(record) -> str:
    """
    What a single-source consumer would have been handed.

    The counterfactual must not be derived from the consensus value. On a
    tie QUORUM deliberately publishes nothing, and reading it from there
    made this report that a naive consumer would have done nothing either
    - the exact opposite of the truth, and false precisely in the case the
    field exists to illustrate. Someone reading one source gets that
    source's figure whether or not the sources agreed.
    """
    for a in record["answers"] or []:
        if str(a["status"]) == "found" and str(a["answer"]).strip():
            return str(a["answer"]).strip()
    return ""


def _as_dict(settlement_id: str, s: Settlement) -> dict:
    return {
        "settlement_id": settlement_id,
        "check_id": s.check_id,
        "claim": s.claim,
        "settled": s.settled,
        "reason": s.reason,
        "value": s.value,
        "verdict": s.verdict,
        "agreement_percent": s.agreement_percent,
        "dissenting": list(s.dissenting),
        "naive_value": s.naive_value,
        "naive_would_settle": s.naive_would_settle,
        "decided_by": s.decided_by.as_hex,
    }
