"use client";

import { useState } from "react";
import { ArchiveIcon, CopyIcon, ExternalLinkIcon, MoreHorizontalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { errorMessage } from "@/lib/api";
import {
  daysSince,
  formatBytes,
  formatDate,
  formatDateTime,
  formatDuration,
  formatInDays,
  formatNumber,
} from "@/lib/format";
import { useGames, useRecordings } from "@/lib/queries";
import type { RecordingOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { ChannelAvatar } from "./channel-avatar";
import { LabelChips } from "./label-chips";
import { copyText, EmptyState, ErrorState, isRowActivation, SectionHeader, SkeletonRows } from "./shared";
import { RecordingStatusBadge } from "./status-badge";

export const BUCKET_CONSOLE_URL = "https://console.cloud.google.com/storage/browser/mmohighlights/archives";
const PAGE_SIZE = 20;
const NEARLINE_AFTER_DAYS = 30;

function DeletesCell({ recording, now }: { recording: RecordingOut; now: number }) {
  if (recording.purged_at) {
    return <span className="text-muted-foreground">Deleted {formatDate(recording.purged_at)}</span>;
  }
  if (!now) return null;
  const age = daysSince(recording.ended_at ?? recording.started_at, now);
  return (
    <span className="text-muted-foreground">
      {formatInDays(recording.delete_at, now)}
      {age > NEARLINE_AFTER_DAYS ? " · Nearline" : ""}
    </span>
  );
}

export function CompletedCard({ onOpenRecording }: { onOpenRecording: (id: string) => void }) {
  const games = useGames();
  const now = useNow();
  const [gameId, setGameId] = useState<number | null>(null);
  const [tierId, setTierId] = useState<number | null>(null);
  const [page, setPage] = useState(1);

  const recordings = useRecordings({
    status: "completed",
    game_id: gameId,
    tier_id: tierId,
    page,
    page_size: PAGE_SIZE,
  });

  const allGames = games.data ?? [];
  const tierGroups = gameId === null ? allGames : allGames.filter((g) => g.id === gameId);
  const data = recordings.data;
  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / (data?.page_size ?? PAGE_SIZE)));
  const filtered = gameId !== null || tierId !== null;

  const filters = (
    <>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={gameId === null ? "all" : String(gameId)}
        onValueChange={(v) => {
          if (!v) return; // keep one option selected
          setGameId(v === "all" ? null : Number(v));
          setTierId(null);
          setPage(1);
        }}
        aria-label="Filter by game"
      >
        <ToggleGroupItem value="all" className="px-3">
          All games
        </ToggleGroupItem>
        {allGames.map((g) => (
          <ToggleGroupItem key={g.id} value={String(g.id)} className="px-3">
            {g.name}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <Select
        value={tierId === null ? "all" : String(tierId)}
        onValueChange={(v) => {
          setTierId(v === "all" ? null : Number(v));
          setPage(1);
        }}
      >
        <SelectTrigger size="sm" className="w-52" aria-label="Filter by tier">
          <span className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-left">
            <span className="text-muted-foreground">Tier:</span>
            <SelectValue />
          </span>
        </SelectTrigger>
        <SelectContent position="popper" align="end">
          <SelectItem value="all">All tiers</SelectItem>
          {tierGroups.map((g) =>
            g.tiers.length ? (
              <SelectGroup key={g.id}>
                <SelectLabel>{g.name}</SelectLabel>
                {g.tiers.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                    {t.archived ? " (archived)" : ""}
                  </SelectItem>
                ))}
              </SelectGroup>
            ) : null,
          )}
        </SelectContent>
      </Select>
      <Button variant="outline" size="sm" asChild>
        <a href={BUCKET_CONSOLE_URL} target="_blank" rel="noreferrer">
          <ExternalLinkIcon />
          Open bucket
        </a>
      </Button>
    </>
  );

  return (
    <Card className="gap-4 shadow-none">
      <SectionHeader
        title="Completed recordings"
        description="Kept for 90 days. Files move to Nearline storage after 30 days."
        actions={filters}
      />
      <div className="px-2 sm:px-4">
        {recordings.isError && !data ? (
          <ErrorState message={errorMessage(recordings.error)} onRetry={() => void recordings.refetch()} />
        ) : !recordings.isLoading && rows.length === 0 ? (
          <EmptyState
            icon={<ArchiveIcon />}
            title={filtered ? "No recordings match these labels" : "No completed recordings yet"}
            description={
              filtered
                ? "Try another game or tier, or label recordings from the table above."
                : "Finished recordings show up here once their last segment is uploaded."
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="min-w-40">Channel</TableHead>
                <TableHead>Stream title</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead className="text-right">Chat msgs</TableHead>
                <TableHead>Deletes</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recordings.isLoading ? (
                <SkeletonRows columns={9} rows={4} />
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
                      <div className="min-w-48 max-w-72">
                        <p className="truncate">{r.title}</p>
                        <LabelChips recordingId={r.id} game={r.game} tier={r.tier} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <RecordingStatusBadge recording={r} />
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                      {formatDateTime(r.started_at)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatDuration(r.duration_s)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {r.purged_at ? "–" : formatBytes(r.bytes_recorded)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{formatNumber(r.chat_messages)}</TableCell>
                    <TableCell className="text-xs whitespace-nowrap">
                      <DeletesCell recording={r} now={now} />
                    </TableCell>
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label="Recording actions">
                            <MoreHorizontalIcon />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem asChild disabled={!!r.purged_at}>
                            <a href={r.gcs_console_url} target="_blank" rel="noreferrer">
                              <ExternalLinkIcon />
                              Open in Cloud Storage
                            </a>
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => void copyText(r.gcs_uri, "gs:// path")}>
                            <CopyIcon />
                            Copy gs:// path
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}
      </div>
      {data && total > 0 ? (
        <div className="flex items-center justify-between gap-4 px-4 pt-1 sm:px-6">
          <p className="text-xs text-muted-foreground tabular-nums">
            Showing {rows.length} of {total} recording{total === 1 ? "" : "s"}
            {lastPage > 1 ? ` · page ${page} of ${lastPage}` : ""}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= lastPage || recordings.isPlaceholderData}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      ) : null}
    </Card>
  );
}
