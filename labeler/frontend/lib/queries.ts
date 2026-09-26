"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AnnotationDoc, ImageRow, Job, Project, ProjectPatch } from "@/lib/types";

export const queryKeys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (slug: string) => ["project", slug] as const,
  images: (slug: string) => ["images", slug] as const,
  annotation: (slug: string, file: string) => ["annotation", slug, file] as const,
  imports: (slug: string) => ["imports", slug] as const,
};

export function useHealth() {
  return useQuery({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 5_000 });
}

export function useProjects() {
  return useQuery({ queryKey: queryKeys.projects, queryFn: api.listProjects });
}

export function useProject(slug: string) {
  return useQuery({ queryKey: queryKeys.project(slug), queryFn: () => api.getProject(slug) });
}

export function useImages(slug: string) {
  return useQuery({
    queryKey: queryKeys.images(slug),
    queryFn: () => api.listImages(slug),
    staleTime: Infinity, // kept current locally after each save
  });
}

export function annotationQuery(slug: string, file: string) {
  return {
    queryKey: queryKeys.annotation(slug, file),
    queryFn: () => api.getAnnotation(slug, file),
    staleTime: Infinity,
  };
}

export function useImports(slug: string) {
  return useQuery({
    queryKey: queryKeys.imports(slug),
    queryFn: () => api.listImports(slug),
    refetchInterval: (q) => ((q.state.data as Job[] | undefined)?.some((j) => j.state === "running") ? 1000 : false),
  });
}

/** Reflect a saved annotation in the image list without refetching it. */
export function patchImageRow(qc: QueryClient, slug: string, file: string, doc: AnnotationDoc) {
  const accepted = doc.objects.filter((o) => o.accepted).length;
  qc.setQueryData<ImageRow[]>(queryKeys.images(slug), (rows) =>
    rows?.map((r) =>
      r.file === file
        ? {
            ...r,
            status: doc.status,
            objects: accepted,
            suggested: doc.objects.length - accepted,
            labels: doc.labels,
          }
        : r,
    ),
  );
}

export function useUpdateProject(slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: ProjectPatch) => api.updateProject(slug, patch),
    onSuccess: (project) => qc.setQueryData<Project>(queryKeys.project(slug), project),
  });
}

const UPLOAD_BATCH_BYTES = 24 * 1024 * 1024;

/** Upload in batches that stay under the proxy's body limit. */
export async function uploadInBatches(
  slug: string,
  files: File[],
  onProgress: (done: number, total: number) => void,
) {
  let added = 0;
  let skipped = 0;
  const errors: string[] = [];
  let batch: File[] = [];
  let size = 0;
  let done = 0;
  const flush = async () => {
    if (!batch.length) return;
    const r = await api.upload(slug, batch);
    added += r.added;
    skipped += r.skipped;
    errors.push(...r.errors);
    done += batch.length;
    onProgress(done, files.length);
    batch = [];
    size = 0;
  };
  for (const f of files) {
    if (batch.length && (size + f.size > UPLOAD_BATCH_BYTES || batch.length >= 50)) await flush();
    batch.push(f);
    size += f.size;
  }
  await flush();
  return { added, skipped, errors };
}
