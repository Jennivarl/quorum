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

This is real output from a real run against the five archived sources,
reproducible from `fixtures/` and asserted by the test suite. It is not
currently readable from the chain: see [Deployment](#deployment) for why.

```
verdict:    contested
value:      13,491,800
agreement:  40%
settled by: arithmetic

agreeing    citypopulation          13,491,800
            britannica              13,745,000

dissenting  wikipedia               between 17 and 21 million
            worldpopulationreview   14,881,845
            wikidata                15070000
```

Two sources put Lagos State near 13.5 million on the 2022 projection.
Three measure the metropolitan area instead and land between 14.9 and 21
million. That is a documented methodological dispute rather than an
error, and it is exactly what a single-source oracle would have hidden
behind one confident number.

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
site/                    the frontend, Vite and React, GitHub Pages
test/                    69 tests
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
check_ids() -> list                                       # view
summaries() -> list                                       # view
count() -> int                                            # view
```

A `TreeMap` cannot be walked from outside the contract, so the keys are
kept in a `DynArray` as well. Without that an archive of past checks is
unreadable, and reading one by one would be N round trips to list N rows.
`summaries` deliberately omits the quotes and per-source answers, which
are most of the payload and none of what an index shows.

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

The reference check fetches them from `raw.githubusercontent.com` at a
pinned commit SHA rather than at `main`. A branch URL moves when the
branch does, which would reintroduce exactly the drift the freezing was
meant to remove. A commit URL cannot change.

---

## Deployment

| Contract | Network | Address |
|---|---|---|
| `Quorum` | Bradbury | [`0x407C90fB85C0613EFC0a7Dc4833ce1Cea52C9882`](https://explorer-bradbury.genlayer.com/address/0x407C90fB85C0613EFC0a7Dc4833ce1Cea52C9882) |

All seven view methods work and are free to call:

```bash
genlayer call 0x407C90fB85C0613EFC0a7Dc4833ce1Cea52C9882 count \
  --rpc https://rpc-bradbury.genlayer.com
```

### Checks stored on chain

Two checks are stored and readable right now, both of the same claim
against different pairs of sources:

| id | verdict | agreement | sources |
|---|---|---|---|
| `lagos-pair` | contested | 50% | citypopulation, wikidata |
| `lagos-metro-vs-state` | contested | 50% | wikipedia, citypopulation |

```bash
genlayer call 0x407C90fB85C0613EFC0a7Dc4833ce1Cea52C9882 summaries \
  --rpc https://rpc-bradbury.genlayer.com
```

The five-source run shown at the top of this file produced the correct
verdict and the correct three dissenters, and can be reproduced locally
from `fixtures/`, but it has never survived to finalisation. See below.

### What Bradbury will and will not carry

A `check` write costs one fetch and one prompt per source, and every
validator repeats the whole thing independently. A five-source check is
therefore roughly thirty model calls inside a single transaction.

Observed across a dozen attempts on two deployments:

| sources | outcome |
|---|---|
| 2 | lands, roughly half the time |
| 3 | `LEADER_TIMEOUT` every attempt |
| 5 | `LEADER_TIMEOUT` or `VALIDATORS_TIMEOUT` every attempt |

Three properties of this are worth knowing before you debug something
that is not broken.

**A timeout is not proof of failure.** One run reported `LEADER_TIMEOUT`
and had nevertheless been written by the time the status was read back.

**A successful read is not proof of success.** The same run later rolled
back to nothing, because the transaction never finalised. A separate
check, `lagos-state-figures`, was readable for several minutes and then
vanished the same way. Read twice, minutes apart, before believing state
exists.

**A failed attempt writes nothing at all.** Nothing partial is ever
stored, so retrying is always safe.

Separately, the network sometimes reverts every write at the consensus
contract, including writes with fresh ids on freshly deployed contracts,
while `eth_call` replaying the identical transaction against current
state succeeds. That is validator assignment failing upstream, not a
contract error, and the only remedy is to wait.

Deploys and all seven view calls go through immediately throughout.

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
