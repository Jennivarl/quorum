# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
QUORUM: a fact is only as good as the number of independent sources
that agree on it, so record how many did, and name the ones that did not.

An oracle that reads one page and returns a number tells you what one
publisher said. If that publisher is wrong, or was edited, or is the party
with an interest in the answer, the contract consuming it has no way to
know. Existing web-reading contracts on GenLayer fetch a single URL and
reach consensus on its contents, which answers "what does this page say"
rather than "is this true".

This reads several independent sources and reports the disagreement as a
first-class output. A number three sources agree on is a different thing
from the same number with two sources contradicting it, and a caller
deciding whether to pay out on it deserves to know which one it has.

How a check runs:

  1. Every source is fetched from whatever URL the caller supplied.
     Archived or revision-pinned URLs are strongly preferred, because a
     page that changes between validators fetching it makes them disagree
     for reasons that have nothing to do with the claim.
  2. Each source is read in isolation, one prompt per source, to find what
     that source alone says. See judgment.py for why batching them would
     quietly destroy the premise.
  3. Answers are compared by arithmetic wherever possible: percentages,
     dates, counts, and yes or no all have objective agreement rules, and
     asking a model to compare them would only add a chance of being wrong
     about something that was never in doubt.
  4. Only genuine prose falls through to the model for reconciliation.

The consensus design is the part worth reading closely, and the rule is
that anything durable enough to be read as evidence has to be attested.
Three things are checked by every validator independently:

  Quotations, by finding them. A stored quote must appear verbatim in the
  copy of the page that validator fetched for itself. This is what stops a
  leader inventing a plausible sentence and having it displayed to readers
  as a receipt.

  Values, by reading them again. Numbers, percentages, dates and yes or no
  answers are compared as values under the usual tolerance, so a validator
  has to have read the same figure, not merely agreed about the outcome.

  Decisions, by deriving them. The verdict and the lists of dissenting and
  silent sources, which is what a caller actually acts on.

What is deliberately not compared is prose wording. Two models reading the
same page write "40 percent" and "40%" and both are correct, so prose is
attested by its quote being real and by the reconciliation step, never by
string equality.

