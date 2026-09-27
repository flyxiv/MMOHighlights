"use client";

import { ActivityIcon, CloudUploadIcon, HardDriveIcon, VideoIcon, WifiOffIcon } from "lucide-react";
import type { LiveConnection } from "@/lib/events";
import { formatBytes, formatRelative, secondsBetween } from "@/lib/format";
import { useHealth } from "@/lib/queries";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

export function TopBar({ connection }: { connection: LiveConnection }) {
  const { data: health, isError } = useHealth();
  const now = useNow();

  const lastRun = health?.poll_last_run_at ?? null;
  const pollAge = lastRun && now ? secondsBetween(lastRun, now) : null;
  const pollerOk = pollAge !== null && pollAge < 90;

  return (
    <header className="border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex min-h-14 max-w-[1440px] flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2 sm:px-6 lg:px-12">
        <div className="flex items-center gap-3">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <VideoIcon className="size-4" />
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <span className="font-semibold">MMOHighlights</span>
            <span className="text-muted-foreground/60">/</span>
            <span className="text-muted-foreground">Live Recorder</span>
          </nav>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground tabular-nums">
          {connection === "reconnecting" ? (
            <span className="inline-flex items-center gap-1.5 text-warning">
              <WifiOffIcon className="size-3.5" />
              Reconnecting…
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className={cn(
                "size-2 rounded-full",
                isError ? "bg-live" : pollerOk ? "bg-success" : lastRun ? "bg-warning" : "bg-muted-foreground/50",
              )}
            />
            <ActivityIcon className="size-3.5" />
            {isError && !health
              ? "Backend unreachable"
              : lastRun && now
                ? `Poller ran ${formatRelative(lastRun, now)}`
                : "Poller hasn't run yet"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CloudUploadIcon className="size-3.5" />
            Upload queue: {health ? `${health.upload_backlog} segment${health.upload_backlog === 1 ? "" : "s"}` : "–"}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <HardDriveIcon className="size-3.5" />
            Spool: {health ? `${formatBytes(health.spool_free_bytes)} free` : "–"}
          </span>
        </div>
      </div>
    </header>
  );
}
