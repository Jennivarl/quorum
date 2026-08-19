import { useMemo, useState } from "react";
import { CONTRACT, RPC, isChecked } from "../lib/chain";
import "./runcheck.css";

const MIN_SOURCES = 2;
const MAX_SOURCES = 8;

const PINNED =
  "https://raw.githubusercontent.com/Jennivarl/quorum/" +
  "3b31b473f78a86d6383790f8c9d3c299f718d435/fixtures/sources";

const EXAMPLE = {
  id: "lagos-population",
  claim: "What is the population of Lagos, Nigeria?",
  sources: [
    `${PINNED}/wikipedia.txt`,
    `${PINNED}/citypopulation.txt`,
    `${PINNED}/worldpopulationreview.txt`,
    `${PINNED}/britannica.txt`,
    `${PINNED}/wikidata.txt`,
  ],
};

type Problem = { field: string; message: string };

function validate(id: string, claim: string, sources: string[]): Problem[] {
  const out: Problem[] = [];
  const key = id.trim().toLowerCase();

  if (!key) {
    out.push({ field: "id", message: "A check needs an id to be stored under." });
  } else if (!/^[a-z0-9][a-z0-9-]*$/.test(key)) {
    out.push({
      field: "id",
      message: "Use lowercase letters, digits and hyphens only.",
    });
  }

  if (!claim.trim()) {
    out.push({ field: "claim", message: "Say what you want corroborated." });
  } else if (!claim.trim().includes(" ")) {
    out.push({
      field: "claim",
      message: "A single word is not a claim. Ask a question.",
    });
  }

  const filled = sources.map((s) => s.trim()).filter(Boolean);

  if (filled.length < MIN_SOURCES) {
    out.push({
      field: "sources",
      message:
        "At least two sources. One source is a quotation, not a corroboration.",
    });
  }
  if (filled.length > MAX_SOURCES) {
    out.push({
      field: "sources",
      message: `At most ${MAX_SOURCES}. Each one costs a fetch and a prompt on every validator.`,
    });
  }

  for (const url of filled) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "https:") {
        out.push({ field: url, message: "Sources must be https." });
      }
    } catch {
      out.push({ field: url, message: `Not a URL: ${url}` });
    }
  }

  const hosts = filled.map((u) => {
    try {
      return new URL(u).hostname;
    } catch {
      return u;
    }
  });
  const dupes = hosts.filter((h, i) => hosts.indexOf(h) !== i);
  if (dupes.length && new Set(hosts).size < 2) {
    out.push({
      field: "sources",
      message:
        "Every source is on the same host. Corroboration needs independent publishers, not one publisher read several times.",
    });
  }

  if (new Set(filled).size !== filled.length) {
    out.push({ field: "sources", message: "The same URL is listed twice." });
  }

  return out;
}

function buildCommand(id: string, claim: string, sources: string[]): string {
  const filled = sources.map((s) => s.trim()).filter(Boolean);
  const json = JSON.stringify(filled);
  return [
    `genlayer write ${CONTRACT} check \\`,
    `  --args ${id.trim().toLowerCase() || "my-check"} ${JSON.stringify(claim.trim())} \\`,
    `  '${json}' \\`,
    `  --rpc ${RPC}`,
  ].join("\n");
}

