import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { HealthStatus } from "../api/types";

/**
 * Polls the backend /health endpoint. `error` is set when the backend can't be
 * reached at all (e.g. the API server is down), distinct from a reachable backend
 * reporting that Ollama or the search backend isn't configured.
 */
export function useHealth(pollMs = 30000) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .health()
        .then((h) => {
          if (!alive) return;
          setHealth(h);
          setError(false);
        })
        .catch(() => alive && setError(true))
        .finally(() => alive && setLoading(false));
    tick();
    const id = setInterval(tick, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [pollMs]);

  return { health, error, loading };
}
