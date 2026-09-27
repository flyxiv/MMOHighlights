import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { initials } from "@/lib/format";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PLATFORMS } from "./platform";

export function ChannelAvatar({
  name,
  platform,
  thumbnailUrl,
  size = "default",
  className,
}: {
  name: string;
  platform: Platform;
  thumbnailUrl: string | null;
  size?: "sm" | "default" | "lg";
  className?: string;
}) {
  return (
    <Avatar
      size={size}
      className={cn(
        "ring-2 ring-offset-2 ring-offset-background overflow-visible",
        PLATFORMS[platform].ring,
        size === "default" && "size-7",
        className,
      )}
      title={`${PLATFORMS[platform].label} · ${name}`}
    >
      {thumbnailUrl ? (
        <AvatarImage src={thumbnailUrl} alt="" className="rounded-full object-cover" />
      ) : null}
      <AvatarFallback className="bg-background text-[11px] font-medium text-foreground">
        {initials(name)}
      </AvatarFallback>
    </Avatar>
  );
}
