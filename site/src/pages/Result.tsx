import { useEffect, useState } from "react";
import { GlyphRow, Glyph } from "../components/Glyph";
import { SourceBadge } from "../components/Chrome";
import { CONTRACT, EXPLORER, loadReference, readCheck } from "../lib/chain";
import {
  publisherOf,
  standingOf,
  tally,
  type CheckRecord,
  type SourceAnswer,
  type Standing,
} from "../lib/types";
import "./result.css";

type State =
  | { phase: "loading" }
  | {
      phase: "ready";
      record: CheckRecord;
      origin: "chain" | "cache";
      reason?: "absent" | "unreachable";
    }
  | { phase: "missing" }
  | { phase: "error"; message: string };

export default function Result({ checkId }: { checkId: string }) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let live = true;
    setState({ phase: "loading" });

    (async () => {
      const reference = await loadReference().catch(() => null);

      try {
        const live_record = await readCheck(checkId);
        if (!live) return;
        // The chain stores URLs only. Publisher names and retrieval times
        // live in the committed reference, so merge them in by URL where
        // they exist and fall back to the URL where they do not.
        const byUrl = new Map(
          (reference?.answers ?? []).map((a) => [a.url, a]),
        );
        setState({
          phase: "ready",
          origin: "chain",
          record: {
            ...live_record,
            answers: live_record.answers.map((a) => ({
              ...a,
              publisher: byUrl.get(a.url)?.publisher,
              retrieved: byUrl.get(a.url)?.retrieved,
            })),
          },
        });
      } catch (err) {
        if (!live) return;
        const message = err instanceof Error ? err.message : String(err);
        // A KeyError from the contract means the id simply is not stored,
        // which is a different thing from the chain being unreachable and
        // deserves a different page.
        if (message.includes("KeyError")) {
          if (reference && reference.check_id === checkId) {
            setState({
              phase: "ready",
              record: reference,
              origin: "cache",
              reason: "absent",
            });
          } else {
            setState({ phase: "missing" });
          }
          return;
        }
        if (reference && reference.check_id === checkId) {
          setState({
            phase: "ready",
            record: reference,
            origin: "cache",
            reason: "unreachable",
          });
          return;
        }
        setState({ phase: "error", message });
      }
    })();

    return () => {
      live = false;
    };
  }, [checkId]);

  if (state.phase === "loading") {
    return (
      <div className="shell page-body result" aria-busy="true">
        <span className="label">Reading the contract</span>
        <div className="result-skeleton" />
      </div>
    );
  }

  if (state.phase === "missing") {
    return (
      <Empty
        label="No such check"
        title={`Nothing is stored under "${checkId}".`}
        body="The contract has no record with that id. It may never have been run, or a write may have timed out before it finalised."
      />
    );
  }

  if (state.phase === "error") {
    return (
      <Empty
        label="Could not read the contract"
        title="The chain did not answer."
        body={state.message}
      />
    );
  }

  const { record, origin } = state;
  const reason = state.reason;
  const counts = tally(record);

  return (
    <div className="shell page-body result">
      <header className="result-head">
        <div className="result-meta">
          <span className="label">
            Check {checkId} &middot; {record.answers.length} sources &middot;
            settled by {record.settled_by}
          </span>
          <SourceBadge source={origin} reason={reason} />
        </div>

        <h1 className="claim result-claim">{record.claim}</h1>

        <div className="verdict-band">
          <span className={`verdict-word v-${record.verdict}`}>
            {record.verdict.replace("_", " ")}
          </span>
          <GlyphRow
            agreed={counts.agreed}
            dissented={counts.dissented}
            silent={counts.silent}
          />
          <span className="value verdict-stat">
            {record.agreement_percent}% agreement &middot; {counts.agreed} of{" "}
            {record.answers.length} answered &middot; {counts.silent} silent
          </span>
        </div>
      </header>

      <section className="sources">
        {record.answers.map((answer) => (
          <SourceEntry
            key={answer.url}
            answer={answer}
            standing={standingOf(answer, record.dissenting)}
          />
        ))}
      </section>

      <section className="counterpoint">
        <span className="label">What a single-source oracle returns</span>
        <p className="value counterpoint-value">
          {record.consensus_value || "nothing"}
        </p>
        <p className="soft counterpoint-note">
          {counts.dissented > 0
            ? `No caveat, no spread, no sign that ${counts.dissented} other ${
                counts.dissented === 1 ? "source" : "sources"
              } said something different. Same fetch, same model, one URL.`
            : "Here it would have been right, which is the point: you could not have known that in advance without the other sources."}
        </p>
      </section>

      <section className="onchain">
        <div className="section-head">
          <span className="label">On chain</span>
          <h2>Verify this yourself</h2>
        </div>

        <dl className="record">
          <div>
            <dt className="label">Contract</dt>
            <dd className="value">
              <a
                className="inline-link"
                href={EXPLORER}
                target="_blank"
                rel="noreferrer noopener"
              >
                {CONTRACT}
              </a>
            </dd>
          </div>
          <div>
            <dt className="label">Checked by</dt>
            <dd className="value">{record.checked_by}</dd>
          </div>
          <div>
            <dt className="label">Settled by</dt>
            <dd className="value">{record.settled_by}</dd>
          </div>
        </dl>

        <div className="cmd">
          <span className="label">Read it back without spending anything</span>
          <pre className="value">
{`genlayer call ${CONTRACT} get_check \\
  --args ${checkId} \\
  --rpc https://rpc-bradbury.genlayer.com`}
          </pre>
        </div>
      </section>
    </div>
  );
}

function SourceEntry({
  answer,
  standing,
}: {
  answer: SourceAnswer;
  standing: Standing;
}) {
  const [open, setOpen] = useState(false);
  const hasDetail = Boolean(answer.quote);

  return (
    <article className={`entry st-${standing}`}>
      <div className="entry-row">
        <span className="entry-pub">{publisherOf(answer)}</span>
        <span className="value entry-val">
          {answer.answer || (standing === "silent" ? "did not answer" : "")}
        </span>
        <span className="entry-glyph">
          <Glyph kind={standing} />
        </span>
        {hasDetail ? (
          <button
            type="button"
            className="label entry-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "hide" : "quote"}
          </button>
        ) : (
          <span />
        )}
      </div>

      {open && hasDetail && (
        <div className="entry-detail">
          {answer.quote && (
            <blockquote className="entry-quote">
              &ldquo;{answer.quote}&rdquo;
            </blockquote>
          )}
          <div className="entry-prov">
            {answer.retrieved && (
              <span className="label">Retrieved {answer.retrieved}</span>
            )}
            <a
              className="label prov-link"
              href={answer.url}
              target="_blank"
              rel="noreferrer noopener"
            >
              Archived copy actually read
            </a>
          </div>
        </div>
      )}
    </article>
  );
}

function Empty({
  label,
  title,
  body,
}: {
  label: string;
  title: string;
  body: string;
}) {
  return (
    <div className="shell page-body result">
      <div className="stack" style={{ gap: "1rem", paddingTop: "2rem" }}>
        <span className="label">{label}</span>
        <h1 className="claim result-claim">{title}</h1>
        <p className="reading soft">{body}</p>
        <p style={{ marginTop: "0.5rem" }}>
          <a className="textlink" href="#/archive">
            See every check on the contract
          </a>
        </p>
      </div>
    </div>
  );
}
