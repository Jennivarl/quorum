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

The consensus design is the part worth reading closely. Validators do not
compare the extracted text, because two models reading the same page will
write "40 percent" and "40%" and both are correct. They compare the
decisions those extractions produce: the verdict, and exactly which
sources dissented. Those are what a caller acts on, and they are stable
across reasonable differences in wording.
"""

from dataclasses import dataclass

from genlayer import *

from contracts.agreement import assess, classify
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

        urls = [str(u).strip() for u in (sources or []) if str(u).strip()]
        if len(urls) < 2:
            raise gl.vm.UserError(
                "corroboration needs at least two sources; one source is a "
                "quotation, not a corroboration"
            )
        if len(urls) > _MAX_SOURCES:
            raise gl.vm.UserError(f"at most {_MAX_SOURCES} sources per check")

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
                found.append(
                    {
                        "url": url,
                        "status": got.status,
                        "answer": got.answer,
                        "quote": got.quote[:_MAX_QUOTE],
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
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader = leaders_res.calldata
            mine = leader_fn()

            # Compare decisions, not prose. Two models reading the same
            # page will write "40 percent" and "40%", and rejecting the
            # leader over that would fail every check that ever ran. What
            # must match is what a caller acts on: the verdict, and which
            # sources were counted as dissenting or silent.
            if mine["verdict"] != leader["verdict"]:
                return False
            if sorted(mine["dissenting"]) != sorted(leader["dissenting"]):
                return False
            return sorted(mine["abstaining"]) == sorted(leader["abstaining"])

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
                    status=f["status"],
                    answer=f["answer"],
                    quote=f["quote"],
                )
                for f in result["found"]
            ],
            dissenting=sorted(dissenting),
            settled_by=settled_by,
            checked_by=gl.message.sender_address,
        )
        self.checks[key] = record
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
            {"url": a.url, "status": a.status, "answer": a.answer, "quote": a.quote}
            for a in record.answers
        ],
        "dissenting": list(record.dissenting),
        "settled_by": record.settled_by,
        "checked_by": record.checked_by.as_hex,
    }
