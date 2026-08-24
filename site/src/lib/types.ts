export type Verdict = "corroborated" | "majority" | "contested" | "no_data";

export type SourceStatus = "found" | "not_stated" | "unreadable";

/** How a source ended up counted, which is what the glyph draws. */
export type Standing = "agreed" | "dissented" | "silent";

export interface SourceAnswer {
  url: string;
  status: SourceStatus;
  answer: string;
  quote: string;
  /** Only present on the committed reference record, not on chain. */
  publisher?: string;
  origin?: string;
  retrieved?: string;
}

export interface CheckRecord {
  claim: string;
  verdict: Verdict;
  consensus_value: string;
  agreement_percent: number;
  sources_answered: number;
  sources_dissenting: number;
  sources_silent: number;
  answers: SourceAnswer[];
  dissenting: string[];
  settled_by: string;
  checked_by: string;
}

export interface ReferenceRecord extends CheckRecord {
  check_id: string;
  contract: string;
  run_at: string;
}

/**
 * What the archive needs, which is deliberately not the whole record. The
 * quotes and per-source answers are most of the payload and none of what an
 * index shows.
 */
export interface Summary {
  check_id: string;
  claim: string;
  verdict: Verdict;
  consensus_value: string;
  agreement_percent: number;
  sources_answered: number;
  sources_dissenting: number;
  sources_silent: number;
  settled_by: string;
}

/**
 * The contract stores who dissented, not who agreed, because dissent is the
 * output that matters and the rest is derivable. Derive it here rather than
 * asking the chain for something it deliberately does not keep.
 */
export function standingOf(answer: SourceAnswer, dissenting: string[]): Standing {
  if (answer.status !== "found" || !answer.answer) return "silent";
  return dissenting.includes(answer.url) ? "dissented" : "agreed";
}

export function tally(record: CheckRecord): Record<Standing, number> {
  const out: Record<Standing, number> = { agreed: 0, dissented: 0, silent: 0 };
  for (const a of record.answers) out[standingOf(a, record.dissenting)] += 1;
  return out;
}

/**
 * A readable name for a source. The chain stores the raw URL, which for the
 * pinned fixtures is a 130-character githubusercontent path that tells a
 * reader nothing. Fall back to the host when there is no better label.
 */
export function publisherOf(answer: SourceAnswer): string {
  if (answer.publisher) return answer.publisher;

  // The contract now stores the origin, so the publisher can be named from
  // where the claim was published rather than from whatever file the
  // archived copy happens to sit in. Falling back to the archive URL would
  // label every source "raw.githubusercontent.com", which tells a reader
  // nothing about independence.
  const candidate = answer.origin || answer.url;
  try {
    const url = new URL(candidate);
    const host = url.hostname.replace(/^www\./, "");
    if (host !== "raw.githubusercontent.com") return host;
    const file = url.pathname.split("/").pop() ?? "";
    return file.endsWith(".txt") ? file.replace(/\.txt$/, "") : host;
  } catch {
    return candidate;
  }
}
