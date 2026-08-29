"use client";

import { useState } from "react";
import { money } from "@/lib/format";
import type { PolicyBoundary } from "@/lib/types";

// Prix unitaire du fournisseur principal. Sert uniquement à anticiper le
// verdict de politique AVANT de lancer — la décision réelle reste au backend.
const UNIT_PRICE_SUP_A = 4.0;
const SUP_A_CAPACITY = 1500;

/**
 * Création paramétrée de mission.
 *
 * Sans paramètres, chaque mission était un clone : même objectif, même
 * fournisseur, même montant. Rien ne les distinguait qu'un identifiant.
 * Le volume à lui seul change la narration, sans aucune panne à injecter :
 *   1 200 u → 4 800 $  → autonome
 *   1 500 u → 6 000 $  → approbation humaine (seuil franchi)
 *   2 000 u → capacité insuffisante → Failure Twin
 */
export function NewMissionForm({
  policy,
  onCreate,
  onCancel,
  busy,
}: {
  policy: PolicyBoundary | null;
  onCreate: (params: {
    objective: string;
    required_units: number;
    deadline_hours: number;
    priority: string;
  }) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [objective, setObjective] = useState("Protect production schedule");
  const [units, setUnits] = useState(1200);
  const [deadline, setDeadline] = useState(48);
  const [priority, setPriority] = useState("HIGH");

  const threshold = policy?.thresholds.purchase_autonomous_max ?? 5000;
  const ceiling = policy?.thresholds.purchase_approval_max ?? 25000;
  const amount = units * UNIT_PRICE_SUP_A;

  const forecast = (() => {
    if (units > SUP_A_CAPACITY) {
      return {
        tone: "text-state-recovering",
        label: "SUP-A capacity insufficient → the Failure Twin will be activated",
      };
    }
    if (amount > ceiling) {
      return { tone: "text-state-blocked", label: "Above the ceiling → action blocked" };
    }
    if (amount > threshold) {
      return {
        tone: "text-state-risk",
        label: `${money(amount)} exceeds the autonomous threshold → human approval`,
      };
    }
    return {
      tone: "text-state-healthy",
      label: `${money(amount)} within autonomous authority → no intervention`,
    };
  })();

  return (
    <section className="panel border-state-executing/30">
      <header className="panel-header">
        <h2 className="panel-title">Nouvelle mission</h2>
        <button onClick={onCancel} className="font-mono text-[10px] text-ink-dim
                                             hover:text-ink">
          annuler
        </button>
      </header>

      <div className="space-y-3 p-4">
        <label className="block">
          <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
            Objectif
          </span>
          <input
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            className="mt-1 w-full rounded border border-edge bg-base px-3 py-2 text-sm
                       outline-none focus:border-ink-muted"
          />
        </label>

        <div className="grid grid-cols-3 gap-3">
          <label className="block">
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
              Volume
            </span>
            <input
              type="number"
              min={1}
              step={100}
              value={units}
              onChange={(e) => setUnits(Math.max(1, Number(e.target.value) || 0))}
              className="mt-1 w-full rounded border border-edge bg-base px-3 py-2
                         font-mono text-sm outline-none focus:border-ink-muted"
            />
          </label>
          <label className="block">
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
              Deadline (h)
            </span>
            <input
              type="number"
              min={1}
              value={deadline}
              onChange={(e) => setDeadline(Math.max(1, Number(e.target.value) || 0))}
              className="mt-1 w-full rounded border border-edge bg-base px-3 py-2
                         font-mono text-sm outline-none focus:border-ink-muted"
            />
          </label>
          <label className="block">
            <span className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
              Priority
            </span>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="mt-1 w-full rounded border border-edge bg-base px-3 py-2
                         font-mono text-sm outline-none focus:border-ink-muted"
            >
              {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
        </div>

        <p className={`font-mono text-[11px] ${forecast.tone}`}>
          ▸ {forecast.label}
        </p>

        <button
          onClick={() => onCreate({
            objective, required_units: units, deadline_hours: deadline, priority,
          })}
          disabled={busy}
          className="btn w-full"
        >
          {busy ? "…" : "Launch mission"}
        </button>
      </div>
    </section>
  );
}
