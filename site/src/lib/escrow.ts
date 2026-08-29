import { RPC } from "./chain";
import { MAX_ROTATIONS, ensureChain, currentAccount, connect } from "./wallet";

/**
 * The escrow: money that moves on a verdict, and does not move when the
 * sources disagree.
 *
 * This lives in the browser because the GenLayer CLI has no way to send
 * value with a write. There is no `--value` flag, so a deposit cannot be
 * made from a terminal at all, and a wallet is the only route.
 */

export const ESCROW = "0xD2c89eF60744Ff2845b85b0B19Cc5c095116c7Db";
export const ESCROW_EXPLORER = `https://explorer-bradbury.genlayer.com/address/${ESCROW}`;

export type DealState = "open" | "released" | "refunded" | "cancelled";

export interface Deal {
  deal_id: string;
  check_id: string;
  claim: string;
  depositor: string;
  payee: string;
  amount: string | number | bigint;
  state: DealState;
  verdict: string;
  agreement_percent: number;
  dissenting: number;
  reason: string;
  naive_would_pay: boolean;
}

export interface Divergence {
  deal_id: string;
  claim: string;
  check_id: string;
  verdict: string;
  agreement_percent: number;
  dissenting: number;
  amount_returned: string | number | bigint;
  reason: string;
}

type ReadClient = {
  readContract: (a: {
    address: `0x${string}`;
    functionName: string;
    args: unknown[];
  }) => Promise<unknown>;
};

let readerPromise: Promise<ReadClient> | null = null;

function reader(): Promise<ReadClient> {
  if (!readerPromise) {
    readerPromise = (async () => {
      const [{ createClient, createAccount }, { testnetBradbury }] =
        await Promise.all([
          import("genlayer-js"),
          import("genlayer-js/chains"),
        ]);
      return createClient({
        chain: testnetBradbury,
        account: createAccount(),
      }) as unknown as ReadClient;
    })();
  }
  return readerPromise;
}

async function view<T>(functionName: string, args: unknown[] = []): Promise<T> {
  const c = await reader();
  return (await c.readContract({
    address: ESCROW as `0x${string}`,
    functionName,
    args,
  })) as T;
}

export async function readDealIds(): Promise<string[]> {
  return (await view<string[] | null>("deal_ids")) ?? [];
}

export function readDeal(dealId: string): Promise<Deal> {
  return view<Deal>("get_deal", [dealId]);
}

export async function readDivergences(): Promise<Divergence[]> {
  return (await view<Divergence[] | null>("divergences")) ?? [];
}

export async function readAllDeals(): Promise<Deal[]> {
  const ids = await readDealIds();
  const out: Deal[] = [];
  for (const id of ids) {
    try {
      out.push(await readDeal(id));
    } catch {
      // A deal that cannot be read is not worth failing the whole page for.
    }
  }
  return out;
}

async function writer() {
  await ensureChain();
  const account = (await currentAccount()) ?? (await connect());
  const [{ createClient }, { testnetBradbury }] = await Promise.all([
    import("genlayer-js"),
    import("genlayer-js/chains"),
  ]);
  const provider = (window as unknown as { ethereum?: unknown }).ethereum;
  return createClient({
    chain: testnetBradbury,
    account: account as `0x${string}`,
    provider: provider as never,
  });
}

/** GEN has 18 decimals, same as ether. */
export function toWei(gen: string): bigint {
  const [whole, frac = ""] = gen.trim().split(".");
  const padded = (frac + "0".repeat(18)).slice(0, 18);
  return BigInt(whole || "0") * BigInt("1000000000000000000") + BigInt(padded || "0");
}

export function fromWei(wei: string | number | bigint): string {
  const v = BigInt(wei ?? 0);
  const whole = v / BigInt("1000000000000000000");
  const frac = (v % BigInt("1000000000000000000")).toString().padStart(18, "0");
  const trimmed = frac.replace(/0+$/, "").slice(0, 4);
  return trimmed ? `${whole}.${trimmed}` : String(whole);
}

export async function openDeal(
  dealId: string,
  checkId: string,
  claim: string,
  payee: string,
  amountGen: string,
): Promise<string> {
  const client = await writer();
  const hash = await client.writeContract({
    address: ESCROW as `0x${string}`,
    functionName: "open_deal",
    args: [dealId, checkId, claim, payee],
    value: toWei(amountGen),
    consensusMaxRotations: MAX_ROTATIONS,
  });
  return String(hash);
}

export async function resolveDeal(dealId: string): Promise<string> {
  const client = await writer();
  const hash = await client.writeContract({
    address: ESCROW as `0x${string}`,
    functionName: "resolve",
    args: [dealId],
    value: BigInt(0),
    consensusMaxRotations: MAX_ROTATIONS,
  });
  return String(hash);
}

export async function cancelDeal(dealId: string): Promise<string> {
  const client = await writer();
  const hash = await client.writeContract({
    address: ESCROW as `0x${string}`,
    functionName: "cancel",
    args: [dealId],
    value: BigInt(0),
    consensusMaxRotations: MAX_ROTATIONS,
  });
  return String(hash);
}

/** Whether a deal id already exists, so the form can say so before signing. */
export async function dealExists(dealId: string): Promise<boolean> {
  const ids = await readDealIds();
  return ids.includes(dealId.trim().toLowerCase());
}

export { RPC };
