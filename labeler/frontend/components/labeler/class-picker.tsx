"use client";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { classColor, colorOf, formatNumber } from "@/lib/format";
import type { Dataset } from "@/lib/types";

/** Opens next to a freshly drawn shape that has no class yet. */
export function ClassPicker({
  dataset,
  task,
  lastClass,
  onPick,
  onCancel,
  style,
}: {
  dataset: Dataset;
  task: string;
  lastClass: string | null;
  onPick: (cls: string) => void;
  onCancel: () => void;
  style?: React.CSSProperties;
}) {
  const classes = dataset.classes[task] ?? [];
  const counts = dataset.stats.class_counts[task] ?? {};
  const last = lastClass && classes.includes(lastClass) ? lastClass : null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    } else if (e.key === "Tab" && last) {
      e.preventDefault();
      onPick(last);
    } else if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey) {
      const c = classes[Number(e.key) - 1];
      if (c) {
        e.preventDefault();
        onPick(c);
      }
    }
  };

  const row = (c: string) => (
    <CommandItem key={c} value={c} onSelect={() => onPick(c)} className="gap-2">
      <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: colorOf(classColor(dataset, task, c)) }} />
      <span className="flex-1 truncate">{c}</span>
      <span className="font-mono text-xs text-muted-foreground tnum">{formatNumber(counts[c] ?? 0)}</span>
      {classes.indexOf(c) < 9 ? <Kbd>{classes.indexOf(c) + 1}</Kbd> : null}
    </CommandItem>
  );

  return (
    <div
      className="absolute z-20 w-68 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-lg"
      style={style}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <Command loop onKeyDown={onKeyDown}>
        <div className="relative">
          <CommandInput autoFocus placeholder={`${task}: search classes…`} />
          <Kbd className="absolute top-1/2 right-2 -translate-y-1/2">Esc</Kbd>
        </div>
        <CommandList className="max-h-72">
          <CommandEmpty>No class matches.</CommandEmpty>
          {last ? <CommandGroup heading="Last used">{row(last)}</CommandGroup> : null}
          <CommandGroup heading={last ? "All classes" : "Classes"}>
            {classes.filter((c) => c !== last).map(row)}
          </CommandGroup>
        </CommandList>
      </Command>
      <div className="flex items-center gap-1.5 border-t bg-muted px-3 py-2 text-xs text-muted-foreground">
        <Kbd className="bg-background">Enter</Kbd> apply
        {last ? (
          <>
            <span className="flex-1" />
            <Kbd className="bg-background">Tab</Kbd> reuse last
          </>
        ) : null}
      </div>
    </div>
  );
}
