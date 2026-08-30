"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMissionStream } from "@/hooks/useMissionStream";
import { ApprovalModal } from "@/components/ApprovalModal";
import { DemoControls } from "@/components/DemoControls";
import { FleetPanel } from "@/components/FleetPanel";
import { MetricsBar } from "@/components/MetricsBar";
import { MissionHeader } from "@/components/MissionHeader";
import { MissionSwitcher } from "@/components/MissionSwitcher";
import { NewMissionForm } from "@/components/NewMissionForm";
import { PolicyPanel } from "@/components/PolicyPanel";
import { RecoveryPanel } from "@/components/RecoveryPanel";
import { Timeline } from "@/components/Timeline";
import { TracePanel } from "@/components/TracePanel";
import type {
  Agent, Approval, FleetMetrics, MissionSummary, PolicyBoundary, RecoveryAttempt,
  TraceNode,
} from "@/lib/types";

type Tab = "timeline" | "recovery" | "trace";

export default function MissionControl() {
  const [missionId, setMissionId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [recoveries, setRecoveries] = useState<RecoveryAttempt[]>([]);
  const [trace, setTrace] = useState<TraceNode[]>([]);
  const [fleet, setFleet] = useState<FleetMetrics | null>(null);
  const [policy, setPolicy] = useState<PolicyBoundary | null>(null);
  const [launching, setLaunching] = useState(false);
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [justCreated, setJustCreated] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deferredApprovalId, setDeferredApprovalId] = useState<string | null>(null);

  const { mission, events, live, error, refresh } = useMissionStream(missionId);

  // Contexte global : registre et politique ne changent pas en cours de mission.
  useEffect(() => {
    void (async () => {
      try {
        const [fleetAgents, boundary] = await Promise.all([api.agents(), api.policy()]);
        setAgents(fleetAgents.agents);
        setPolicy(boundary);
      } catch {
        /* le bandeau d'erreur ci-dessous informe l'opérateur */
      }
    })();
  }, []);

  const loadMissions = useCallback(async () => {
    try {
      const { missions: list } = await api.listMissions();
      setMissions(list);
      return list;
    } catch {
      return [] as MissionSummary[];
    }
  }, []);

  // Reprise de la mission active au chargement : la démo survit à un F5.
  useEffect(() => {
    void (async () => {
      const list = await loadMissions();
      if (missionId) return;
      const active = list.find((m) => m.status !== "COMPLETED") ?? list[0];
      if (active) setMissionId(active.mission_id);
    })();
  }, [missionId, loadMissions]);

  const loadSideData = useCallback(async () => {
    try {
      const [pending, metrics] = await Promise.all([
        api.approvals("PENDING"),
        api.metrics(),
      ]);
      setApprovals(pending.approvals);
      setFleet(metrics);
      if (missionId) {
        const [rec, tr] = await Promise.all([
          api.recoveries(missionId),
          api.trace(missionId),
        ]);
        setRecoveries(rec.recoveries);
        setTrace(tr.trace);
      }
    } catch {
      /* silencieux : la vue principale porte déjà l'état d'erreur */
    }
  }, [missionId]);

  useEffect(() => {
    void loadSideData();
    // La liste des missions doit suivre : sinon elle affiche une progression
    // figée à l'instant du chargement (25 % pour une mission terminée à 100 %).
    void loadMissions();
  }, [loadSideData, loadMissions, mission?.version, mission?.status,
      mission?.progress]);

  async function launch(params: {
    objective: string;
    required_units: number;
    deadline_hours: number;
    priority: string;
  }) {
    setLaunching(true);
    try {
      const created = await api.createMission(params);
      setMissionId(created.mission_id);
      setShowForm(false);
      await loadMissions();
      // Une mission nominale se termine en quelques millisecondes. Sans accuse
      // de reception explicite, le clic semble n'avoir aucun effet.
      setJustCreated(created.mission_id);
      setTimeout(() => setJustCreated(null), 5000);
    } finally {
      setLaunching(false);
    }
  }

  const refreshAll = useCallback(() => {
    void refresh();
    void loadSideData();
    void loadMissions();
  }, [refresh, loadSideData, loadMissions]);

  const pendingApproval =
    approvals.find(
      (a) => a.mission_id === missionId && a.action === "purchase.execute",
    ) ?? approvals.find((a) => a.mission_id === missionId) ?? null;

  // An approval the operator chose to inspect before deciding. It stays
  // pending in the control plane — only this window is closed — and a banner
  // keeps it one click away, so a deferred decision can never be lost.
  const deferred = deferredApprovalId === pendingApproval?.approval_id;
  const blockingApproval = deferred ? null : pendingApproval;

  return (
    <main className="mx-auto max-w-[1600px] space-y-4 p-4 lg:p-6">
      <TopBar
        live={live}
        onLaunch={() => setShowForm((open) => !open)}
        launching={launching}
        missionId={missionId}
        formOpen={showForm}
      />

      {showForm && (
        <NewMissionForm
          policy={policy}
          onCreate={launch}
          onCancel={() => setShowForm(false)}
          busy={launching}
        />
      )}

      {justCreated && (
        <p className="rounded border border-state-healthy/40 bg-state-healthy/5 px-4 py-2
                      font-mono text-xs text-state-healthy">
          Mission {justCreated} created and selected.
        </p>
      )}

      {error && (
        <p className="rounded border border-state-failed/40 bg-state-failed/5 px-4 py-2 font-mono text-xs text-state-failed">
          {error} — check that the Control Plane is listening on {" "}
          {process.env.NEXT_PUBLIC_ACC_API ?? "http://localhost:8080"}
        </p>
      )}

      <MetricsBar fleet={fleet} mission={mission?.metrics ?? null} />

      {mission ? (
        <>
          <MissionHeader mission={mission} live={live} />

          <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
            <div className="space-y-4">
              <nav className="flex gap-1">
                {(
                  [
                    ["timeline", "Timeline"],
                    ["recovery", `Recovery${recoveries.length ? ` (${recoveries.length})` : ""}`],
                    ["trace", "Trace"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setTab(key)}
                    className={`btn ${
                      tab === key ? "border-ink-muted text-ink" : "text-ink-dim"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </nav>

              {tab === "timeline" && <Timeline events={events} />}
              {tab === "recovery" && <RecoveryPanel recoveries={recoveries} />}
              {tab === "trace" && <TracePanel nodes={trace} />}
            </div>

            <aside className="space-y-4">
              <MissionSwitcher
                missions={missions}
                current={missionId}
                onSelect={setMissionId}
              />
              <FleetPanel agents={agents} mission={mission} />
              <DemoControls
                missionId={missionId}
                missionStatus={mission?.status}
                agentMode={policy?.agent_mode}
                onChange={refreshAll}
              />
              <PolicyPanel policy={policy} />
            </aside>
          </div>
        </>
      ) : (
        // The side column stays mounted with no mission. Hiding it made the
        // documented demo order impossible: Reset clears every mission, and
        // "Fail SUP-A" must be armed BEFORE launching — a nominal mission
        // finishes in 0.3 s, so a failure injected afterwards has no effect.
        // The operator was left with a Reset button that removed the Reset
        // button.
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <EmptyState onLaunch={() => setShowForm(true)} launching={launching} />
          <aside className="space-y-4">
            <FleetPanel agents={agents} mission={null} />
            <DemoControls
              missionId={null}
              missionStatus={undefined}
              agentMode={policy?.agent_mode}
              onChange={refreshAll}
            />
            <PolicyPanel policy={policy} />
          </aside>
        </div>
      )}

      {blockingApproval && (
        <ApprovalModal
          approval={blockingApproval}
          onDecided={() => {
            setDeferredApprovalId(null);
            refreshAll();
          }}
          onDismiss={() => setDeferredApprovalId(blockingApproval.approval_id)}
        />
      )}

      {deferred && pendingApproval && (
        <button
          type="button"
          onClick={() => setDeferredApprovalId(null)}
          className="fixed bottom-4 right-4 z-40 rounded border border-warn
                     bg-surface px-4 py-2 text-xs text-warn shadow-lg
                     hover:text-ink"
        >
          ▲ {pendingApproval.approval_id} awaiting your decision — review
        </button>
      )}
    </main>
  );
}

function TopBar({
  live,
  onLaunch,
  launching,
  missionId,
  formOpen,
}: {
  live: boolean;
  onLaunch: () => void;
  launching: boolean;
  missionId: string | null;
  formOpen: boolean;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="font-mono text-sm uppercase tracking-[0.2em] text-ink">
          ACC · Autonomous Mission Control
        </h1>
        <p className="mt-0.5 font-mono text-[10px] tracking-wider text-ink-dim">
          The agent can fail. The mission doesn&apos;t have to.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="chip text-ink-dim">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              live ? "animate-pulseSoft bg-state-healthy" : "bg-ink-dim"
            }`}
          />
          {live ? "connected" : "offline"}
        </span>
        <button
          onClick={onLaunch}
          disabled={launching}
          className={`btn ${formOpen ? "border-ink-muted text-ink" : ""}`}
        >
          {launching ? "…" : missionId ? "New mission" : "Launch a mission"}
        </button>
      </div>
    </header>
  );
}

function EmptyState({
  onLaunch,
  launching,
}: {
  onLaunch: () => void;
  launching: boolean;
}) {
  return (
    <section className="panel flex flex-col items-center justify-center gap-4 py-20">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink-dim">
        No active mission
      </p>
      <p className="max-w-md text-center text-sm text-ink-muted">
        Launch a production-continuity mission, then inject a supplier failure to
        watch ACC diagnose, pick a permitted recovery and request human authority
        when required.
      </p>
      <button onClick={onLaunch} disabled={launching} className="btn">
        {launching ? "…" : "Launch mission"}
      </button>
    </section>
  );
}
