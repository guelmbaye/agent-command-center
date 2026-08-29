"use client";

import { useCallback, useEffect, useState } from "react";

/** Interrogation periodique simple pour les vues sans flux dedie. */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs = 3000,
  enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await fetcher());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }, [fetcher]);

  useEffect(() => {
    if (!enabled) return;
    void load();
    const timer = setInterval(() => void load(), intervalMs);
    return () => clearInterval(timer);
  }, [enabled, intervalMs, load]);

  return { data, error, reload: load };
}
