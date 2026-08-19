import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import type { CheckRecord, ReferenceRecord, Summary } from "./types";

export const CONTRACT = "0xa6BbF862781407Bd95E434BA7eF44e0c77bD120b";
export const RPC = "https://rpc-bradbury.genlayer.com";
export const EXPLORER = `https://explorer-bradbury.genlayer.com/address/${CONTRACT}`;

export type Loaded<T> = {
  data: T;
  /** Where the record actually came from, which the page states plainly. */
  source: "chain" | "cache";
  error?: string;
};

let cachedClient: ReturnType<typeof createClient> | null = null;

function client() {
  if (!cachedClient) {
    // A throwaway account. Every call the site makes is a view, so nothing is
    // ever signed and there is nothing to fund.
    cachedClient = createClient({
      chain: testnetBradbury,
      account: createAccount(),
    });
  }
  return cachedClient;
}

/**
 * Reads are free and fast, writes are neither. Everything the site renders by
 * default comes from a view call or from the committed reference record.
 */
export async function readCheck(checkId: string): Promise<CheckRecord> {
  const c = client();
  const result = await c.readContract({
    address: CONTRACT as `0x${string}`,
    functionName: "get_check",
    args: [checkId],
  });
  return result as unknown as CheckRecord;
}

export async function isChecked(checkId: string): Promise<boolean> {
  const c = client();
  const result = await c.readContract({
    address: CONTRACT as `0x${string}`,
    functionName: "is_checked",
    args: [checkId],
  });
  return Boolean(result);
}

/** Every check the contract holds, in one call, without the quotes. */
export async function readSummaries(): Promise<Summary[]> {
  const c = client();
  const result = await c.readContract({
    address: CONTRACT as `0x${string}`,
    functionName: "summaries",
    args: [],
  });
  return (result ?? []) as unknown as Summary[];
}

export async function readCheckIds(): Promise<string[]> {
  const c = client();
  const result = await c.readContract({
    address: CONTRACT as `0x${string}`,
    functionName: "check_ids",
    args: [],
  });
  return (result ?? []) as unknown as string[];
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
 * The fallback is not a convenience. Bradbury is a testnet and is regularly
 * unreachable or at capacity, and a page about verifiable claims that shows a
 * spinner forever makes exactly the wrong argument. The committed copy is the
 * same record, read back from this contract, and the page says which one it
 * is looking at rather than quietly pretending.
 *
 * The chain copy has no publisher names or provenance, since the contract
 * stores URLs only, so those fields are merged in from the reference by URL.
 */
export async function loadReferenceCheck(): Promise<Loaded<ReferenceRecord>> {
  const cached = await loadReference();
  try {
    const live = await readCheck(cached.check_id);
    const byUrl = new Map(cached.answers.map((a) => [a.url, a]));
    return {
      data: {
        ...cached,
        ...live,
        answers: live.answers.map((a) => ({
          ...a,
          publisher: byUrl.get(a.url)?.publisher,
          origin: byUrl.get(a.url)?.origin,
          retrieved: byUrl.get(a.url)?.retrieved,
        })),
      },
      source: "chain",
    };
  } catch (err) {
    return {
      data: cached,
      source: "cache",
      error: err instanceof Error ? err.message : String(err),
    };
  }
}