export default function RunCheck() {
  const [id, setId] = useState("");
  const [claim, setClaim] = useState("");
  const [sources, setSources] = useState<string[]>(["", "", ""]);
  const [taken, setTaken] = useState<string | null>(null);
  const [checkingId, setCheckingId] = useState(false);
  const [copied, setCopied] = useState(false);

  const problems = useMemo(
    () => validate(id, claim, sources),
    [id, claim, sources],
  );
  const ready = problems.length === 0;
  const filledCount = sources.filter((s) => s.trim()).length;

  const command = buildCommand(id, claim, sources);

  function setSource(index: number, value: string) {
    setSources((prev) => prev.map((s, i) => (i === index ? value : s)));
  }

  function addSource() {
    setSources((prev) =>
      prev.length >= MAX_SOURCES ? prev : [...prev, ""],
    );
  }

  function removeSource(index: number) {
    setSources((prev) =>
      prev.length <= MIN_SOURCES ? prev : prev.filter((_, i) => i !== index),
    );
  }

  function loadExample() {
    setId(EXAMPLE.id);
    setClaim(EXAMPLE.claim);
    setSources(EXAMPLE.sources);
    setTaken(null);
  }

  async function checkIdTaken() {
    const key = id.trim().toLowerCase();
    if (!key) return;
    setCheckingId(true);
    try {
      setTaken((await isChecked(key)) ? key : null);
    } catch {
      setTaken(null);
    } finally {
      setCheckingId(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="shell page-body run">
      <header className="run-head">
        <span className="label">New check</span>
        <h1 className="claim run-title">What do you want corroborated?</h1>
      </header>

      <section className="form">
        <div className="field">
          <label className="label" htmlFor="claim-input">
            The claim
          </label>
          <input
            id="claim-input"
            className="claim-input"
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            placeholder="What is the population of Lagos, Nigeria?"
            spellCheck
          />
          <Problems problems={problems} field="claim" />
        </div>

        <div className="field">
          <label className="label" htmlFor="id-input">
            Stored under
          </label>
          <div className="id-row">
            <input
              id="id-input"
              className="value id-input"
              value={id}
              onChange={(e) => {
                setId(e.target.value);
                setTaken(null);
              }}
              onBlur={checkIdTaken}
              placeholder="lagos-population"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
            {checkingId && <span className="label">checking</span>}
            {taken && (
              <span className="label taken">
                already used, the contract will refuse it
              </span>
            )}
          </div>
          <Problems problems={problems} field="id" />
        </div>

        <div className="field">
          <div className="sources-head">
            <span className="label">
              Sources &middot; {MIN_SOURCES} minimum, {MAX_SOURCES} maximum
            </span>
            <span className="label">{filledCount} entered</span>
          </div>

          <div className="source-rows">
            {sources.map((value, i) => (
              <div className="source-row" key={i}>
                <span className="label source-n">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <input
                  className="value source-input"
                  value={value}
                  onChange={(e) => setSource(i, e.target.value)}
                  placeholder="https://..."
                  aria-label={`Source ${i + 1}`}
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                />
                <button
                  type="button"
                  className="label row-remove"
                  onClick={() => removeSource(i)}
                  disabled={sources.length <= MIN_SOURCES}
                >
                  remove
                </button>
              </div>
            ))}
          </div>

          <div className="source-actions">
            <button
              type="button"
              className="label textbtn"
              onClick={addSource}
              disabled={sources.length >= MAX_SOURCES}
            >
              + Add source
            </button>
            <button type="button" className="label textbtn" onClick={loadExample}>
              Load the reference check
            </button>
          </div>

          <Problems problems={problems} field="sources" />
          {problems
            .filter((p) => p.field.startsWith("http") || p.message.startsWith("Not a URL"))
            .map((p) => (
              <p className="problem" key={p.message}>
                {p.message}
              </p>
            ))}
        </div>

        <p className="note soft">
          Use archived or revision-pinned URLs. A live page that changes
          between two validators fetching it makes them disagree about the
          page rather than about the claim, and the check then fails for a
          reason that has nothing to do with your question.
        </p>
      </section>

      <section className="runner">
        <div className="section-head">
          <span className="label">Run it</span>
          <h2>From your own terminal, with your own account</h2>
        </div>

        <p className="reading soft">
          A check is a write, so it has to be signed and paid for by whoever
          runs it. This page will not ask for your keys and cannot spend on
          your behalf. It builds the exact command instead.
        </p>

        <div className={`cmd-block${ready ? "" : " is-incomplete"}`}>
          <div className="cmd-head">
            <span className="label">
              {ready ? "Ready to run" : "Fill the form above to complete this"}
            </span>
            <button
              type="button"
              className="label textbtn"
              onClick={copy}
              disabled={!ready}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="value">{command}</pre>
        </div>

        <div className="expectations">
          <div>
            <span className="label">What it costs</span>
            <p className="soft">
              One fetch and one prompt per source, repeated on every
              validator. A five-source check is roughly thirty model calls
              before consensus is reached.
            </p>
          </div>
          <div>
            <span className="label">How long it takes</span>
            <p className="soft">
              Minutes, not seconds, and the client often gives up before the
              chain does. A reported timeout is not proof of failure.
            </p>
          </div>
          <div>
            <span className="label">If it times out</span>
            <p className="soft">
              Read <span className="value">is_checked</span> before assuming
              anything. A genuinely failed attempt writes no state at all, so
              running it again is safe.
            </p>
          </div>
        </div>

        <div className="cmd-block">
          <div className="cmd-head">
            <span className="label">Then read it back, which costs nothing</span>
          </div>
          <pre className="value">
{`genlayer call ${CONTRACT} is_checked \\
  --args ${id.trim().toLowerCase() || "my-check"} \\
  --rpc ${RPC}`}
          </pre>
        </div>
      </section>
    </div>
  );
}

function Problems({
  problems,
  field,
}: {
  problems: Problem[];
  field: string;
}) {
  const mine = problems.filter((p) => p.field === field);
  if (!mine.length) return null;
  return (
    <>
      {mine.map((p) => (
        <p className="problem" key={p.message}>
          {p.message}
        </p>
      ))}
    </>
  );
}
