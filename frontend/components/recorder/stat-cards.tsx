"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatBytes, formatNumber } from "@/lib/format";
import { useChannels, useHealth } from "@/lib/queries";
import type { Platform } from "@/lib/types";
import { useNow } from "@/lib/use-now";
import { PLATFORMS } from "./platform";

function StatCard({
  label,
  value,
  hint,
  dot,
}: {
  label: string;
  value: React.ReactNode;
  hint: React.ReactNode;
  dot?: boolean;
}) {
  return (
    <Card className="gap-2 px-5 py-4 shadow-none">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {dot ? <span aria-hidden className="size-1.5 rounded-full bg-live" /> : null}
        {label}
      </p>
      <div className="text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      <p className="truncate text-xs text-muted-foreground tabular-nums">{hint}</p>
    </Card>
  );
}

export function StatCards() {
  const health = useHealth();
  const channels = useChannels();
  const now = useNow();
  const h = health.data;

  const counts = (channels.data ?? []).reduce<Record<Platform, number>>(
    (acc, c) => ({ ...acc, [c.platform]: acc[c.platform] + 1 }),
    { twitch: 0, youtube: 0, chzzk: 0 },
  );
  const breakdown = (Object.keys(PLATFORMS) as Platform[])
    .filter((p) => counts[p] > 0)
    .map((p) => `${counts[p]} ${PLATFORMS[p].label}`)
    .join(" · ");

  // next_poll_in_s is relative to when the health snapshot arrived; count it down locally.
  let nextCheck: string = "–";
  if (h?.next_poll_in_s != null && now) {
    const remaining = Math.max(0, Math.round(h.next_poll_in_s - (now - health.dataUpdatedAt) / 1000));
    nextCheck = remaining === 0 ? "Checking now…" : `Next check in ${remaining} s`;
  }

  const loading = <Skeleton className="h-8 w-16" />;

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
      <StatCard
        label="Tracked channels"
        value={h ? `${h.tracked_count} / ${h.max_channels}` : loading}
        hint={breakdown || "No channels yet"}
      />
      <StatCard label="Live now" dot value={h ? h.live_count : loading} hint={nextCheck} />
      <StatCard
        label="Recording"
        value={h ? h.recording_count : loading}
        hint={h ? `${formatBytes(h.bytes_active)} captured so far` : "–"}
      />
      <StatCard
        label="Chat captured"
        value={h ? formatNumber(h.chat_messages_active) : loading}
        hint="messages across active recordings"
      />
    </div>
  );
}
