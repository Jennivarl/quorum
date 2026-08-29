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

This is a real record stored on Bradbury, read back from the contract. Both
sources are live third-party APIs on unrelated hosts, not archived copies of
anything in this repository.

```
check:      nigeria-2018
claim:      What was the population of Nigeria in 2018?
verdict:    corroborated
agreement:  100%
value:      204,938,755
settled by: arithmetic

api.worldbank.org     204938755    "date":"2018","value":204938755
countriesnow.space    195874740    {"year":2018,"value":195874740}
```

The two figures differ by 4.4%, which is inside the tolerance, so they count
as the same claim. Both quotations were confirmed verbatim by every
validator against its own copy of the page, and both figures had to be
present inside the quote they came from.

Ask the same two publishers without pinning the year and they stop agreeing:
the World Bank reports 227.9 million for 2023 while countriesnow is still on
2018 data. Thirty-two million apart, both reputable, and a single-source
oracle would hand back whichever one it happened to read.

Four verdicts:

| verdict | meaning |
|---|---|
| `corroborated` | every source that answered agreed |
| `majority` | more agreed than dissented |
| `contested` | the dissenters are as many or more |
| `no_data` | no source answered the question |

Where a source can be quoted, its own words are stored alongside the
verdict, truncated to a sentence, so a reader can check the contract's work
rather than trust it. A quote is not guaranteed: when no exact span can be
copied, the quote is left empty rather than paraphrased, and that source is
attested by every validator re-reading the page in full instead. An empty
quote is a weaker receipt, and showing it empty is the point. The record on
chain for `nigeria-current` has one of each.

---

## How it works

1. **Each source gets its own consensus round.** One `run_nondet_unsafe`
   per source, each carrying a single fetch and a single prompt. Doing
   every source in one round is what made checks time out: validators
   re-read each source, so the round grew with the source count, and two
   sources is the minimum a check can have. Fetching is a plain HTTP
   `get`, not a browser render, because a rendered page depends on script
   timing and two validators can legitimately see different text.
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

### What consensus actually covers

Anything durable enough to be read as evidence has to be attested, not just
the headline. Every validator independently checks three things, cheapest
first:

**Is the quote real?** It must appear verbatim in the copy of the page that
validator fetched for itself. Deterministic and free. This is what stops a
leader inventing a plausible sentence and having it displayed as a receipt.

**Is the figure inside that quote?** Also deterministic and free. Catches a
genuine quotation paired with a number it does not contain.

**Does the passage answer the question asked?** One small closed question,
not a re-read of the document. This exists for the case the other two cannot
see: a real quote, containing the real figure, taken from the wrong place. A
1991 census row where the claim is about 2022.

Reading the page in full is kept as the fallback for any source with no
usable quote, so nothing goes unchecked either way.

What is deliberately not compared is prose wording. Two models reading the
same page write "40 percent" and "40%" and both are right, so demanding
identical text would fail every honest check.

Nothing unattested is stored in its place. Where prose settles a check, the
recorded value is the agreeing source's own quote, which every validator
confirmed verbatim against the page it fetched itself. The model is never
asked to write a summary of what the sources agreed on, because a sentence
two models word differently cannot be compared here, and storing one that
was never compared would put a claim on chain that consensus never checked.

Independence is enforced rather than assumed. A check whose sources share a
host is rejected. It is judged on the host of the URL the contract actually
fetches, which is the one part of a source a caller cannot restate.

