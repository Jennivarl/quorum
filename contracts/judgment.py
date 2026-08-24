"""
The two jobs that need a model.

First, reading a source and finding what it actually says about the claim.
A page is thousands of words and the answer is usually one number or one
sentence, and no amount of regex reliably finds it.

Second, reconciling prose. When arithmetic cannot settle whether two
answers match, because they are sentences rather than numbers, something
has to decide whether "the deal closed in March" and "the acquisition
completed in Q1" are the same claim.

**Sources are extracted in isolation, one prompt each.** This is the most
important decision in the file and it costs real money, so the reason
matters. Batching every source into a single prompt is cheaper and it is
also how a corroboration oracle quietly becomes worthless: a model shown
five documents at once will read an ambiguous source in light of a
confident one, and report agreement that the sources themselves do not
contain. That fabricates exactly the thing the contract exists to measure.
Each source is therefore shown to the model alone, with no knowledge that
other sources exist. The prompts run inside one consensus block, so the
isolation costs prompt calls rather than consensus rounds.
"""

import json
from dataclasses import dataclass
from typing import Any

# Answer shapes the extractor is allowed to return, so a caller can branch
# without pattern matching prose.
ANSWER_FOUND = "found"
ANSWER_NOT_STATED = "not_stated"
ANSWER_UNREADABLE = "unreadable"

_EXTRACTION_PROMPT = """You are reading ONE document to find what it says about a
specific claim. You have not seen any other document, and you must not guess
at what other sources might say.

Claim to check:
{claim}

Document:
```document
{document}
```

Answer only from this document. If it does not address the claim, say so
rather than inferring a likely answer; a document that is silent is more
useful to record as silent than to fill in.

The "quote" must be copied out of the document character for character. Do
not tidy it, shorten it in the middle, fix its punctuation, or write it in
your own words. Every validator checks the quote against its own copy of
this document and the whole check is rejected if it is not found there, so
a paraphrase is worse than no quote at all. If you cannot copy an exact
span, leave it empty and give the answer alone.

Respond using ONLY this JSON format:
{{
"status": "found" | "not_stated" | "unreadable",
"answer": "the shortest exact answer the document supports, or empty",
"quote": "an exact span copied from the document, or empty"
}}
Use "found" only when the document directly supports an answer. Use
"not_stated" when the document is readable but does not address the claim.
Use "unreadable" when the document is an error page, a paywall, or is
otherwise not the content it should be. Keep "answer" short: a number, a
date, a yes or no, or one clause. Respond with JSON only.
"""

_RECONCILIATION_PROMPT = """Several sources answered the same question in prose,
so they cannot be compared as numbers. Decide which of them are making the
same claim.

Question:
{claim}

Answers:
{answers}

Two answers agree when they assert the same thing about the world, even if
worded differently. They disagree when one contradicts the other. Different
levels of detail are not disagreement; a contradiction is.

Respond using ONLY this JSON format:
{{
"consensus": "the claim the largest group of answers supports, or empty",
"agreeing": [answer numbers that support it],
"dissenting": [answer numbers that contradict it]
}}
Every answer number must appear in exactly one of the two lists. Use the
numbers exactly as labelled. Respond with JSON only.
"""


_SUPPORT_PROMPT = """A source was read to answer a question, and you are checking
whether the passage it was taken from actually supports the answer given.

Question:
{claim}

Passage quoted from the source:
```passage
{quote}
```

Answer reported from that passage:
{answer}

Say no if the passage is about a different thing than the question asks. A
passage can be genuine, and contain the reported figure, and still be the
wrong passage: a historical value where the question asks for a current one,
a different place, a different measure, a different year. That is exactly
what you are looking for.

Say yes if the passage genuinely supports that answer to that question.

Respond using ONLY this JSON format:
{{
"supports": true | false
}}
Respond with JSON only.
"""


@dataclass
class Extraction:
    status: str
    answer: str = ""
    quote: str = ""


@dataclass
class Reconciliation:
    consensus: str = ""
    agreeing: list = None
    dissenting: list = None

    def __post_init__(self):
        if self.agreeing is None:
            self.agreeing = []
        if self.dissenting is None:
            self.dissenting = []


