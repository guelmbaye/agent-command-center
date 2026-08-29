"use client";

import { Empty, Panel } from "./Panel";
import { StateDot } from "./StateDot";
import type { Agent, MissionDetail } from "@/lib/types";

/**
 * Santé de flotte. Le Failure Twin apparaît en veille tant qu'aucun échec
 * n'est survenu : son activation est un signal visuel fort pendant la démo.
 */
export function FleetPanel({
  agents,
  mission,
}: {
  agents: Agent[];
  mission: MissionDetail | null;
}) {
  if (!agents.length) return <Panel title="Agent fleet"><Empty>Registre vide</Empty></Panel>;

  const recovering = mission
    ? ["AT_RISK", "RECOVERING"].includes(mission.status)
    : false;

  // Une mission terminale n'a plus d'agent au travail, même si `active_agent_id`
  // conserve le dernier agent sollicité. Afficher « EN COURS » sur une mission
  // ÉCHOUÉE ferait croire à une exécution qui n'a plus lieu.
  const settled = mission
    ? ["COMPLETED", "FAILED", "ABORTED"].includes(mission.status)
    : true;

  const displayState = (agent: Agent) => {
    if (agent.agent_id === "failure-twin") {
      if (settled) return agent.status === "AVAILABLE" ? "STANDBY" : agent.status;
      return recovering ? "BUSY" : agent.status === "AVAILABLE" ? "STANDBY" : agent.status;
    }
    if (!settled && mission?.active_agent_id === agent.agent_id) return "BUSY";
    return agent.status;
  };

  return (
    <Panel title="Agent fleet">
      <ul className="space-y-px">
        {agents.map((agent) => {
          const state = displayState(agent);
          return (
            <li
              key={agent.agent_id}
              className="flex items-center justify-between rounded bg-base-raised/40 px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate text-sm">{agent.name}</p>
                <p className="mt-0.5 font-mono text-[10px] text-ink-dim">
                  v{agent.version} · {agent.capabilities.length} capabilities ·{" "}
                  {agent.authority_level.toLowerCase()}
                </p>
              </div>
              <StateDot state={state} pulse={state === "BUSY"} />
            </li>
          );
        })}
      </ul>
      <p className="mt-3 border-t border-edge pt-3 font-mono text-[10px] leading-relaxed text-ink-dim">
        Each agent holds only the capabilities declared in the registry. A capability
        is necessary but never sufficient: the Gateway decides.
      </p>
    </Panel>
  );
}
