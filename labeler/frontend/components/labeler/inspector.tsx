"use client";

import { useState } from "react";
import { CheckIcon, EyeIcon, EyeOffIcon, LockIcon, LockOpenIcon, PlusIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  acceptSuggestions,
  applyClass,
  deleteObject,
  setLabel,
  setSelectedBox,
  toggleLabel,
} from "@/lib/actions";
import { errorMessage } from "@/lib/api";
import { useEditor } from "@/lib/editor-store";
import { CHIP_LIMIT, formatNumber, GROUP_KEYS, labelColor } from "@/lib/format";
import { useUpdateProject } from "@/lib/queries";
import type { ImageRow, LabelClass, LabelGroup, LabelObject, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const NO_LABELS: Record<string, string> = {};
const NO_OBJECTS: LabelObject[] = [];

function SectionHeader({ title, meta, children }: { title: string; meta?: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-h-8 items-center gap-2">
      <h2 className="text-sm font-medium">{title}</h2>
      {meta ? <span className="truncate text-xs text-muted-foreground">{meta}</span> : null}
      <div className="flex-1" />
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ image class

function GroupField({ group, value, hotkeys }: { group: LabelGroup; value: string | undefined; hotkeys: boolean }) {
  if (group.options.length > CHIP_LIMIT) {
    return (
      <Select value={value ?? "__none"} onValueChange={(v) => setLabel(group.name, v === "__none" ? null : v)}>
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none">
            <span className="text-muted-foreground">Not set</span>
          </SelectItem>
          {group.options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {group.options.map((o, i) => {
        const on = value === o;
        return (
          <button
            key={o}
            onClick={() => toggleLabel(group.name, o)}
            aria-pressed={on}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-md border pr-1 pl-2 text-xs font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent",
              !hotkeys && "pr-2",
            )}
          >
            {on ? <CheckIcon className="size-3.5" /> : null}
            {o}
            {hotkeys && i < GROUP_KEYS.length ? (
              <Kbd className={cn(on && "border-transparent bg-primary-foreground/15 text-primary-foreground")}>
                {GROUP_KEYS[i].toUpperCase()}
              </Kbd>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function AddGroup({ project, onDone }: { project: Project; onDone: () => void }) {
  const update = useUpdateProject(project.slug);
  const [name, setName] = useState("");
  const [options, setOptions] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const opts = options.split(",").map((o) => o.trim()).filter(Boolean);
    if (!name.trim() || !opts.length) return;
    update.mutate(
      { groups: [...project.groups, { name: name.trim(), options: opts }] },
      { onSuccess: onDone, onError: (err) => toast.error(errorMessage(err)) },
    );
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded-md bg-muted/60 p-3">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Group name, e.g. fight_state"
        className="h-8 rounded-sm border border-input bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
      <input
        value={options}
        onChange={(e) => setOptions(e.target.value)}
        placeholder="Options, comma separated"
        className="h-8 rounded-sm border border-input bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="xs" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" size="xs" disabled={update.isPending}>
          Add group
        </Button>
      </div>
    </form>
  );
}

function ImageClassSection({ project }: { project: Project }) {
  const labels = useEditor((s) => s.doc?.labels ?? NO_LABELS);
  const [adding, setAdding] = useState(false);
  const firstChip = project.groups.findIndex((g) => g.options.length <= CHIP_LIMIT);
  return (
    <section className="flex flex-col gap-2 p-4 pt-3">
      <SectionHeader title="Image class" meta="classification">
        <Button variant="ghost" size="xs" onClick={() => setAdding(true)} className="text-muted-foreground">
          <PlusIcon />
          Group
        </Button>
      </SectionHeader>
      {project.groups.map((g, i) => (
        <div key={g.name} className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted-foreground">{g.name}</span>
          <GroupField group={g} value={labels[g.name]} hotkeys={i === firstChip} />
        </div>
      ))}
      {!project.groups.length && !adding ? (
        <p className="text-xs text-muted-foreground">
          Add a label group (a question with one answer per image, like fight_state) to classify images.
        </p>
      ) : null}
      {adding ? <AddGroup project={project} onDone={() => setAdding(false)} /> : null}
    </section>
  );
}

// ------------------------------------------------------------------ objects

function objectMeta(o: LabelObject): string {
  const size = `${Math.round(o.bbox[2])} × ${Math.round(o.bbox[3])}`;
  const shape = o.type === "polygon" ? `${o.points?.length ?? 0} points` : size;
  if (o.source === "model") {
    const score = o.score != null ? ` ${o.score.toFixed(2)}` : "";
    return `Model${score} · ${o.accepted ? "accepted" : "suggested"}`;
  }
  return `Manual · ${shape}`;
}

function IconToggle({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
          aria-label={label}
          className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_svg]:size-4"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function ObjectRow({ o, index, cls }: { o: LabelObject; index: number; cls: LabelClass | undefined }) {
  const selected = useEditor((s) => s.selectedId === o.id);
  const hidden = useEditor((s) => !!s.hidden[o.id]);
  const locked = useEditor((s) => !!s.locked[o.id]);
  const { select, toggleHidden, toggleLocked } = useEditor.getState();
  const color = cls ? labelColor(cls.color) : "#a1a1aa";
  return (
    <div
      role="button"
      tabIndex={-1}
      onClick={() => select(selected ? null : o.id)}
      className={cn(
        "flex cursor-default items-center gap-2 rounded-md border border-transparent py-1 pr-1 pl-2",
        selected ? "border-ring bg-accent" : "hover:bg-accent/60",
        hidden && "opacity-50",
      )}
    >
      <span
        className="size-2.5 shrink-0 rounded-[3px]"
        style={o.accepted ? { background: color } : { border: `1.5px dashed ${color}` }}
      />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-baseline gap-1.5">
          <span className="truncate text-sm font-medium">{cls?.name ?? `class ${o.class_id}`}</span>
          <span className="font-mono text-xs text-muted-foreground">#{index + 1}</span>
        </span>
        <span className="truncate text-xs text-muted-foreground">{objectMeta(o)}</span>
      </span>
      {!o.accepted ? (
        <>
          <IconToggle label="Accept suggestion" onClick={() => acceptSuggestions([o.id])}>
            <CheckIcon />
          </IconToggle>
          <IconToggle label="Reject suggestion" onClick={() => deleteObject(o.id)}>
            <XIcon />
          </IconToggle>
        </>
      ) : (
        <>
          <IconToggle label={hidden ? "Show" : "Hide"} onClick={() => toggleHidden(o.id)}>
            {hidden ? <EyeOffIcon /> : <EyeIcon />}
          </IconToggle>
          <IconToggle label={locked ? "Unlock" : "Lock (can't be moved)"} onClick={() => toggleLocked(o.id)}>
            {locked ? <LockIcon /> : <LockOpenIcon />}
          </IconToggle>
        </>
      )}
    </div>
  );
}

function NumberField({ label, value, onCommit }: { label: string; value: number; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null) {
      const v = Number(draft);
      if (Number.isFinite(v)) onCommit(v);
    }
    setDraft(null);
  };
  return (
    <label className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-sm border border-input bg-background px-2 focus-within:ring-[3px] focus-within:ring-ring/50">
      <span className="text-xs text-muted-foreground">{label}</span>
      <input
        value={draft ?? String(Math.round(value))}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setDraft(null);
            e.currentTarget.blur();
          }
        }}
        inputMode="numeric"
        className="w-full min-w-0 bg-transparent font-mono text-xs outline-none tnum"
      />
    </label>
  );
}

function SelectedGeometry({ o, cls, image, classIndex }: { o: LabelObject; cls: LabelClass | undefined; image: ImageRow; classIndex: number }) {
  const [x, y, w, h] = o.bbox;
  const set = (i: number, v: number) => {
    const b: [number, number, number, number] = [x, y, w, h];
    b[i] = v;
    setSelectedBox(b, image.width, image.height);
  };
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/60 px-3 pt-2.5 pb-3">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="font-medium">{cls?.name ?? "object"}</span>
        <div className="flex-1" />
        <span className="text-muted-foreground">Change class</span>
        {classIndex >= 0 && classIndex < 9 ? <Kbd>{classIndex + 1}</Kbd> : null}
      </div>
      {o.type === "box" ? (
        <div className="flex gap-1.5">
          <NumberField label="X" value={x} onCommit={(v) => set(0, v)} />
          <NumberField label="Y" value={y} onCommit={(v) => set(1, v)} />
          <NumberField label="W" value={w} onCommit={(v) => set(2, v)} />
          <NumberField label="H" value={h} onCommit={(v) => set(3, v)} />
        </div>
      ) : (
        <p className="font-mono text-xs text-muted-foreground">
          {o.points?.length ?? 0} points · bounds {Math.round(x)}, {Math.round(y)} · {Math.round(w)} × {Math.round(h)}
        </p>
      )}
    </div>
  );
}

function ObjectsSection({ project, image }: { project: Project; image: ImageRow }) {
  const objects = useEditor((s) => s.doc?.objects ?? NO_OBJECTS);
  const selectedId = useEditor((s) => s.selectedId);
  const classes = new Map(project.classes.map((c) => [c.id, c]));
  const suggested = objects.filter((o) => !o.accepted).length;
  const selected = objects.find((o) => o.id === selectedId);
  return (
    <section className="flex flex-col gap-2 p-4 pt-3">
      <SectionHeader title="Objects" meta={`${objects.length} on this image`}>
        {suggested ? (
          <Button variant="ghost" size="xs" onClick={() => acceptSuggestions()}>
            <CheckIcon />
            Accept {suggested}
            <Kbd>Enter</Kbd>
          </Button>
        ) : null}
      </SectionHeader>
      {objects.length ? (
        <div className="flex flex-col gap-px">
          {objects.map((o, i) => (
            <ObjectRow key={o.id} o={o} index={i} cls={classes.get(o.class_id)} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Press <Kbd>B</Kbd> and drag on the image to draw a box.
        </p>
      )}
      {selected ? (
        <SelectedGeometry
          o={selected}
          cls={classes.get(selected.class_id)}
          image={image}
          classIndex={project.classes.findIndex((c) => c.id === selected.class_id)}
        />
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ classes

function AddClass({ project, onDone }: { project: Project; onDone: () => void }) {
  const update = useUpdateProject(project.slug);
  const [name, setName] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    update.mutate(
      { classes: [...project.classes.map(({ id, name, color }) => ({ id, name, color })), { name: name.trim() }] },
      {
        onSuccess: () => {
          setName("");
          onDone();
        },
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  };
  return (
    <form onSubmit={submit} className="flex gap-1.5">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && onDone()}
        placeholder="New class name"
        className="h-8 min-w-0 flex-1 rounded-sm border border-input bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
      <Button type="submit" size="sm" disabled={update.isPending || !name.trim()}>
        Add
      </Button>
    </form>
  );
}

function ClassesSection({ project }: { project: Project }) {
  const activeClassId = useEditor((s) => s.activeClassId);
  const [adding, setAdding] = useState(false);
  const active = project.classes.find((c) => c.id === activeClassId);
  return (
    <section className="flex flex-col gap-2 p-4 pt-3">
      <SectionHeader title="Classes" meta={active ? `next shape → ${active.name}` : "asks after drawing"}>
        <Button variant="ghost" size="xs" onClick={() => setAdding(true)}>
          <PlusIcon />
          Add
        </Button>
      </SectionHeader>
      <div className="flex flex-col">
        {project.classes.map((c, i) => {
          const on = c.id === activeClassId;
          return (
            <button
              key={c.id}
              onClick={() => applyClass(c.id)}
              className={cn(
                "flex h-8 items-center gap-2 rounded-md pr-1.5 pl-2 text-left text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                on ? "bg-accent font-medium" : "hover:bg-accent/60",
              )}
            >
              <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: labelColor(c.color) }} />
              <span className="flex-1 truncate">{c.name}</span>
              <span className="font-mono text-xs text-muted-foreground tnum">
                {formatNumber(project.stats.class_counts[c.id] ?? 0)}
              </span>
              {i < 9 ? <Kbd>{i + 1}</Kbd> : <span className="w-5" />}
            </button>
          );
        })}
      </div>
      {!project.classes.length && !adding ? (
        <p className="text-xs text-muted-foreground">Add the classes you want to draw.</p>
      ) : null}
      {adding ? <AddClass project={project} onDone={() => setAdding(false)} /> : null}
    </section>
  );
}

export function Inspector({ project, image }: { project: Project; image: ImageRow | null }) {
  const hasShapes = project.tasks.includes("detection") || project.tasks.includes("segmentation");
  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l">
      {project.tasks.includes("classification") ? (
        <>
          <ImageClassSection project={project} />
          <Separator />
        </>
      ) : null}
      {hasShapes && image ? (
        <>
          <ObjectsSection project={project} image={image} />
          <Separator />
        </>
      ) : null}
      {hasShapes ? <ClassesSection project={project} /> : null}
    </aside>
  );
}
