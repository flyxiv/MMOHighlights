"use client";

import { useMemo, useState } from "react";
import { CopyIcon, ExternalLinkIcon, MessageSquareTextIcon, PencilIcon, SquareIcon, VideoIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import {
  formatBytes,
  formatChatOffset,
  formatDateTime,
  formatDuration,
  formatNumber,
  recordingElapsed,
} from "@/lib/format";
import { useRecording } from "@/lib/queries";
import { isActiveRecording, type RecordingDetailOut, type SegmentOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { ChannelAvatar } from "./channel-avatar";
import { ChatChart } from "./chat-chart";
import { GameChip, TierChip } from "./label-chips";
import { LabelPicker } from "./label-picker";
import { copyText } from "./shared";
import { RecordingStatusBadge, SegmentStatusBadge } from "./status-badge";
import { StopRecordingDialog } from "./stop-recording-dialog";

const SEGMENTS_PREVIEW = 4;

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate text-sm tabular-nums">{children}</dd>
    </div>
  );
}

function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{children}</h3>
      {aside}
    </div>
  );
}

interface SegmentRow {
  seq: number;
  start_s: number | null;
  end_s: number | null;
  video?: SegmentOut;
  chat?: SegmentOut;
}

function SegmentsList({ segments }: { segments: SegmentOut[] }) {
  const [showAll, setShowAll] = useState(false);
  const rows = useMemo(() => {
    const map = new Map<number, SegmentRow>();
    for (const s of segments) {
      const row = map.get(s.seq) ?? { seq: s.seq, start_s: s.start_s, end_s: s.end_s };
      row[s.kind] = s;
      if (s.kind === "video") {
        row.start_s = s.start_s;
        row.end_s = s.end_s;
      }
      map.set(s.seq, row);
    }
    return [...map.values()].sort((a, b) => b.seq - a.seq);
  }, [segments]);

  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No segments yet.</p>;
  }
  const visible = showAll ? rows : rows.slice(0, SEGMENTS_PREVIEW);

  return (
    <div className="space-y-2">
      <ul className="divide-y rounded-lg border">
        {visible.map((row) => (
          <li key={row.seq} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5 text-sm">
            <div className="w-28 shrink-0">
              <p className="font-mono text-xs tabular-nums">#{String(row.seq).padStart(3, "0")}</p>
              <p className="font-mono text-xs text-muted-foreground tabular-nums">
                {row.start_s != null ? formatDuration(row.start_s) : "–"}
                {row.end_s != null ? `–${formatDuration(row.end_s)}` : " →"}
              </p>
            </div>
            <div className="flex flex-1 flex-wrap items-center gap-x-4 gap-y-1.5">
              {(["video", "chat"] as const).map((kind) => {
                const seg = row[kind];
                const Icon = kind === "video" ? VideoIcon : MessageSquareTextIcon;
                return (
                  <span key={kind} className="inline-flex items-center gap-2">
                    <Icon className="size-3.5 text-muted-foreground" aria-label={kind} />
                    {seg ? (
                      <>
                        <SegmentStatusBadge status={seg.status} closed={seg.end_s !== null} />
                        {kind === "video" && seg.size_bytes > 0 ? (
                          <span className="font-mono text-xs text-muted-foreground tabular-nums">
                            {formatBytes(seg.size_bytes)}
                          </span>
                        ) : null}
                        {seg.status === "failed" || seg.attempts > 1 ? (
                          <span className="text-xs text-muted-foreground">
                            {seg.attempts} attempt{seg.attempts === 1 ? "" : "s"}
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
      {rows.length > SEGMENTS_PREVIEW ? (
        <Button variant="ghost" size="sm" className="w-full" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show fewer" : `Show all ${rows.length} segments`}
        </Button>
      ) : null}
    </div>
  );
}

function SheetBody({ rec, onStop }: { rec: RecordingDetailOut; onStop: () => void }) {
  const now = useNow();
  const active = isActiveRecording(rec.status);
  const segmentCount = new Set(rec.segments.filter((s) => s.kind === "video").map((s) => s.seq)).size;

  return (
    <>
      <SheetHeader className="gap-3 border-b px-6 pt-6 pb-5">
        <div className="flex flex-wrap items-center gap-2 pr-8">
          <ChannelAvatar name={rec.channel.display_name} platform={rec.channel.platform} thumbnailUrl={rec.channel.thumbnail_url} size="sm" />
          <span className="text-sm font-medium">{rec.channel.display_name}</span>
          <RecordingStatusBadge recording={rec} />
        </div>
        <SheetTitle className="text-2xl leading-tight font-semibold tracking-tight">{rec.title}</SheetTitle>
        <SheetDescription className="sr-only">Recording details, chat activity and segments.</SheetDescription>
        <div className="flex flex-wrap items-center gap-1.5">
          {rec.game ? <GameChip game={rec.game} /> : null}
          {rec.tier ? <TierChip tier={rec.tier} /> : null}
          {!rec.game && !rec.tier ? <span className="text-xs text-muted-foreground">No labels</span> : null}
          <LabelPicker recordingId={rec.id} game={rec.game} tier={rec.tier}>
            <Button variant="ghost" size="xs" className="text-muted-foreground">
              <PencilIcon />
              Edit labels
            </Button>
          </LabelPicker>
        </div>
      </SheetHeader>

      <div className="flex-1 space-y-7 overflow-y-auto px-6 py-5">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4">
          <Detail label="Started">{formatDateTime(rec.started_at)}</Detail>
          <Detail label="Quality">{rec.quality ?? "—"}</Detail>
          <Detail label="Size · segments">
            <span>{rec.purged_at ? "–" : formatBytes(rec.bytes_recorded)}</span>
            <span className="text-muted-foreground"> · {segmentCount || rec.segments_closed} segments</span>
          </Detail>
          <Detail label="Chat messages">
            {formatNumber(rec.chat_messages)}
          </Detail>
          <Detail label="Chat offset">
            {formatChatOffset(rec.chat_offset_s)}
          </Detail>
          <Detail label="Stream ID">
            <span className="font-mono">{rec.platform_stream_id ?? "—"}</span>
          </Detail>
          <Detail label="Duration">
            <span className="font-mono">{formatDuration(recordingElapsed(rec, now))}</span>
          </Detail>
          <Detail label="Uploaded">
            <span className="font-mono">
              {rec.segments_uploaded} / {rec.segments_closed}
            </span>
          </Detail>
        </dl>

        {rec.last_error ? (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            {rec.last_error}
          </p>
        ) : null}

        <div className="flex items-center gap-2 rounded-lg border bg-muted/50 py-1.5 pr-1.5 pl-3">
          <code className="min-w-0 flex-1 truncate font-mono text-xs" title={rec.gcs_uri}>
            {rec.gcs_uri}
          </code>
          <Button variant="outline" size="xs" onClick={() => void copyText(rec.gcs_uri, "gs:// path")}>
            <CopyIcon />
            Copy
          </Button>
        </div>

        <section className="space-y-3">
          <SectionTitle
            aside={<span className="text-xs text-muted-foreground">messages per minute</span>}
          >
            Chat activity
          </SectionTitle>
          <ChatChart minutes={rec.chat_minutes} />
        </section>

        <Separator />

        <section className="space-y-3">
          <SectionTitle aside={<span className="text-xs text-muted-foreground">newest first · 5 min each</span>}>
            Segments
          </SectionTitle>
          <SegmentsList segments={rec.segments} />
        </section>
      </div>

      <SheetFooter className="flex-row justify-end gap-2 border-t px-6 py-4">
        <Button variant="outline" asChild>
          <a href={rec.gcs_console_url} target="_blank" rel="noreferrer">
            <ExternalLinkIcon />
            Open in Cloud Storage
          </a>
        </Button>
        {active ? (
          <Button variant="destructive" onClick={onStop} disabled={rec.status === "finalizing"}>
            <SquareIcon />
            Stop recording
          </Button>
        ) : null}
      </SheetFooter>
    </>
  );
}

export function RecordingSheet({
  recordingId,
  open,
  onOpenChange,
}: {
  /** Kept after closing so the content stays put during the exit animation. */
  recordingId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const detail = useRecording(recordingId);
  const [stopping, setStopping] = useState(false);
  const rec = detail.data;

  return (
    <Sheet open={open && !!recordingId} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[560px]">
        {rec ? (
          <SheetBody rec={rec} onStop={() => setStopping(true)} />
        ) : detail.isError ? (
          <div className="space-y-2 p-6">
            <SheetTitle>Couldn&apos;t load this recording</SheetTitle>
            <SheetDescription>{errorMessage(detail.error)}</SheetDescription>
          </div>
        ) : (
          <div className="space-y-4 p-6">
            <SheetTitle className="sr-only">Loading recording</SheetTitle>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-4 w-32" />
            <div className="grid grid-cols-2 gap-4 pt-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </SheetContent>
      <StopRecordingDialog
        recording={stopping && rec ? rec : null}
        onOpenChange={(open) => {
          if (!open) setStopping(false);
        }}
      />
    </Sheet>
  );
}
