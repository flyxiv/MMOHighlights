"use client";

import { BanIcon, CheckIcon, ChevronLeftIcon, FlagIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { useEditor } from "@/lib/editor-store";
import { formatNumber } from "@/lib/format";
import type { Sample } from "@/lib/types";
import { cn } from "@/lib/utils";

export function NavBar({
  image,
  position,
  count,
  onPrev,
  onNext,
  onFlag,
  onExclude,
}: {
  image: Sample;
  position: number;
  count: number;
  onPrev: () => void;
  onNext: () => void;
  onFlag: () => void;
  onExclude: () => void;
}) {
  const status = useEditor((s) => s.doc?.status ?? "todo");
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-t px-3">
      <Button variant="outline" size="sm" onClick={onPrev} disabled={position <= 1}>
        <ChevronLeftIcon />
        Previous
      </Button>
      <Kbd>A</Kbd>
      <div className="flex min-w-0 flex-1 items-center justify-center gap-2 text-sm">
        <span className="shrink-0 font-medium whitespace-nowrap tnum">
          {position > 0 ? `${formatNumber(position)} of ${formatNumber(count)}` : `${formatNumber(count)} in list`}
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="truncate font-mono text-xs text-muted-foreground" title={image.id}>
          {image.name}
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="shrink-0 font-mono text-xs whitespace-nowrap text-muted-foreground tnum">
          {image.width} × {image.height}
        </span>
        <span className="shrink-0 font-mono text-xs text-muted-foreground">{image.new ? "new" : image.split}</span>
        {status === "done" ? (
          <span className="rounded-sm bg-success-soft px-1.5 text-xs font-medium text-success">Done</span>
        ) : null}
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onFlag}
        className={cn(status === "review" && "bg-warning-soft text-warning hover:bg-warning-soft hover:text-warning")}
      >
        <FlagIcon />
        {status === "review" ? "Flagged" : "Review"}
      </Button>
      <Kbd>F</Kbd>
      <Button
        variant="ghost"
        size="sm"
        onClick={onExclude}
        className={cn(status === "excluded" && "bg-muted text-muted-foreground")}
      >
        <BanIcon />
        {status === "excluded" ? "Excluded" : "Exclude"}
      </Button>
      <Kbd>X</Kbd>
      <span className="w-2" />
      <Kbd>D</Kbd>
      <Button size="sm" onClick={onNext}>
        <CheckIcon />
        Save &amp; next
      </Button>
    </div>
  );
}
