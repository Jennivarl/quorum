# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Money that moves on a verdict, and does not move when the sources disagree.

QUORUM records that publishers disagreed. This is the contract that makes
that recording cost something. Funds are deposited against a claim before it
is checked. If the sources corroborate, the money is released. If they
contest it, the money goes back, and the record says which sources caused
that and what a single-source oracle would have paid out instead.

The refusal is the product. An oracle that hands back one number gives a
consumer nothing to refuse on, so it pays out on a figure that two reputable
publishers disagree about by thirty million and nobody ever finds out.

Design notes worth reading before changing anything:

**No privileged resolver.** Anyone may call `resolve`. The outcome is fully
determined by a verdict already settled under consensus, so there is nothing
for a caller to influence, and requiring a trusted party would reintroduce
exactly the operator this whole design removes.

**State changes before value moves.** Every path marks the deal settled and
then transfers, never the other way round.

**Transfers are emitted on finalisation, not acceptance.** State on this
network has been observed readable and then rolled back. A transfer emitted
on acceptance could move real value out of a transaction that never
finalises.

**No deterministic judgement of its own.** This contract reads a stored
verdict and applies a threshold. It runs no model, fetches no page, and
needs no equivalence principle, so it settles quickly and cheaply even when
the oracle itself is struggling to reach consensus.
"""

from dataclasses import dataclass

from genlayer import *

# Ordered weakest to strongest. A deal releases only at or above its bar.
_STRENGTH = {
    "no_data": 0,
    "contested": 1,
    "majority": 2,
    "corroborated": 3,
}

_DEFAULT_MINIMUM = "majority"

STATE_OPEN = "open"
STATE_RELEASED = "released"
STATE_REFUNDED = "refunded"
STATE_CANCELLED = "cancelled"


def _as_address(value) -> Address:
    """
    Coerce whatever the calldata layer handed us into an Address.

    GenLayer decodes address-shaped arguments into `Address` objects
    regardless of the annotation, so a parameter typed `str` may arrive
    either way. Getting this wrong costs a deployment, and it has before.
    """
    if hasattr(value, "as_hex"):
        return value
    return Address(str(value).strip())


@allow_storage
@dataclass
class Deal:
    check_id: str
    claim: str
    depositor: Address
    payee: Address
    amount: u256
    state: str
    verdict: str
    agreement_percent: u256
    dissenting: u256
    reason: str
    # What an ordinary oracle would have caused. True whenever the check
    # produced a figure at all, because a single-source oracle reports a
    # figure and no spread, and a consumer holding only that would have paid.
    naive_would_pay: bool


class Escrow(gl.Contract):
    quorum: str
    minimum: str
    deals: TreeMap[str, Deal]
    ids: DynArray[str]

    def __init__(self, quorum_address: str, minimum_verdict: str = _DEFAULT_MINIMUM):
        wanted = str(minimum_verdict).strip().lower()
        if wanted not in _STRENGTH:
            raise gl.vm.UserError(
                "minimum_verdict must be one of: " + ", ".join(sorted(_STRENGTH))
            )
        self.quorum = _as_address(quorum_address).as_hex
        self.minimum = wanted

    # ----------------------------------------------------------------
    # opening
    # ----------------------------------------------------------------

    @gl.public.write.payable
    def open_deal(
        self, deal_id: str, check_id: str, claim: str, payee: str
    ) -> dict:
        """
        Deposit funds against a claim that has not been settled yet.

        The check does not need to exist at this point, and usually will
        not: the ordinary sequence is to escrow first, then run the check,
        then resolve. `cancel` exists for the case where the check never
        arrives.
        """
        key = deal_id.strip().lower()
        if key in self.deals:
            raise gl.vm.UserError(f"deal already exists: {key}")

        amount = gl.message.value
        if amount <= 0:
            raise gl.vm.UserError(
                "an escrow with nothing in it settles nothing; send value "
                "with this call"
            )

        target = _as_address(payee)
        depositor = gl.message.sender_address
        if target.as_hex.lower() == depositor.as_hex.lower():
            raise gl.vm.UserError(
                "payee and depositor are the same account, so the verdict "
                "could not change where the money ends up"
            )

        deal = Deal(
            check_id=check_id.strip().lower(),
            claim=claim.strip(),
            depositor=depositor,
            payee=target,
            amount=amount,
            state=STATE_OPEN,
            verdict="",
            agreement_percent=0,
            dissenting=0,
            reason="",
            naive_would_pay=False,
        )
        self.deals[key] = deal
        self.ids.append(key)
        return _as_dict(key, deal)

    # ----------------------------------------------------------------
    # resolving
    # ----------------------------------------------------------------

    @gl.public.write
    def resolve(self, deal_id: str) -> dict:
        """
        Read the verdict and move the money accordingly.

        Callable by anyone. The verdict was settled under consensus in
        another contract, the threshold was fixed at deployment, and this
        method has no discretion, so there is nothing a caller could bias.
        """
        key = deal_id.strip().lower()
        deal = self.deals[key]
        if deal.state != STATE_OPEN:
            raise gl.vm.UserError(f"deal is already {deal.state}: {key}")

        record = (
            gl.get_contract_at(Address(self.quorum)).view().get_check(deal.check_id)
        )
        verdict = str(record["verdict"])
        percent = int(record["agreement_percent"])
        dissenting = [str(d) for d in (record["dissenting"] or [])]
        value = str(record["consensus_value"])

        release = _STRENGTH.get(verdict, 0) >= _STRENGTH[self.minimum]

        if release:
            reason = f"{verdict} at {percent}% meets the {self.minimum} bar"
        elif verdict == "no_data":
            reason = "no source answered, so there is nothing to pay out on"
        else:
            reason = (
                f"{verdict} at {percent}%, below the {self.minimum} bar; "
                f"{len(dissenting)} source(s) disagreed, so the deposit is "
                f"returned rather than paid on a figure in dispute"
            )

        deal.state = STATE_RELEASED if release else STATE_REFUNDED
        deal.verdict = verdict
        deal.agreement_percent = percent
        deal.dissenting = len(dissenting)
        deal.reason = reason
        # A single-source oracle returns a figure and no spread, so any
        # check that produced a value at all would have been paid out on.
        deal.naive_would_pay = bool(value)
        self.deals[key] = deal

        # State is settled above before any value moves, and the transfer is
        # emitted on finalisation so a rolled-back transaction cannot move
        # real funds.
        recipient = deal.payee if release else deal.depositor
        gl.get_contract_at(recipient).emit_transfer(value=deal.amount)

        return _as_dict(key, deal)

    @gl.public.write
    def cancel(self, deal_id: str) -> dict:
        """
        Take a deposit back while the claim is still unchecked.

        Without this, a check that never finalises would strand the funds
        forever, which on a testnet that regularly fails to carry a check is
        not a hypothetical.

        It is deliberately unavailable once a verdict exists. Otherwise a
        depositor could watch the result and withdraw whenever it went
        against them, which would make the whole arrangement pointless.

        Known limitation, stated rather than hidden: a depositor can cancel
        in the window between a check being run and it being stored. A
        production version would take a deadline at open time and allow
        cancellation only after it passes.
        """
        key = deal_id.strip().lower()
        deal = self.deals[key]
        if deal.state != STATE_OPEN:
            raise gl.vm.UserError(f"deal is already {deal.state}: {key}")

        caller = gl.message.sender_address
        if caller.as_hex.lower() != deal.depositor.as_hex.lower():
            raise gl.vm.UserError("only the depositor can cancel a deal")

        already = gl.get_contract_at(Address(self.quorum)).view().is_checked(
            deal.check_id
        )
        if already:
            raise gl.vm.UserError(
                "this claim has already been checked; resolve it instead of "
                "cancelling"
            )

        deal.state = STATE_CANCELLED
        deal.reason = "cancelled by the depositor before the claim was checked"
        self.deals[key] = deal

        gl.get_contract_at(deal.depositor).emit_transfer(value=deal.amount)
        return _as_dict(key, deal)

    # ----------------------------------------------------------------
    # reading
    # ----------------------------------------------------------------

    @gl.public.view
    def get_deal(self, deal_id: str) -> dict:
        key = deal_id.strip().lower()
        return _as_dict(key, self.deals[key])

    @gl.public.view
    def deal_ids(self) -> list:
        return [d for d in self.ids]

    @gl.public.view
    def count(self) -> int:
        return len(self.ids)

    @gl.public.view
    def oracle(self) -> str:
        return self.quorum

    @gl.public.view
    def minimum_verdict(self) -> str:
        return self.minimum

    @gl.public.view
    def divergences(self) -> list:
        """
        Every deal where recording the dissent changed where the money went.

        This is the list the whole project argues for. Each entry is real
        value that a single-source oracle would have paid out, and that was
        returned instead because the sources did not agree.
        """
        out = []
        for did in self.ids:
            deal = self.deals[did]
            if deal.state == STATE_REFUNDED and deal.naive_would_pay:
                out.append(
                    {
                        "deal_id": did,
                        "claim": deal.claim,
                        "check_id": deal.check_id,
                        "verdict": deal.verdict,
                        "agreement_percent": deal.agreement_percent,
                        "dissenting": deal.dissenting,
                        "amount_returned": deal.amount,
                        "reason": deal.reason,
                    }
                )
        return out


def _as_dict(deal_id: str, deal: Deal) -> dict:
    return {
        "deal_id": deal_id,
        "check_id": deal.check_id,
        "claim": deal.claim,
        "depositor": deal.depositor.as_hex,
        "payee": deal.payee.as_hex,
        "amount": deal.amount,
        "state": deal.state,
        "verdict": deal.verdict,
        "agreement_percent": deal.agreement_percent,
        "dissenting": deal.dissenting,
        "reason": deal.reason,
        "naive_would_pay": deal.naive_would_pay,
    }
