"use client";

import { Empty, Panel } from "./Panel";
import type { RecoveryAttempt } from "@/lib/types";

/**
 * Le panneau qui vend le produit.
 *
 * On n'affiche pas seulement l'option retenue : on montre les options ÉCARTÉES
 * et pourquoi. C'est la démonstration visuelle de « meilleure option
 * opérationnelle ≠ meilleure option permise » (Doc 03 §21).
 */
export function RecoveryPanel({ recoveries }: { recoveries: RecoveryAttempt[] }) {
  if (!recoveries.length) {
    return (
      <Panel title="Recovery intelligence">
        <Empty>Failure Twin on standby — no failure detected</Empty>
      </Panel>
    );
  }

  return (
    <Panel title="Failure Twin — recovery decision">
      <div className="space-y-5">
        {recoveries.map((recovery) => {
          const permitted = recovery.options.filter((o) => o.permitted).length;
          return (
            <article key={recovery.recovery_id} className="space-y-3">
              <header className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm text-ink">{recovery.diagnosis}</p>
                <span className="chip text-ink-muted">
                  {recovery.failure_class} · impact {recovery.impact}
                </span>
              </header>

              <ul className="space-y-1.5">
                {recovery.options.map((option, index) => (
                  <li
                    key={`${recovery.recovery_id}-${index}`}
                    className={`rounded border px-3 py-2 ${
                      option.strategy === recovery.selected_option && option.permitted
                        ? "border-state-healthy/40 bg-state-healthy/5"
                        : option.permitted
                          ? "border-edge bg-base-raised/30"
                          : "border-state-failed/25 bg-state-failed/5"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p
                          className={`text-[13px] ${
                            option.permitted ? "text-ink" : "text-ink-muted line-through"
                          }`}
                        >
                          {option.label}
                        </p>
                        {option.denial_reason && (
                          <p className="mt-0.5 font-mono text-[10px] text-state-failed">
                            {option.denial_reason}
                          </p>
                        )}
                        {!option.denial_reason && option.rationale && (
                          <p className="mt-0.5 font-mono text-[10px] text-ink-dim">
                            {option.rationale}
                          </p>
                        )}
                      </div>
                      <span
                        className={`shrink-0 font-mono text-[10px] uppercase tracking-wider ${
                          option.permitted ? "text-state-healthy" : "text-state-failed"
                        }`}
                      >
                        {option.permitted ? "permitted" : "not permitted"}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>

              <footer className="rounded border border-edge bg-base-raised/50 px-3 py-2">
                <p className="font-mono text-[10px] uppercase tracking-wider text-ink-dim">
                  {permitted}/{recovery.options.length} options permitted · selected:{" "}
                  <span className="text-state-healthy">{recovery.selected_option}</span>
                </p>
                <p className="mt-1 text-[13px] leading-snug text-ink-muted">
                  {recovery.reason}
                </p>
                {recovery.policy_decision_id && (
                  <p className="mt-1.5 font-mono text-[10px] text-ink-dim">
                    This plan itself passed through the Policy Engine ·{" "}
                    {recovery.policy_decision_id}
                  </p>
                )}
              </footer>
            </article>
          );
        })}
      </div>
    </Panel>
  );
}
