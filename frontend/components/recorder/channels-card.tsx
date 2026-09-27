"use client";

import { useState } from "react";
import { CopyIcon, ExternalLinkIcon, MoreHorizontalIcon, PlusIcon, RadioTowerIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { ACTIVE_RECORDINGS_QUERY, useAddChannel, useChannels, useRecordings } from "@/lib/queries";
import type { ChannelOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { ChannelAvatar } from "./channel-avatar";
import { LabelChips } from "./label-chips";
import { PlatformLabel } from "./platform";
import { RemoveChannelDialog } from "./remove-channel-dialog";
import { copyText, EmptyState, ErrorState, isRowActivation, SectionHeader, SkeletonRows } from "./shared";
import { ChannelStatusBadge } from "./status-badge";

function displayUrl(url: string): string {
  return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

function AddChannelForm() {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useAddChannel();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const value = url.trim();
    if (!value) {
      setError("Paste a channel URL first.");
      return;
    }
    add.mutate(value, {
      onSuccess: (channel) => {
        setUrl("");
        setError(null);
        toast.success(`Tracking ${channel.display_name}`, {
          description: "Recording starts automatically when the channel goes live.",
        });
      },
      onError: (err) => setError(errorMessage(err)),
    });
  };

  return (
    <form onSubmit={submit} className="flex w-full flex-col gap-1.5 lg:w-auto" noValidate>
      <div className="flex w-full gap-2">
        <Input
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            if (error) setError(null);
          }}
          placeholder="Paste a Twitch, YouTube or Chzzk channel URL"
          aria-label="Channel URL"
          aria-invalid={!!error}
          aria-describedby={error ? "add-channel-error" : undefined}
          className="min-w-0 flex-1 lg:w-80"
          disabled={add.isPending}
        />
        <Button type="submit" disabled={add.isPending}>
          <PlusIcon />
          {add.isPending ? "Adding…" : "Add channel"}
        </Button>
      </div>
      {error ? (
        <p id="add-channel-error" role="alert" className="text-xs text-destructive lg:max-w-[28rem]">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function StreamCell({ channel }: { channel: ChannelOut }) {
  const failing = channel.check_failures >= 3;
  const live = channel.status === "live";
  const title = channel.last_recording_title ?? (live ? channel.live_title : null);

  let text: React.ReactNode;
  if (failing && channel.last_error) {
    text = <span className="text-muted-foreground">{channel.last_error}</span>;
  } else if (title) {
    text = live ? title : <span className="text-muted-foreground">Last: {title}</span>;
  } else {
    text = <span className="text-muted-foreground">—</span>;
  }

  return (
    <div className="min-w-56 max-w-80">
      <p className="truncate">{text}</p>
      <LabelChips
        recordingId={channel.active_recording_id}
        game={channel.last_recording_game}
        tier={channel.last_recording_tier}
      />
    </div>
  );
}

export function ChannelsCard({ onOpenRecording }: { onOpenRecording: (id: string) => void }) {
  const channels = useChannels();
  const active = useRecordings(ACTIVE_RECORDINGS_QUERY);
  const now = useNow();
  const [removing, setRemoving] = useState<ChannelOut | null>(null);

  const removingStartedAt =
    removing?.active_recording_id
      ? (active.data?.items.find((r) => r.id === removing.active_recording_id)?.started_at ?? null)
      : null;

  const rows = channels.data ?? [];

  return (
    <Card className="gap-4 shadow-none">
      <SectionHeader
        title="Tracked channels"
        description="Recording starts automatically when a channel goes live. Paste a channel URL to add it."
        actions={<AddChannelForm />}
      />
      <div className="px-2 sm:px-4">
        {channels.isError && !channels.data ? (
          <ErrorState message={errorMessage(channels.error)} onRetry={() => void channels.refetch()} />
        ) : !channels.isLoading && rows.length === 0 ? (
          <EmptyState
            icon={<RadioTowerIcon />}
            title="No channels tracked yet"
            description="Paste a Twitch, YouTube or Chzzk channel URL above. You can track up to 10 channels."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="min-w-56">Channel</TableHead>
                <TableHead>Platform</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Current or last stream</TableHead>
                <TableHead>Last checked</TableHead>
                <TableHead className="w-10">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channels.isLoading ? (
                <SkeletonRows columns={6} rows={4} />
              ) : (
                rows.map((c) => (
                  <TableRow
                    key={c.id}
                    className={cn(c.active_recording_id && "cursor-pointer")}
                    onClick={(e) => {
                      if (c.active_recording_id && isRowActivation(e)) onOpenRecording(c.active_recording_id);
                    }}
                  >
                    <TableCell className="py-3">
                      <div className="flex items-center gap-3">
                        <ChannelAvatar name={c.display_name} platform={c.platform} thumbnailUrl={c.thumbnail_url} />
                        <div className="min-w-0">
                          <p className="truncate font-medium">{c.display_name}</p>
                          <p className="max-w-52 truncate font-mono text-xs text-muted-foreground">
                            {displayUrl(c.url)}
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <PlatformLabel platform={c.platform} />
                    </TableCell>
                    <TableCell>
                      <ChannelStatusBadge channel={c} />
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <StreamCell channel={c} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground tabular-nums">
                      {c.last_checked_at && now ? formatRelative(c.last_checked_at, now) : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${c.display_name}`}>
                            <MoreHorizontalIcon />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem asChild>
                            <a href={c.url} target="_blank" rel="noreferrer">
                              <ExternalLinkIcon />
                              Open channel
                            </a>
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => void copyText(c.url, "Channel URL")}>
                            <CopyIcon />
                            Copy URL
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem variant="destructive" onSelect={() => setRemoving(c)}>
                            <Trash2Icon />
                            Remove
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
      <RemoveChannelDialog
        channel={removing}
        recordingStartedAt={removingStartedAt}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
      />
    </Card>
  );
}
