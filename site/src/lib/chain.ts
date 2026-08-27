import type { CheckRecord, ReferenceRecord, Summary } from "./types";

export const CONTRACT = "0x407C90fB85C0613EFC0a7Dc4833ce1Cea52C9882";
export const RPC = "https://rpc-bradbury.genlayer.com";
export const EXPLORER = `https://explorer-bradbury.genlayer.com/address/${CONTRACT}`;

export type Loaded<T> = {
  data: T;
  /** Where the record actually came from, which the page states plainly. */
  source: "chain" | "cache";
  /**
   * Why the cache was used, when it was.
   *
   * "absent" and "unreachable" are genuinely different and were previously
   * reported as the same thing, which had the page claiming the chain was
   * down whenever a record simply did not exist. On a site arguing that
   * sources should be reported accurately, that was the wrong thing to get
   * wrong.
   */
  reason?: "absent" | "unreachable";
  error?: string;
};

/**
 * genlayer-js is most of this site's weight, and two of the five pages never
 * touch the chain at all. Importing it dynamically keeps it out of the entry
 * bundle, so the page renders first and the library arrives only when
 * something actually needs to read from Bradbury.
 */
type ReadOnlyClient = {
  readContract: (args: {
    address: `0x${string}`;
    functionName: string;
    args: unknown[];
  }) => Promise<unknown>;
};

let clientPromise: Promise<ReadOnlyClient> | null = null;

function client(): Promise<ReadOnlyClient> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const [{ createClient, createAccount }, { testnetBradbury }] =
        await Promise.all([
          import("genlayer-js"),
          import("genlayer-js/chains"),
        ]);
      // A throwaway account. Every call the site makes is a view, so nothing
      // is ever signed and there is nothing to fund.
      return createClient({
        chain: testnetBradbury,
        account: createAccount(),
      }) as unknown as ReadOnlyClient;
    })();
  }
  return clientPromise;
}

async function view<T>(functionName: string, args: unknown[] = []): Promise<T> {
  const c = await client();
  const result = await c.readContract({
    address: CONTRACT as `0x${string}`,
    functionName,
    args,
  });
  return result as T;
}

/**
 * Reads are free and fast, writes are neither. Everything the site renders by
 * default comes from a view call or from the committed reference record.
 */
export function readCheck(checkId: string): Promise<CheckRecord> {
  return view<CheckRecord>("get_check", [checkId]);
}

export async function isChecked(checkId: string): Promise<boolean> {
  return Boolean(await view<boolean>("is_checked", [checkId]));
}

/** Every check the contract holds, in one call, without the quotes. */
export async function readSummaries(): Promise<Summary[]> {
  return (await view<Summary[] | null>("summaries")) ?? [];
}

export async function readCheckIds(): Promise<string[]> {
  return (await view<string[] | null>("check_ids")) ?? [];
}

export async function readCount(): Promise<number> {
  return Number(await view<number>("count"));
}

/**
 * Which check the home page should lead with.
 *
 * A contested one, if the contract holds any. Corroboration is the boring
 * case and the page is arguing that disagreement is the thing worth
 * recording, so leading with unanimity would undercut it. Falls back to the
 * committed record when the contract is empty or unreachable.
 */
async function featuredId(fallback: string): Promise<string> {
  const rows = await readSummaries();
  if (!rows.length) return fallback;
  const contested = rows.find((r) => r.verdict === "contested");
  if (contested) return contested.check_id;
  const majority = rows.find((r) => r.verdict === "majority");
  return (majority ?? rows[rows.length - 1]).check_id;
}

let cachedReference: ReferenceRecord | null = null;

export async function loadReference(): Promise<ReferenceRecord> {
  if (cachedReference) return cachedReference;
  const res = await fetch(`${import.meta.env.BASE_URL}reference.json`);
  cachedReference = (await res.json()) as ReferenceRecord;
  return cachedReference;
}

/**
 * The reference check, preferring the chain and falling back to the committed
 * copy.
 *
 * The fallback is not a convenience. Bradbury is a testnet and regularly
 * cannot carry a check to consensus, and a page about verifiable claims that
 * shows a spinner forever makes exactly the wrong argument. The committed
 * copy is genuine output from a real run of this contract, and the page says
 * which one it is showing rather than quietly pretending.
 *
 * The chain copy has no publisher names or provenance, since the contract
 * stores URLs only, so those fields are merged in from the reference by URL.
 */
export async function loadReferenceCheck(): Promise<Loaded<ReferenceRecord>> {
  const cached = await loadReference();
  try {
    const id = await featuredId(cached.check_id);
    const live = await readCheck(id);
    // Do not write the live id back onto `cached`: it is the module-level
    // fallback and other pages read it. Overwriting it would make a later
    // fallback claim to be a check that is not in the file.
    const byUrl = new Map(cached.answers.map((a) => [a.url, a]));
    return {
      data: {
        ...cached,
        ...live,
        check_id: id,
        // Everything shown about a source comes from the chain, because
        // consensus checked it there. The committed copy contributes only
        // the two presentational fields the record does not hold: a human
        // publisher name and when the archive was captured.
        answers: live.answers.map((a) => ({
          ...a,
          publisher: byUrl.get(a.url)?.publisher,
          retrieved: byUrl.get(a.url)?.retrieved,
        })),
      },
      source: "chain",
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // A KeyError from the contract means the record is not stored. That is
    // a different fact from the chain being unreachable, and saying so
    // matters more here than almost anywhere.
    return {
      data: cached,
      source: "cache",
      reason: message.includes("KeyError") ? "absent" : "unreachable",
      error: message,
    };
  }
}
