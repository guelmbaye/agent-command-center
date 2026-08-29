"use client";

import { Empty, Panel } from "./Panel";
import { clockTime, duration, money } from "@/lib/format";
import type { TraceNode } from "@/lib/types";

const NODE_STYLE: Record<TraceNode["type"], { glyph: string; tone: string; label: string }> = {
  agent:    { glyph: "▸", tone: "text-ink",                label: "Agent" },
  recovery: { glyph: "↻", tone: "text-state-recovering",   label: "Recovery" },
  policy:   { glyph: "⬢", tone: "text-state-executing",    label: "Policy" },
  approval: { glyph: "◈", tone: "text-state-risk",         label: "Approval" },
  security: { glyph: "⛨", tone: "text-state-blocked",      label: "Security" },
};

const DECISION_TONE: Record<string, string> = {
  // Un abandon délibéré n'est pas une panne : le distinguer d'un FAILED évite
  // de faire passer une décision correcte pour un dysfonctionnement.
  ABORTED: "text-state-risk",
  ALLOW: "text-state-healthy",
  DENY: "text-state-failed",
  APPROVAL_REQUIRED: "text-state-risk",
  APPROVED: "text-state-healthy",
  REJECTED: "text-state-failed",
  BLOCKED: "text-state-blocked",
  REPLAYED: "text-state-recovering",
};

/** Arbre d'exécution : la preuve technique montrée au jury. */
export function TracePanel({ nodes }: { nodes: TraceNode[] }) {
  if (!nodes.length) {
    return <Panel title="Execution trace"><Empty>Aucune trace</Empty></Panel>;
  }

  return (
    <Panel
      title="Execution trace"
      action={
        <span className="font-mono text-[10px] text-ink-dim">{nodes.length} nodes</span>
      }
    >
      <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
        {nodes.map((node, index) => {
          const style = NODE_STYLE[node.type];
          const verdict = node.decision ?? node.status ?? "";
          return (
            <li
              key={`${node.type}-${index}`}
              className="rounded bg-base-raised/30 px-3 py-2"
            >
              <div className="flex items-start gap-2.5">
                <span className={`mt-0.5 font-mono text-xs ${style.tone}`}>
                  {style.glyph}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="font-mono text-[12px] text-ink">{node.name}</p>
                    <span
                      className={`font-mono text-[10px] uppercase tracking-wider ${
                        DECISION_TONE[verdict] ?? "text-ink-dim"
                      }`}
                    >
                      {verdict}
                    </span>
                  </div>

                  {node.finding && (
                    <p className="mt-0.5 text-[12px] text-ink-muted">{node.finding}</p>
                  )}
                  {node.diagnosis && (
                    <p className="mt-0.5 text-[12px] text-ink-muted">{node.diagnosis}</p>
                  )}
                  {node.reason && (
                    <p className="mt-0.5 text-[12px] text-ink-muted">{node.reason}</p>
                  )}
                  {node.detail && (
                    <p className="mt-0.5 text-[12px] text-ink-muted">{node.detail}</p>
                  )}

                  <p className="mt-1 font-mono text-[10px] text-ink-dim">
                    {clockTime(node.timestamp)} · {style.label}
                    {node.rule_id ? ` · ${node.rule_id}` : ""}
                    {node.amount ? ` · ${money(node.amount)}` : ""}
                    {node.duration_ms !== null && node.duration_ms !== undefined
                      ? ` · ${node.duration_ms} ms`
                      : ""}
                    {node.latency_s !== null && node.latency_s !== undefined
                      ? ` · waited ${duration(node.latency_s)}`
                      : ""}
                    {node.decided_by ? ` · ${node.decided_by}` : ""}
                  </p>

                  {node.evidence && node.evidence.length > 0 && (
                    <ul className="mt-1 flex flex-wrap gap-1">
                      {node.evidence.slice(0, 6).map((item, i) => (
                        <li key={i} className="chip text-ink-dim">{item}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 border-t border-edge pt-3 font-mono text-[10px] leading-relaxed text-ink-dim">
        Structured evidence, never the model's raw reasoning. Every node is
        correlated to the mission by trace_id.
      </p>
    </Panel>
  );
}
