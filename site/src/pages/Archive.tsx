import { useEffect, useMemo, useState } from "react";
import { GlyphRow } from "../components/Glyph";
import { SourceBadge } from "../components/Chrome";
import { loadReference, readSummaries } from "../lib/chain";
import type { Summary, Verdict } from "../lib/types";
import "./archive.css";

const FILTERS: [string, string][] = [
  ["all", "All"],
  ["corroborated", "Corroborated"],
  ["majority", "Majority"],
  ["contested", "Contested"],
  ["no_data", "No data"],
];

type State =
  | { phase: "loading" }
  | { phase: "ready"; rows: Summary[]; origin: "chain" | "cache" }
  | { phase: "error"; message: string };

export default function Archive() {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    let live = true;

    (async () => {
      try {
        const rows = await readSummaries();
        if (!live) return;
        setState({ phase: "ready", rows, origin: "chain" });
      } catch (err) {
        // Fall back to the one check that is committed to the repository.
        // Showing a real single row beats an error page, and the badge says
        // plainly that this did not come from the chain.
        const reference = await loadReference().catch(() => null);
        if (!live) return;
        if (reference) {
          setState({
            phase: "ready",
            origin: "cache",
            rows: [
              {
                check_id: reference.check_id,
                claim: reference.claim,
                verdict: reference.verdict,
                consensus_value: reference.consensus_value,
                agreement_percent: reference.agreement_percent,
                sources_answered: reference.sources_answered,
                sources_dissenting: reference.sources_dissenting,
                sources_silent: reference.sources_silent,
                settled_by: reference.settled_by,
              },
            ],
          });
          return;
        }
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    })();

    return () => {
      live = false;
    };
  }, []);

  const rows = state.phase === "ready" ? state.rows : [];

  const counts = useMemo(() => {
    const out: Record<string, number> = {
      all: rows.length,
      corroborated: 0,
      majority: 0,
      contested: 0,
      no_data: 0,
    };
    for (const r of rows) out[r.verdict] = (out[r.verdict] ?? 0) + 1;
    return out;
  }, [rows]);

  const shown = filter === "all" ? rows : rows.filter((r) => r.verdict === filter);

  return (
    <div className="shell page-body archive">
      <header className="archive-head">
        <span className="label">Archive</span>
        <h1 className="claim archive-title">
          Every check this contract has settled.
        </h1>

        {state.phase === "ready" && (
          <div className="archive-meta">
            <span className="value archive-tally">
              {counts.all} {counts.all === 1 ? "check" : "checks"}
              {counts.corroborated ? ` · ${counts.corroborated} corroborated` : ""}
              {counts.majority ? ` · ${counts.majority} majority` : ""}
              {counts.contested ? ` · ${counts.contested} contested` : ""}
              {counts.no_data ? ` · ${counts.no_data} no data` : ""}
            </span>
            <SourceBadge source={state.origin} />
          </div>
        )}
      </header>

      {state.phase === "loading" && (
        <div aria-busy="true">
          <span className="label">Reading the contract</span>
          <div className="archive-skeleton" />
        </div>
      )}

      {state.phase === "error" && (
        <div className="stack" style={{ gap: "1rem" }}>
          <span className="label">Could not read the contract</span>
          <p className="reading soft">{state.message}</p>
        </div>
      )}

      {state.phase === "ready" && rows.length === 0 && (
        <div className="stack" style={{ gap: "1rem" }}>
          <span className="label">Nothing yet</span>
          <p className="reading soft">
            This contract has settled no checks. A write that times out
            before it finalises leaves no record, which is the honest
            outcome: nothing half-written is stored.
          </p>
          <p>
            <a className="textlink" href="#/run">
              Run the first one
            </a>
          </p>
        </div>
      )}

      {state.phase === "ready" && rows.length > 0 && (
        <>
          <nav className="filters" aria-label="Filter by verdict">
            {FILTERS.filter(([key]) => key === "all" || counts[key] > 0).map(
              ([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`label filter${filter === key ? " is-on" : ""}`}
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                >
                  {label} <span className="filter-n">{counts[key] ?? 0}</span>
                </button>
              ),
            )}
          </nav>

          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th scope="col">Claim</th>
                  <th scope="col">Verdict</th>
                  <th scope="col">Sources</th>
                  <th scope="col" className="num">
                    Agreement
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <Row key={row.check_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ row }: { row: Summary }) {
  const agreed = row.sources_answered - row.sources_dissenting;
  return (
    <tr
      className="ledger-row"
      onClick={() => {
        window.location.hash = `#/check/${row.check_id}`;
      }}
    >
      <td>
        <a className="ledger-claim" href={`#/check/${row.check_id}`}>
          {row.claim}
        </a>
        <span className="label ledger-id">{row.check_id}</span>
      </td>
      <td>
        <span className={`value ledger-verdict v-${row.verdict}`}>
          {row.verdict.replace("_", " ")}
        </span>
      </td>
      <td>
        <GlyphRow
          agreed={agreed}
          dissented={row.sources_dissenting}
          silent={row.sources_silent}
        />
      </td>
      <td className="num">
        <span className="value">{row.agreement_percent}%</span>
      </td>
    </tr>
  );
}

export type { Verdict };
