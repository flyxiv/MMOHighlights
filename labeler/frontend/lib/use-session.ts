"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, imageUrl } from "@/lib/api";
import { docFromSample, saveFromDoc } from "@/lib/convert";
import { useEditor } from "@/lib/editor-store";
import { patchRow, queryKeys, sampleQuery } from "@/lib/queries";
import type { Dataset, Sample } from "@/lib/types";

const SAVE_DELAY_MS = 400;

/**
 * Loads samples into the editor and autosaves edits. Saves go to the local backend (instant), which
 * writes labeling/labels/<id>.json to the bucket in the background.
 */
export function useSession(dataset: Dataset | undefined) {
  const qc = useQueryClient();
  const name = dataset?.name ?? "";
  const tasksRef = useRef(dataset?.tasks);
  tasksRef.current = dataset?.tasks;
  const datasetRef = useRef(dataset);
  datasetRef.current = dataset;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef<Promise<void>>(Promise.resolve());
  const statsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [current, setCurrent] = useState<Sample | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshStatsSoon = useCallback(() => {
    if (statsTimer.current) clearTimeout(statsTimer.current);
    statsTimer.current = setTimeout(() => void qc.invalidateQueries({ queryKey: queryKeys.dataset(name) }), 800);
  }, [qc, name]);

  const save = useCallback(() => {
    const run = async () => {
      const { file: id, doc, version, savedVersion, setSaving, markSaved } = useEditor.getState();
      const tasks = tasksRef.current;
      if (!id || !doc || !tasks || version === savedVersion) return;
      setSaving(true);
      try {
        const sample = await api.saveSample(name, id, saveFromDoc(doc, tasks));
        qc.setQueryData(queryKeys.sample(name, id), sample);
        patchRow(qc, name, id, doc);
        // The editor may have moved on to another sample while this was in flight.
        if (useEditor.getState().file === id) markSaved(version);
        useEditor.getState().setSaving(false);
        refreshStatsSoon();
      } catch (e) {
        useEditor.getState().setSaving(false, errorMessage(e));
      }
    };
    inflight.current = inflight.current.then(run);
    return inflight.current;
  }, [qc, name, refreshStatsSoon]);

  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    await save();
  }, [save]);

  // Debounced autosave on every edit.
  useEffect(
    () =>
      useEditor.subscribe((s, prev) => {
        if (s.version !== prev.version && s.version !== s.savedVersion && s.file === prev.file) {
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => {
            timer.current = null;
            void save();
          }, SAVE_DELAY_MS);
        }
      }),
    [save],
  );

  // Closing the tab: send unsaved edits with keepalive so the request outlives the page.
  useEffect(() => {
    const onHide = () => {
      const { file: id, doc, version, savedVersion } = useEditor.getState();
      const tasks = tasksRef.current;
      if (!id || !doc || !tasks || version === savedVersion) return;
      void fetch(`/api/datasets/${name}/samples/${id}`, {
        method: "PUT",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(saveFromDoc(doc, tasks)),
      });
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [name]);

  const goTo = useCallback(
    async (id: string, prefetch: string[] = []) => {
      await flush();
      const ds = datasetRef.current;
      if (!ds) return;
      let sample: Sample;
      try {
        sample = await qc.fetchQuery(sampleQuery(name, id));
      } catch (e) {
        setLoadError(errorMessage(e));
        return;
      }
      setLoadError(null);
      setCurrent(sample);
      useEditor.getState().load(id, docFromSample(sample, ds));
      const url = new URL(window.location.href);
      url.searchParams.set("sample", id);
      window.history.replaceState(null, "", url);
      // Warm the next samples so D feels instant.
      for (const next of prefetch) {
        void qc.prefetchQuery(sampleQuery(name, next));
        const img = new Image();
        img.src = imageUrl(name, next);
      }
    },
    [flush, qc, name],
  );

  return { goTo, flush, current, loadError };
}
