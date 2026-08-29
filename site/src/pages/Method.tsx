import { GlyphRow } from "../components/Glyph";
import { CONTRACT, EXPLORER } from "../lib/chain";
import "./method.css";

const TOLERANCES: [string, string][] = [
  ["numeric", "within 5% of each other"],
  ["percent", "within 5%, or within 1 absolute point"],
  ["date", "exact, and only unambiguous formats are parsed at all"],
  ["boolean", "exact"],
  ["text", "handed to the model, because arithmetic cannot settle it"],
  ["abstain", "excluded from the denominator entirely"],
];

const VERDICTS: [string, number, number, number, string][] = [
  [
    "corroborated",
    4,
    0,
    0,
    "Every source that answered agreed. Safe to act on, with the caveat that agreement between sources that copy each other is not independence.",
  ],
  [
    "majority",
    3,
    1,
    0,
    "More agreed than dissented. Usable, and the objection is named so a caller can weigh it rather than discover it later.",
  ],
  [
    "contested",
    2,
    3,
    0,
    "The dissenters equal or outnumber. Do not settle a contract on this figure without deciding whose methodology you are trusting.",
  ],
  [
    "no data",
    0,
    0,
    3,
    "Nobody answered. Reported as its own verdict, never as agreement, because unanimous silence is not unanimity.",
  ],
];

const INTERFACE: [string, string, string][] = [
  ["check", "write", "check_id, claim, sources"],
  ["get_check", "view", "check_id"],
  ["verdict_of", "view", "check_id"],
  ["is_checked", "view", "check_id"],
  ["check_ids", "view", ""],
  ["summaries", "view", ""],
  ["count", "view", ""],
];

