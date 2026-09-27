"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatRelative, formatShortDuration, secondsBetween } from "@/lib/format";
import type { ChannelOut, RecordingOut, SegmentStatus } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

export type Tone = "live" | "warning" | "success" | "muted" | "destructive";

const TONES: Record<Tone, string> = {
  live: "bg-live-soft text-live",
  warning: "bg-warning-soft text-warning",
  success: "bg-success-soft text-success",
  muted: "bg-muted text-muted-foreground",
  destructive: "bg-destructive text-white dark:bg-destructive/70",
};

const DOTS: Partial<Record<Tone, string>> = {
  live: "bg-live",
  warning: "bg-warning",
  success: "bg-success",
};

export function StatusPill({
  tone,
  dot = false,
  pulse = false,
  children,
  className,
}: {
  tone: Tone;
  dot?: boolean;
  pulse?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-xs font-medium whitespace-nowrap tabular-nums",
        TONES[tone],
        className,
      )}
    >
      {dot && DOTS[tone] ? (
        <span className="relative flex size-1.5 shrink-0">
          {pulse ? (
            <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", DOTS[tone])} />
          ) : null}
          <span className={cn("relative inline-flex size-1.5 rounded-full", DOTS[tone])} />
        </span>
      ) : null}
      {children}
    </span>
  );
}

export function ChannelStatusBadge({ channel }: { channel: ChannelOut }) {
  const now = useNow();
  if (channel.check_failures >= 3) {
    const pill = (
      <StatusPill tone="warning">Check failing · {channel.check_failures}×</StatusPill>
    );
    if (!channel.last_error) return pill;
    return (
      <Tooltip>
        <TooltipTrigger asChild>{pill}</TooltipTrigger>
        <TooltipContent>{channel.last_error}</TooltipContent>
      </Tooltip>
    );
  }
  if (channel.status === "live") {
    const since = channel.live_started_at;
    return (
      <StatusPill tone="live" dot pulse>
        Live{since && now ? ` · ${formatShortDuration(secondsBetween(since, now))}` : ""}
      </StatusPill>
    );
  }
  if (channel.last_live_ended_at) {
    return (
      <StatusPill tone="muted">
        Offline · ended {now ? formatRelative(channel.last_live_ended_at, now) : ""}
      </StatusPill>
    );
  }
  return <StatusPill tone="muted">Offline · not seen live yet</StatusPill>;
}

export function RecordingStatusBadge({ recording }: { recording: RecordingOut }) {
  const now = useNow();
  switch (recording.status) {
    case "recording":
      return (
        <StatusPill tone="live" dot pulse>
          Recording
        </StatusPill>
      );
    case "ending": {
      const offlineFor =
        recording.ended_at && now ? Math.max(1, Math.floor(secondsBetween(recording.ended_at, now) / 60)) : null;
      return (
        <StatusPill tone="warning">
          Ending{offlineFor ? ` · offline ${offlineFor} min` : ""}
        </StatusPill>
      );
    }
    case "finalizing":
      return <StatusPill tone="warning">Finalizing</StatusPill>;
    case "failed": {
      const pill = (
        <StatusPill tone="destructive">
          Failed{recording.last_error ? ` · ${shortError(recording.last_error)}` : ""}
        </StatusPill>
      );
      if (!recording.last_error) return pill;
      return (
        <Tooltip>
          <TooltipTrigger asChild>{pill}</TooltipTrigger>
          <TooltipContent className="max-w-xs">{recording.last_error}</TooltipContent>
        </Tooltip>
      );
    }
    case "completed":
      if (recording.purged_at) return <StatusPill tone="muted">Expired</StatusPill>;
      return <StatusPill tone="success">Completed</StatusPill>;
  }
}

function shortError(error: string): string {
  const first = error.split(/[.\n]/)[0];
  return first.length > 28 ? `${first.slice(0, 27)}…` : first;
}

const SEGMENT_LABEL: Record<SegmentStatus, { label: string; tone: Tone }> = {
  pending: { label: "Writing", tone: "live" },
  uploading: { label: "Uploading", tone: "warning" },
  uploaded: { label: "Uploaded", tone: "success" },
  failed: { label: "Failed", tone: "destructive" },
};

export function SegmentStatusBadge({ status, closed }: { status: SegmentStatus; closed: boolean }) {
  if (status === "pending" && closed) return <StatusPill tone="muted">Queued</StatusPill>;
  const meta = SEGMENT_LABEL[status];
  return (
    <StatusPill tone={meta.tone} dot={status === "pending"} pulse={status === "pending"}>
      {meta.label}
    </StatusPill>
  );
}
