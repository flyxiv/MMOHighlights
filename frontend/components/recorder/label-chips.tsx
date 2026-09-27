"use client";

import { PlusIcon } from "lucide-react";
import type { GameRef, TierOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { gameDotClass } from "./game-colors";
import { LabelPicker } from "./label-picker";

const chip =
  "inline-flex h-5 max-w-full items-center gap-1.5 rounded-[5px] border px-1.5 text-xs leading-none whitespace-nowrap";

export function GameChip({ game }: { game: GameRef }) {
  return (
    <span className={chip}>
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", gameDotClass(game.name))} />
      {game.name}
    </span>
  );
}

export function TierChip({ tier }: { tier: TierOut }) {
  return (
    <span className={cn(chip, "truncate")} title={tier.archived ? `${tier.name} (archived)` : tier.name}>
      <span className="truncate">{tier.name}</span>
    </span>
  );
}

/**
 * Game + tier chips. When `recordingId` is given and a label is missing, a dashed
 * "+ Label" chip opens the label picker.
 */
export function LabelChips({
  recordingId,
  game,
  tier,
  className,
}: {
  recordingId: string | null;
  game: GameRef | null;
  tier: TierOut | null;
  className?: string;
}) {
  const missing = !game || !tier;
  if (!game && !tier && !recordingId) return null;
  return (
    <div className={cn("mt-1 flex flex-wrap items-center gap-1", className)}>
      {game ? <GameChip game={game} /> : null}
      {tier ? <TierChip tier={tier} /> : null}
      {missing && recordingId ? (
        <LabelPicker recordingId={recordingId} game={game} tier={tier}>
          <button
            type="button"
            onClick={(e) => e.stopPropagation()}
            className={cn(
              chip,
              "border-dashed text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none",
            )}
          >
            <PlusIcon className="size-3" />
            Label
          </button>
        </LabelPicker>
      ) : null}
    </div>
  );
}
