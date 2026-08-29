# Consuming QUORUM from your own contract

QUORUM stores a verdict, an agreement share, and the name of every source
that disagreed. This is how another contract reads that and acts on it.

Everything here is deterministic. Reading a stored verdict needs no model,
no web access, and no equivalence principle, because the judgement already
happened inside QUORUM under consensus. A consumer should be cheap.

`contracts/settle.py` is a working example of everything below.

---

## Reading a verdict

```python
from genlayer import *

QUORUM = "0x09c857e5c27290F0Fb7A60259132E19be9Af339e"

record = gl.get_contract_at(Address(QUORUM)).view().get_check("nigeria-2018")

record["verdict"]            # corroborated | majority | contested | no_data
record["consensus_value"]    # the agreed figure, as the source wrote it
record["agreement_percent"]  # share of answering sources that agreed
record["dissenting"]         # URLs of the sources that did not
record["answers"]            # per source: url, status, answer, quote
```

If you only need to branch, `verdict_of(check_id)` returns the verdict
alone and `is_checked(check_id)` tells you whether a record exists at all.
Calling `get_check` on an id that was never checked raises, so guard it.

---

## Deciding what to do with it

The four verdicts are ordered. Pick the weakest one you are willing to act
on and refuse below it.

```python
_STRENGTH = {"no_data": 0, "contested": 1, "majority": 2, "corroborated": 3}

def acceptable(verdict: str, minimum: str = "majority") -> bool:
    return _STRENGTH.get(verdict, 0) >= _STRENGTH[minimum]
```

What each one should mean to you:

| verdict | what happened | reasonable response |
|---|---|---|
| `corroborated` | every source that answered agreed | act on the value |
| `majority` | more agreed than dissented | act, and record the objection |
| `contested` | dissenters equal or outnumber | refuse, or escalate to a human |
| `no_data` | nobody answered | refuse; this is not a zero |

`no_data` is the one worth being careful about. It is not "the answer is
none", it is "nothing was found", and treating it as a value is how a
silent source becomes a settled fact.

---

## Do not average the dissent away

The temptation, given a contested check, is to take the consensus value
anyway because it is the largest cluster. That throws away the only
information QUORUM adds over an ordinary oracle.

A contested result means the sources are measuring different things, and
usually the right move is to find out which one you want rather than to
pick the more popular number. In the reference check, two sources report
Lagos State and three report the metropolitan area. Neither is wrong.
Averaging them produces a figure that describes nothing.

---

## Show the counterfactual

`settle.py` stores, for every decision, what it would have decided given
only a single source's number. That is what an ordinary oracle hands you.

```python
naive_would_settle = bool(record["consensus_value"])
actually_settled   = acceptable(record["verdict"], minimum)
```

When those differ, the difference is the value of the dissent record. The
`divergences()` view lists exactly those cases: settlements that a
single-source oracle would have waved through and this one refused.

If you build a consumer, record this. It is the clearest evidence that the
extra information changed an outcome rather than decorating one.

---

## Running a check from a contract

You cannot, and this is deliberate. `check` is a write that costs one fetch
and one prompt per source on every validator, so it has to be paid for and
signed by whoever wants the answer. A contract that could trigger checks
would let any caller spend the deployer's balance.

The intended shape is: someone runs the check, then contracts read the
stored verdict as many times as they like for free.

---

## Choosing sources

The contract enforces two rules and will reject a check that breaks them.

**At least two, at most eight.** One source is a quotation, not a
corroboration. Past three or four the marginal source stops paying for its
fetch and prompt.

**Independent publishers.** A check whose sources share a host is rejected,
judged on the host of the URL the contract fetches. Nothing you supply
alongside the URL takes part in that decision, so the rule cannot be talked
out of:

```python
sources = [
    "https://api.worldbank.org/...",
    "https://countriesnow.space/...",
]
```

Dicts of the form `{"url": ...}` are accepted too, and any other key is
ignored. The consequence worth planning for is that several archived copies
served from one host count as a single publisher, so build a check out of
live third-party URLs rather than out of one archive.

**Prefer stable, directly fetchable URLs.** Sources are read with a plain
HTTP `get`, not a browser, so what the contract sees is the response body.
Small machine-readable endpoints and archived snapshots work well. Pages
that assemble themselves with JavaScript do not, because the body is a
shell. Redirects are not followed either, so a URL that moves is recorded
as unreadable rather than quietly resolved somewhere else.

A page that changes between two validators fetching it makes them disagree
about the page rather than about the claim, and the check then fails for a
reason that has nothing to do with your question.

---

## What consensus does and does not cover

Worth knowing before you treat a stored field as proof.

**Covered.** The verdict, the agreement share, and the dissent list. Every
stored quotation, which each validator confirms appears verbatim in its own
copy of the page. Every stored figure, which must be present in the quote it
came from and must survive a check that the passage answers the question
asked.

**Not covered.** The exact wording of a prose answer, deliberately, because
two models reading the same page phrase things differently and demanding
identical text would fail every honest check. Prose is backed by its
verifiable quote instead.

**Outside the contract entirely.** Whether the publishers are any good. If
you feed it two sources that are both wrong in the same way, it will report
`corroborated` and be exactly as wrong as they are. It measures agreement,
not truth.
