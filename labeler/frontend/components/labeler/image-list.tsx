"use client";

import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { SearchIcon } from "lucide-react";
import { Kbd } from "@/components/ui/kbd";
import { thumbUrl } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { ImageRow } from "@/lib/types";
import { cn } from "@/lib/utils";

export type StatusFilter = "all" | "todo" | "review";

export const STATUS_TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "todo", label: "To do" },
  { key: "review", label: "Review" },
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
  return (
    <div className={cn("flex rounded-md bg-muted p-[3px]", className)} role="tablist">
      {STATUS_TABS.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "flex flex-1 items-center justify-center gap-1 rounded-sm py-1 text-xs text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            value === t.key && "bg-background font-medium text-foreground shadow-xs",
          )}
        >
          {t.label}
          <span className="font-mono text-muted-foreground tnum">{formatNumber(counts[t.key])}</span>
        </button>
      ))}
    </div>
  );
}

export function rowMeta(r: ImageRow, firstGroup: string | undefined): string {
  const parts: string[] = [];
  if (r.objects) parts.push(`${formatNumber(r.objects)} object${r.objects === 1 ? "" : "s"}`);
  if (r.suggested) parts.push(`${formatNumber(r.suggested)} suggested`);
  if (firstGroup && r.labels[firstGroup]) parts.push(r.labels[firstGroup]);
  if (parts.length) return parts.join(" · ");
  return r.status === "todo" ? "Not labeled" : "No objects";
}

function StatusDot({ row, current }: { row: ImageRow; current: boolean }) {
  if (current) return <span className="size-2 shrink-0 rounded-full bg-primary" />;
  if (row.status === "done") return <span className="size-2 shrink-0 rounded-full bg-success" title="Done" />;
  if (row.status === "review")
    return <span className="size-2 shrink-0 rounded-full bg-warning" title="Flagged for review" />;
  return <span className="size-2 shrink-0 rounded-full border border-muted-foreground" title="To do" />;
}

export function ImageList({
  slug,
  rows,
  total,
  counts,
  tab,
  onTab,
  search,
  onSearch,
  currentFile,
  onOpen,
  firstGroup,
  searchRef,
}: {
  slug: string;
  rows: ImageRow[];
  total: number;
  counts: Record<StatusFilter, number>;
  tab: StatusFilter;
  onTab: (t: StatusFilter) => void;
  search: string;
  onSearch: (s: string) => void;
  currentFile: string | null;
  onOpen: (file: string) => void;
  firstGroup: string | undefined;
  searchRef: React.RefObject<HTMLInputElement | null>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 50,
    overscan: 12,
  });

  const currentIndex = currentFile ? rows.findIndex((r) => r.file === currentFile) : -1;
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
            placeholder="Search file names…"
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
              const current = r.file === currentFile;
              return (
                <button
                  key={r.file}
                  onClick={() => onOpen(r.file)}
                  className={cn(
                    "absolute left-0 flex w-full items-center gap-2.5 rounded-md border border-transparent px-2 py-1.5 text-left outline-none hover:bg-accent/60 focus-visible:ring-[3px] focus-visible:ring-ring/50",
                    current && "border-ring bg-accent hover:bg-accent",
                  )}
                  style={{ top: v.start, height: 48 }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={thumbUrl(slug, r.file)}
                    alt=""
                    loading="lazy"
                    className={cn("h-9 w-16 shrink-0 rounded bg-muted object-cover", r.status === "todo" && !current && "opacity-85")}
                  />
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="truncate font-mono text-xs" title={r.file}>
                      {r.file}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{rowMeta(r, firstGroup)}</span>
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
          ? `${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(rows.length)} · sorted by name`
          : `${formatNumber(total)} images`}
      </div>
    </aside>
  );
}
