"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChannelOut, RecordingLabels, RecordingQuery } from "@/lib/types";

export const queryKeys = {
  channels: ["channels"] as const,
  recordingsAll: ["recordings"] as const,
  recordings: (q: RecordingQuery) => ["recordings", q] as const,
  recordingAll: ["recording"] as const,
  recording: (id: string) => ["recording", id] as const,
  games: ["games"] as const,
  health: ["health"] as const,
};

export function useChannels() {
  return useQuery({ queryKey: queryKeys.channels, queryFn: api.listChannels });
}

export function useRecordings(q: RecordingQuery) {
  return useQuery({
    queryKey: queryKeys.recordings(q),
    queryFn: () => api.listRecordings(q),
    placeholderData: keepPreviousData,
  });
}

export function useRecording(id: string | null) {
  return useQuery({
    queryKey: queryKeys.recording(id ?? ""),
    queryFn: () => api.getRecording(id!),
    enabled: !!id,
  });
}

export function useGames() {
  return useQuery({ queryKey: queryKeys.games, queryFn: api.listGames, staleTime: 5 * 60_000 });
}

export function useHealth() {
  // SSE pushes health every ~10 s; polling is only a fallback when the stream is down.
  return useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 30_000 });
}

export function useAddChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => api.addChannel(url),
    onSuccess: (channel) => {
      qc.setQueryData<ChannelOut[]>(queryKeys.channels, (old) =>
        old ? [...old.filter((c) => c.id !== channel.id), channel] : [channel],
      );
      void qc.invalidateQueries({ queryKey: queryKeys.health });
    },
  });
}

export function useRemoveChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, stopRecording }: { id: string; stopRecording: boolean }) =>
      api.removeChannel(id, stopRecording),
    onSuccess: (_data, { id }) => {
      qc.setQueryData<ChannelOut[]>(queryKeys.channels, (old) => old?.filter((c) => c.id !== id));
      void qc.invalidateQueries({ queryKey: queryKeys.recordingsAll });
      void qc.invalidateQueries({ queryKey: queryKeys.health });
    },
  });
}

export function useStopRecording() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.stopRecording(id),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: queryKeys.recordingsAll });
      void qc.invalidateQueries({ queryKey: queryKeys.recording(id) });
      void qc.invalidateQueries({ queryKey: queryKeys.channels });
    },
  });
}

export function useUpdateLabels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, labels }: { id: string; labels: RecordingLabels }) =>
      api.updateLabels(id, labels),
    // Returning the promise keeps the mutation pending until the lists are refetched.
    onSuccess: (_rec, { id }) =>
      Promise.all([
        qc.invalidateQueries({ queryKey: queryKeys.recordingsAll }),
        qc.invalidateQueries({ queryKey: queryKeys.recording(id) }),
        // Channel rows show the labels of their active / last recording.
        qc.invalidateQueries({ queryKey: queryKeys.channels }),
      ]),
  });
}

export function useCreateTier() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ gameId, name }: { gameId: number; name: string }) => api.createTier(gameId, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.games }),
  });
}

/** Shared by every component that lists in-progress recordings (one cache entry). */
export const ACTIVE_RECORDINGS_QUERY: RecordingQuery = { status: "active", page: 1, page_size: 50 };