def build_extraction_prompt(claim: str, document: str, max_chars: int = 6000) -> str:
    """
    One claim, one document. `max_chars` truncates very long pages: a
    prompt the model silently truncates itself would drop the end of the
    document without saying so, and an answer drawn from a page the model
    only half read is worse than an honest "not stated".
    """
    body = (document or "").strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "\n[document truncated]"
    return _EXTRACTION_PROMPT.format(claim=(claim or "").strip(), document=body)


def build_support_prompt(claim: str, quote: str, answer: str) -> str:
    """
    The cheap verification a validator runs instead of re-reading the page.

    A full extraction sends the whole document and asks an open question,
    which is slow enough that validators time out before consensus is
    reached. This sends one passage and asks a closed one, so it is a
    fraction of the size and a much easier judgement, which also makes
    validators far more likely to agree with each other.

    It exists to catch the one failure the deterministic checks cannot: a
    quote that is real, and contains the reported figure, but answers a
    different question than the one asked.
    """
    return _SUPPORT_PROMPT.format(
        claim=(claim or "").strip(),
        quote=(quote or "").strip(),
        answer=(answer or "").strip(),
    )


def parse_support(raw: Any) -> bool:
    """
    Unreadable output means not supported.

    The opposite of the rule in parse_extraction, and deliberately so.
    There, inventing an answer from a broken response would put a
    fabricated data point into a corroboration count. Here, reading a
    broken response as approval would wave through the exact thing this
    check exists to stop.
    """
    data = _decode(raw)
    if not isinstance(data, dict):
        return False
    value = data.get("supports")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def build_reconciliation_prompt(claim: str, answers: list) -> str:
    numbered = "\n".join(
        f"Answer {i}: {a}" for i, a in enumerate(answers, start=1)
    )
    return _RECONCILIATION_PROMPT.format(claim=(claim or "").strip(), answers=numbered)


def _decode(raw: Any):
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def parse_extraction(raw: Any) -> Extraction:
    """
    Unparseable output becomes "unreadable" rather than an answer.

    A model that returns broken JSON has told us nothing about the
    document, and inventing an answer from that would put a fabricated
    data point into a corroboration count. Recording it as unreadable
    keeps the source out of the tally instead, which is the honest effect
    of not knowing.
    """
    data = _decode(raw)
    if not isinstance(data, dict):
        return Extraction(status=ANSWER_UNREADABLE)

    status = str(data.get("status", "")).strip().lower()
    if status not in (ANSWER_FOUND, ANSWER_NOT_STATED, ANSWER_UNREADABLE):
        status = ANSWER_UNREADABLE

    answer = str(data.get("answer", "") or "").strip()
    # A "found" with nothing in it is not a finding.
    if status == ANSWER_FOUND and not answer:
        status = ANSWER_NOT_STATED

    return Extraction(
        status=status,
        answer=answer if status == ANSWER_FOUND else "",
        quote=str(data.get("quote", "") or "").strip(),
    )


def parse_reconciliation(raw: Any, answer_count: int) -> Reconciliation:
    """
    Validate the returned indices against the list actually sent.

    Same reasoning as the extraction guard: an index pointing at an answer
    that was never shown cannot be resolved to a real source, and guessing
    which one was meant would attribute a position to a source that never
    took it. Out of range entries are dropped, and anything unaccounted
    for is treated as dissent, because silence from the reconciler is not
    evidence of agreement.
    """
    data = _decode(raw)
    if not isinstance(data, dict):
        return Reconciliation(dissenting=list(range(answer_count)))

    def valid(key):
        out = []
        for item in data.get(key, []) or []:
            try:
                idx = int(item) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < answer_count:
                out.append(idx)
        return sorted(set(out))

    agreeing = valid("agreeing")
    dissenting = [i for i in valid("dissenting") if i not in agreeing]

    accounted = set(agreeing) | set(dissenting)
    unaccounted = [i for i in range(answer_count) if i not in accounted]
    dissenting = sorted(dissenting + unaccounted)

    return Reconciliation(
        consensus=str(data.get("consensus", "") or "").strip(),
        agreeing=agreeing,
        dissenting=dissenting,
    )
