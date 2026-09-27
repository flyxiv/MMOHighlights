import { cn } from "@/lib/utils";
import type { Platform } from "@/lib/types";

export const PLATFORMS: Record<Platform, { label: string; bg: string; ring: string }> = {
  twitch: { label: "Twitch", bg: "bg-twitch", ring: "ring-twitch" },
  youtube: { label: "YouTube", bg: "bg-youtube", ring: "ring-youtube" },
  chzzk: { label: "Chzzk", bg: "bg-chzzk", ring: "ring-chzzk" },
};

export function PlatformLabel({ platform, className }: { platform: Platform; className?: string }) {
  const meta = PLATFORMS[platform];
  return (
    <span className={cn("inline-flex items-center gap-2 text-sm whitespace-nowrap", className)}>
      <span aria-hidden className={cn("size-2 shrink-0 rounded-[2px]", meta.bg)} />
      {meta.label}
    </span>
  );
}