An earlier version accepted a separate publisher name alongside each URL,
so that archived copies served from one host could still count as
independent. That handed the caller the test: two pages from a single
publisher passed by declaring different origins. Archived copies from one
host now count as one publisher. The cost is that some genuinely
independent checks are refused, which is the safe direction to fail in;
accepting sources that are not independent is the direction that makes a
stored verdict a lie.

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
contracts/escrow.py      holds value, releases or returns it on a verdict
contracts/settle.py      read-only reference consumer
contracts/quorum_bundle.py  generated, this is what deploys
deploy/build_bundle.py   inlines the modules into one file
fixtures/                archived sources for the reference check
site/                    the frontend, Vite and React, GitHub Pages
test/                    124 tests
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
| `Quorum` | Bradbury | [`0x09c857e5c27290F0Fb7A60259132E19be9Af339e`](https://explorer-bradbury.genlayer.com/address/0x09c857e5c27290F0Fb7A60259132E19be9Af339e) |
| `Escrow` | Bradbury | [`0x2e666d867eF145847935CD97D01826A10211d75D`](https://explorer-bradbury.genlayer.com/address/0x2e666d867eF145847935CD97D01826A10211d75D) |
| `Settle` | Bradbury | [`0x58AfABc9D74E8D73818d55Ead7999EA01800CdBF`](https://explorer-bradbury.genlayer.com/address/0x58AfABc9D74E8D73818d55Ead7999EA01800CdBF) |

Both directions are exercised on chain against the same contract. The same
method, called the same way, paid the payee on a corroborated check and
returned the deposit on a contested one. Nobody approved either; the only
input was whether independent sources agreed. `resolve` is deliberately
callable by anyone, because the verdict is already fixed by consensus and a
privileged resolver would reinstate the trusted operator this design exists
to remove.

`Escrow` holds real value and releases or returns it on a verdict.
`Settle` is a read-only reference consumer. See
[INTEGRATING.md](INTEGRATING.md).

Every view is free to call:

```bash
genlayer call 0x09c857e5c27290F0Fb7A60259132E19be9Af339e summaries \
  --rpc https://rpc-bradbury.genlayer.com
```

### Stored on chain

```
Quorum   nigeria-2018        corroborated 100%   204,938,755
                             api.worldbank.org   204938755
                             countriesnow.space  195874740

Quorum   nigeria-current     contested     50%   dissent recorded
                             api.worldbank.org   237,527,782
                             countriesnow.space  195,874,740   <- dissenting

Escrow   nigeria-deal-1      released
                             "corroborated at 100% meets the majority bar"
                             0.01 GEN, depositor -> payee

Escrow   nigeria-refund-1    refunded
                             "contested at 50%, below the majority bar;
                              1 source(s) disagreed, so the deposit is
                              returned rather than paid on a figure in
                              dispute"
                             0.01 GEN, returned to depositor
                             naive_would_pay: true

Settle   settle-nigeria-2018 settled
Settle   settle-nigeria-current  NOT settled
                             "contested at 50% is below the majority bar;
                              1 source(s) disagreed"
                             naive_would_settle: true
```

Both sources are live third-party APIs on unrelated hosts. Every quotation
was confirmed verbatim by each validator against its own copy of the page,
and every figure had to appear inside the quote it came from.

The second record is the one worth reading. Asked the same question without
pinning a year, the World Bank answers with 2025 and countriesnow with 2018,
forty-two million apart. Both publishers are right about their own figure.
QUORUM records `contested`, names countriesnow as the dissenter, and settles
nothing, while `naive_would_settle: true` states plainly that a single-source
oracle reading the first result would have paid out on 237,527,782. That
divergence is queryable on chain through `divergences()` rather than asserted
here.

The independence rule is also demonstrable rather than merely claimed. A
check submitted with two sources from the same publisher returned
`FINISHED_WITH_ERROR` with `resultName: AGREE`, meaning every validator
independently agreed to reject it, and nothing was stored.

### What Bradbury does to a check, in detail

A check is heavy because every validator re-reads every source rather than
taking the leader's word for it. How that work is divided turned out to
matter more than how much of it there is.

**Work per consensus round is the real limit.** Measured on this network
with probe contracts differing in one variable at a time: validators doing
no web work settled in about 25 seconds, three times out of three.
Validators doing two fetches in a single round never reached a terminal
state at all, three times out of three, reporting `LEADER_TIMEOUT` with
`NOT_VOTED` and an empty `eqBlocksOutputs`. Since two sources is the
minimum a check can have, every check this contract would accept was the
shape that could not finish. Splitting into one round per source fixed it:
the reference check stored on the first attempt in 52 seconds.

**A transaction can also be cancelled without ever running.** The status
goes `Pending` and then straight to `Canceled`. No leader executed it, no
validator voted, nothing was rejected. Nothing about the contract or the
claim influences this, and no setting avoids it.

**A transaction that does run can exhaust its rotations.** When a validator
set runs out of time, consensus rotates the work to a fresh set and retries
inside the same transaction. **The default is three, and the CLI has no flag
to change it.** The frontend asks for eight.

**`Finalized` does not mean it worked.** One check reached `Finalized` with
`eqBlocksOutputs: ""`, every validator vote zero, and nothing stored. Read
the state, not the status word.

Telling them apart matters, because the fixes are opposite. Query the status
directly rather than trusting a client:

```bash
curl -s -X POST https://rpc-bradbury.genlayer.com \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"gen_getTransactionStatus",
       "params":[{"txId":"0x..."}]}'
```

The `params` must be an **object**, not a bare string, and
`eth_getTransactionByHash` returns null for GenLayer transactions. A pending
GenLayer check also does **not** show up as a pending EVM nonce, because it
queues inside the consensus contract rather than the mempool. Checking
`eth_getTransactionCount` tells you nothing about whether a check is waiting.

### Three properties worth knowing before debugging something that works

**A timeout is not proof of failure.** One run reported `LEADER_TIMEOUT` and
had nevertheless been written by the time the status was read back.

**A successful read is not proof of success.** The same run later rolled back
to nothing, because the transaction never finalised. Read twice, minutes
apart, before believing state exists.

**A failed attempt writes nothing at all.** Nothing partial is ever stored,
so retrying is always safe.

Deploys and view calls go through immediately throughout, which is why a
stalled write is never a funding problem or a contract error.

### Value moves on finalisation, not acceptance

`Escrow` emits transfers with `on='finalized'`. The consequence is visible in
practice: a resolved deal records `released` promptly while the funds stay in
the contract until the transaction finalises, which is much later.

That is the deliberate trade. State on this network has been observed
readable and then rolled back, and an escrow that pays out on a transaction
which later disappears is worse than one that pays slowly. The site says so
on screen rather than showing `released` and letting a reader assume the
money has arrived.

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
