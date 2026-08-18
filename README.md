# QUORUM

**An oracle that tells you who disagreed.**

A GenLayer Intelligent Contract that checks a claim against several
independent web sources, decides whether they actually agree, and records
the dissent as a first-class output.

---

## The problem

An oracle that reads one page and returns a number tells you what one
publisher said. If that publisher is wrong, or was edited, or is the party
with an interest in the answer, the contract consuming the number has no
way to know.

Existing web-reading contracts fetch a single URL and reach consensus on
its contents. That answers "what does this page say", not "is this true".

A number three sources agree on is a different thing from the same number
with two sources contradicting it. QUORUM returns both, so a caller
deciding whether to pay out on a value knows which one it is holding.

---

## What a check returns

```
verdict:    contested
value:      13,491,800
agreement:  40%

agreeing    citypopulation          13,491,800
            britannica              13,745,000

dissenting  wikipedia               17-21 million
            worldpopulationreview   14,881,845
            wikidata                15,070,000
```

Four verdicts:

| verdict | meaning |
|---|---|
| `corroborated` | every source that answered agreed |
| `majority` | more agreed than dissented |
| `contested` | the dissenters are as many or more |
| `no_data` | no source answered the question |

Every source's own words are stored alongside the verdict, truncated to a
sentence, so a reader can check the contract's work rather than trust it.

---

## How it works

1. **Each source is fetched separately.** `gl.nondet.web.render` per URL.
2. **Each source is read in isolation, one prompt each.** Batching is
   cheaper and destroys the premise: a model shown several documents at
   once reads the ambiguous one in light of the confident one and reports
   agreement the sources do not contain. That fabricates the exact thing
   being measured.
3. **Answers are compared by arithmetic wherever possible.** Percentages,
   dates, counts, ranges and yes-or-no all have objective agreement rules.
   Asking a model to compare them only adds a chance of being wrong about
   something that was never in doubt.
4. **Only genuine prose falls through to the model** for reconciliation.

### The consensus design

Validators do not compare extracted text. Two models reading the same page
write "40 percent" and "40%" and both are right, so comparing prose would
fail every check that ever ran.

They compare the **decisions** those extractions produce: the verdict, and
exactly which sources were counted as dissenting or silent. Those are what
a caller acts on, and they are stable across reasonable differences in
wording.

### Agreement rules

Two numbers count as the same claim within **5% relative tolerance**.
Sources round differently and report at different precisions, so demanding
exact equality would manufacture disagreement out of journalistic
convention rather than substance.

Percentages also get a **1 absolute point** tolerance, because relative
tolerance behaves badly near zero: 0.1% and 0.2% differ by 100% relatively
while being the same claim.

Ranges are read as their midpoint. Dates are only parsed in unambiguous
formats; `03/04/2026` is deliberately rejected, because it means March in
one country and April in another and guessing would silently invent
agreement.

Abstentions are excluded from the denominator. A source silent on a claim
is not evidence against it.

The majority cluster is found by scoring every answer against every other,
so the verdict does not depend on which source happened to be listed first.

---

## Layout

```
contracts/agreement.py   arithmetic core, no model involved
contracts/judgment.py    prompt construction and response parsing
contracts/quorum.py      the contract
contracts/quorum_bundle.py  generated, this is what deploys
deploy/build_bundle.py   inlines the modules into one file
fixtures/                archived sources for the reference check
test/                    41 tests
```

GenVM deploys a single file with no access to sibling modules, so the
local imports that work under pytest fail on chain. `build_bundle.py`
inlines them. Edit the modules, never the bundle.

---

## Interface

```python
check(check_id: str, claim: str, sources: list) -> dict   # write
get_check(check_id: str) -> dict                          # view
verdict_of(check_id: str) -> str                          # view
is_checked(check_id: str) -> bool                         # view
```

Two sources minimum, eight maximum. One source is a quotation, not a
corroboration. Each source costs a fetch and a prompt on every validator,
and the value of another source drops off sharply after the first few.

---

## Source pinning

Sources should be archived or revision-pinned URLs. A live page that
changes between two validators fetching it makes them disagree about the
page rather than about the claim, and the transaction then fails for a
reason unrelated to the question asked.

`fixtures/` holds five real sources on Lagos population, captured
2026-08-18, each with a provenance header recording its original URL and
retrieval time. They are frozen so the reference check stays reproducible
for anyone reading this months from now, and the original URLs are there
to audit against.

---

## Running it

```bash
pip install -r requirements.txt
pytest test/ -q
python deploy/build_bundle.py
genvm-lint lint contracts/quorum_bundle.py
genvm-lint validate contracts/quorum_bundle.py
```

---

## License

MIT
