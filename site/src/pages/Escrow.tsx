import { useEffect, useState } from "react";
import { GlyphRow } from "../components/Glyph";
import { CONTRACT } from "../lib/chain";
import {
  ESCROW,
  ESCROW_EXPLORER,
  cancelDeal,
  fromWei,
  openDeal,
  readAllDeals,
  readDivergences,
  resolveDeal,
  type Deal,
  type Divergence,
} from "../lib/escrow";
import {
  currentAccount,
  connect,
  walletAvailable,
  walletError,
} from "../lib/wallet";
import "./escrow.css";

type Busy = { kind: "open" | "resolve" | "cancel"; id: string } | null;

export default function Escrow() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [divergences, setDivergences] = useState<Divergence[]>([]);
  const [account, setAccount] = useState<string | null>(null);
  const [hasWallet, setHasWallet] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [dealId, setDealId] = useState("");
  const [checkId, setCheckId] = useState("");
  const [claim, setClaim] = useState("");
  const [payee, setPayee] = useState("");
  const [amount, setAmount] = useState("0.01");

  async function refresh() {
    const [d, v] = await Promise.all([
      readAllDeals().catch(() => []),
      readDivergences().catch(() => []),
    ]);
    setDeals(d);
    setDivergences(v);
    setLoading(false);
  }

  useEffect(() => {
    setHasWallet(walletAvailable());
    currentAccount().then(setAccount);
    refresh();
  }, []);

  async function act(fn: () => Promise<string>, kind: Busy) {
    setBusy(kind);
    setNote(null);
    try {
      const hash = await fn();
      setNote(
        `Submitted ${hash.slice(0, 14)}... This takes minutes. The list below ` +
          `updates when it lands.`,
      );
      window.setTimeout(refresh, 45000);
    } catch (err) {
      const message = walletError(err);
      if (message) setNote(message);
    } finally {
      setBusy(null);
    }
  }

  const canOpen =
    Boolean(account) &&
    dealId.trim() &&
    checkId.trim() &&
    claim.trim() &&
    /^0x[0-9a-fA-F]{40}$/.test(payee.trim()) &&
    Number(amount) > 0;

  return (
    <div className="shell page-body escrow">
      <header className="escrow-head">
        <span className="label">Escrow</span>
        <h1 className="claim escrow-title">
          Money that does not move when the sources disagree.
        </h1>
        <p className="escrow-lede">
          Deposit against a claim before it is checked. If the sources
          corroborate, the funds are released. If they contest it, the funds
          go back, and the record says which sources caused that.
        </p>
      </header>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Why this exists</span>
          <h2>A refusal is only meaningful if something was at stake</h2>
        </div>
        <p className="reading soft">
          An oracle that hands back a single number gives a consumer nothing
          to refuse on. It pays out on a figure two reputable publishers
          disagree about by thirty million, and nobody finds out. Here the
          disagreement has a consequence: the deposit is returned rather than
          paid on a figure in dispute.
        </p>
        <p className="reading soft">
          Nobody privileged decides. Anyone may resolve a deal, because the
          verdict was already settled under consensus in{" "}
          <span className="value">{CONTRACT.slice(0, 10)}...</span> and this
          contract only applies a threshold to it.
        </p>
      </section>

      {divergences.length > 0 && (
        <section className="divergences">
          <div className="section-head">
            <span className="label">Dissent changed where the money went</span>
            <h2>
              {divergences.length} deal{divergences.length === 1 ? "" : "s"}{" "}
              refunded that a single-source oracle would have paid
            </h2>
          </div>
          {divergences.map((d) => (
            <div className="divergence" key={d.deal_id}>
              <p className="claim divergence-claim">{d.claim}</p>
              <p className="value divergence-line">
                {fromWei(d.amount_returned)} GEN returned &middot;{" "}
                <span className="v-contested">{d.verdict}</span> at{" "}
                {d.agreement_percent}% &middot; {d.dissenting} source
                {d.dissenting === 1 ? "" : "s"} disagreed
              </p>
              <p className="soft divergence-reason">{d.reason}</p>
            </div>
          ))}
        </section>
      )}

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Open a deal</span>
          <h2>Deposit against a claim</h2>
        </div>

        {!hasWallet && (
          <p className="note soft">
            A deposit sends value, and the GenLayer CLI has no way to do that.
            A browser wallet is the only route, and none is available here.
          </p>
        )}

        {hasWallet && !account && (
          <button
            type="button"
            className="run-button"
            onClick={() =>
              connect()
                .then(setAccount)
                .catch((e) => setNote(walletError(e)))
            }
          >
            Connect wallet
          </button>
        )}

        {hasWallet && account && (
          <div className="escrow-form">
            <Field label="Deal id" value={dealId} onChange={setDealId} mono
              placeholder="nigeria-deal-1" />
            <Field label="Check id" value={checkId} onChange={setCheckId} mono
              placeholder="nigeria-2018" />
            <Field label="Claim" value={claim} onChange={setClaim}
              placeholder="What was the population of Nigeria in 2018?" />
            <Field label="Payee" value={payee} onChange={setPayee} mono
              placeholder="0x... (must not be you)" />
            <Field label="Amount in GEN" value={amount} onChange={setAmount} mono
              placeholder="0.01" />

            <div className="run-row">
              <button
                type="button"
                className="run-button"
                disabled={!canOpen || busy !== null}
                onClick={() =>
                  act(
                    () => openDeal(dealId, checkId, claim, payee, amount),
                    { kind: "open", id: dealId },
                  )
                }
              >
                {busy?.kind === "open" ? "Depositing" : "Deposit"}
              </button>
              <span className="label value">
                {account.slice(0, 6)}...{account.slice(-4)}
              </span>
            </div>
          </div>
        )}

        {note && <p className="note soft">{note}</p>}
      </section>

      <section className="stack" style={{ gap: "var(--gap-m)" }}>
        <div className="section-head">
          <span className="label">Deals</span>
          <h2>{loading ? "Reading the contract" : `${deals.length} on chain`}</h2>
        </div>

        {!loading && deals.length === 0 && (
          <p className="reading soft">
            No deals yet. The contract is deployed and its views answer; it is
            waiting for the first deposit.
          </p>
        )}

        <div className="deals">
          {deals.map((d) => (
            <div className={`deal st-${d.state}`} key={d.deal_id}>
              <div className="deal-head">
                <span className="value deal-id">{d.deal_id}</span>
                <span className={`value deal-state s-${d.state}`}>{d.state}</span>
              </div>
              <p className="claim deal-claim">{d.claim}</p>
              <p className="value deal-line">
                {fromWei(d.amount)} GEN &middot; check{" "}
                <a className="inline-link" href={`#/check/${d.check_id}`}>
                  {d.check_id}
                </a>
                {d.verdict ? ` · ${d.verdict} at ${d.agreement_percent}%` : ""}
              </p>
              {d.reason && <p className="soft deal-reason">{d.reason}</p>}
              {d.state === "open" && account && (
                <div className="deal-actions">
                  <button
                    type="button"
                    className="label textbtn"
                    disabled={busy !== null}
                    onClick={() =>
                      act(() => resolveDeal(d.deal_id), {
                        kind: "resolve",
                        id: d.deal_id,
                      })
                    }
                  >
                    Resolve
                  </button>
                  {account.toLowerCase() === d.depositor.toLowerCase() && (
                    <button
                      type="button"
                      className="label textbtn"
                      disabled={busy !== null}
                      onClick={() =>
                        act(() => cancelDeal(d.deal_id), {
                          kind: "cancel",
                          id: d.deal_id,
                        })
                      }
                    >
                      Cancel and refund
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="stack" style={{ gap: "var(--gap-s)" }}>
        <div className="section-head">
          <span className="label">On chain</span>
          <h2>Verify it yourself</h2>
        </div>
        <p className="value">
          <a
            className="inline-link"
            href={ESCROW_EXPLORER}
            target="_blank"
            rel="noreferrer noopener"
          >
            {ESCROW}
          </a>
        </p>
        <p className="soft" style={{ fontSize: "var(--step-1)" }}>
          Three writes: open_deal, resolve, cancel. Value leaves only to the
          payee or the depositor, state is settled before any transfer, and
          transfers are emitted on finalisation so a rolled-back transaction
          cannot move funds.
        </p>
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <label className="escrow-field">
      <span className="label">{label}</span>
      <input
        className={mono ? "value escrow-input" : "escrow-input"}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
      />
    </label>
  );
}

export { GlyphRow };
