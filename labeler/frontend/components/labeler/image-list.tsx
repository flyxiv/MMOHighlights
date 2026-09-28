"use client";

import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { SearchIcon } from "lucide-react";
import { Kbd } from "@/components/ui/kbd";
import { thumbUrl } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { SampleRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export type StatusFilter = "all" | "todo" | "review" | "done" | "excluded";

export const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "todo", label: "To do" },
  { key: "review", label: "Review" },
  { key: "done", label: "Done" },
  { key: "excluded", label: "Excluded" },
];

export function FilterTabs({
  value,
  counts,
  onChange,
  className,
}: {
  value: StatusFilter;
  counts: Record<StatusFilter, number>;
  onChange: (v: StatusFilter) => void;
  className?: string;
}) {
  // Excluded only shows up once something is excluded.
  const tabs = STATUS_TABS.filter((t) => t.key !== "excluded" || counts.excluded > 0 || value === "excluded");
  return (
    <div className={cn("flex rounded-md bg-muted p-[3px]", className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "flex min-w-0 flex-auto items-center justify-center gap-1 rounded-sm px-1 py-1 text-[11px] whitespace-nowrap text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            value === t.key && "bg-background font-medium text-foreground shadow-xs",
          )}
        >
          {t.label}
          {counts[t.key] || value === t.key ? (
            <span className="font-mono text-muted-foreground tnum">{formatNumber(counts[t.key])}</span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function rowMeta(r: SampleRow, firstTask: string | undefined): string {
  const parts: string[] = [];
  if (r.objects) parts.push(`${formatNumber(r.objects)} object${r.objects === 1 ? "" : "s"}`);
  if (r.suggested) parts.push(`${formatNumber(r.suggested)} suggested`);
  const v = firstTask ? r.labels[firstTask] : undefined;
  if (v) parts.push(Array.isArray(v) ? v.join(", ") : v);
  if (parts.length) return parts.join(" · ");
  if (r.status === "excluded") return "Excluded";
  return r.status === "todo" ? "Not labeled" : "No objects";
}

function StatusDot({ row, current }: { row: SampleRow; current: boolean }) {
  if (current) return <span className="size-2 shrink-0 rounded-full bg-primary" />;
  if (row.status === "done") return <span className="size-2 shrink-0 rounded-full bg-success" title="Done" />;
  if (row.status === "review")
    return <span className="size-2 shrink-0 rounded-full bg-warning" title="Flagged for review" />;
  if (row.status === "excluded")
    return <span className="size-2 shrink-0 rounded-full bg-muted-foreground/40" title="Excluded from releases" />;
  return <span className="size-2 shrink-0 rounded-full border border-muted-foreground" title="To do" />;
}

export function ImageList({
  dataset,
  rows,
  total,
  counts,
  tab,
  onTab,
  search,
  onSearch,
  currentFile,
  onOpen,
  firstTask,
  searchRef,
}: {
  dataset: string;
  rows: SampleRow[];
  total: number;
  counts: Record<StatusFilter, number>;
  tab: StatusFilter;
  onTab: (t: StatusFilter) => void;
  search: string;
  onSearch: (s: string) => void;
  currentFile: string | null;
  onOpen: (file: string) => void;
  firstTask: string | undefined;
  searchRef: React.RefObject<HTMLInputElement | null>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 50,
    overscan: 12,
  });

  const currentIndex = currentFile ? rows.findIndex((r) => r.id === currentFile) : -1;
  useEffect(() => {
    if (currentIndex >= 0) virtualizer.scrollToIndex(currentIndex, { align: "auto" });
  }, [currentIndex, virtualizer]);

  const items = virtualizer.getVirtualItems();
  const first = items.length ? items[0].index + 1 : 0;
  const last = items.length ? items[items.length - 1].index + 1 : 0;

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r">
      <div className="flex flex-col gap-3 px-4 pt-4 pb-3">
        <label className="flex h-9 items-center gap-2 rounded-md border border-input bg-background px-2.5 focus-within:ring-[3px] focus-within:ring-ring/50">
          <SearchIcon className="size-4 text-muted-foreground" />
          <input
            ref={searchRef}
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape" || e.key === "Enter") e.currentTarget.blur();
            }}
            placeholder="Search names or ids…"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <Kbd>/</Kbd>
        </label>
        <FilterTabs value={tab} counts={counts} onChange={onTab} />
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {rows.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">
            {total === 0 ? "No images yet." : "No images match."}
          </p>
        ) : (
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {items.map((v) => {
              const r = rows[v.index];
              const current = r.id === currentFile;
              return (
                <button
                  key={r.id}
                  onClick={() => onOpen(r.id)}
                  className={cn(
                    "absolute left-0 flex w-full items-center gap-2.5 rounded-md border border-transparent px-2 py-1.5 text-left outline-none hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50",
                    current && "border-ring bg-accent hover:bg-accent",
                  )}
                  style={{ top: v.start, height: 48 }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={thumbUrl(dataset, r.id)}
                    alt=""
                    loading="lazy"
                    className={cn(
                      "h-9 w-16 shrink-0 rounded bg-muted object-cover",
                      r.status === "todo" && !current && "opacity-85",
                      r.status === "excluded" && "opacity-40 grayscale",
                    )}
                  />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-baseline gap-1.5">
                      <span className="truncate font-mono text-xs" title={`${r.name} · ${r.id}`}>
                        {r.name}
                      </span>
                      {r.new ? <span className="shrink-0 text-[10px] text-muted-foreground uppercase">new</span> : null}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{rowMeta(r, firstTask)}</span>
                  </span>
                  <StatusDot row={r} current={current} />
                </button>
              );
            })}
          </div>
        )}
      </div>
      <div className="border-t px-4 py-2.5 text-xs text-muted-foreground tnum">
        {rows.length
          ? `${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(rows.length)} · release order, then new`
          : `${formatNumber(total)} images`}
      </div>
    </aside>
  );
}
