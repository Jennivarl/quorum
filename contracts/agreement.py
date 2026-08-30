"""
Deciding when two answers from different sources actually agree.

This is the part that makes a corroboration oracle more than a loop around
`fetch`. Counting how many sources responded is trivial. Deciding whether
"about 40 percent", "38.7%", and "roughly two in five" are the same claim,
while "rose sharply" and "fell slightly" are not, is the whole problem.

The work is split deliberately. Anything that can be decided by arithmetic
is decided here, with no model involved: numbers with units, percentages,
dates, and plain yes or no answers all have objective agreement rules, and
a model asked to compare them would only introduce a chance of being wrong
about something that was never in doubt. What is left over is genuinely
subjective prose, and that goes to the model in judgment.py.

Splitting it this way also keeps consensus cheap. Two validators comparing
"38.7%" against "about 40 percent" will always reach the same answer here,
because the comparison is a tolerance check rather than an opinion.
"""

import re
from dataclasses import dataclass, field

# Two numbers count as the same claim when they are within this fraction of
# each other. Sources round differently and report at different precisions,
# so demanding exact equality would manufacture disagreement out of
# journalistic convention rather than substance.
_RELATIVE_TOLERANCE = 0.05

# Percentages are compared in absolute points as well, because a relative
# tolerance behaves badly near zero: 0.1% and 0.2% differ by 100% relatively
# while being the same claim in substance.
_ABSOLUTE_POINT_TOLERANCE = 1.0

_NUMBER_WORDS = {
    "zero": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0,
    "five": 5.0, "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0,
    "ten": 10.0, "eleven": 11.0, "twelve": 12.0, "half": 0.5,
}

_SCALE_WORDS = {
    "hundred": 1e2, "thousand": 1e3, "k": 1e3,
    "million": 1e6, "m": 1e6, "mn": 1e6,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "trillion": 1e12, "tn": 1e12,
}

_AFFIRMATIVE = {"yes", "true", "correct", "confirmed", "affirmative", "y"}
_NEGATIVE = {"no", "false", "incorrect", "denied", "negative", "n"}

# Answers that mean the source did not actually say. Treated as abstention
# rather than disagreement, because a source that is silent on a claim is
# not evidence against it.
_NO_ANSWER = {
    "", "unknown", "not stated", "notstated", "unclear", "none",
    "not found", "notfound", "n/a", "na", "not mentioned", "notmentioned",
    "no answer", "noanswer", "unavailable",
}

KIND_NUMERIC = "numeric"
KIND_PERCENT = "percent"
KIND_BOOLEAN = "boolean"
KIND_DATE = "date"
KIND_TEXT = "text"
KIND_ABSTAIN = "abstain"


@dataclass
class Extracted:
    """What one source was found to say about the claim."""

    source: str
    raw: str
    kind: str
    value: float = 0.0
    text: str = ""


@dataclass
class AgreementResult:
    verdict: str
    kind: str
    consensus_value: str
    agreeing: list = field(default_factory=list)
    dissenting: list = field(default_factory=list)
    abstaining: list = field(default_factory=list)
    needs_model: bool = False

    @property
    def agreement_ratio_percent(self) -> int:
        """
        Share of sources that actually answered and agreed. Abstentions are
        excluded from the denominator: three sources agreeing out of three
        that answered is not weakened by a fourth that was silent.
        """
        answered = len(self.agreeing) + len(self.dissenting)
        if answered == 0:
            return 0
        return (len(self.agreeing) * 100) // answered


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower())


