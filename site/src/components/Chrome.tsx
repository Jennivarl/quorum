import { Logo } from "./Glyph";
import { CONTRACT, EXPLORER } from "../lib/chain";
import "./chrome.css";

const NAV: [string, string][] = [
  ["#/run", "Run a check"],
  ["#/archive", "Archive"],
  ["#/method", "Method"],
];

const REPO = "https://github.com/Jennivarl/quorum";

export function Header({ route }: { route: string }) {
  return (
    <header className="masthead">
      <div className="shell masthead-inner">
        <a className="brand" href="#/">
          <Logo size={26} />
          <span>Quorum</span>
        </a>

        <nav aria-label="Primary">
          {NAV.map(([href, label]) => (
            <a
              key={href}
              href={href}
              aria-current={route === href.slice(1) ? "page" : undefined}
            >
              {label}
            </a>
          ))}
          <a href={REPO} target="_blank" rel="noreferrer noopener">
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="site-foot">
      <div className="shell site-foot-inner">
        <span className="label">Quorum</span>
        <a className="label foot-link" href={EXPLORER} target="_blank" rel="noreferrer noopener">
          {CONTRACT}
        </a>
        <a className="label foot-link" href={REPO} target="_blank" rel="noreferrer noopener">
          github.com/Jennivarl/quorum
        </a>
      </div>
    </footer>
  );
}

/**
 * Says where the record on screen actually came from. On a page arguing that
 * provenance matters, quietly serving a cached copy as though it were live
 * would be the one unforgivable detail.
 */
export function SourceBadge({
  source,
  reason,
}: {
  source: "chain" | "cache";
  reason?: "absent" | "unreachable";
}) {
  if (source === "chain") {
    return <span className="label source-badge">Read live from the contract</span>;
  }
  return (
    <span className="label source-badge">
      {reason === "absent"
        ? "Committed copy, this check is not on the contract"
        : "Committed copy, the chain did not answer"}
    </span>
  );
}
