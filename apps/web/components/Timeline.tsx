"use client";

import { useEffect, useRef } from "react";
import { Empty, Panel } from "./Panel";
import { EVENT_GLYPH, clockTime } from "@/lib/format";
import type { TimelineEvent } from "@/lib/types";

const TONE: Record<string, string> = {
  alert: "text-state-risk",
  failure: "text-state-failed",
  security: "text-state-blocked",
  recovery: "text-state-recovering",
  approval: "text-state-risk",
  policy: "text-state-executing",
  success: "text-state-healthy",
  checkpoint: "text-ink-muted",
  resume: "text-state-recovering",
  agent: "text-ink-muted",
  mission: "text-ink",
  event: "text-ink-dim",
};

/** Fil d'events — l'élément d'interface le plus important de la démo. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  return (
    <Panel
      title="Mission timeline"
      action={
        <span className="font-mono text-[10px] text-ink-dim">
          {events.length} events
        </span>
      }
    >
      {events.length === 0 ? (
        <Empty>No events</Empty>
      ) : (
        <ol className="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
          {events.map((event) => {
            const tone = TONE[event.kind] ?? "text-ink-dim";
            return (
              <li key={event.event_id} className="flex items-start gap-3 py-1">
                <time className="mt-0.5 shrink-0 font-mono text-[10px] tabular-nums text-ink-dim">
                  {clockTime(event.timestamp)}
                </time>
                <span className={`mt-0.5 shrink-0 font-mono text-xs ${tone}`}>
                  {EVENT_GLYPH[event.kind] ?? "·"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`text-[13px] leading-snug ${tone}`}>{event.message}</p>
                  <p className="font-mono text-[10px] text-ink-dim">
                    {event.type} · {event.source}
                  </p>
                </div>
              </li>
            );
          })}
          <div ref={endRef} />
        </ol>
      )}
    </Panel>
  );
}
