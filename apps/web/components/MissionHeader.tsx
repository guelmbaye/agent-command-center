"use client";

import { StateDot } from "./StateDot";
import { money, stateStyle } from "@/lib/format";
import type { MissionDetail } from "@/lib/types";

/** Bandeau de mission : objectif, état, progression, contexte métier. */
export function MissionHeader({
  mission,
  live,
}: {
  mission: MissionDetail;
  live: boolean;
}) {
  const style = stateStyle(mission.status);
  const ctx = mission.context;
  const atRisk = ["AT_RISK", "RECOVERING", "WAITING_APPROVAL"].includes(mission.status);

  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <span className="font-mono text-[11px] text-ink-dim">
              {mission.mission_id}
            </span>
            <span className="chip text-ink-muted">
              <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-state-healthy" : "bg-ink-dim"}`} />
              {live ? "live stream" : "polling"}
            </span>
          </div>
          <h1 className="mt-1.5 truncate text-xl font-semibold tracking-tight">
            {mission.objective}
          </h1>
          <p className="mt-1 font-mono text-[11px] text-ink-dim">
            stage: {mission.current_stage}
            {mission.active_agent_id ? ` · agent: ${mission.active_agent_id}` : ""}
            {mission.checkpoint_id ? ` · ${mission.checkpoint_id}` : ""}
          </p>
        </div>

        <div className="text-right">
          <StateDot state={mission.status} pulse={atRisk} />
          <p className="mt-1 font-mono text-3xl font-semibold tabular-nums">
            {mission.progress}
            <span className="text-lg text-ink-dim">%</span>
          </p>
        </div>
      </div>

      <div className="h-1 w-full bg-base-raised">
        <div
          className={`h-full transition-all duration-700 ${style.dot}`}
          style={{ width: `${mission.progress}%` }}
        />
      </div>

      <dl className="grid grid-cols-2 gap-px bg-edge sm:grid-cols-4">
        <Field label="Supplier" value={ctx.selected_supplier ?? ctx.primary_supplier} />
        <Field label="Volume" value={`${ctx.required_units} u.`} />
        <Field label="Deadline" value={`${ctx.deadline_hours} h`} />
        <Field
          label="Amount"
          value={money(ctx.purchase_amount)}
          highlight={Boolean(ctx.purchase_amount && ctx.purchase_amount > 5000)}
        />
      </dl>
    </section>
  );
}

function Field({
  label,
  value,
  highlight = false,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="bg-base-panel px-4 py-3">
      <dt className="font-mono text-[10px] uppercase tracking-[0.15em] text-ink-dim">
        {label}
      </dt>
      <dd
        className={`mt-0.5 font-mono text-sm ${
          highlight ? "text-state-risk" : "text-ink"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
