"use client";

import { useState } from "react";
import { api } from "@/lib/api";

/**
 * Demo controls, deterministic and operator-triggered.
 *
 * Le jury ne dépend jamais d'une panne aléatoire : chaque moment de la démo
 * est déclenché explicitement (Doc 06 §21).
 */
export function DemoControls({
  missionId,
  missionStatus,
  agentMode,
  onChange,
}: {
  missionId: string | null;
  missionStatus?: string | null;
  /** Read from the control plane. A literal here once claimed "deterministic"
   *  on a fleet running `hybrid`, and a two-minute run looked like a
   *  performance problem instead of evidence that a model was answering. */
  agentMode?: string;
  onChange: () => void;
}) {
  // Interrupt and resume need a LIVE mission: with none selected, or once the
  // mission has settled, the backend refuses them. Leaving the buttons active
  // would produce an error mid-demonstration.
  //
  // Reset, failure injection and hostile injection act on the enterprise
  // systems and on stored state, so they stay available with no mission — the
  // documented order arms the failure BEFORE launching.
  const settled = missionStatus
    ? ["COMPLETED", "FAILED", "ABORTED"].includes(missionStatus)
    : false;
  const liveMission = Boolean(missionId) && !settled;
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function run(key: string, action: () => Promise<unknown>, message: string) {
    setBusy(key);
    setNote(null);
    try {
      await action();
      setNote(message);
      onChange();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Command failed");
    } finally {
      setBusy(null);
    }
  }

  const actions = [
    {
      key: "fail",
      label: "Fail SUP-A",
      hint: "Primary supplier returns 503",
      run: () => run("fail", api.demo.failSupplierA, "SUP-A down"),
      enabled: true,
      danger: true,
    },
    {
      key: "poison",
      label: "Hostile injection",
      hint: "SUP-B tries to bypass policy",
      run: () => run("poison", api.demo.injectMalicious, "Hostile content armed"),
      enabled: true,
      danger: true,
    },
    {
      key: "interrupt",
      label: "Kill the runtime",
      hint: "Mission state must survive",
      run: () =>
        run(
          "interrupt",
          () => api.demo.interrupt(missionId!),
          "Runtime interrupted",
        ),
      enabled: liveMission,
      danger: true,
    },
    {
      key: "resume",
      label: "Resume",
      hint: "Restore from the latest checkpoint",
      run: () =>
        run("resume", () => api.resume(missionId!), "Mission resumed"),
      enabled: liveMission,
      danger: false,
    },
    {
      key: "reset",
      label: "Reset",
      hint: "Resets ACC and the enterprise systems",
      run: () =>
        run(
          "reset",
          async () => {
            await api.demo.reset();
          },
          "State reset",
        ),
      enabled: true,
      danger: false,
    },
  ];

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Demo controls</h2>
        <span className="font-mono text-[10px] text-ink-dim">{agentMode ?? "…"}</span>
      </header>
      <div className="space-y-1.5 p-4">
        {actions.map((action) => (
          <button
            key={action.key}
            onClick={() => void action.run()}
            disabled={!action.enabled || busy !== null}
            className={`w-full rounded border px-3 py-2 text-left transition
              disabled:cursor-not-allowed disabled:opacity-35
              ${
                action.danger
                  ? "border-state-risk/30 bg-state-risk/5 hover:border-state-risk/60"
                  : "border-edge bg-base-raised/40 hover:border-ink-muted"
              }`}
          >
            <p className="font-mono text-[11px] uppercase tracking-wider text-ink">
              {busy === action.key ? "…" : action.label}
            </p>
            <p className="mt-0.5 font-mono text-[10px] text-ink-dim">{action.hint}</p>
          </button>
        ))}
        {settled && (
          <p className="pt-1 text-center font-mono text-[10px] text-ink-dim">
            {missionId
            ? "Mission finished: nothing left to interrupt or resume."
            : "Arm a failure, then launch a mission. Interrupt and resume need a running one."}
          </p>
        )}
        {note && (
          <p className="pt-1 text-center font-mono text-[10px] text-ink-muted">
            {note}
          </p>
        )}
      </div>
    </section>
  );
}
