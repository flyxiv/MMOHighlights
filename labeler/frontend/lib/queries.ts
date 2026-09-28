"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { rowLabels } from "@/lib/convert";
import type { Dataset, EditorDoc, Job, LabelingPatch, SampleRow } from "@/lib/types";

export const queryKeys = {
  health: ["health"] as const,
  datasets: ["datasets"] as const,
  dataset: (name: string) => ["dataset", name] as const,
  samples: (name: string) => ["samples", name] as const,
  sample: (name: string, id: string) => ["sample", name, id] as const,
  imports: (name: string) => ["imports", name] as const,
};

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 5_000 });
}

export function useDatasets() {
  return useQuery({ queryKey: queryKeys.datasets, queryFn: api.listDatasets });
}

export function useDataset(name: string) {
  return useQuery({ queryKey: queryKeys.dataset(name), queryFn: () => api.getDataset(name) });
}

export function useSamples(name: string) {
  return useQuery({
    queryKey: queryKeys.samples(name),
    queryFn: () => api.listSamples(name),
    staleTime: Infinity, // kept current locally after each save
  });
}

export function sampleQuery(name: string, id: string) {
  return { queryKey: queryKeys.sample(name, id), queryFn: () => api.getSample(name, id), staleTime: Infinity };
}

export function useImports(name: string) {
  return useQuery({
    queryKey: queryKeys.imports(name),
    queryFn: () => api.listImports(name),
    refetchInterval: (q) => ((q.state.data as Job[] | undefined)?.some((j) => j.state === "running") ? 1000 : false),
  });
}

/** Reflect a saved sample in the image list without refetching it. */
export function patchRow(qc: QueryClient, name: string, id: string, doc: EditorDoc) {
  const accepted = doc.objects.filter((o) => o.accepted).length;
  qc.setQueryData<SampleRow[]>(queryKeys.samples(name), (rows) =>
    rows?.map((r) =>
      r.id === id
        ? { ...r, status: doc.status, objects: accepted, suggested: doc.objects.length - accepted, labels: rowLabels(doc) }
        : r,
    ),
  );
}

export function useUpdateLabeling(name: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: LabelingPatch) => api.updateLabeling(name, patch),
    onSuccess: (dataset) => qc.setQueryData<Dataset>(queryKeys.dataset(name), dataset),
  });
}

const UPLOAD_BATCH_BYTES = 24 * 1024 * 1024;

/** Upload in batches that stay under the proxy's body limit. */
export async function uploadInBatches(
  name: string,
  files: File[],
  onProgress: (done: number, total: number) => void,
) {
  let added = 0;
  let skipped = 0;
  const errors: string[] = [];
  // frames.json sidecars go with every batch so the server can match them to their frames.
  const sidecars = files.filter((f) => f.name === "frames.json");
  const images = files.filter((f) => f.name !== "frames.json");
  let batch: File[] = [];
  let size = 0;
  let done = 0;
  const flush = async () => {
    if (!batch.length) return;
    const r = await api.upload(name, [...sidecars, ...batch]);
    added += r.added;
    skipped += r.skipped;
    errors.push(...r.errors);
    done += batch.length;
    onProgress(done, images.length);
    batch = [];
    size = 0;
  };
  for (const f of images) {
    if (batch.length && (size + f.size > UPLOAD_BATCH_BYTES || batch.length >= 50)) await flush();
    batch.push(f);
    size += f.size;
  }
  await flush();
  return { added, skipped, errors };
}
