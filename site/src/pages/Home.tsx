import { useEffect, useRef, useState } from "react";
import { GlyphRow, Glyph } from "../components/Glyph";
import { SourceBadge } from "../components/Chrome";
import { loadReferenceCheck } from "../lib/chain";
import {
  publisherOf,
  standingOf,
  tally,
  type ReferenceRecord,
} from "../lib/types";
import "./home.css";

const STEPS: [string, string, string][] = [
  [
    "01",
    "Fetch",
    "Every source is fetched separately, from a different publisher. A stable URL matters: a page that changes between two validators reading it makes them disagree about the page rather than the claim.",
  ],
  [
    "02",
    "Read alone",
    "One prompt per source, each shown no other document. A model that sees five at once reads the vague one in light of the confident one, and reports agreement the sources never contained.",
  ],
  [
    "03",
    "Compare by arithmetic",
    "Percentages, dates, counts and ranges have objective agreement rules. Asking a model to compare them only adds a chance of being wrong about something that was never in doubt.",
  ],
  [
    "04",
    "Record the dissent",
    "The verdict, the agreement share, and the name of every source that disagreed, written to the chain.",
  ],
];

export default function Home() {
  const [record, setRecord] = useState<ReferenceRecord | null>(null);
  const [origin, setOrigin] = useState<"chain" | "cache">("cache");
  const [why, setWhy] = useState<"absent" | "unreachable" | undefined>();

  useEffect(() => {
    let live = true;
    loadReferenceCheck().then(({ data, source, reason }) => {
      if (!live) return;
      setRecord(data);
      setOrigin(source);
      setWhy(reason);
    });
    return () => {
      live = false;
    };
  }, []);

  return (
    <div className="shell page-body home">
      <section className="hero">
        <h1 className="claim hero-line">
          An oracle that tells you <em>who disagreed</em>.
        </h1>
        <p className="hero-lede">
          Most oracles read one page and hand back a number. This one reads
          several, and tells you which of them said something else.
        </p>
        <div className="hero-links">
          <a className="textlink" href="#/run">
            Run a check
          </a>
          <a className="textlink" href="#/method">
            See how it decides
          </a>
        </div>
      </section>

      <ProofPanel record={record} origin={origin} reason={why} />

      <section className="stack" style={{ gap: "var(--gap-l)" }}>
        <div className="section-head">
          <span className="label">How it works</span>
          <h2>Four steps, and only one of them involves a model deciding</h2>
        </div>
        <ol className="steps">
          {STEPS.map(([num, title, body]) => (
            <li key={num}>
              <span className="label">{num}</span>
              <h3>{title}</h3>
              <p className="soft">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="closing">
        <p className="reading">
          Validators do not compare the extracted text. Two models reading the
          same page will write &ldquo;40 percent&rdquo; and
          &ldquo;40%&rdquo;, and both are right. They compare the decisions
          those readings produce: the verdict, and exactly which sources
          dissented.
        </p>
      </section>
    </div>
  );
}

function ProofPanel({
  record,
  origin,
  reason,
}: {
  record: ReferenceRecord | null;
  origin: "chain" | "cache";
  reason?: "absent" | "unreachable";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [resolved, setResolved] = useState(false);

  // The one animation on the site: the check resolving. Every row starts
  // flush in ink, then the dissenters step out into the margin. That is the
  // product, so it is worth showing happening once.
  useEffect(() => {
    if (!record || !ref.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setResolved(true);
      return;
    }
    const node = ref.current;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            window.setTimeout(() => setResolved(true), 380);
            io.disconnect();
          }
        }
      },
      { threshold: 0.3 },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [record]);

  if (!record) {
    return (
      <section className="proof" aria-busy="true">
        <span className="label">Loading the reference check</span>
        <div className="proof-skeleton" />
      </section>
    );
  }

  const counts = tally(record);

  return (
    <section className="proof">
      <div className="proof-meta">
        <span className="label">
          Check {record.check_id} &middot; {record.answers.length} independent
          sources &middot; settled by {record.settled_by}
        </span>
        <SourceBadge source={origin} reason={reason} />
      </div>

      <h2 className="claim proof-claim">{record.claim}</h2>

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
          {record.answers.length} &middot; {counts.silent} silent
        </span>
      </div>

      <div className={`rows${resolved ? " is-resolved" : ""}`} ref={ref}>
        {record.answers.map((a, i) => {
          const standing = standingOf(a, record.dissenting);
          return (
            <div
              key={a.url}
              className={`row st-${standing}`}
              style={{ transitionDelay: `${i * 70}ms` }}
            >
              <span className="row-pub">{publisherOf(a)}</span>
              <span className="value row-val">{a.answer || "no answer"}</span>
              <span className="row-glyph">
                <Glyph kind={standing} />
              </span>
            </div>
          );
        })}
      </div>

      <div className="counterpoint">
        <span className="label">What a single-source oracle returns</span>
        <p className="value counterpoint-value">{record.consensus_value}</p>
        <p className="soft counterpoint-note">
          {counts.dissented > 0
            ? `No caveat, no spread, no sign that ${counts.dissented} other ${
                counts.dissented === 1 ? "source" : "sources"
              } said something different. Same fetch, same model, one URL.`
            : "Here it would have been right. The point is that you could not have known that without reading the others."}
        </p>
      </div>
    </section>
  );
}
