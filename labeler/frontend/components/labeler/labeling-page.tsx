"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircleIcon } from "lucide-react";
import { toast } from "sonner";
import { GridView } from "@/components/labeler/grid-view";
import { ImageList, type StatusFilter } from "@/components/labeler/image-list";
import { EMPTY_SOURCE, ImportPanel, runImport, sourceReady, type ImportSource } from "@/components/labeler/import-panel";
import { currentShapeTask, hotkeyTask, Inspector } from "@/components/labeler/inspector";
import { drawTaskFor, LabelCanvas } from "@/components/labeler/label-canvas";
import { NavBar } from "@/components/labeler/nav-bar";
import { NewDatasetDialog } from "@/components/labeler/new-dataset-dialog";
import { ReleaseDialog } from "@/components/labeler/release-dialog";
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
  toggleChoice,
} from "@/lib/actions";
import { errorMessage } from "@/lib/api";
import { docFromSample, taskGroups } from "@/lib/convert";
import { isTyping, useEditor, type Tool } from "@/lib/editor-store";
import { formatNumber, GROUP_KEYS } from "@/lib/format";
import { queryKeys, sampleQuery, useDataset, useImports, useSamples } from "@/lib/queries";
import { useSession } from "@/lib/use-session";
import type { Job, Status } from "@/lib/types";

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