def host_of(url: str) -> str:
    """
    The publisher a URL belongs to.

    Hand-rolled rather than parsed with a library, because this decides
    whether a check is rejected and every validator must derive exactly the
    same answer from the same string. It also lives here, with the rest of
    the deterministic logic, so it can be tested without a chain.
    """
    text = (url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
            break
    text = text.split("/")[0].split("?")[0].split("#")[0]
    if "@" in text:
        text = text.split("@")[-1]
    text = text.split(":")[0]
    if text.startswith("www."):
        text = text[4:]
    return text


def normalize_space(raw: str) -> str:
    """Collapse whitespace without touching case. For comparing spans."""
    return re.sub(r"\s+", " ", (raw or "").strip())


def same_publisher(a: str, b: str) -> bool:
    """
    Do two hosts belong to the same publisher?

    Equal hosts obviously do. So does a host that sits underneath another,
    because `news.example.com` and `example.com` are one publisher wearing
    two names, and treating them as two would let a check be built entirely
    out of one outlet.

    What this deliberately does not do is reduce a host to its registrable
    domain. That needs the public suffix list to be correct, and the naive
    version of it, comparing the last two labels, would read every
    `*.co.uk` site as one publisher and reject genuinely independent
    British sources. Refusing to guess leaves one known gap: two sibling
    subdomains of a parent that is never itself cited, such as
    `a.example.com` alongside `b.example.com`. That is narrower than the
    damage the guess would do.
    """
    x = (a or "").strip().lower().strip(".")
    y = (b or "").strip().lower().strip(".")
    if not x or not y:
        return x == y
    return x == y or x.endswith("." + y) or y.endswith("." + x)


def quote_is_verbatim(quote: str, document: str) -> bool:
    """
    Does this quote actually appear in this document?

    A stored quote is only evidence if it can be found in the source. The
    contract shows quotes to readers as receipts, so an unverifiable one is
    worse than none: it invites trust it has not earned. Every validator
    fetches its own copy of the page, so each can answer this question
    independently, which is what turns a quote from an assertion by the
    leader into something consensus actually covers.

    Whitespace is normalised on both sides because page rendering collapses
    runs of space unpredictably. Nothing else is: no case folding, no
    punctuation stripping, no fuzzy matching. A near-miss is a paraphrase,
    and a paraphrase presented as a quotation is exactly what this is
    meant to catch.
    """
    needle = normalize_space(quote)
    if not needle:
        return False
    return needle in normalize_space(document)


def numbers_in(text: str) -> list:
    """
    Every number a span contains, scale words applied.

    Used to check that a reported figure is actually present in the quote it
    was supposedly taken from, so a whole row of a table can be quoted and
    the specific figure still located inside it.
    """
    cleaned = _clean(text)
    out = []
    pattern = (
        r"(-?[\d,]*\.?\d+)\s*"
        r"(hundred|thousand|million|billion|trillion|k|m|mn|bn|b|tn)?\b"
    )
    for match in re.finditer(pattern, cleaned):
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if match.group(2):
            value *= _SCALE_WORDS[match.group(2)]
        out.append(value)
    return out


def answer_grounded_in_quote(answer: str, quote: str) -> bool:
    """
    Is the reported answer actually contained in the quote it came from?

    The second of three checks a validator makes, and the one that catches a
    leader pairing a genuine quotation with a figure the quotation does not
    contain. Deterministic, so it costs nothing and every node reaches the
    same conclusion.

    A quote is not required. Where there is none, this cannot say anything
    and defers rather than blocking, and the caller falls back to reading
    the page properly.
    """
    if not normalize_space(quote):
        return True

    extracted = classify("answer", answer)
    if extracted.kind == KIND_ABSTAIN:
        return True

    # The plainest case: the answer is written out inside the quote.
    if normalize_space(answer).lower() in normalize_space(quote).lower():
        return True

    # Otherwise the figure has to be one of the numbers the quote contains,
    # which lets a whole table row stand as the quote for one of its cells.
    if extracted.kind in (KIND_NUMERIC, KIND_PERCENT, KIND_DATE):
        return any(
            _values_agree(extracted.kind, extracted.value, candidate)
            for candidate in numbers_in(quote)
        )

    # Prose and yes or no cannot be located numerically. The support check
    # in judgment.py covers those.
    return True


def answers_attest(leader: str, mine: str) -> bool:
    """
    Can a validator sign off on the leader's extracted answer?

    Not string equality. Two models reading the same page write "40
    percent" and "40%", and both are right, so demanding identical wording
    would fail every check that ever ran.

    Where the answers are objectively comparable, numbers, percentages,
    dates, yes or no, they are compared as values under the same tolerance
    used everywhere else. Where they are prose, no comparison is attempted
    here: wording genuinely varies, and prose is attested instead by its
    quote being verifiable in the source, plus the reconciliation step
    that decides which prose answers make the same claim.
    """
    a = classify("leader", leader)
    b = classify("mine", mine)

    if a.kind == KIND_ABSTAIN or b.kind == KIND_ABSTAIN:
        return a.kind == b.kind
    if a.kind == KIND_TEXT and b.kind == KIND_TEXT:
        return True
    if a.kind != b.kind:
        return False
    return _values_agree(a.kind, a.value, b.value)


def classify(source: str, raw: str) -> Extracted:
    """
    Work out what kind of answer a source gave, so the right comparison
    rule applies. Order matters: percentages are checked before bare
    numbers, because "40%" is both and the percent reading is the specific
    one.
    """
    cleaned = _clean(raw)

    if cleaned in _NO_ANSWER:
        return Extracted(source=source, raw=raw, kind=KIND_ABSTAIN)

    percent = _parse_percent(cleaned)
    if percent is not None:
        return Extracted(source, raw, KIND_PERCENT, value=percent)

    date = _parse_date(cleaned)
    if date is not None:
        return Extracted(source, raw, KIND_DATE, value=date)

    boolean = _parse_boolean(cleaned)
    if boolean is not None:
        return Extracted(source, raw, KIND_BOOLEAN, value=boolean)

    number = _parse_number(cleaned)
    if number is not None:
        return Extracted(source, raw, KIND_NUMERIC, value=number)

    return Extracted(source, raw, KIND_TEXT, text=cleaned)


def _parse_percent(cleaned: str):
    match = re.search(r"(-?[\d,]*\.?\d+)\s*(?:%|percent|per cent|pct)", cleaned)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    # "two in five" and "1 in 4" are percentages wearing a different hat.
    ratio = re.search(r"\b(\w+|\d+)\s+in\s+(\w+|\d+)\b", cleaned)
    if ratio:
        num = _word_or_digit(ratio.group(1))
        den = _word_or_digit(ratio.group(2))
        if num is not None and den not in (None, 0):
            return (num / den) * 100.0
    return None


def _word_or_digit(token: str):
    token = token.strip()
    if token in _NUMBER_WORDS:
        return _NUMBER_WORDS[token]
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _parse_range(cleaned: str):
    """
    A stated range such as "between 17 and 21 million" or "13 to 15m".

    Ranges are read as their midpoint. A source giving a range is making a
    less precise claim than one giving a figure, but it is still a claim,
    and the tolerance in _values_agree is what decides whether it matches
    a neighbour. Discarding the range and keeping only its first number
    would be worse than either: "between 17 and 21 million" would become
    the number 17, which is not a population and would disagree with
    everything by a factor of a million.
    """
    m = re.search(
        r"(-?[\d,]*\.?\d+)\s*(?:to|and|through|[-])\s*(-?[\d,]*\.?\d+)"
        r"\s*(hundred|thousand|million|billion|trillion|k|m|mn|bn|b|tn)?\b",
        cleaned,
    )
    if not m:
        return None
    try:
        low = float(m.group(1).replace(",", ""))
        high = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    # A trailing scale word applies to both ends: "17 and 21 million" is
    # not seventeen and twenty-one million.
    scale = _SCALE_WORDS[m.group(3)] if m.group(3) else 1.0
    return ((low + high) / 2.0) * scale


def _parse_number(cleaned: str):
    # Ranges first: the range pattern contains bare numbers, so a plain
    # number search would match the low end and silently drop the rest.
    ranged = _parse_range(cleaned)
    if ranged is not None:
        return ranged

    # A bare number, optionally with a scale word: "3.2 million", "40k".
    match = re.search(
        r"(-?[\d,]*\.?\d+)\s*(hundred|thousand|million|billion|trillion|k|m|mn|bn|b|tn)?\b",
        cleaned,
    )
    if match:
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            return None
        scale = match.group(2)
        if scale:
            value *= _SCALE_WORDS[scale]
        return value

    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", cleaned):
            scale_match = re.search(
                r"\b(hundred|thousand|million|billion|trillion)\b", cleaned
            )
            return value * (_SCALE_WORDS[scale_match.group(1)] if scale_match else 1.0)
    return None


def _parse_boolean(cleaned: str):
    first = cleaned.split(" ")[0].strip(".,;:!")
    if first in _AFFIRMATIVE:
        return 1.0
    if first in _NEGATIVE:
        return 0.0
    return None


def _parse_date(cleaned: str):
    """
    Dates become a sortable integer so comparison is exact. Only
    unambiguous formats are accepted; 03/04/2026 is deliberately not
    parsed, because it means March in one country and April in another and
    guessing would silently invent agreement or disagreement.
    """
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", cleaned)
    if iso:
        return float(f"{iso.group(1)}{iso.group(2)}{iso.group(3)}")

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
        "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
        "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    named = re.search(
        r"\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b|\b([a-z]+)\s+(\d{1,2}),?\s+(\d{4})\b",
        cleaned,
    )
    if named:
        if named.group(2):
            day, month_name, year = named.group(1), named.group(2), named.group(3)
        else:
            month_name, day, year = named.group(4), named.group(5), named.group(6)
        month = months.get(month_name)
        if month:
            return float(f"{year}{month:02d}{int(day):02d}")
    return None


