"use client";

import { useState } from "react";
import { CircleDotIcon, SquareIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api";
import { formatBytes, formatDuration, formatNumber, recordingElapsed } from "@/lib/format";
import { ACTIVE_RECORDINGS_QUERY, useRecordings } from "@/lib/queries";
import type { RecordingOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { ChannelAvatar } from "./channel-avatar";
import { LabelChips } from "./label-chips";
import { EmptyState, ErrorState, isRowActivation, SectionHeader, SkeletonRows } from "./shared";
import { RecordingStatusBadge } from "./status-badge";
import { StopRecordingDialog } from "./stop-recording-dialog";

export function UploadProgress({ recording }: { recording: RecordingOut }) {
  const { segments_uploaded: up, segments_closed: closed } = recording;
  const pct = closed === 0 ? 0 : Math.min(100, (up / closed) * 100);
  return (
    <div className="flex min-w-36 items-center gap-3">
      <Progress value={pct} className="h-1.5 w-20" aria-label={`${up} of ${closed} segments uploaded`} />
      <span className="font-mono text-xs text-muted-foreground tabular-nums whitespace-nowrap">
        {up} / {closed}
      </span>
    </div>
  );
}

export function RecordingsCard({ onOpenRecording }: { onOpenRecording: (id: string) => void }) {
  const active = useRecordings(ACTIVE_RECORDINGS_QUERY);
  const now = useNow();
  const [stopping, setStopping] = useState<RecordingOut | null>(null);
  const rows = active.data?.items ?? [];

  return (
    <Card className="gap-4 shadow-none">
      <SectionHeader
        title="Recordings in progress"
        description="Video and chat upload to gs://mmohighlights/archives in 5-minute segments."
      />
      <div className="px-2 sm:px-4">
        {active.isError && !active.data ? (
          <ErrorState message={errorMessage(active.error)} onRetry={() => void active.refetch()} />
        ) : !active.isLoading && rows.length === 0 ? (
          <EmptyState
            icon={<CircleDotIcon />}
            title="Nothing is recording"
            description="Recording starts on its own when a tracked channel goes live."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="min-w-44">Channel</TableHead>
                <TableHead>Stream title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Chat msgs</TableHead>
                <TableHead>Uploaded</TableHead>
                <TableHead className="w-20">
                  <span className="sr-only">Stop</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {active.isLoading ? (
                <SkeletonRows columns={8} rows={3} />
              ) : (
                rows.map((r) => (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer"
                    onClick={(e) => {
                      if (isRowActivation(e)) onOpenRecording(r.id);
                    }}
                  >
                    <TableCell className="py-3">
                      <div className="flex items-center gap-3">
                        <ChannelAvatar
                          name={r.channel.display_name}
                          platform={r.channel.platform}
                          thumbnailUrl={r.channel.thumbnail_url}
                        />
                        <span className="truncate font-medium">{r.channel.display_name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="min-w-52 max-w-72">
                        <p className="truncate">{r.title}</p>
                        <LabelChips recordingId={r.id} game={r.game} tier={r.tier} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <RecordingStatusBadge recording={r} />
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {formatDuration(recordingElapsed(r, now))}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatBytes(r.bytes_recorded)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatNumber(r.chat_messages)}</TableCell>
                    <TableCell>
                      <UploadProgress recording={r} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={r.status === "finalizing"}
                        onClick={() => setStopping(r)}
                      >
                        <SquareIcon className="size-3.5" />
                        Stop
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>
      <StopRecordingDialog
        recording={stopping}
        onOpenChange={(open) => {
          if (!open) setStopping(null);
        }}
      />
    </Card>
  );
}
