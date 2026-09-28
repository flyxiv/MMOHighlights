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
  setChoice,
  setSelectedBox,
  toggleChoice,
} from "@/lib/actions";
import { errorMessage } from "@/lib/api";
import { describeLabel, taskGroups } from "@/lib/convert";
import { useEditor } from "@/lib/editor-store";
import { CHIP_LIMIT, classColor, colorOf, formatNumber, GROUP_KEYS, TYPE_NAMES } from "@/lib/format";
import { useUpdateLabeling } from "@/lib/queries";
import type { Dataset, EditableType, EditorDoc, LabelObject, Sample } from "@/lib/types";
import { cn } from "@/lib/utils";

const NO_CHOICES: EditorDoc["choices"] = {};
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

const inputCls =
  "h-8 min-w-0 rounded-sm border border-input bg-background px-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

/** The first image-level task that gets the Q W E R… keys. */
export function hotkeyTask(dataset: Dataset): string | undefined {
  return taskGroups(dataset.tasks).choices.find((t) => (dataset.classes[t]?.length ?? 0) <= CHIP_LIMIT);
}

// ------------------------------------------------------------------ add a task

function AddTask({
  dataset,
  types,
  onDone,
}: {
  dataset: Dataset;
  types: EditableType[];
  onDone: () => void;
}) {
  const update = useUpdateLabeling(dataset.name);
  const [name, setName] = useState("");
  const [type, setType] = useState<EditableType>(types[0]);
  const [classes, setClasses] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const task = name.trim();
    const list = classes.split(",").map((c) => c.trim()).filter(Boolean);
    if (!task) return;
    update.mutate(
      {
        tasks: { ...dataset.tasks, [task]: { type } },
        classes: { ...dataset.classes, [task]: list },
      },
      { onSuccess: onDone, onError: (err) => toast.error(errorMessage(err)) },
    );
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 rounded-md bg-muted/60 p-3">
      <div className="flex gap-2">
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
          placeholder="task_name, e.g. fight_state"
          className={cn(inputCls, "flex-1 font-mono text-xs")}
        />
        {types.length > 1 ? (
          <Select value={type} onValueChange={(v) => setType(v as EditableType)}>
            <SelectTrigger size="sm" className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {types.map((t) => (
                <SelectItem key={t} value={t}>
                  {TYPE_NAMES[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>
      <input
        value={classes}
        onChange={(e) => setClasses(e.target.value)}
        placeholder="Classes, comma separated"
        className={inputCls}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="xs" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" size="xs" disabled={update.isPending || !name.trim()}>
          Add task
        </Button>
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ image-level tasks

function ChoiceField({ dataset, task, hotkeys }: { dataset: Dataset; task: string; hotkeys: boolean }) {
  const choices = useEditor((s) => s.doc?.choices ?? NO_CHOICES);
  const multi = dataset.tasks[task].type === "multilabel";
  const options = dataset.classes[task] ?? [];
  const value = choices[task];
  const isOn = (o: string) => (multi ? Array.isArray(value) && value.includes(o) : value === o);

  if (!multi && options.length > CHIP_LIMIT) {
    return (
      <Select
        value={typeof value === "string" ? value : "__none"}
        onValueChange={(v) => setChoice(task, v === "__none" ? null : v)}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none">
            <span className="text-muted-foreground">Not set</span>
          </SelectItem>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }
  if (!options.length) return <p className="text-xs text-muted-foreground">No classes yet.</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o, i) => {
        const on = isOn(o);
        const key = hotkeys && i < GROUP_KEYS.length ? GROUP_KEYS[i].toUpperCase() : null;
        return (
          <button
            key={o}
            onClick={() => toggleChoice(task, o, multi)}
            aria-pressed={on}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-md border pl-2 text-xs font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              key ? "pr-1" : "pr-2",
              on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent",
            )}
          >
            {on ? <CheckIcon className="size-3.5" /> : null}
            {o}
            {key ? (
              <Kbd className={cn(on && "border-transparent bg-primary-foreground/15 text-primary-foreground")}>{key}</Kbd>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function ImageLabelsSection({ dataset }: { dataset: Dataset }) {
  const [adding, setAdding] = useState(false);
  const { choices } = taskGroups(dataset.tasks);
  const keys = hotkeyTask(dataset);
  return (
    <section className="flex flex-col gap-2 p-4 pt-3">
      <SectionHeader title="Image labels" meta="class · tags">
        <Button variant="ghost" size="xs" onClick={() => setAdding(true)} className="text-muted-foreground">
          <PlusIcon />
          Task
        </Button>
      </SectionHeader>
      {choices.map((t) => (
        <div key={t} className="flex flex-col gap-1.5">
          <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <span className="font-mono">{t}</span>
            {dataset.tasks[t].type === "multilabel" ? <span className="font-normal">· any number</span> : null}
          </span>
          <ChoiceField dataset={dataset} task={t} hotkeys={t === keys} />
        </div>
      ))}
      {!choices.length && !adding ? (
        <p className="text-xs text-muted-foreground">
          Add a class task (one answer per image, like fight_state) or a tags task (any number).
        </p>
      ) : null}
      {adding ? <AddTask dataset={dataset} types={["class", "multilabel"]} onDone={() => setAdding(false)} /> : null}
    </section>
  );
}

// ------------------------------------------------------------------ objects

function objectMeta(o: LabelObject): string {
  const size = `${Math.round(o.bbox[2])} × ${Math.round(o.bbox[3])}`;
  if (!o.accepted) return `Model${o.score != null ? ` ${o.score.toFixed(2)}` : ""} · suggested`;
  return o.type === "polygon" ? `${o.points?.length ?? 0} points` : size;
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

function ObjectRow({ o, index, dataset, showTask }: { o: LabelObject; index: number; dataset: Dataset; showTask: boolean }) {
  const selected = useEditor((s) => s.selectedId === o.id);
  const hidden = useEditor((s) => !!s.hidden[o.id]);
  const locked = useEditor((s) => !!s.locked[o.id]);
  const { select, toggleHidden, toggleLocked } = useEditor.getState();
  const color = colorOf(classColor(dataset, o.task, o.cls));
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
          <span className="truncate text-sm font-medium">{o.cls}</span>
          <span className="font-mono text-xs text-muted-foreground">#{index + 1}</span>
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {showTask ? <span className="font-mono">{o.task} · </span> : null}
          {objectMeta(o)}
        </span>
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

function SelectedGeometry({ o, sample, dataset }: { o: LabelObject; sample: Sample; dataset: Dataset }) {
  const [x, y, w, h] = o.bbox;
  const classIndex = (dataset.classes[o.task] ?? []).indexOf(o.cls);
  // Corners are what the manifest stores (xyxy); edit them directly.
  const set = (x1: number, y1: number, x2: number, y2: number) =>
    setSelectedBox([Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1)], sample.width, sample.height);
  return (
    <div className="flex flex-col gap-2 rounded-md bg-muted/60 px-3 pt-2.5 pb-3">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="font-medium">{o.cls}</span>
        <div className="flex-1" />
        <span className="text-muted-foreground">Change class</span>
        {classIndex >= 0 && classIndex < 9 ? <Kbd>{classIndex + 1}</Kbd> : null}
      </div>
      {o.type === "box" ? (
        <div className="flex gap-1.5">
          <NumberField label="X1" value={x} onCommit={(v) => set(v, y, x + w, y + h)} />
          <NumberField label="Y1" value={y} onCommit={(v) => set(x, v, x + w, y + h)} />
          <NumberField label="X2" value={x + w} onCommit={(v) => set(x, y, v, y + h)} />
          <NumberField label="Y2" value={y + h} onCommit={(v) => set(x, y, x + w, v)} />
        </div>
      ) : (
        <p className="font-mono text-xs text-muted-foreground">
          {o.points?.length ?? 0} points · bounds {Math.round(x)}, {Math.round(y)} → {Math.round(x + w)}, {Math.round(y + h)}
        </p>
      )}
    </div>
  );
}

function ObjectsSection({ dataset, sample }: { dataset: Dataset; sample: Sample }) {
  const objects = useEditor((s) => s.doc?.objects ?? NO_OBJECTS);
  const selectedId = useEditor((s) => s.selectedId);
  const suggested = objects.filter((o) => !o.accepted).length;
  const selected = objects.find((o) => o.id === selectedId);
  const showTask = taskGroups(dataset.tasks).shapes.length > 1;
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
            <ObjectRow key={o.id} o={o} index={i} dataset={dataset} showTask={showTask} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Press <Kbd>B</Kbd> and drag on the image to draw a box.
        </p>
      )}
      {selected ? <SelectedGeometry o={selected} sample={sample} dataset={dataset} /> : null}
    </section>
  );
}

// ------------------------------------------------------------------ classes of the shape tasks

function AddClass({ dataset, task, onDone }: { dataset: Dataset; task: string; onDone: () => void }) {
  const update = useUpdateLabeling(dataset.name);
  const [name, setName] = useState("");
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    update.mutate(
      { classes: { [task]: [...(dataset.classes[task] ?? []), name.trim()] } },
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
        placeholder={`New class in ${task}`}
        className={cn(inputCls, "flex-1")}
      />
      <Button type="submit" size="sm" disabled={update.isPending || !name.trim()}>
        Add
      </Button>
    </form>
  );
}

export function currentShapeTask(dataset: Dataset, activeTask: string | null): string | undefined {
  const { shapes } = taskGroups(dataset.tasks);
  return activeTask && shapes.includes(activeTask) ? activeTask : shapes[0];
}

function ClassesSection({ dataset }: { dataset: Dataset }) {
  const activeTask = useEditor((s) => s.activeTask);
  const activeClass = useEditor((s) => s.activeClass);
  const setActiveTask = useEditor((s) => s.setActiveTask);
  const [adding, setAdding] = useState<"class" | "task" | null>(null);
  const { shapes } = taskGroups(dataset.tasks);
  const task = currentShapeTask(dataset, activeTask);
  const classes = task ? (dataset.classes[task] ?? []) : [];
  const counts = task ? (dataset.stats.class_counts[task] ?? {}) : {};
  const active = task && activeTask === task ? activeClass : null;
  return (
    <section className="flex flex-col gap-2 p-4 pt-3">
      <SectionHeader title="Classes" meta={active ? `next shape → ${active}` : "asks after drawing"}>
        {task ? (
          <Button variant="ghost" size="xs" onClick={() => setAdding("class")}>
            <PlusIcon />
            Add
          </Button>
        ) : null}
      </SectionHeader>
      {shapes.length > 1 ? (
        <div className="flex flex-wrap gap-1">
          {shapes.map((t) => (
            <button
              key={t}
              onClick={() => setActiveTask(t)}
              className={cn(
                "rounded-sm px-2 py-0.5 font-mono text-xs text-muted-foreground outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50",
                t === task && "bg-accent font-medium text-foreground",
              )}
            >
              {t} <span className="font-sans">· {TYPE_NAMES[dataset.tasks[t].type]}</span>
            </button>
          ))}
        </div>
      ) : task ? (
        <span className="font-mono text-xs text-muted-foreground">
          {task} · {TYPE_NAMES[dataset.tasks[task].type].toLowerCase()}
        </span>
      ) : null}
      <div className="flex flex-col">
        {task
          ? classes.map((c, i) => (
              <button
                key={c}
                onClick={() => applyClass(task, c)}
                className={cn(
                  "flex h-8 items-center gap-2 rounded-md pr-1.5 pl-2 text-left text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  c === active ? "bg-accent font-medium" : "hover:bg-accent/60",
                )}
              >
                <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: colorOf(classColor(dataset, task, c)) }} />
                <span className="flex-1 truncate">{c}</span>
                <span className="font-mono text-xs text-muted-foreground tnum">{formatNumber(counts[c] ?? 0)}</span>
                {i < 9 ? <Kbd>{i + 1}</Kbd> : <span className="w-5" />}
              </button>
            ))
          : null}
      </div>
      {!task && adding !== "task" ? (
        <p className="text-xs text-muted-foreground">Add a boxes or polygons task to draw shapes.</p>
      ) : null}
      {task && !classes.length && !adding ? <p className="text-xs text-muted-foreground">Add the classes you want to draw.</p> : null}
      {adding === "class" && task ? <AddClass dataset={dataset} task={task} onDone={() => setAdding(null)} /> : null}
      {adding === "task" ? <AddTask dataset={dataset} types={["bbox", "polygon"]} onDone={() => setAdding(null)} /> : null}
      {adding === null ? (
        <Button variant="ghost" size="xs" className="w-fit text-muted-foreground" onClick={() => setAdding("task")}>
          <PlusIcon />
          Shape task
        </Button>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ read-only tasks

function OtherLabels({ dataset, sample }: { dataset: Dataset; sample: Sample }) {
  const { other } = taskGroups(dataset.tasks);
  const present = other.filter((t) => sample.labels[t]);
  if (!present.length) return null;
  return (
    <>
      <Separator />
      <section className="flex flex-col gap-1.5 p-4 pt-3">
        <SectionHeader title="Other labels" meta="kept as they are" />
        {present.map((t) => (
          <div key={t} className="flex items-baseline gap-2 text-xs">
            <span className="font-mono text-muted-foreground">{t}</span>
            <span className="truncate">{describeLabel(sample.labels[t].value, sample.labels[t].type)}</span>
          </div>
        ))}
      </section>
    </>
  );
}

export function Inspector({ dataset, sample }: { dataset: Dataset; sample: Sample | null }) {
  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l">
      <ImageLabelsSection dataset={dataset} />
      <Separator />
      {sample && taskGroups(dataset.tasks).shapes.length ? (
        <>
          <ObjectsSection dataset={dataset} sample={sample} />
          <Separator />
        </>
      ) : null}
      <ClassesSection dataset={dataset} />
      {sample ? <OtherLabels dataset={dataset} sample={sample} /> : null}
    </aside>
  );
}
