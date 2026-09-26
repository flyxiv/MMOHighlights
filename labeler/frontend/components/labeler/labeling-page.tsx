"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircleIcon } from "lucide-react";
import { toast } from "sonner";
import { GridView } from "@/components/labeler/grid-view";
import { ImageList, type StatusFilter } from "@/components/labeler/image-list";
import { EMPTY_SOURCE, ImportPanel, runImport, sourceReady, type ImportSource } from "@/components/labeler/import-panel";
import { Inspector } from "@/components/labeler/inspector";
import { LabelCanvas } from "@/components/labeler/label-canvas";
import { NavBar } from "@/components/labeler/nav-bar";
import { NewProjectDialog } from "@/components/labeler/new-project-dialog";
import { ShortcutsDialog } from "@/components/labeler/shortcuts-dialog";
import { availableTools, Toolbar } from "@/components/labeler/toolbar";
import { TopBar } from "@/components/labeler/top-bar";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import {
  acceptSuggestions,
  applyClass,
  cycleSelection,
  deleteSelected,
  finishPolygon,
  nudgeSelected,
  pasteObjects,
  setStatus,
  toggleLabel,
} from "@/lib/actions";
import { errorMessage } from "@/lib/api";
import { isTyping, useEditor, type Tool } from "@/lib/editor-store";
import { CHIP_LIMIT, formatNumber, GROUP_KEYS } from "@/lib/format";
import { annotationQuery, queryKeys, useImages, useImports, useProject } from "@/lib/queries";
import { useSession } from "@/lib/use-session";
import type { ImageRow, Job } from "@/lib/types";

const TOOL_KEYS: Record<string, Tool> = { v: "select", b: "box", p: "polygon", h: "pan" };

function ImportProgress({ jobs }: { jobs: Job[] }) {
  const running = jobs.filter((j) => j.state === "running");
  if (!running.length) return null;
  return (
    <div className="flex shrink-0 items-center gap-3 border-b bg-muted/50 px-6 py-2 text-xs">
      <LoaderCircleIcon className="size-4 animate-spin text-muted-foreground" />
      {running.map((j) => (
        <span key={j.id} className="flex min-w-0 flex-1 items-center gap-3">
          <span className="truncate">
            Importing from <span className="font-mono">{j.source}</span>
          </span>
          <Progress value={j.total ? (j.processed / j.total) * 100 : 0} className="w-48" />
          <span className="text-muted-foreground tnum">
            {formatNumber(j.processed)} / {j.total ? formatNumber(j.total) : "…"}
          </span>
        </span>
      ))}
    </div>
  );
}

