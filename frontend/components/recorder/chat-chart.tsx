"use client";

import { useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { formatMinuteOffset, formatNumber } from "@/lib/format";
import type { ChatMinuteOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const chartConfig = {
  messages: { label: "Messages", color: "var(--muted-foreground)" },
} satisfies ChartConfig;

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Top `n` peaks: the highest minute of each run of consecutive above-threshold minutes. */
function findPeaks(minutes: ChatMinuteOut[], threshold: number, n: number): ChatMinuteOut[] {
  const clusters: ChatMinuteOut[] = [];
  let best: ChatMinuteOut | null = null;
  let prevMinute = -Infinity;
  for (const m of minutes) {
    if (threshold > 0 && m.messages >= threshold) {
      if (best && m.minute - prevMinute <= 2) {
        if (m.messages > best.messages) best = m;
      } else {
        if (best) clusters.push(best);
        best = m;
      }
      prevMinute = m.minute;
    }
  }
  if (best) clusters.push(best);
  return clusters
    .sort((a, b) => b.messages - a.messages)
    .slice(0, n)
    .sort((a, b) => a.minute - b.minute);
}

export function ChatChart({ minutes }: { minutes: ChatMinuteOut[] }) {
  const [focus, setFocus] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { data, threshold, peaks } = useMemo(() => {
    const sorted = [...minutes].sort((a, b) => a.minute - b.minute);
    const med = median(sorted.map((m) => m.messages));
    const threshold = med * 2;
    return {
      data: sorted.map((m) => ({ ...m, peak: threshold > 0 && m.messages >= threshold })),
      threshold,
      peaks: findPeaks(sorted, threshold, 3),
    };
  }, [minutes]);

  if (data.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
        No chat captured yet.
      </p>
    );
  }

  const jump = (minute: number) => {
    setFocus(minute);
    containerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <div className="space-y-3">
      <div ref={containerRef} className="rounded-lg border p-3 pt-4">
        <ChartContainer config={chartConfig} className="aspect-auto h-40 w-full">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={1}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis
              dataKey="minute"
              tickLine={false}
              axisLine={false}
              tickMargin={6}
              minTickGap={32}
              tickFormatter={(m: number) => formatMinuteOffset(m)}
            />
            <YAxis
              width={36}
              tickLine={false}
              axisLine={false}
              tickMargin={4}
              tickCount={3}
              tickFormatter={(v: number) => (v >= 1000 ? `${Math.round(v / 100) / 10}k` : String(v))}
            />
            <ChartTooltip
              cursor={{ fillOpacity: 0.5 }}
              content={
                <ChartTooltipContent
                  hideIndicator
                  labelFormatter={(_, payload) => {
                    const minute = (payload?.[0]?.payload as { minute?: number } | undefined)?.minute;
                    return minute === undefined ? "" : `At ${formatMinuteOffset(minute)}`;
                  }}
                  formatter={(value) => (
                    <span className="font-mono text-foreground tabular-nums">
                      {formatNumber(Number(value))} messages
                    </span>
                  )}
                />
              }
            />
            <Bar dataKey="messages" radius={[3, 3, 0, 0]} isAnimationActive={false} onClick={(d) => setFocus((d.payload as { minute: number }).minute)}>
              {data.map((d) => (
                <Cell
                  key={d.minute}
                  fill={d.peak ? "var(--live)" : "var(--color-messages)"}
                  fillOpacity={
                    focus === null ? (d.peak ? 1 : 0.35) : d.minute === focus ? 1 : d.peak ? 0.45 : 0.2
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ChartContainer>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="size-2 rounded-[2px] bg-muted-foreground/35" />
            Messages / min
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="size-2 rounded-[2px] bg-live" />
            Peak ≥ 2× median{threshold > 0 ? ` (${formatNumber(Math.ceil(threshold))})` : ""}
          </span>
        </div>
        {peaks.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {peaks.map((p) => (
              <Button
                key={p.minute}
                variant="outline"
                size="xs"
                className={cn("font-mono tabular-nums", focus === p.minute && "border-live text-live")}
                onClick={() => jump(p.minute)}
                title={`${formatNumber(p.messages)} messages`}
              >
                Jump to {formatMinuteOffset(p.minute)}
              </Button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
