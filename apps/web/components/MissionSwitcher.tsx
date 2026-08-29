"use client";

import { clockTime, money, stateStyle } from "@/lib/format";
import type { MissionSummary } from "@/lib/types";

/**
 * Sélecteur de mission.
 *
 * Sans lui, créer une mission donnait l'illusion qu'il ne se passait rien :
 * une mission nominale se termine en quelques millisecondes et la suivante est
 * visuellement identique à la précédente. L'opérateur avait quatre missions en
 * base et aucun moyen de les voir.
 */
export function MissionSwitcher({
  missions,
  current,
  onSelect,
}: {
  missions: MissionSummary[];
  current: string | null;
  onSelect: (missionId: string) => void;
}) {
  if (missions.length === 0) return null;

  return (
    <div className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Missions</h2>
        <span className="font-mono text-[10px] text-ink-dim">{missions.length}</span>
      </header>
      <ul className="max-h-56 overflow-y-auto p-2">
        {missions.map((mission) => {
          const style = stateStyle(mission.status);
          const active = mission.mission_id === current;
          return (
            <li key={mission.mission_id}>
              <button
                onClick={() => onSelect(mission.mission_id)}
                className={`w-full rounded px-2 py-2 text-left transition ${
                  active
                    ? "bg-base-raised ring-1 ring-inset ring-edge"
                    : "hover:bg-base-raised/50"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${style.dot}`} />
                  <span className="truncate text-[12px] text-ink">
                    {mission.objective}
                  </span>
                  <span className={`ml-auto shrink-0 font-mono text-[10px] ${style.text}`}>
                    {mission.progress}%
                  </span>
                </div>
                {/* Ce qui distingue reellement deux missions : volume, montant,
                    fournisseur retenu. L'identifiant seul ne suffit pas. */}
                <div className="mt-0.5 flex items-center gap-2 pl-3.5
                                font-mono text-[10px] text-ink-dim">
                  <span>{mission.mission_id}</span>
                  <span>· {mission.required_units} u.</span>
                  {mission.purchase_amount !== null && (
                    <span>· {money(mission.purchase_amount)}</span>
                  )}
                  {mission.selected_supplier && (
                    <span>· {mission.selected_supplier}</span>
                  )}
                  <time className="ml-auto">{clockTime(mission.created_at)}</time>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
