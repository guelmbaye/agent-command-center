"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamUrl } from "@/lib/api";
import type { MissionDetail, TimelineEvent } from "@/lib/types";

/**
 * Observe une mission en temps reel.
 *
 * SSE en priorite ; repli automatique sur polling si le flux tombe. L'etat
 * affiche vient TOUJOURS du Control Plane : le frontend n'est jamais source
 * de verite (Doc 07 §23).
 */
export function useMissionStream(missionId: string | null, intervalMs = 2000) {
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    if (!missionId) return;
    try {
      const [detail, timeline] = await Promise.all([
        api.getMission(missionId),
        api.timeline(missionId),
      ]);
      setMission(detail);
      setEvents(timeline.events);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Control Plane injoignable");
    }
  }, [missionId]);

  // Flux SSE : chaque evenement declenche une relecture de l'etat autoritatif.
  useEffect(() => {
    if (!missionId) return;

    // Purger l'etat precedent AVANT de charger le nouveau. Sans cela, les
    // donnees de la mission precedente restent affichees pendant le
    // rechargement : l'operateur lit un etat qui n'est plus celui de la
    // mission selectionnee.
    setMission(null);
    setEvents([]);
    void refresh();

    let source: EventSource | null = null;
    try {
      source = new EventSource(streamUrl(missionId));
      sourceRef.current = source;
      source.onopen = () => setLive(true);
      source.onmessage = () => void refresh();
      source.onerror = () => {
        setLive(false);
        source?.close();
      };
    } catch {
      setLive(false);
    }

    return () => {
      source?.close();
      sourceRef.current = null;
    };
  }, [missionId, refresh]);

  // Filet de securite : polling tant que le SSE n'est pas etabli.
  useEffect(() => {
    if (!missionId || live) return;
    const timer = setInterval(() => void refresh(), intervalMs);
    return () => clearInterval(timer);
  }, [missionId, live, intervalMs, refresh]);

  return { mission, events, live, error, refresh };
}
