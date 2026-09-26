"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, filePath, imageUrl } from "@/lib/api";
import { useEditor } from "@/lib/editor-store";
import { annotationQuery, patchImageRow, queryKeys } from "@/lib/queries";
import type { Annotation } from "@/lib/types";

const SAVE_DELAY_MS = 400;

/**
 * Loads images into the editor and autosaves edits. Saves go to the local backend (instant); the
 * backend pushes them to the bucket in the background.
 */
export function useSession(slug: string) {
  const qc = useQueryClient();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef<Promise<void>>(Promise.resolve());
  const statsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshStatsSoon = useCallback(() => {
    if (statsTimer.current) clearTimeout(statsTimer.current);
    statsTimer.current = setTimeout(() => void qc.invalidateQueries({ queryKey: queryKeys.project(slug) }), 800);
  }, [qc, slug]);

  const save = useCallback(() => {
    const run = async () => {
      const { file, doc, version, savedVersion, setSaving, markSaved } = useEditor.getState();
      if (!file || !doc || version === savedVersion) return;
      setSaving(true);
      try {
        const ann = await api.saveAnnotation(slug, file, doc);
        qc.setQueryData(queryKeys.annotation(slug, file), ann);
        patchImageRow(qc, slug, file, doc);
        // The editor may have moved on to another image while this was in flight.
        if (useEditor.getState().file === file) markSaved(version);
        useEditor.getState().setSaving(false);
        refreshStatsSoon();
      } catch (e) {
        useEditor.getState().setSaving(false, errorMessage(e));
      }
    };
    inflight.current = inflight.current.then(run);
    return inflight.current;
  }, [qc, slug, refreshStatsSoon]);

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
      const { file, doc, version, savedVersion } = useEditor.getState();
      if (!file || !doc || version === savedVersion) return;
      void fetch(`/api/projects/${slug}/annotations/${filePath(file)}`, {
        method: "PUT",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(doc),
      });
    };
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [slug]);

  const goTo = useCallback(
    async (file: string, prefetch: string[] = []) => {
      await flush();
      let ann: Annotation;
      try {
        ann = await qc.fetchQuery(annotationQuery(slug, file));
      } catch (e) {
        setLoadError(errorMessage(e));
        return;
      }
      setLoadError(null);
      useEditor.getState().load(file, { status: ann.status, labels: ann.labels, objects: ann.objects });
      const url = new URL(window.location.href);
      url.searchParams.set("image", file);
      window.history.replaceState(null, "", url);
      // Warm the next images so D feels instant.
      for (const f of prefetch) {
        void qc.prefetchQuery(annotationQuery(slug, f));
        const img = new Image();
        img.src = imageUrl(slug, f);
      }
    },
    [flush, qc, slug],
  );

  return { goTo, flush, loadError };
}