Independence is enforced rather than assumed. Five pages from a single
publisher is not corroboration, and the stored record would not otherwise
distinguish it from five independent ones. Sources may be given as an
archive URL paired with the origin it was published at, and the check is
rejected when two origins share a host.
"""

from dataclasses import dataclass

from genlayer import *

from contracts.agreement import (
    answers_attest,
    assess,
    classify,
    host_of,
    quote_is_verbatim,
)
from contracts.judgment import (
    ANSWER_FOUND,
    build_extraction_prompt,
    build_reconciliation_prompt,
    parse_extraction,
    parse_reconciliation,
)

# Each source costs a fetch and a prompt on every validator, so the cap is
# a real cost control rather than a formality. Corroboration also stops
# paying for itself well before this: the difference between three sources
# and four is large, between eleven and twelve is noise.
_MAX_SOURCES = 8

# Quotes are stored so a reader can check the contract's work, but storage
# is replicated and kept indefinitely, so they are truncated rather than
# kept whole. A sentence is enough to find the passage in the source.
_MAX_QUOTE = 240


@allow_storage
@dataclass
class SourceAnswer:
    url: str
    # Where the claim was originally published, as distinct from the
    # archived copy actually fetched. Independence is judged on this, and a
    # reader auditing the check needs it, so it belongs on chain rather
    # than in a file the frontend happens to ship.
    origin: str
    status: str
    answer: str
    quote: str


@allow_storage
@dataclass
class CheckRecord:
    claim: str
    verdict: str
    consensus_value: str
    agreement_percent: u256
    sources_answered: u256
    sources_dissenting: u256
    sources_silent: u256
    answers: DynArray[SourceAnswer]
    dissenting: DynArray[str]
    settled_by: str
    checked_by: Address


class Quorum(gl.Contract):
    checks: TreeMap[str, CheckRecord]
    # A TreeMap cannot be walked from outside the contract, so an archive of
    # past checks would be unreadable without keeping the keys in order as
    # well. Insertion order is the useful order here: it is the order the
    # checks were actually settled in.
    ids: DynArray[str]

    def __init__(self):
        pass

    @gl.public.write
    def check(self, check_id: str, claim: str, sources: list) -> dict:
        """
        Read every source, decide whether they agree, and store the result
        along with who dissented.

        `sources` should be archived or revision-pinned URLs. A live page
        that changes between two validators fetching it produces a
        disagreement about the page rather than about the claim, and the
        transaction fails for a reason unrelated to the question asked.
        """
        key = check_id.strip().lower()
        if key in self.checks:
            raise gl.vm.UserError(f"already checked: {key}")

        urls = []
        origins = []
        for entry in sources or []:
            if isinstance(entry, dict):
                url = str(entry.get("url", "") or "").strip()
                origin = str(entry.get("origin", "") or "").strip() or url
            else:
                url = str(entry).strip()
                origin = url
            if url:
                urls.append(url)
                origins.append(origin)

        if len(urls) < 2:
            raise gl.vm.UserError(
                "corroboration needs at least two sources; one source is a "
                "quotation, not a corroboration"
            )
        if len(urls) > _MAX_SOURCES:
            raise gl.vm.UserError(f"at most {_MAX_SOURCES} sources per check")
        if len(set(urls)) != len(urls):
            raise gl.vm.UserError("the same URL is listed more than once")

        # Independence is enforced here rather than trusted, because a
        # check over five pages from one publisher is not corroboration and
        # would otherwise be indistinguishable, in the stored record, from
        # one over five independent ones.
        #
        # It is judged on the origin, not the fetched URL, so that archived
        # copies served from a single host still count as independent when
        # they were published independently. That is the honest reading:
        # what matters is who made the claim, not who is hosting the copy.
        hosts = [host_of(o) for o in origins]
        repeated = sorted({h for h in hosts if hosts.count(h) > 1})
        if repeated:
            raise gl.vm.UserError(
                "sources must be independent publishers; more than one is "
                "from " + ", ".join(repeated)
            )

        claim_text = claim.strip()

        def leader_fn():
            # One fetch and one prompt per source, each prompt seeing only
            # its own document. Reading them together would let a confident
            # source colour an ambiguous one and manufacture agreement.
            found = []
            for url in urls:
                try:
                    page = gl.nondet.web.render(url, mode="text")
                except Exception:
                    found.append(
                        {"url": url, "status": "unreadable", "answer": "", "quote": ""}
                    )
                    continue
                raw = gl.nondet.exec_prompt(
                    build_extraction_prompt(claim_text, page), response_format="json"
                )
                got = parse_extraction(raw)
                quote = got.quote[:_MAX_QUOTE]
                # A quote that cannot be found in the page is a paraphrase,
                # and storing it would hand a reader something that looks
                # like evidence and is not. Drop it and keep the answer.
                if quote and not quote_is_verbatim(quote, page):
                    quote = ""
                found.append(
                    {
                        "url": url,
                        "status": got.status,
                        "answer": got.answer,
                        "quote": quote,
                    }
                )

            # Classification and agreement are deterministic, and are run
            # in here so the verdict itself is part of what consensus
            # covers rather than something each node derives afterwards.
            classified = [
                classify(f["url"], f["answer"] if f["status"] == ANSWER_FOUND else "")
                for f in found
            ]
            verdict = assess(classified)

            return {
                "found": found,
                "verdict": verdict.verdict,
                "value": verdict.consensus_value,
                "agreeing": verdict.agreeing,
                "dissenting": verdict.dissenting,
                "abstaining": verdict.abstaining,
                "percent": verdict.agreement_ratio_percent,
                "needs_model": verdict.needs_model,
            }

        def validator_fn(leaders_res) -> bool:
            """
            Attest everything the contract is about to store, not just the
            verdict.

            An earlier version compared only the verdict and the dissent
            lists. That left the per-source answers and the quotations
            unattested, which is a real hole: those are shown to readers as
            evidence, and a leader could have invented them without any
            validator disagreeing. Anything durable enough to be treated as
            evidence has to be covered here.

            The fetch loop is written out again rather than shared with
            leader_fn because genvm-lint cannot trace gl.nondet calls
            through a helper, and because the point is that this validator
            reads the pages itself instead of taking the leader's word for
            what they contained.
            """
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader = leaders_res.calldata

            claimed = leader["found"]
            if len(claimed) != len(urls):
                return False

            mine = []
            for i, url in enumerate(urls):
                # The leader must have read the sources it was asked for,
                # in the order it was asked for them.
                if str(claimed[i]["url"]) != url:
                    return False

                try:
                    page = gl.nondet.web.render(url, mode="text")
                except Exception:
                    mine.append(
                        {"url": url, "status": "unreadable", "answer": "", "quote": ""}
                    )
                    continue

                # Check the leader's quote against the copy this validator
                # fetched. This is what turns a stored quotation from an
                # assertion into something consensus covers, and it costs
                # nothing beyond the fetch already being made.
                leader_quote = str(claimed[i]["quote"] or "")
                if leader_quote and not quote_is_verbatim(leader_quote, page):
                    return False

                raw = gl.nondet.exec_prompt(
                    build_extraction_prompt(claim_text, page), response_format="json"
                )
                got = parse_extraction(raw)
                quote = got.quote[:_MAX_QUOTE]
                if quote and not quote_is_verbatim(quote, page):
                    quote = ""
                mine.append(
                    {
                        "url": url,
                        "status": got.status,
                        "answer": got.answer,
                        "quote": quote,
                    }
                )

                # The stored value has to be one this validator can sign,
                # compared as a value rather than as a string.
                leader_answer = (
                    str(claimed[i]["answer"] or "")
                    if str(claimed[i]["status"]) == ANSWER_FOUND
                    else ""
                )
                my_answer = got.answer if got.status == ANSWER_FOUND else ""
                if not answers_attest(leader_answer, my_answer):
                    return False

            classified = [
                classify(f["url"], f["answer"] if f["status"] == ANSWER_FOUND else "")
                for f in mine
            ]
            verdict = assess(classified)

            # Then the decisions, as before. Two models will word the same
            # finding differently, so what must match is what a caller acts
            # on: the verdict, and exactly who dissented or stayed silent.
            if verdict.verdict != leader["verdict"]:
                return False
            if sorted(verdict.dissenting) != sorted(leader["dissenting"]):
                return False
            if sorted(verdict.abstaining) != sorted(leader["abstaining"]):
                return False

            # The headline value is displayed as the answer, so it must be
            # one of the answers just attested rather than free text.
            value = str(leader["value"] or "")
            if value and value not in [str(f["answer"] or "") for f in claimed]:
                return False

            return True

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        verdict = result["verdict"]
        value = result["value"]
        agreeing = list(result["agreeing"])
        dissenting = list(result["dissenting"])
        settled_by = "arithmetic"

        if result["needs_model"]:
            value, agreeing, dissenting = self._reconcile(claim_text, result["found"])
            answered = len(agreeing) + len(dissenting)
            if not answered:
                verdict = "no_data"
            elif not dissenting:
                verdict = "corroborated"
            elif len(agreeing) > len(dissenting):
                verdict = "majority"
            else:
                verdict = "contested"
            settled_by = "judgment"

        answered = len(agreeing) + len(dissenting)
        percent = (len(agreeing) * 100) // answered if answered else 0

        record = CheckRecord(
            claim=claim_text,
            verdict=verdict,
            consensus_value=value,
            agreement_percent=percent,
            sources_answered=answered,
            sources_dissenting=len(dissenting),
            sources_silent=len(result["abstaining"]),
            answers=[
                SourceAnswer(
                    url=f["url"],
                    origin=origins[i],
                    status=f["status"],
                    answer=f["answer"],
                    quote=f["quote"],
                )
                for i, f in enumerate(result["found"])
            ],
            dissenting=sorted(dissenting),
            settled_by=settled_by,
            checked_by=gl.message.sender_address,
        )
        self.checks[key] = record
        self.ids.append(key)
        return _as_dict(record)

    def _reconcile(self, claim: str, found: list) -> tuple:
        """
        Ask the model which prose answers are making the same claim.

        Only reached when arithmetic could not settle it, which means the
        answers are sentences rather than numbers. The model is given the
        answers alone, never the source URLs, because which outlet said
        something should not influence whether it agrees with another.
        """
        answered = [f for f in found if f["status"] == ANSWER_FOUND and f["answer"]]
        if not answered:
            return "", [], []

        texts = [f["answer"] for f in answered]

        def leader_fn():
            raw = gl.nondet.exec_prompt(
                build_reconciliation_prompt(claim, texts), response_format="json"
            )
            got = parse_reconciliation(raw, len(texts))
            return {
                "consensus": got.consensus,
                "agreeing": got.agreeing,
                "dissenting": got.dissenting,
            }

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader = leaders_res.calldata
            mine = leader_fn()
            # The split is the decision; the summary sentence may vary.
            return sorted(mine["agreeing"]) == sorted(leader["agreeing"])

        out = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        return (
            out["consensus"],
            [answered[i]["url"] for i in out["agreeing"]],
            [answered[i]["url"] for i in out["dissenting"]],
        )

    @gl.public.view
    def get_check(self, check_id: str) -> dict:
        return _as_dict(self.checks[check_id.strip().lower()])

    @gl.public.view
    def verdict_of(self, check_id: str) -> str:
        """Just the verdict, for callers that only branch on it."""
        return self.checks[check_id.strip().lower()].verdict

    @gl.public.view
    def is_checked(self, check_id: str) -> bool:
        return check_id.strip().lower() in self.checks

    @gl.public.view
    def check_ids(self) -> list:
        """Every check this contract has settled, oldest first."""
        return [cid for cid in self.ids]

    @gl.public.view
    def count(self) -> int:
        return len(self.ids)

    @gl.public.view
    def summaries(self) -> list:
        """
        Enough of every check to render an index, in one call.

        Reading the archive as one call per id would be N round trips to
        list N rows, and the quotes and per-source answers are most of the
        payload while being none of what an index shows. This returns the
        verdict line only; the full record is one `get_check` away.
        """
        out = []
        for cid in self.ids:
            record = self.checks[cid]
            out.append(
                {
                    "check_id": cid,
                    "claim": record.claim,
                    "verdict": record.verdict,
                    "consensus_value": record.consensus_value,
                    "agreement_percent": record.agreement_percent,
                    "sources_answered": record.sources_answered,
                    "sources_dissenting": record.sources_dissenting,
                    "sources_silent": record.sources_silent,
                    "settled_by": record.settled_by,
                }
            )
        return out


def _as_dict(record: CheckRecord) -> dict:
    return {
        "claim": record.claim,
        "verdict": record.verdict,
        "consensus_value": record.consensus_value,
        "agreement_percent": record.agreement_percent,
        "sources_answered": record.sources_answered,
        "sources_dissenting": record.sources_dissenting,
        "sources_silent": record.sources_silent,
        "answers": [
            {
                "url": a.url,
                "origin": a.origin,
                "status": a.status,
                "answer": a.answer,
                "quote": a.quote,
            }
            for a in record.answers
        ],
        "dissenting": list(record.dissenting),
        "settled_by": record.settled_by,
        "checked_by": record.checked_by.as_hex,
    }
