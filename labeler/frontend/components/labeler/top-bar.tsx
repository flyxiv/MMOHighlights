"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckIcon, ChevronDownIcon, CloudOffIcon, KeyboardIcon, LoaderCircleIcon, PackageIcon, PlusIcon, TagIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEditor } from "@/lib/editor-store";
import { formatNumber } from "@/lib/format";
import { useDatasets, useHealth } from "@/lib/queries";
import type { Dataset } from "@/lib/types";

export function Brand({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2 text-sm">
      <Link href="/" className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <TagIcon className="size-4" />
        </span>
        <span className="font-medium">MMOHighlights</span>
      </Link>
      <span className="text-muted-foreground">/</span>
      <Link href="/" className="text-muted-foreground hover:text-foreground">
        Image Labeling
      </Link>
      {children}
    </div>
  );
}

export function SyncStatus() {
  const saving = useEditor((s) => s.saving);
  const saveError = useEditor((s) => s.saveError);
  const { data: health, isError } = useHealth();

  if (saveError || isError) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 text-xs text-danger">
            <CloudOffIcon className="size-4" />
            {saveError ? "Not saved" : "Backend unreachable"}
          </span>
        </TooltipTrigger>
        <TooltipContent>{saveError ?? "The labeler backend isn't responding."}</TooltipContent>
      </Tooltip>
    );
  }
  if (saving) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <LoaderCircleIcon className="size-4 animate-spin" />
        Saving
      </span>
    );
  }
  if (health?.last_sync_error) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center gap-1 text-xs text-warning">
            <CloudOffIcon className="size-4" />
            Saved locally · {formatNumber(health.pending_sync)} waiting for the bucket
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm">
          Labels are safe on this PC and upload when the bucket is reachable again. {health.last_sync_error}
        </TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <CheckIcon className="size-4 text-success" />
          {health && health.pending_sync > 0 ? `Syncing ${formatNumber(health.pending_sync)}` : "Saved"}
        </span>
      </TooltipTrigger>
      <TooltipContent>{health ? `Stored in ${health.storage}` : "Saved"}</TooltipContent>
    </Tooltip>
  );
}

export function TopBar({
  dataset,
  onNewDataset,
  onRelease,
}: {
  dataset: Dataset;
  onNewDataset: () => void;
  onRelease: () => void;
}) {
  const router = useRouter();
  const { data: datasets } = useDatasets();
  const setShortcutsOpen = useEditor((s) => s.setShortcutsOpen);
  const { total, done, excluded } = dataset.stats;
  const counted = total - excluded;
  const pct = counted ? Math.round((done / counted) * 100) : 0;

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b px-6">
      <Brand>
        <span className="text-muted-foreground">/</span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50">
              <span className="truncate font-mono">{dataset.name}</span>
              <span className="rounded-sm bg-muted px-1.5 font-mono text-xs font-normal text-muted-foreground">
                {dataset.base_release ? `${dataset.base_release} → ${dataset.next_release}` : `new → ${dataset.next_release}`}
              </span>
              <ChevronDownIcon className="size-4 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-72">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Datasets</DropdownMenuLabel>
            {(datasets ?? []).map((d) => (
              <DropdownMenuItem key={d.name} onSelect={() => router.push(`/d/${d.name}`)}>
                <span className="flex-1 truncate font-mono">{d.name}</span>
                <span className="text-xs text-muted-foreground">{d.latest ?? "no release"}</span>
                {d.name === dataset.name ? <CheckIcon /> : null}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onNewDataset}>
              <PlusIcon />
              New dataset…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Brand>
      <div className="flex-1" />
      <div className="flex items-center gap-2.5 text-xs text-muted-foreground tnum">
        {formatNumber(done)} / {formatNumber(counted)} reviewed
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
        </div>
        <span className="font-mono">{pct}%</span>
      </div>
      <SyncStatus />
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" onClick={() => setShortcutsOpen(true)} aria-label="Keyboard shortcuts">
            <KeyboardIcon className="text-muted-foreground" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Keyboard shortcuts · ?</TooltipContent>
      </Tooltip>
      <Button variant="outline" size="sm" onClick={onRelease}>
        <PackageIcon />
        Cut {dataset.next_release}
      </Button>
    </header>
  );
}