def _values_agree(kind: str, a: float, b: float) -> bool:
    if kind == KIND_BOOLEAN:
        return a == b
    if kind == KIND_DATE:
        return a == b
    if kind == KIND_PERCENT:
        if abs(a - b) <= _ABSOLUTE_POINT_TOLERANCE:
            return True
        return _within_relative(a, b)
    return _within_relative(a, b)


def _within_relative(a: float, b: float) -> bool:
    if a == b:
        return True
    largest = max(abs(a), abs(b))
    if largest == 0:
        return True
    return abs(a - b) / largest <= _RELATIVE_TOLERANCE


def assess(extracted: list) -> AgreementResult:
    """
    Decide whether the sources agree, and record exactly who did not.

    The dissent record is the output that matters. An oracle that returns
    only a value hides the one fact a caller needs in order to weigh it: a
    number three sources agree on is a different thing from the same number
    with two sources actively contradicting it.
    """
    answered = [e for e in extracted if e.kind != KIND_ABSTAIN]
    abstaining = [e.source for e in extracted if e.kind == KIND_ABSTAIN]

    if not answered:
        return AgreementResult(
            verdict="no_data",
            kind=KIND_ABSTAIN,
            consensus_value="",
            abstaining=abstaining,
        )

    kinds = {e.kind for e in answered}

    # Mixed kinds, or prose, cannot be settled by arithmetic. Hand it on.
    if len(kinds) > 1 or kinds == {KIND_TEXT}:
        return AgreementResult(
            verdict="needs_judgment",
            kind=KIND_TEXT if kinds == {KIND_TEXT} else "mixed",
            consensus_value="",
            abstaining=abstaining,
            needs_model=True,
        )

    kind = answered[0].kind

    # The majority cluster wins. Each answer is scored by how many others
    # agree with it, rather than trusting the first source to reply.
    #
    # Clusters are collected rather than a single best kept, because two
    # different clusters can be the same size and picking one of them would
    # hand the outcome to whoever ordered the sources. Two sources that
    # contradict each other are exactly that case: taking the first would
    # name the second as the dissenter and publish the first as the value,
    # on no evidence beyond list position.
    best_size = 0
    clusters = []
    for candidate in answered:
        agreeing = [e for e in answered if _values_agree(kind, candidate.value, e.value)]
        members = frozenset(e.source for e in agreeing)
        if len(agreeing) > best_size:
            best_size = len(agreeing)
            clusters = [(members, candidate, agreeing)]
        elif len(agreeing) == best_size and all(m != members for m, _, _ in clusters):
            clusters.append((members, candidate, agreeing))

    if len(clusters) > 1:
        # No cluster is larger than the others, so no answer is backed by a
        # majority and naming one side the dissenters would assert something
        # the sources do not support. Every source that answered is recorded
        # as dissenting, because each is contradicted by another and none is
        # corroborated, and no value is published at all.
        return AgreementResult(
            verdict="contested",
            kind=kind,
            consensus_value="",
            agreeing=[],
            dissenting=[e.source for e in answered],
            abstaining=abstaining,
        )

    _, _, best_agreeing = clusters[0]
    # Which member of the cluster is published still matters, because the
    # members round differently and any of them is a fair representative.
    # Choosing by source rather than by list position means reordering the
    # same sources cannot change the stored value.
    best = sorted(best_agreeing, key=lambda e: e.source)[0]
    dissenting = [e for e in answered if e not in best_agreeing]

    if not dissenting:
        verdict = "corroborated"
    elif len(best_agreeing) > len(dissenting):
        verdict = "majority"
    else:
        verdict = "contested"

    return AgreementResult(
        verdict=verdict,
        kind=kind,
        consensus_value=best.raw,
        agreeing=[e.source for e in best_agreeing],
        dissenting=[e.source for e in dissenting],
        abstaining=abstaining,
    )