function AddImages({ name }: { name: string }) {
  const qc = useQueryClient();
  const [source, setSource] = useState<ImportSource>(EMPTY_SOURCE);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const start = async () => {
    setBusy(true);
    try {
      const r = await runImport(name, source, (d, t) => setProgress([d, t]));
      if (r) {
        toast.success(`Uploaded ${formatNumber(r.added)} images`, { description: r.errors[0] });
        void qc.invalidateQueries({ queryKey: queryKeys.samples(name) });
        void qc.invalidateQueries({ queryKey: queryKeys.dataset(name) });
      } else {
        void qc.invalidateQueries({ queryKey: queryKeys.imports(name) });
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
            They&apos;re stored under <span className="font-mono">raw/labeler/</span>, named by content, and show up in
            the list as they arrive.
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

export function LabelingPage({ name }: { name: string }) {
  const qc = useQueryClient();
  const { data: dataset, error: datasetError } = useDataset(name);
  const { data: samples } = useSamples(name);
  const { data: jobs } = useImports(name);
  const { goTo, flush, current, loadError } = useSession(dataset);

  const file = useEditor((s) => s.file);
  const viewMode = useEditor((s) => s.viewMode);
  const [tab, setTab] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Fresh editor state per dataset.
  useEffect(() => {
    useEditor.setState({
      file: null,
      doc: null,
      viewMode: "single",
      activeTask: null,
      activeClass: null,
      lastClass: null,
      tool: "select",
    });
  }, [name]);

  const all = useMemo(() => samples ?? [], [samples]);
  const counts = useMemo(() => {
    const c = { all: all.length, todo: 0, review: 0, done: 0, excluded: 0 };
    for (const r of all) c[r.status]++;
    return c;
  }, [all]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(
      (r) =>
        // The open sample stays in the list after D marks it done, so neighbours stay stable.
        (r.id === file || tab === "all" || r.status === tab) &&
        (!q || r.name.toLowerCase().includes(q) || r.id.includes(q)),
    );
  }, [all, tab, search, file]);
  const index = file ? filtered.findIndex((r) => r.id === file) : -1;
  const image = current && current.id === file ? current : null;

  const open = useCallback(
    (id: string) => {
      const i = filtered.findIndex((r) => r.id === id);
      const ahead = i >= 0 ? filtered.slice(i + 1, i + 3).map((r) => r.id) : [];
      return goTo(id, ahead);
    },
    [filtered, goTo],
  );

  // Open the sample from the URL, else the first one still to do.
  useEffect(() => {
    if (!samples?.length || !dataset || file) return;
    const wanted = new URL(window.location.href).searchParams.get("sample");
    const first = samples.find((r) => r.id === wanted) ?? samples.find((r) => r.status === "todo") ?? samples[0];
    void open(first.id);
  }, [samples, dataset, file, open]);

  // Back from the grid: bulk edits may have changed the open sample.
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
        void qc.invalidateQueries({ queryKey: queryKeys.samples(name) });
        void qc.invalidateQueries({ queryKey: queryKeys.dataset(name) });
        if (j.state === "failed") toast.error(`Import failed: ${j.message}`);
        else toast.success(j.message ?? "Import finished", { description: j.errors[0] });
      }
    }
    // While importing, poll the list so new images appear.
    if (running.current.size) void qc.invalidateQueries({ queryKey: queryKeys.samples(name) });
  }, [jobs, qc, name]);

  const next = index >= 0 ? filtered[index + 1] : undefined;
  const prev = index > 0 ? filtered[index - 1] : undefined;
  const prevInOrder = useMemo(() => {
    const i = file ? all.findIndex((r) => r.id === file) : -1;
    return i > 0 ? all[i - 1] : undefined;
  }, [all, file]);

  const saveAndNext = useCallback(async () => {
    const { doc } = useEditor.getState();
    if (doc && doc.status !== "done") setStatus("done");
    if (next) await open(next.id);
    else {
      await flush();
      toast("That was the last image in this list.");
    }
  }, [next, open, flush]);

  const goPrev = useCallback(() => {
    if (prev) void open(prev.id);
  }, [prev, open]);

  const toggleStatus = useCallback((status: Status) => {
    const cur = useEditor.getState().doc?.status;
    setStatus(cur === status ? "todo" : status);
  }, []);

  const copyPrevious = useCallback(async () => {
    if (!prevInOrder || !image || !dataset) return;
    try {
      const sample = await qc.fetchQuery(sampleQuery(name, prevInOrder.id));
      const n = pasteObjects(docFromSample(sample, dataset).objects, image.width, image.height);
      toast(n ? `Copied ${n} object${n === 1 ? "" : "s"} from ${prevInOrder.name}` : `${prevInOrder.name} has no objects`);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }, [prevInOrder, image, dataset, qc, name]);

  // ---- keyboard

  useEffect(() => {
    if (!dataset) return;
    const tools = availableTools(dataset);
    const keyTask = hotkeyTask(dataset);
    const onKey = (e: KeyboardEvent) => {
      const s = useEditor.getState();
      if (isTyping(e.target) || s.shortcutsOpen || newOpen || releaseOpen || s.draft) return;
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
        // B/P switch the classes list to a task of the matching type.
        const t = drawTaskFor(dataset, TOOL_KEYS[k], s.activeTask);
        if (t && t !== s.activeTask) s.setActiveTask(t);
      } else if (/^[1-9]$/.test(k)) {
        const selected = s.doc?.objects.find((o) => o.id === s.selectedId);
        const task = selected?.task ?? currentShapeTask(dataset, s.activeTask);
        const cls = task ? dataset.classes[task]?.[Number(k) - 1] : undefined;
        if (task && cls) applyClass(task, cls);
      } else if (keyTask && (GROUP_KEYS as readonly string[]).includes(k)) {
        const cls = dataset.classes[keyTask]?.[GROUP_KEYS.indexOf(k as (typeof GROUP_KEYS)[number])];
        if (cls) toggleChoice(keyTask, cls, dataset.tasks[keyTask].type === "multilabel");
      } else if (k === "Enter") {
        const task = drawTaskFor(dataset, "polygon", s.activeTask);
        if (s.polyPoints.length && task) finishPolygon(task);
        else acceptSuggestions();
      } else if (k === "Escape") {
        if (s.polyPoints.length) s.setPolyPoints([]);
        else if (s.selectedId) s.select(null);
        else s.setActiveClass(null);
      } else if (k === "Delete" || k === "Backspace") {
        e.preventDefault();
        if (s.polyPoints.length) s.setPolyPoints(s.polyPoints.slice(0, -1));
        else deleteSelected();
      } else if (k.startsWith("Arrow") && image && s.selectedId) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        const [dx, dy] =
          { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[k] ?? [0, 0];
        nudgeSelected(dx, dy, image.width, image.height);
      } else if (k === "Tab") {
        e.preventDefault();
        cycleSelection(e.shiftKey ? -1 : 1);
      } else if (k === "d" && once) {
        void saveAndNext();
      } else if (k === "a" && once) {
        goPrev();
      } else if (k === "f" && once) {
        toggleStatus("review");
      } else if (k === "x" && once) {
        toggleStatus("excluded");
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
  }, [dataset, image, newOpen, releaseOpen, saveAndNext, goPrev, toggleStatus, copyPrevious]);

  // ---- render

  if (datasetError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-sm">
        <p>{errorMessage(datasetError)}</p>
        <Button variant="outline" asChild>
          <Link href="/">All datasets</Link>
        </Button>
      </div>
    );
  }
  if (!dataset || !samples) {
    return (
      <div className="flex h-screen flex-col">
        <div className="flex h-14 items-center gap-3 border-b px-6">
          <Skeleton className="h-7 w-72" />
        </div>
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="size-4 animate-spin" />
          Loading the dataset from the bucket…
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar dataset={dataset} onNewDataset={() => setNewOpen(true)} onRelease={() => setReleaseOpen(true)} />
      <ImportProgress jobs={jobs ?? []} />
      {viewMode === "grid" ? (
        <GridView
          dataset={dataset}
          rows={filtered}
          counts={counts}
          tab={tab}
          onTab={setTab}
          onOpen={(id) => {
            useEditor.getState().setViewMode("single");
            void open(id);
          }}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <ImageList
            dataset={name}
            rows={filtered}
            total={all.length}
            counts={counts}
            tab={tab}
            onTab={setTab}
            search={search}
            onSearch={setSearch}
            currentFile={file}
            onOpen={(id) => void open(id)}
            firstTask={taskGroups(dataset.tasks).choices[0]}
            searchRef={searchRef}
          />
          <main className="flex min-w-0 flex-1 flex-col">
            <Toolbar dataset={dataset} onCopyPrevious={() => void copyPrevious()} canCopyPrevious={!!prevInOrder} />
            {all.length === 0 ? (
              (jobs ?? []).some((j) => j.state === "running") ? (
                <div className="flex flex-1 items-center justify-center bg-canvas text-sm text-muted-foreground">
                  Images appear here as the import copies them…
                </div>
              ) : (
                <AddImages name={name} />
              )
            ) : image ? (
              <>
                <LabelCanvas dataset={dataset} image={image} />
                <NavBar
                  image={image}
                  position={index + 1}
                  count={filtered.length}
                  onPrev={goPrev}
                  onNext={() => void saveAndNext()}
                  onFlag={() => toggleStatus("review")}
                  onExclude={() => toggleStatus("excluded")}
                />
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center bg-canvas text-sm text-muted-foreground">
                {loadError ?? "Loading…"}
              </div>
            )}
          </main>
          <Inspector dataset={dataset} sample={image} />
        </div>
      )}
      <ShortcutsDialog />
      <NewDatasetDialog open={newOpen} onOpenChange={setNewOpen} />
      <ReleaseDialog dataset={dataset} open={releaseOpen} onOpenChange={setReleaseOpen} flush={flush} />
    </div>
  );
}
