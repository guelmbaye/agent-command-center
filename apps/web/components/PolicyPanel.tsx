"use client";

import { Panel } from "./Panel";
import { money } from "@/lib/format";
import type { PolicyBoundary } from "@/lib/types";

/**
 * La frontière d'autonomie est une feature produit, pas une règle cachée.
 * Un acheteur doit pouvoir répondre à « que fait cet agent sans moi ? ».
 */
export function PolicyPanel({ policy }: { policy: PolicyBoundary | null }) {
  if (!policy) return null;

  const bands = [
    {
      label: "Autonomous",
      tone: "text-state-healthy",
      items: [`Purchase ≤ ${money(policy.thresholds.purchase_autonomous_max)}`, "Supplier, risk and production reads"],
    },
    {
      label: "Human approval",
      tone: "text-state-risk",
      items: [
        // Formaté ici, avec la même locale que le reste de l'interface :
        // le backend expose des seuils bruts, pas des chaînes localisées.
        `Purchase from ${money(policy.thresholds.purchase_autonomous_max)} to ${money(
          policy.thresholds.purchase_approval_max,
        )}`,
        ...policy.approval_required.filter((item) => !item.startsWith("purchase.execute")),
      ],
    },
    {
      label: "Blocked",
      tone: "text-state-blocked",
      items: [
        `Purchase > ${money(policy.thresholds.purchase_approval_max)}`,
        ...policy.blocked.slice(0, 3),
      ],
    },
  ];

  return (
    <Panel title="Autonomy boundary">
      <div className="space-y-3">
        {bands.map((band) => (
          <div key={band.label}>
            <p className={`font-mono text-[10px] uppercase tracking-[0.15em] ${band.tone}`}>
              {band.label}
            </p>
            <ul className="mt-1 space-y-0.5">
              {band.items.map((item, i) => (
                <li key={i} className="font-mono text-[11px] text-ink-muted">
                  · {item}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-3 border-t border-edge pt-3 font-mono text-[10px] text-ink-dim">
        Default decision: {policy.default}. Any action not explicitly authorised
        is denied.
      </p>
    </Panel>
  );
}
