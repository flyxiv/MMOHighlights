"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { CheckIcon, FlagIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import { FilterTabs, type StatusFilter } from "@/components/labeler/image-list";
import { ViewToggle } from "@/components/labeler/toolbar";
import { Kbd } from "@/components/ui/kbd";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage, thumbUrl } from "@/lib/api";
import { isTyping, useEditor } from "@/lib/editor-store";
import { formatNumber, GROUP_KEYS } from "@/lib/format";
import { queryKeys } from "@/lib/queries";
import type { ImageRow, Project, Status } from "@/lib/types";
import { cn } from "@/lib/utils";

const MIN_TILE = 200;
const GAP = 12;
const FOOTER = 33;

export function GridView({
  project,
  rows,
  counts,
  tab,
  onTab,
  onOpen,
}: {
  project: Project;
  rows: ImageRow[];
  counts: Record<StatusFilter, number>;
  tab: StatusFilter;
  onTab: (t: StatusFilter) => void;
  onOpen: (file: string) => void;
}) {
  const qc = useQueryClient();
  const setViewMode = useEditor((s) => s.setViewMode);
  const groups = project.groups;
  const [groupName, setGroupName] = useState(groups[0]?.name ?? "");
  const group = groups.find((g) => g.name === groupName) ?? groups[0];
  const [valueFilter, setValueFilter] = useState<string>("__any");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const anchor = useRef<number | null>(null);

  const visible = useMemo(() => {
    if (!group || valueFilter === "__any") return rows;
    if (valueFilter === "__unset") return rows.filter((r) => !r.labels[group.name]);
    return rows.filter((r) => r.labels[group.name] === valueFilter);
  }, [rows, group, valueFilter]);

  // ---- layout

  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const inner = Math.max(0, width - 48);
  const cols = Math.max(1, Math.floor((inner + GAP) / (MIN_TILE + GAP)));
  const tileW = cols ? (inner - GAP * (cols - 1)) / cols : MIN_TILE;
  const tileH = Math.round((tileW * 9) / 16) + FOOTER;
  const rowCount = Math.ceil(visible.length / cols);
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tileH + GAP,
    overscan: 3,
  });
  useEffect(() => virtualizer.measure(), [tileH, virtualizer]);

  // ---- selection and bulk edits

  const click = (e: React.MouseEvent, index: number) => {
    const file = visible[index].file;
    setSelected((cur) => {
      if (e.shiftKey && anchor.current !== null) {
        const [a, b] = [Math.min(anchor.current, index), Math.max(anchor.current, index)];
        const next = new Set(e.ctrlKey || e.metaKey ? cur : []);
        for (let i = a; i <= b; i++) next.add(visible[i].file);
        return next;
      }
      anchor.current = index;
      if (e.ctrlKey || e.metaKey) {
        const next = new Set(cur);
        if (next.has(file)) next.delete(file);
        else next.add(file);
        return next;
      }
      return cur.size === 1 && cur.has(file) ? new Set() : new Set([file]);
    });
  };

  const apply = async (labels: Record<string, string | null>, status?: Status) => {
    const files = [...selected];
    if (!files.length) return;
    try {
      await api.bulk(project.slug, { files, labels, status });
    } catch (e) {
      toast.error(errorMessage(e));
      return;
    }
    const set = new Set(files);
    qc.setQueryData<ImageRow[]>(queryKeys.images(project.slug), (old) =>
      old?.map((r) => {
        if (!set.has(r.file)) return r;
        const next = { ...r.labels };
        for (const [k, v] of Object.entries(labels)) {
          if (v === null) delete next[k];
          else next[k] = v;
        }
        return { ...r, labels: next, status: status ?? r.status };
      }),
    );
    for (const f of files) qc.removeQueries({ queryKey: queryKeys.annotation(project.slug, f) });
    void qc.invalidateQueries({ queryKey: queryKeys.project(project.slug) });
    toast.success(
      `${status === "review" ? "Flagged" : "Updated"} ${formatNumber(files.length)} image${files.length === 1 ? "" : "s"}`,
    );
  };

  const applyRef = useRef(apply);
  applyRef.current = apply;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || useEditor.getState().shortcutsOpen) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === "a") {
        e.preventDefault();
        setSelected(new Set(visible.map((r) => r.file)));
      } else if (k === "escape") {
        setSelected(new Set());
      } else if (e.ctrlKey || e.metaKey || e.altKey) {
        return;
      } else if (group && GROUP_KEYS.includes(k as (typeof GROUP_KEYS)[number])) {
        const opt = group.options[GROUP_KEYS.indexOf(k as (typeof GROUP_KEYS)[number])];
        if (opt) {
          e.preventDefault();
          void applyRef.current({ [group.name]: opt });
        }
      } else if (group && (k === "backspace" || k === "delete")) {
        void applyRef.current({ [group.name]: null });
      } else if (k === "f") {
        void applyRef.current({}, "review");
      } else if (k === "enter" && selected.size) {
        const first = visible.find((r) => selected.has(r.file));
        if (first) onOpen(first.file);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, group, selected, onOpen]);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b px-6">
        <ViewToggle value="grid" onChange={setViewMode} />
        <FilterTabs value={tab} counts={counts} onChange={onTab} className="w-72" />
        {group ? (
          <>
            {groups.length > 1 ? (
              <Select value={group.name} onValueChange={(v) => { setGroupName(v); setValueFilter("__any"); }}>
                <SelectTrigger size="sm" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((g) => (
                    <SelectItem key={g.name} value={g.name}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <Select value={valueFilter} onValueChange={setValueFilter}>
              <SelectTrigger size="sm" className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__any">{group.name}: any</SelectItem>
                <SelectItem value="__unset">{group.name}: not set</SelectItem>
                {group.options.map((o) => (
                  <SelectItem key={o} value={o}>
                    {group.name}: {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        ) : null}
        <span className="text-xs text-muted-foreground tnum">{formatNumber(visible.length)} images</span>
        <div className="flex-1" />
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          Click, Shift-click or Ctrl-click to select · <Kbd>Ctrl</Kbd>
          <Kbd>A</Kbd> all · double-click opens
        </span>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto bg-canvas">
        {!group ? (
          <p className="p-8 text-center text-sm text-muted-foreground">
            Add a label group in the inspector (single view) to classify images in bulk here.
          </p>
        ) : null}
        <div className="relative mx-6 my-5" style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map((vr) => (
            <div key={vr.key} className="absolute left-0 flex w-full gap-3" style={{ top: vr.start, height: tileH }}>
              {visible.slice(vr.index * cols, vr.index * cols + cols).map((r, j) => {
                const index = vr.index * cols + j;
                const on = selected.has(r.file);
                const value = group ? r.labels[group.name] : undefined;
                return (
                  <button
                    key={r.file}
                    onClick={(e) => click(e, index)}
                    onDoubleClick={() => onOpen(r.file)}
                    className={cn(
                      "relative flex flex-col overflow-hidden rounded-lg border bg-card text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                      on && "border-primary ring-1 ring-primary",
                    )}
                    style={{ width: tileW, height: tileH }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={thumbUrl(project.slug, r.file)} alt="" loading="lazy" className="min-h-0 w-full flex-1 bg-muted object-cover" />
                    <span
                      className={cn(
                        "absolute top-2 left-2 flex size-[18px] items-center justify-center rounded-[4px] border border-zinc-500 bg-white/85",
                        on && "border-primary bg-primary text-primary-foreground",
                      )}
                    >
                      {on ? <CheckIcon className="size-3" /> : null}
                    </span>
                    {r.status !== "todo" ? (
                      <span
                        className={cn(
                          "absolute top-2 right-2 flex size-5 items-center justify-center rounded-full",
                          r.status === "done" ? "bg-success text-white" : "bg-warning text-white",
                        )}
                        title={r.status === "done" ? "Done" : "Flagged for review"}
                      >
                        {r.status === "done" ? <CheckIcon className="size-3" /> : <FlagIcon className="size-3" />}
                      </span>
                    ) : null}
                    <span className="flex h-[33px] shrink-0 items-center gap-1.5 border-t px-2.5">
                      <span className="flex-1 truncate font-mono text-xs text-muted-foreground" title={r.file}>
                        {r.file.replace(/\.[^.]+$/, "")}
                      </span>
                      {value ? (
                        <span className="shrink-0 rounded-sm bg-muted px-1.5 text-xs font-medium">{value}</span>
                      ) : group ? (
                        <span className="shrink-0 rounded-sm border border-dashed px-1.5 text-xs text-muted-foreground">
                          not set
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {selected.size && group ? (
        <div className="absolute bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-2.5 rounded-lg bg-primary py-2 pr-2 pl-4 whitespace-nowrap text-primary-foreground shadow-xl">
          <span className="text-sm font-medium tnum">{formatNumber(selected.size)} selected</span>
          <span className="h-5 w-px bg-primary-foreground/25" />
          <span className="text-xs">Set {group.name}</span>
          {group.options.slice(0, GROUP_KEYS.length).map((o, i) => (
            <button
              key={o}
              onClick={() => void apply({ [group.name]: o })}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-primary-foreground/25 pr-1 pl-2 text-xs font-medium hover:bg-primary-foreground/10"
            >
              {o}
              <Kbd className="border-transparent bg-primary-foreground/15 text-primary-foreground">{GROUP_KEYS[i].toUpperCase()}</Kbd>
            </button>
          ))}
          <span className="h-5 w-px bg-primary-foreground/25" />
          <button
            onClick={() => void apply({}, "review")}
            className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium hover:bg-primary-foreground/10"
          >
            <FlagIcon className="size-4" />
            Review
          </button>
          <button
            onClick={() => setSelected(new Set())}
            aria-label="Clear selection"
            className="inline-flex size-7 items-center justify-center rounded-md hover:bg-primary-foreground/10"
          >
            <XIcon className="size-4" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
