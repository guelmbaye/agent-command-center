"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/format";
import type { Approval } from "@/lib/types";

/**
 * Frontière d'autorité humaine.
 *
 * Le modal expose le motif, le montant, le risque et les preuves : l'opérateur
 * décide sur des faits, jamais sur une formulation de modèle. La décision
 * devient un enregistrement durable de la mission (Doc 03 §9).
 */
export function ApprovalModal({
  approval,
  onDecided,
  onDismiss,
}: {
  approval: Approval;
  onDecided: () => void;
  /** Close WITHOUT deciding.
   *
   *  ACC's own claim is that an approval is durable state, not a UI session.
   *  A modal with no exit contradicted it: the operator could not open the
   *  Recovery tab to read the evidence, nor reach the demo controls, without
   *  first approving or rejecting — deciding before inspecting.
   */
  onDismiss: () => void;
}) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  // One decision often creates another: the modal stays mounted with a NEW
  // approval. Without this reset it kept the previous decision's "busy" state
  // — buttons disabled, a frozen "…" — and nothing could be decided again.
  useEffect(() => {
    setBusy(null);
    setComment("");
    setError(null);
  }, [approval.approval_id]);

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "reject");
    setError(null);
    try {
      await api.decideApproval(approval.approval_id, approve, comment || undefined);
      onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision refused");
    } finally {
      // Always release: on success as on failure.
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="panel w-full max-w-lg border-state-risk/40">
        <header className="panel-header border-state-risk/30 bg-state-risk/5">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-state-risk">
            ▲ Action requiring approval
          </h2>
          <span className="font-mono text-[10px] text-ink-dim">
            {approval.approval_id}
            <button
              type="button"
              onClick={onDismiss}
              disabled={busy !== null}
              className="ml-3 rounded border border-line px-2 py-0.5 text-[10px]
                         uppercase tracking-wide text-ink-dim
                         hover:text-ink disabled:opacity-40"
            >
              Decide later
            </button>
          </span>
        </header>

        <div className="space-y-4 p-5">
          <dl className="grid grid-cols-2 gap-3">
            <Row label="Agent" value={approval.agent_id} />
            <Row label="Action" value={approval.action} />
            <Row label="Resource" value={approval.resource ?? "—"} />
            <Row
              label="Amount"
              value={money(approval.amount)}
              emphasis
            />
          </dl>

          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
              Reason
            </p>
            <p className="mt-1 text-sm text-ink-muted">{approval.reason}</p>
          </div>

          {approval.evidence.length > 0 && (
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
                Preuves
              </p>
              <ul className="mt-1 space-y-0.5">
                {approval.evidence.map((item, i) => (
                  <li key={i} className="font-mono text-[11px] text-ink-muted">
                    · {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Comment (recorded in the audit trail)"
            className="w-full rounded border border-edge bg-base px-3 py-2 text-sm
                       outline-none placeholder:text-ink-dim focus:border-ink-muted"
          />

          {error && (
            <p className="font-mono text-[11px] text-state-failed">{error}</p>
          )}

          <div className="flex gap-2">
            <button
              onClick={() => void decide(false)}
              disabled={busy !== null}
              className="btn btn-reject flex-1"
            >
              {busy === "reject" ? "…" : "Reject"}
            </button>
            <button
              onClick={() => void decide(true)}
              disabled={busy !== null}
              className="btn btn-approve flex-1"
            >
              {busy === "approve" ? "…" : "Approve"}
            </button>
          </div>

          <p className="text-center font-mono text-[10px] leading-relaxed text-ink-dim">
            A rejection puts the mission in safe hold: no execution follows.
          </p>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
        {label}
      </dt>
      <dd
        className={`mt-0.5 font-mono text-sm ${
          emphasis ? "text-state-risk" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
