"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  CheckIcon,
  ChevronDownIcon,
  CloudOffIcon,
  DownloadIcon,
  KeyboardIcon,
  LoaderCircleIcon,
  PlusIcon,
  TagIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useEditor } from "@/lib/editor-store";
import { formatNumber, tasksLabel } from "@/lib/format";
import { useHealth, useProjects } from "@/lib/queries";
import type { Project } from "@/lib/types";

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

function ExportMenu({ project }: { project: Project }) {
  const [includeUnfinished, setIncludeUnfinished] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async (format: "yolo" | "coco") => {
    setBusy(true);
    try {
      const r = await api.exportProject(project.slug, { format, include_unfinished: includeUnfinished });
      toast.success(`Exported ${formatNumber(r.images)} images, ${formatNumber(r.objects)} objects`, {
        description: r.uri,
        duration: 15_000,
        action: { label: "Copy path", onClick: () => void navigator.clipboard.writeText(r.uri) },
      });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" disabled={busy}>
          {busy ? <LoaderCircleIcon className="animate-spin" /> : <DownloadIcon />}
          Export
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
          Written to {project.storage_uri}/exports/
        </DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => void run("yolo")}>
          YOLO
          <span className="ml-auto text-xs text-muted-foreground">
            {project.tasks.includes("segmentation") ? "labels/*.txt · seg" : "labels/*.txt"}
          </span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void run("coco")}>
          COCO
          <span className="ml-auto text-xs text-muted-foreground">annotations.json</span>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuCheckboxItem
          checked={includeUnfinished}
          onCheckedChange={(v) => setIncludeUnfinished(v === true)}
          onSelect={(e) => e.preventDefault()}
        >
          Include images not marked done
        </DropdownMenuCheckboxItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TopBar({ project, onNewProject }: { project: Project; onNewProject: () => void }) {
  const router = useRouter();
  const { data: projects } = useProjects();
  const setShortcutsOpen = useEditor((s) => s.setShortcutsOpen);
  const { total, done } = project.stats;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b px-6">
      <Brand>
        <span className="text-muted-foreground">/</span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="inline-flex min-w-0 items-center gap-1.5 rounded-md border px-2 py-1 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50">
              <span className="truncate">{project.name}</span>
              <span className="rounded-sm bg-muted px-1.5 text-xs font-normal text-muted-foreground">
                {tasksLabel(project.tasks)}
              </span>
              <ChevronDownIcon className="size-4 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
            <DropdownMenuLabel className="text-xs text-muted-foreground">Projects</DropdownMenuLabel>
            {(projects ?? []).map((p) => (
              <DropdownMenuItem key={p.slug} onSelect={() => router.push(`/p/${p.slug}`)}>
                <span className="flex-1 truncate">{p.name}</span>
                {p.slug === project.slug ? <CheckIcon /> : null}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onNewProject}>
              <PlusIcon />
              New project…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Brand>
      <div className="flex-1" />
      <div className="flex items-center gap-2.5 text-xs text-muted-foreground tnum">
        {formatNumber(done)} / {formatNumber(total)} labeled
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
      <ExportMenu project={project} />
    </header>
  );
}