export default function Method() {
  return (
    <div className="shell page-body method">
      <header className="method-head">
        <span className="label">Method</span>
        <h1 className="claim method-title">
          How it decides that two sources agree.
        </h1>
        <p className="method-lede">
          Counting how many sources replied is trivial. Deciding whether
          &ldquo;about 40 percent&rdquo;, &ldquo;38.7%&rdquo; and
          &ldquo;roughly two in five&rdquo; are the same claim, while
          &ldquo;rose sharply&rdquo; and &ldquo;fell slightly&rdquo; are not,
          is the whole problem.
        </p>
      </header>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">One</span>
          <h2>Arithmetic before judgment</h2>
        </div>

        <p className="reading">
          Anything that can be decided by arithmetic is decided with no model
          involved. Numbers with units, percentages, dates and plain yes or no
          all have objective agreement rules, and a model asked to compare
          them would only introduce a chance of being wrong about something
          that was never in doubt.
        </p>
        <p className="reading">
          It also keeps consensus cheap. Two validators comparing
          &ldquo;38.7%&rdquo; against &ldquo;about 40 percent&rdquo; will
          always reach the same answer, because that comparison is a tolerance
          check rather than an opinion.
        </p>

        <div className="table-wrap">
          <table className="spec-table">
            <thead>
              <tr>
                <th scope="col">Kind</th>
                <th scope="col">Agreement rule</th>
              </tr>
            </thead>
            <tbody>
              {TOLERANCES.map(([kind, rule]) => (
                <tr key={kind}>
                  <th scope="row" className="value">
                    {kind}
                  </th>
                  <td>{rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="notes">
          <p>
            Percentages get an absolute tolerance as well, because a relative
            tolerance behaves badly near zero: 0.1% and 0.2% differ by 100%
            relatively while being the same claim in substance.
          </p>
          <p>
            <span className="value">03/04/2026</span> is deliberately
            rejected. It means March in one country and April in another, and
            guessing would silently invent agreement or disagreement.
          </p>
          <p>
            A stated range such as &ldquo;between 17 and 21 million&rdquo; is
            read as its midpoint. Keeping only its first number would turn it
            into 17, which is not a population, and it would then disagree
            with everything by a factor of a million.
          </p>
          <p>
            The majority cluster is found by scoring every answer against
            every other, so the verdict does not depend on which source
            happened to be listed first.
          </p>
        </div>
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Two</span>
          <h2>Every source is read alone</h2>
        </div>

        <div className="compare">
          <div>
            <span className="label">Batched, one prompt</span>
            <p className="soft">
              Cheaper, and it quietly destroys the premise. A model shown five
              documents at once reads the ambiguous one in light of the
              confident one and reports agreement the sources do not contain.
              That fabricates the exact thing being measured.
            </p>
          </div>
          <div>
            <span className="label">Isolated, one prompt each</span>
            <p className="soft">
              Each source is shown to the model alone, with no knowledge that
              other sources exist. The prompts run inside one consensus block,
              so the isolation costs prompt calls rather than consensus
              rounds.
            </p>
          </div>
        </div>
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Three</span>
          <h2>What validators actually compare</h2>
        </div>

        <p className="pull claim">
          Two models reading the same page will write &ldquo;40 percent&rdquo;
          and &ldquo;40%&rdquo;, and both are right.
        </p>

        <p className="reading">
          So validators do not compare the extracted text. Rejecting a leader
          over wording would fail every check that ever ran. They compare the
          decisions those readings produce: the verdict, and the sorted lists
          of which sources dissented and which stayed silent. Those are what a
          caller acts on, and they are stable across reasonable differences in
          phrasing.
        </p>
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Four</span>
          <h2>The verdicts</h2>
        </div>

        <div className="verdicts">
          {VERDICTS.map(([name, agreed, dissented, silent, note]) => (
            <div key={name} className="verdict-cell">
              <GlyphRow
                agreed={agreed}
                dissented={dissented}
                silent={silent}
              />
              <span
                className={`value verdict-name v-${name.replace(" ", "_")}`}
              >
                {name}
              </span>
              <p className="soft">{note}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Five</span>
          <h2>Interface</h2>
        </div>

        <div className="table-wrap">
          <table className="spec-table iface">
            <thead>
              <tr>
                <th scope="col">Method</th>
                <th scope="col">Kind</th>
                <th scope="col">Arguments</th>
              </tr>
            </thead>
            <tbody>
              {INTERFACE.map(([name, kind, args]) => (
                <tr key={name}>
                  <th scope="row" className="value">
                    {name}
                  </th>
                  <td className="value kind-cell">{kind}</td>
                  <td className="value soft">{args || "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="notes">
          <p>
            Two sources minimum, eight maximum. One source is a quotation, not
            a corroboration.
          </p>
          <p>
            Each source costs one fetch and one prompt on every validator,
            and each gets its own consensus round rather than sharing one.
            That split is what makes a check finish at all: measured on this
            network, validators doing two fetches inside a single round never
            reached a terminal state, while the same work divided across
            rounds settled in under a minute. The value of another source
            also drops off sharply: the difference between three and four is
            large, between eleven and twelve is noise.
          </p>
          <p>
            Deployed on Bradbury at{" "}
            <a
              className="value inline-link"
              href={EXPLORER}
              target="_blank"
              rel="noreferrer noopener"
            >
              {CONTRACT}
            </a>
            .
          </p>
        </div>
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Six</span>
          <h2>Why the sources are frozen</h2>
        </div>

        <p className="reading">
          A live page that changes between two validators fetching it makes
          them disagree about the page rather than about the claim, and the
          check then fails for a reason that has nothing to do with the
          question asked. Pinning is a correctness requirement, not demo
          hygiene.
        </p>
        <p className="reading">
          The check stored on chain reads two live third-party APIs on
          unrelated hosts, not copies kept here. Archived snapshots are still
          in the repository with a header recording each original URL and the
          moment it was retrieved, but they can no longer form a check between
          them: independence is judged on the host actually fetched, and every
          snapshot is served from the same one. Refusing sources that might be
          independent is the safe direction to fail in. Accepting sources that
          are not is the direction that makes a stored verdict a lie.
        </p>
      </section>
    </div>
  );
}
