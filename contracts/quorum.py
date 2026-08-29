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
same page write "40 percent" and "40%" and both are correct, so demanding
string equality would fail honest checks. Nothing unattested is stored in
its place: where prose settles a check, the recorded value is the agreeing
source's own quote, which every validator verified verbatim against the
page it fetched itself. The model is never asked to write a summary, so
there is no sentence on chain that consensus did not check.

Independence is enforced rather than assumed. Five pages from a single
publisher is not corroboration, and the stored record would not otherwise
distinguish it from five independent ones. It is judged on the host of the
URL the contract fetches, which is the one part of a source the caller
cannot restate. An earlier version accepted a separate publisher name
alongside each URL so that archived copies could still count as
independent; that made the test caller-controlled, since two pages from one
publisher passed by declaring different origins. Archived copies from a
single host now count as one publisher, which refuses some checks that were
in fact independent rather than accepting some that were not.
"""

from dataclasses import dataclass

from genlayer import *

from contracts.agreement import (
    answer_grounded_in_quote,
    answers_attest,
    assess,
    classify,
    host_of,
    same_publisher,
    quote_is_verbatim,
)
from contracts.judgment import (
    ANSWER_FOUND,
    build_extraction_prompt,
    build_reconciliation_prompt,
    build_support_prompt,
    parse_extraction,
    parse_reconciliation,
    parse_support,
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
        for entry in sources or []:
            if isinstance(entry, dict):
                # Only the URL is read. An earlier version accepted a
                # separate `origin` naming the publisher, so that archived
                # copies could still count as independent. That handed the
                # caller the independence test: two pages from one
                # publisher passed by declaring different origins. Any such
                # field is now ignored.
                url = str(entry.get("url", "") or "").strip()
            else:
                url = str(entry).strip()
            if url:
                urls.append(url)

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
        # It is judged on the host of the URL the contract actually
        # fetches, because that is the one thing here the caller cannot
        # restate. The cost is that archived copies served from a single
        # host now count as one publisher, so a check built entirely out of
        # one archive is rejected. That is the conservative direction to
        # fail in: it refuses checks that might be independent, rather than
        # accepting checks that are not.
        hosts = [host_of(u) for u in urls]
        clashes = sorted(
            {
                " and ".join(sorted((hosts[i], hosts[j])))
                for i in range(len(hosts))
                for j in range(i + 1, len(hosts))
                if same_publisher(hosts[i], hosts[j])
            }
        )
        if clashes:
            raise gl.vm.UserError(
                "sources must be independent publishers; these are the same "
                "publisher: " + "; ".join(clashes)
            )

        claim_text = claim.strip()
        # One consensus round per source, rather than one round covering
        # all of them.
        #
        # The total work is identical. What changes is how much a single
        # round has to finish before it times out, and on this network that
        # is the whole difference. Measured back to back: validators doing
        # no web work settled in about 25 seconds every time, validators
        # doing two fetches in one round never reached a terminal state at
        # all. Every check QUORUM can legally accept has at least two
        # sources, so the old shape could not reliably complete a single
        # check it was willing to run.
        #
        # Splitting also removes the need to attest the verdict inside a
        # block. The verdict is a pure function of the per-source answers,
        # so once each source is attested in its own round, every node
        # derives the same verdict from the same inputs as ordinary
        # contract code, which consensus already covers. Comparing it
        # inside the block was guarding something that could not differ.
        found = []
        for url in urls:

            def leader_fn(url=url):
                page = ""
                try:
                    # A plain GET, not `render`. `render` returns the page
                    # "after rendering it in a browser-like environment",
                    # which is a browser per call on every validator. It is
                    # also the less honest fetch here: a rendered page
                    # depends on script timing, so two validators can
                    # legitimately see different text and disagree about the
                    # page rather than about the claim. A response body is
                    # the same bytes for everyone, which is what quoting
                    # needs. The cost is that a redirect is not followed, so
                    # a source that moves is recorded unreadable instead of
                    # silently resolved somewhere else.
                    resp = gl.nondet.web.get(url)
                    if resp.status < 400:
                        page = (resp.body or b"").decode("utf-8", errors="replace")
                except Exception:
                    page = ""

                # An error page, a redirect we did not follow, or nothing at
                # all. All three mean the same thing here: this source did
                # not give us a document to read, which is recorded rather
                # than guessed around.
                if not page.strip():
                    return {"status": "unreadable", "answer": "", "quote": ""}

                raw = gl.nondet.exec_prompt(
                    build_extraction_prompt(claim_text, page),
                    response_format="json",
                )
                got = parse_extraction(raw)
                quote = got.quote[:_MAX_QUOTE]
                # A quote that is not in the page is a paraphrase, and
                # storing it would hand a reader something that looks like
                # evidence and is not.
                if quote and not quote_is_verbatim(quote, page):
                    quote = ""
                return {
                    "status": got.status,
                    "answer": got.answer,
                    "quote": quote,
                }

            def validator_fn(leaders_res, url=url) -> bool:
                """
                Attest this one source against a page this validator read
                for itself, cheapest check first.

                  1. Is the quote real? Verbatim in my own copy. Free.
                  2. Does the quote contain the figure? Free, and catches a
                     genuine quotation paired with an invented number.
                  3. Does the passage answer the question asked? One small
                     closed question, for the case the first two cannot
                     see: a real quote, with the real figure, taken from
                     the wrong place.

                A claimed silence cannot take the cheap path, because layer
                two defers on an empty answer and layer three does not run,
                so all three would pass while the status was copied. That
                let a leader bury a dissenting source by attaching a real
                quote and reporting nothing. Silence is re-read instead.
                """
                if not isinstance(leaders_res, gl.vm.Return):
                    return False
                leader = leaders_res.calldata

                page = ""
                try:
                    resp = gl.nondet.web.get(url)
                    if resp.status < 400:
                        page = (resp.body or b"").decode("utf-8", errors="replace")
                except Exception:
                    page = ""

                if not page.strip():
                    # I could not read it either, so the only claim I can
                    # honestly agree with is that it was unreadable.
                    return str(leader["status"]) == "unreadable"

                leader_quote = str(leader["quote"] or "")
                leader_answer = (
                    str(leader["answer"] or "")
                    if str(leader["status"]) == ANSWER_FOUND
                    else ""
                )

                if leader_quote and leader_answer:
                    if not quote_is_verbatim(leader_quote, page):
                        return False
                    if not answer_grounded_in_quote(leader_answer, leader_quote):
                        return False
                    verdict_raw = gl.nondet.exec_prompt(
                        build_support_prompt(claim_text, leader_quote, leader_answer),
                        response_format="json",
                    )
                    return bool(parse_support(verdict_raw))

                # Reaching here means this validator read the page, so a
                # leader claiming it could not be read is contradicted by
                # something already in hand. Without this the two silent
                # statuses are interchangeable to consensus: "unreadable"
                # and "not_stated" both produce an empty answer, so
                # answers_attest agrees to either, and whichever the leader
                # sent is what gets stored and shown. Free to check, and it
                # is the difference between "the source is broken" and "the
                # source is silent", which are not the same claim.
                if str(leader["status"]) == "unreadable":
                    return False

                # No usable quote, or a claimed silence. Read it properly.
                raw = gl.nondet.exec_prompt(
                    build_extraction_prompt(claim_text, page),
                    response_format="json",
                )
                mine = parse_extraction(raw)
                my_answer = mine.answer if mine.status == ANSWER_FOUND else ""
                return answers_attest(leader_answer, my_answer)

            got = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
            found.append(
                {
                    "url": url,
                    "status": str(got["status"]),
                    "answer": str(got["answer"]),
                    "quote": str(got["quote"]),
                }
            )

        # Deterministic from here down. Every node holds the same attested
        # answers, so it reaches the same verdict without another round.
        classified = [
            classify(f["url"], f["answer"] if f["status"] == ANSWER_FOUND else "")
            for f in found
        ]
        assessed = assess(classified)

        verdict = assessed.verdict
        value = assessed.consensus_value
        agreeing = list(assessed.agreeing)
        dissenting = list(assessed.dissenting)
        abstaining = list(assessed.abstaining)
        settled_by = "arithmetic"

        if assessed.needs_model:
            value, agreeing, dissenting = self._reconcile(claim_text, found)
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
            sources_silent=len(abstaining),
            answers=[
                SourceAnswer(
                    url=f["url"],
                    status=f["status"],
                    answer=f["answer"],
                    quote=f["quote"],
                )
                for f in found
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
            # The split is the whole decision. It is also the whole output:
            # the model is not asked for a summary sentence, because a
            # sentence two models word differently cannot be compared here
            # without failing honest checks, and storing one that was never
            # compared would put an unattested claim on chain.
            return sorted(mine["agreeing"]) == sorted(leader["agreeing"])

        out = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        agreeing = sorted(out["agreeing"])
        # The stored value is the agreeing source's own words, not a
        # paraphrase of them. Each quote was verified verbatim against the
        # page every validator fetched for itself, and the agreeing set was
        # compared above, so this string is derived entirely from data
        # consensus has already checked.
        value = answered[agreeing[0]]["quote"] if agreeing else ""
        return (
            value,
            [answered[i]["url"] for i in agreeing],
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