function AddImages({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const [source, setSource] = useState<ImportSource>(EMPTY_SOURCE);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const start = async () => {
    setBusy(true);
    try {
      const r = await runImport(slug, source, (d, t) => setProgress([d, t]));
      if (r) {
        toast.success(`Uploaded ${formatNumber(r.added)} images`, { description: r.errors[0] });
        void qc.invalidateQueries({ queryKey: queryKeys.images(slug) });
        void qc.invalidateQueries({ queryKey: queryKeys.project(slug) });
      } else {
        void qc.invalidateQueries({ queryKey: queryKeys.imports(slug) });
      }
      setSource(EMPTY_SOURCE);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  return (
    <div className="flex flex-1 items-center justify-center bg-canvas p-8">
      <div className="flex w-full max-w-lg flex-col gap-4 rounded-lg border bg-card p-6 shadow-xs">
        <div>
          <h2 className="font-semibold">Add images</h2>
          <p className="text-sm text-muted-foreground">
            They&apos;re copied into this project&apos;s folder in the bucket, then show up in the list as they arrive.
          </p>
        </div>
        <ImportPanel value={source} onChange={setSource} />
        {progress ? <Progress value={(progress[0] / progress[1]) * 100} /> : null}
        <Button className="self-end" onClick={start} disabled={busy || !sourceReady(source)}>
          {busy ? "Importing…" : "Import"}
        </Button>
      </div>
    </div>
  );
}

export function LabelingPage({ slug }: { slug: string }) {
  const qc = useQueryClient();
  const { data: project, error: projectError } = useProject(slug);
  const { data: images } = useImages(slug);
  const { data: jobs } = useImports(slug);
  const { goTo, flush, loadError } = useSession(slug);

  const file = useEditor((s) => s.file);
  const viewMode = useEditor((s) => s.viewMode);
  const [tab, setTab] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Fresh editor state per project.
  useEffect(() => {
    useEditor.setState({ file: null, doc: null, viewMode: "single", activeClassId: null, lastClassId: null, tool: "select" });
  }, [slug]);

  const all = useMemo(() => images ?? [], [images]);
  const counts = useMemo(
    () => ({
      all: all.length,
      todo: all.filter((r) => r.status === "todo").length,
      review: all.filter((r) => r.status === "review").length,
    }),
    [all],
  );
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(
      (r) =>
        // The open image stays in the list after D marks it done, so neighbours stay stable.
        (r.file === file || tab === "all" || r.status === tab) && (!q || r.file.toLowerCase().includes(q)),
    );
  }, [all, tab, search, file]);
  const index = file ? filtered.findIndex((r) => r.file === file) : -1;
  const current: ImageRow | null = (file && all.find((r) => r.file === file)) || null;

  const open = useCallback(
    (f: string) => {
      const i = filtered.findIndex((r) => r.file === f);
      const ahead = i >= 0 ? filtered.slice(i + 1, i + 3).map((r) => r.file) : [];
      return goTo(f, ahead);
    },
    [filtered, goTo],
  );

  // Open the image from the URL, else the first one still to do.
  useEffect(() => {
    if (!images?.length || file) return;
    const wanted = new URL(window.location.href).searchParams.get("image");
    const first =
      images.find((r) => r.file === wanted) ?? images.find((r) => r.status === "todo") ?? images[0];
    void open(first.file);
  }, [images, file, open]);

  // Back from the grid: bulk edits may have changed the open image.
  const prevMode = useRef(viewMode);
  useEffect(() => {
    if (prevMode.current === "grid" && viewMode === "single" && file) void goTo(file);
    prevMode.current = viewMode;
  }, [viewMode, file, goTo]);

  // Refresh the list when an import finishes.
  const running = useRef(new Set<string>());
  useEffect(() => {
    for (const j of jobs ?? []) {
      if (j.state === "running") running.current.add(j.id);
      else if (running.current.delete(j.id)) {
        void qc.invalidateQueries({ queryKey: queryKeys.images(slug) });
        void qc.invalidateQueries({ queryKey: queryKeys.project(slug) });
        if (j.state === "failed") toast.error(`Import failed: ${j.message}`);
        else toast.success(j.message ?? "Import finished", { description: j.errors[0] });
      }
    }
    // While importing, poll the list so new images appear.
    if (running.current.size) void qc.invalidateQueries({ queryKey: queryKeys.images(slug) });
  }, [jobs, qc, slug]);

  const next = index >= 0 ? filtered[index + 1] : undefined;
  const prev = index > 0 ? filtered[index - 1] : undefined;
  const prevInOrder = useMemo(() => {
    const i = file ? all.findIndex((r) => r.file === file) : -1;
    return i > 0 ? all[i - 1] : undefined;
  }, [all, file]);

  const saveAndNext = useCallback(async () => {
    const { doc } = useEditor.getState();
    if (doc && doc.status !== "done") setStatus("done");
    if (next) await open(next.file);
    else {
      await flush();
      toast("That was the last image in this list.");
    }
  }, [next, open, flush]);

  const goPrev = useCallback(() => {
    if (prev) void open(prev.file);
  }, [prev, open]);

  const toggleFlag = useCallback(() => {
    const status = useEditor.getState().doc?.status;
    setStatus(status === "review" ? "todo" : "review");
  }, []);

  const copyPrevious = useCallback(async () => {
    if (!prevInOrder || !current) return;
    try {
      const ann = await qc.fetchQuery(annotationQuery(slug, prevInOrder.file));
      const n = pasteObjects(ann.objects, current.width, current.height);
      toast(n ? `Copied ${n} object${n === 1 ? "" : "s"} from ${prevInOrder.file}` : `${prevInOrder.file} has no objects`);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [prevInOrder, current, qc, slug]);

  // ---- keyboard

  useEffect(() => {
    if (!project) return;
    const tools = availableTools(project);
    const chipGroup = project.groups.find((g) => g.options.length <= CHIP_LIMIT);
    const onKey = (e: KeyboardEvent) => {
      const s = useEditor.getState();
      if (isTyping(e.target) || s.shortcutsOpen || newOpen || s.draft) return;
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;

      if (k === "?" || (e.shiftKey && k === "/")) {
        e.preventDefault();
        s.setShortcutsOpen(true);
        return;
      }
      if (k === "g" && !e.ctrlKey && !e.metaKey) {
        s.setViewMode(s.viewMode === "grid" ? "single" : "grid");
        return;
      }
      if (s.viewMode !== "single") return; // the grid has its own keys

      if (e.ctrlKey || e.metaKey) {
        if (k === "z" && !e.shiftKey) {
          e.preventDefault();
          s.undo();
        } else if ((k === "z" && e.shiftKey) || k === "y") {
          e.preventDefault();
          s.redo();
        }
        return;
      }
      if (e.altKey) return;
      const once = !e.repeat;

      if (TOOL_KEYS[k] && tools.includes(TOOL_KEYS[k])) {
        s.setTool(TOOL_KEYS[k]);
      } else if (/^[1-9]$/.test(k)) {
        const c = project.classes[Number(k) - 1];
        if (c) applyClass(c.id);
      } else if (chipGroup && (GROUP_KEYS as readonly string[]).includes(k)) {
        const opt = chipGroup.options[GROUP_KEYS.indexOf(k as (typeof GROUP_KEYS)[number])];
        if (opt) toggleLabel(chipGroup.name, opt);
      } else if (k === "Enter") {
        if (s.polyPoints.length) finishPolygon();
        else acceptSuggestions();
      } else if (k === "Escape") {
        if (s.polyPoints.length) s.setPolyPoints([]);
        else if (s.selectedId) s.select(null);
        else s.setActiveClass(null);
      } else if (k === "Delete" || k === "Backspace") {
        e.preventDefault();
        if (s.polyPoints.length) s.setPolyPoints(s.polyPoints.slice(0, -1));
        else deleteSelected();
      } else if (k.startsWith("Arrow") && current && s.selectedId) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        const [dx, dy] = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[k] ?? [0, 0];
        nudgeSelected(dx, dy, current.width, current.height);
      } else if (k === "Tab") {
        e.preventDefault();
        cycleSelection(e.shiftKey ? -1 : 1);
      } else if (k === "d" && once) {
        void saveAndNext();
      } else if (k === "a" && once) {
        goPrev();
      } else if (k === "f" && once) {
        toggleFlag();
      } else if (k === "c" && once) {
        void copyPrevious();
      } else if (k === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (k === "+" || k === "=") {
        s.zoomAt(1.25);
      } else if (k === "-" || k === "_") {
        s.zoomAt(1 / 1.25);
      } else if (k === "0") {
        s.requestFit();
      } else if (k === "`") {
        s.toggleShowObjects();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [project, current, newOpen, saveAndNext, goPrev, toggleFlag, copyPrevious]);

  // ---- render

  if (projectError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-sm">
        <p>{errorMessage(projectError)}</p>
        <Button variant="outline" asChild>
          <Link href="/">All projects</Link>
        </Button>
      </div>
    );
  }
  if (!project || !images) {
    return (
      <div className="flex h-screen flex-col">
        <div className="flex h-14 items-center gap-3 border-b px-6">
          <Skeleton className="h-7 w-72" />
        </div>
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="size-4 animate-spin" />
          Loading labels from the bucket…
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar project={project} onNewProject={() => setNewOpen(true)} />
      <ImportProgress jobs={jobs ?? []} />
      {viewMode === "grid" ? (
        <GridView
          project={project}
          rows={filtered}
          counts={counts}
          tab={tab}
          onTab={setTab}
          onOpen={(f) => {
            useEditor.getState().setViewMode("single");
            void open(f);
          }}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <ImageList
            slug={slug}
            rows={filtered}
            total={all.length}
            counts={counts}
            tab={tab}
            onTab={setTab}
            search={search}
            onSearch={setSearch}
            currentFile={file}
            onOpen={(f) => void open(f)}
            firstGroup={project.groups[0]?.name}
            searchRef={searchRef}
          />
          <main className="flex min-w-0 flex-1 flex-col">
            <Toolbar project={project} onCopyPrevious={() => void copyPrevious()} canCopyPrevious={!!prevInOrder} />
            {all.length === 0 ? (
              (jobs ?? []).some((j) => j.state === "running") ? (
                <div className="flex flex-1 items-center justify-center bg-canvas text-sm text-muted-foreground">
                  Images appear here as the import copies them…
                </div>
              ) : (
                <AddImages slug={slug} />
              )
            ) : current ? (
              <>
                <LabelCanvas project={project} image={current} />
                <NavBar
                  image={current}
                  position={index + 1}
                  count={filtered.length}
                  onPrev={goPrev}
                  onNext={() => void saveAndNext()}
                  onFlag={toggleFlag}
                />
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center bg-canvas text-sm text-muted-foreground">
                {loadError ?? "Loading…"}
              </div>
            )}
          </main>
          <Inspector project={project} image={current} />
        </div>
      )}
      <ShortcutsDialog />
      <NewProjectDialog open={newOpen} onOpenChange={setNewOpen} />
    </div>
  );
}
