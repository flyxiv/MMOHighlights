"use client";

import { useEffect, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { USE_MOCKS } from "@/lib/api";
import { mockEvents } from "@/lib/mocks";
import { queryKeys } from "@/lib/queries";
import type { ChannelOut, HealthOut, RecordingOut } from "@/lib/types";

export type LiveConnection = "connecting" | "open" | "reconnecting";

/** Override when the dev proxy buffers SSE; must then be CORS-enabled on the backend. */
const EVENTS_URL = process.env.NEXT_PUBLIC_EVENTS_URL || "/api/events";

function applyEvent(qc: QueryClient, event: string, data: unknown) {
  switch (event) {
    case "channel.updated": {
      const channel = data as ChannelOut;
      qc.setQueryData<ChannelOut[]>(queryKeys.channels, (old) => {
        if (!old) return old;
        const idx = old.findIndex((c) => c.id === channel.id);
        if (idx < 0) return [...old, channel];
        const next = old.slice();
        next[idx] = channel;
        return next;
      });
      break;
    }
    case "channel.removed": {
      const { id } = data as { id: string };
      qc.setQueryData<ChannelOut[]>(queryKeys.channels, (old) => old?.filter((c) => c.id !== id));
      break;
    }
    case "recording.updated": {
      const rec = data as RecordingOut;
      void qc.invalidateQueries({ queryKey: queryKeys.recordingsAll });
      void qc.invalidateQueries({ queryKey: queryKeys.recording(rec.id) });
      break;
    }
    case "health": {
      qc.setQueryData<HealthOut>(queryKeys.health, data as HealthOut);
      break;
    }
  }
}

const EVENT_NAMES = ["channel.updated", "channel.removed", "recording.updated", "health"] as const;

/**
 * Subscribes to GET /api/events and folds the events into the TanStack Query cache.
 * Reconnects with backoff and refetches everything after a reconnect to catch up.
 */
export function useLiveEvents(): LiveConnection {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveConnection>("connecting");

  useEffect(() => {
    if (USE_MOCKS) {
      setState("open");
      return mockEvents.subscribe((event, data) => applyEvent(qc, event, data));
    }

    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let disposed = false;
    let hadConnection = false;

    const connect = () => {
      if (disposed) return;
      source = new EventSource(EVENTS_URL);

      source.onopen = () => {
        attempt = 0;
        setState("open");
        if (hadConnection) void qc.invalidateQueries();
        hadConnection = true;
      };

      for (const name of EVENT_NAMES) {
        source.addEventListener(name, (e) => {
          try {
            applyEvent(qc, name, JSON.parse((e as MessageEvent<string>).data));
          } catch {
            // Ignore malformed payloads.
          }
        });
      }

      source.onerror = () => {
        setState("reconnecting");
        // The browser retries on its own unless the stream was closed (e.g. non-200 response).
        if (source?.readyState === EventSource.CLOSED) {
          source.close();
          const wait = Math.min(30_000, 1000 * 2 ** attempt++);
          retryTimer = setTimeout(connect, wait);
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      source?.close();
    };
  }, [qc]);

  return state;
}
