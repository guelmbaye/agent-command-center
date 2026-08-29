import type { MissionHealth, MissionStatus } from "./types";

export const STATE_STYLE: Record<string, { dot: string; text: string; label: string }> = {
  HEALTHY:          { dot: "bg-state-healthy",    text: "text-state-healthy",    label: "HEALTHY" },
  CREATED:          { dot: "bg-ink-dim",          text: "text-ink-muted",        label: "CREATED" },
  PLANNING:         { dot: "bg-ink-dim",          text: "text-ink-muted",        label: "PLANNING" },
  EXECUTING:        { dot: "bg-state-executing",  text: "text-state-executing",  label: "EXECUTING" },
  AT_RISK:          { dot: "bg-state-risk",       text: "text-state-risk",       label: "AT RISK" },
  RECOVERING:       { dot: "bg-state-recovering", text: "text-state-recovering", label: "RECOVERING" },
  WAITING_APPROVAL: { dot: "bg-state-risk",       text: "text-state-risk",       label: "AWAITING APPROVAL" },
  COMPLETED:        { dot: "bg-state-completed",  text: "text-state-completed",  label: "COMPLETED" },
  FAILED:           { dot: "bg-state-failed",     text: "text-state-failed",     label: "FAILED" },
  ABORTED:          { dot: "bg-state-risk",       text: "text-state-risk",       label: "ABORTED" },
  DEGRADED:         { dot: "bg-state-risk",       text: "text-state-risk",       label: "DEGRADED" },
  AVAILABLE:        { dot: "bg-state-healthy",    text: "text-state-healthy",    label: "AVAILABLE" },
  BUSY:             { dot: "bg-state-executing",  text: "text-state-executing",  label: "BUSY" },
  SUSPENDED:        { dot: "bg-state-blocked",    text: "text-state-blocked",    label: "SUSPENDED" },
  REVOKED:          { dot: "bg-state-blocked",    text: "text-state-blocked",    label: "REVOKED" },
  STANDBY:          { dot: "bg-ink-dim",          text: "text-ink-muted",        label: "STANDBY" },
};

export function stateStyle(key: string) {
  return STATE_STYLE[key] ?? { dot: "bg-ink-dim", text: "text-ink-muted", label: key };
}

export const isLiveState = (s: MissionStatus | string) =>
  ["EXECUTING", "AT_RISK", "RECOVERING", "WAITING_APPROVAL"].includes(s);

export const healthTone = (h: MissionHealth) => stateStyle(h).text;

export function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("fr-FR", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format(value);
}

export function clockTime(iso: string) {
  return new Date(iso).toLocaleTimeString("fr-FR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function duration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds - m * 60)} s`;
}

/** Icônes textuelles : lisibles en projection, aucun asset à charger. */
export const EVENT_GLYPH: Record<string, string> = {
  mission: "◆", agent: "▸", alert: "▲", policy: "⬢", approval: "◈",
  checkpoint: "◉", recovery: "↻", security: "⛨", success: "✓",
  failure: "✕", resume: "⟳", event: "·",
};
