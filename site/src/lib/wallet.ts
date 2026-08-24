import { CONTRACT, RPC } from "./chain";

/**
 * Running a check from the browser.
 *
 * A check is a write. It costs one fetch and one prompt per source on every
 * validator, so it has to be signed and paid for by whoever wants the
 * answer. This page never asks for a key and never holds funds; it asks the
 * visitor's wallet to sign, and the wallet decides.
 *
 * Everything here is deliberately honest about failure, because on Bradbury
 * a write frequently does not complete and the ways it does not complete are
 * genuinely confusing. See `waitForCheck` for the specific trap.
 */

export const CHAIN_ID = 4221;
export const CHAIN_ID_HEX = "0x107d";

type Eip1193 = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  on?: (event: string, handler: (...args: unknown[]) => void) => void;
  removeListener?: (event: string, handler: (...args: unknown[]) => void) => void;
};

declare global {
  interface Window {
    ethereum?: Eip1193;
  }
}

export function walletAvailable(): boolean {
  return typeof window !== "undefined" && Boolean(window.ethereum);
}

function provider(): Eip1193 {
  const p = window.ethereum;
  if (!p) throw new Error("No wallet found in this browser.");
  return p;
}

/** Human-readable reason, or null if the wallet simply said no. */
export function walletError(err: unknown): string | null {
  const code = (err as { code?: number })?.code;
  // 4001 is the standard "user rejected". Not an error worth reporting as
  // one; they changed their mind.
  if (code === 4001) return null;
  const message = err instanceof Error ? err.message : String(err);
  return message.replace(/^Error:\s*/, "");
}

export async function connect(): Promise<string> {
  const accounts = (await provider().request({
    method: "eth_requestAccounts",
  })) as string[];
  if (!accounts?.length) throw new Error("Wallet returned no accounts.");
  return accounts[0];
}

export async function currentAccount(): Promise<string | null> {
  if (!walletAvailable()) return null;
  try {
    const accounts = (await provider().request({
      method: "eth_accounts",
    })) as string[];
    return accounts?.[0] ?? null;
  } catch {
    return null;
  }
}

export async function onCorrectChain(): Promise<boolean> {
  try {
    const id = (await provider().request({ method: "eth_chainId" })) as string;
    return parseInt(id, 16) === CHAIN_ID;
  } catch {
    return false;
  }
}

/**
 * Move the wallet to Bradbury, adding it if the wallet has never seen it.
 *
 * 4902 means "unrecognised chain", which is the expected answer the first
 * time and not a failure.
 */
export async function ensureChain(): Promise<void> {
  if (await onCorrectChain()) return;
  try {
    await provider().request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (err) {
    if ((err as { code?: number })?.code !== 4902) throw err;
    await provider().request({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: CHAIN_ID_HEX,
          chainName: "GenLayer Bradbury Testnet",
          rpcUrls: [RPC],
          nativeCurrency: { name: "GEN Token", symbol: "GEN", decimals: 18 },
          blockExplorers: [
            { name: "GenLayer Explorer", url: "https://explorer-bradbury.genlayer.com" },
          ],
        },
      ],
    });
  }
}

export type SourceInput = { url: string; origin: string };

/**
 * Submit a check and return its transaction hash.
 *
 * Returning as soon as the transaction is submitted is deliberate. Waiting
 * for a receipt here would inherit the client's patience, which on this
 * network is consistently shorter than the chain's, and would report
 * failures that later turn out to have succeeded.
 */
export async function submitCheck(
  checkId: string,
  claim: string,
  sources: SourceInput[],
): Promise<string> {
  await ensureChain();
  const account = (await currentAccount()) ?? (await connect());

  const [{ createClient }, { testnetBradbury }] = await Promise.all([
    import("genlayer-js"),
    import("genlayer-js/chains"),
  ]);

  const client = createClient({
    chain: testnetBradbury,
    account: account as `0x${string}`,
    provider: provider() as never,
  });

  const hash = await client.writeContract({
    address: CONTRACT as `0x${string}`,
    functionName: "check",
    args: [
      checkId,
      claim,
      sources.map((s) => ({ url: s.url, origin: s.origin || s.url })),
    ],
    value: BigInt(0),
  });

  return String(hash);
}

export type Settled =
  | { state: "stored" }
  | { state: "gone"; status: string }
  | { state: "waiting"; status: string };

const TERMINAL = new Set(["Finalized", "Canceled", "Undetermined"]);

async function transactionStatus(hash: string): Promise<string> {
  const res = await fetch(RPC, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "gen_getTransactionStatus",
      params: [{ txId: hash }],
    }),
  });
  const body = (await res.json()) as { result?: { status?: string } };
  return body?.result?.status ?? "unknown";
}

/**
 * Wait for a submitted check to actually be stored.
 *
 * This is the part worth reading. On Bradbury neither signal can be trusted
 * on its own:
 *
 *   A timeout is not proof of failure. Writes have reported LEADER_TIMEOUT
 *   and been stored anyway.
 *
 *   A successful read is not proof of success. State has been readable for
 *   minutes and then rolled back when the transaction never finalised.
 *
 * So this waits for the transaction to reach a terminal state AND for the
 * contract to still hold the record afterwards, and reports "waiting"
 * rather than lying when it runs out of patience.
 */
export async function waitForCheck(
  hash: string,
  checkId: string,
  isStored: (id: string) => Promise<boolean>,
  onTick?: (status: string) => void,
  attempts = 40,
  intervalMs = 15000,
): Promise<Settled> {
  let status = "submitted";
  for (let i = 0; i < attempts; i += 1) {
    try {
      status = await transactionStatus(hash);
      onTick?.(status);
      if (TERMINAL.has(status)) {
        // Terminal is not the same as stored. Ask the contract.
        const stored = await isStored(checkId).catch(() => false);
        return stored ? { state: "stored" } : { state: "gone", status };
      }
    } catch {
      // A failed poll is not a failed transaction. Keep waiting.
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { state: "waiting", status };
}
