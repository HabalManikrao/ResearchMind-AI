import { useEffect, useRef, useState } from "react";
import type { ProgressEvent } from "../api/types";
import { api } from "../api/client";

/**
 * Subscribes to the backend SSE stream for a project and accumulates events.
 * Reconnects are handled by the browser's EventSource. Stops on done/error.
 */
export function useEventStream(projectId: string | undefined, active: boolean) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<string>("");
  const [finished, setFinished] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!projectId || !active) return;
    setFinished(false);
    const es = new EventSource(api.streamUrl(projectId));
    esRef.current = es;

    const handle = (type: string) => (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data) as ProgressEvent;
        if (type === "ping" || type === "connected") return;
        setEvents((prev) => [...prev.slice(-200), payload]);
        if (typeof payload.data?.progress === "number") {
          setProgress(payload.data.progress as number);
        }
        if (type === "progress" || type === "stage") setStage(payload.message);
        if (type === "done") {
          setProgress(100);
          setFinished(true);
          es.close();
        }
        if (type === "error") {
          setFinished(true);
          es.close();
        }
      } catch {
        /* ignore malformed */
      }
    };

    for (const t of ["connected", "stage", "activity", "progress", "done", "error", "ping"]) {
      es.addEventListener(t, handle(t) as EventListener);
    }
    es.onerror = () => {
      /* browser auto-reconnects; nothing to do */
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [projectId, active]);

  return { events, progress, stage, finished, setProgress };
}
