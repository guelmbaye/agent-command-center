"use client";

import { duration } from "@/lib/format";
import type { FleetMetrics, MissionMetrics } from "@/lib/types";

/** Bandeau de preuves. Mission Continuity Rate en premier : c'est la North Star. */
export function MetricsBar({
  fleet,
  mission,
}: {
  fleet: FleetMetrics | null;
  mission: MissionMetrics | null;
}) {
  // Une métrique sans échantillon s'affiche « n/a », jamais 100 %.
  const continuity =
    fleet?.mission_continuity_rate === null || fleet === null
      ? null
      : fleet.mission_continuity_rate;

  const cells: { label: string; value: string; tone?: string; note?: string }[] = [
    {
      label: "Mission continuity",
      value: continuity === null || continuity === undefined
        ? "n/a"
        : `${continuity}%`,
      tone: continuity === null || continuity === undefined
        ? "text-ink-dim"
        : "text-state-healthy",
      note: fleet
        ? `${fleet.missions_disrupted} mission(s) disrupted`
        : undefined,
    },
    {
      label: "Missions",
      value: fleet ? `${fleet.missions_total - fleet.missions_at_risk}/${fleet.missions_total}` : "—",
      note: fleet && fleet.mission_success_rate !== null
        ? `${fleet.mission_success_rate}% success rate`
        : undefined,
    },
    {
      label: "Recovery",
      value: mission
        ? `${mission.recovery_success}/${mission.recovery_attempts}`
        : "—",
    },
    {
      label: "Recovery time",
      value: duration(mission?.recovery_duration_s),
    },
    {
      label: "Approvals",
      value: mission
        ? `${mission.approvals_granted}/${mission.approvals_requested}`
        : "—",
    },
    {
      label: "Policy violations",
      value: mission ? String(mission.policy_violations) : "—",
      tone:
        mission && mission.policy_violations > 0
          ? "text-state-failed"
          : "text-state-healthy",
    },
    {
      // Ce compteur mesure des doublons EVITES par l'idempotence, pas des
      // doublons subis : l'ancien libelle se lisait comme un defaut.
      label: "Duplicates prevented",
      value: mission ? String(mission.duplicate_executions) : "—",
      tone: "text-state-healthy",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-edge bg-edge sm:grid-cols-4 lg:grid-cols-7">
      {cells.map((cell) => (
        <div key={cell.label} className="bg-base-panel px-4 py-3">
          <p className="font-mono text-[10px] uppercase leading-tight tracking-[0.12em] text-ink-dim">
            {cell.label}
          </p>
          <p
            className={`mt-1 font-mono text-lg tabular-nums ${cell.tone ?? "text-ink"}`}
          >
            {cell.value}
          </p>
          {cell.note && (
            <p className="font-mono text-[9px] leading-tight text-ink-dim">
              {cell.note}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
