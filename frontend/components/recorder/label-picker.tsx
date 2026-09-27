"use client";

import { useState } from "react";
import { CheckIcon, PlusIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { errorMessage } from "@/lib/api";
import { useCreateTier, useGames, useUpdateLabels } from "@/lib/queries";
import type { GameOut, GameRef, RecordingLabels, TierOut } from "@/lib/types";
import { cn } from "@/lib/utils";
import { gameDotClass } from "./game-colors";

/** Popover + Command for choosing a recording's game and tier. `children` is the trigger. */
export function LabelPicker({
  recordingId,
  game,
  tier,
  children,
  align = "start",
}: {
  recordingId: string;
  game: GameRef | null;
  tier: TierOut | null;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const games = useGames();
  const update = useUpdateLabels();
  const createTier = useCreateTier();

  // Optimistic local selection so the checkmarks move immediately.
  const [pending, setPending] = useState<RecordingLabels | null>(null);
  const gameId = pending ? pending.game_id : (game?.id ?? null);
  const tierId = pending ? pending.tier_id : (tier?.id ?? null);

  const allGames: GameOut[] = games.data ?? [];
  const selectedGame = allGames.find((g) => g.id === gameId) ?? null;
  const tierGroups = selectedGame ? [selectedGame] : allGames;

  const apply = (labels: RecordingLabels, close: boolean) => {
    setPending(labels);
    update.mutate(
      { id: recordingId, labels },
      {
        onError: (err) => {
          setPending(null);
          toast.error("Couldn't update labels", { description: errorMessage(err) });
        },
        onSettled: () => setPending(null),
      },
    );
    if (close) setOpen(false);
  };

  const onSelectGame = (g: GameOut) => {
    if (g.id === gameId) {
      apply({ game_id: null, tier_id: null }, false);
      return;
    }
    const keepTier = g.tiers.some((t) => t.id === tierId) ? tierId : null;
    apply({ game_id: g.id, tier_id: keepTier }, false);
    setSearch("");
  };

  const onSelectTier = (t: TierOut) => {
    if (t.id === tierId) apply({ game_id: t.game_id, tier_id: null }, false);
    else apply({ game_id: t.game_id, tier_id: t.id }, true);
  };

  const trimmed = search.trim();
  const canCreate =
    !!selectedGame &&
    trimmed.length > 0 &&
    !selectedGame.tiers.some((t) => t.name.toLowerCase() === trimmed.toLowerCase());

  const onCreate = () => {
    if (!selectedGame) return;
    createTier.mutate(
      { gameId: selectedGame.id, name: trimmed },
      {
        onSuccess: (t) => {
          toast.success(`Created tier “${t.name}”`);
          apply({ game_id: selectedGame.id, tier_id: t.id }, true);
          setSearch("");
        },
        onError: (err) => toast.error("Couldn't create tier", { description: errorMessage(err) }),
      },
    );
  };

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSearch("");
      }}
    >
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        align={align}
        className="w-72 p-0"
        onClick={(e) => e.stopPropagation()}
      >
        <Command>
          <CommandInput
            placeholder={selectedGame ? `Search or create a ${selectedGame.name} tier…` : "Search games and tiers…"}
            value={search}
            onValueChange={setSearch}
          />
          <CommandList className="max-h-80">
            <CommandEmpty>{games.isLoading ? "Loading…" : "No matches."}</CommandEmpty>
            <CommandGroup heading="Game">
              {allGames.map((g) => (
                <CommandItem key={g.id} value={`game ${g.name}`} onSelect={() => onSelectGame(g)}>
                  <span aria-hidden className={cn("size-2 rounded-full", gameDotClass(g.name))} />
                  <span className="flex-1">{g.name}</span>
                  <CheckIcon className={cn("size-4", g.id === gameId ? "opacity-100" : "opacity-0")} />
                </CommandItem>
              ))}
            </CommandGroup>
            {tierGroups.map((g) => {
              const tiers = g.tiers.filter((t) => !t.archived || t.id === tierId);
              if (tiers.length === 0) return null;
              return (
                <CommandGroup key={g.id} heading={`Tier · ${g.name}`}>
                  {tiers.map((t) => (
                    <CommandItem
                      key={t.id}
                      value={`tier ${g.name} ${t.name}`}
                      onSelect={() => onSelectTier(t)}
                    >
                      <span className="flex-1 truncate">
                        {t.name}
                        {t.archived ? <span className="text-muted-foreground"> · archived</span> : null}
                      </span>
                      <CheckIcon className={cn("size-4", t.id === tierId ? "opacity-100" : "opacity-0")} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              );
            })}
            <CommandSeparator alwaysRender />
            <CommandGroup forceMount>
              {canCreate ? (
                <CommandItem
                  forceMount
                  value={`__create ${trimmed}`}
                  onSelect={onCreate}
                  disabled={createTier.isPending}
                >
                  <PlusIcon className="size-4" />
                  <span className="truncate">Create tier “{trimmed}”</span>
                </CommandItem>
              ) : null}
              {gameId !== null || tierId !== null ? (
                <CommandItem
                  forceMount
                  value="__clear"
                  onSelect={() => apply({ game_id: null, tier_id: null }, true)}
                >
                  <XIcon className="size-4" />
                  Clear labels
                </CommandItem>
              ) : null}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
