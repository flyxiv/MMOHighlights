"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PlusIcon, XIcon } from "lucide-react";
import { toast } from "sonner";
import { EMPTY_SOURCE, ImportPanel, runImport, sourceReady, type ImportSource } from "@/components/labeler/import-panel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, errorMessage } from "@/lib/api";
import { formatNumber, TYPE_NAMES } from "@/lib/format";
import { queryKeys } from "@/lib/queries";
import { EDITABLE_TYPES, type EditableType } from "@/lib/types";

const NAME_RE = /^[a-z0-9][a-z0-9_]{1,63}$/;
const TASK_RE = /^[a-z][a-z0-9_]{0,63}$/;

const TYPE_HINTS: Record<EditableType, string> = {
  class: "one answer per image",
  multilabel: "any number per image",
  bbox: "boxes around objects",
  polygon: "outlines around objects",
};

interface TaskDraft {
  name: string;
  type: EditableType;
  classes: string;
}

const DEFAULT_TASKS: TaskDraft[] = [
  { name: "fight_state", type: "class", classes: "pre_pull, in_combat, wipe, kill, cutscene" },
  { name: "ui", type: "bbox", classes: "boss_hp_bar, cast_bar, party_list" },
];

function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {hint ? <span className="-mt-1 text-xs text-muted-foreground">{hint}</span> : null}
      {children}
    </div>
  );
}

function snake(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64);
}

export function NewDatasetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [tasks, setTasks] = useState<TaskDraft[]>(DEFAULT_TASKS);
  const [source, setSource] = useState<ImportSource>(EMPTY_SOURCE);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);

  const reset = () => {
    setTitle("");
    setName("");
    setNameTouched(false);
    setTasks(DEFAULT_TASKS);
    setSource(EMPTY_SOURCE);
    setProgress(null);
  };

  const finalName = nameTouched ? name : snake(title);
  const cleanTasks = tasks.filter((t) => t.name.trim());
  const taskNames = cleanTasks.map((t) => t.name.trim());
  const problem = !title.trim()
    ? "Give it a title."
    : !NAME_RE.test(finalName)
      ? "The folder name is lowercase letters, digits and _, at least 2 characters."
      : !cleanTasks.length
        ? "Add at least one task."
        : taskNames.some((t) => !TASK_RE.test(t))
          ? "Task names are lowercase snake_case and start with a letter."
          : new Set(taskNames).size !== taskNames.length
            ? "Task names must be unique."
            : null;

  const update = (i: number, patch: Partial<TaskDraft>) =>
    setTasks((cur) => cur.map((t, j) => (j === i ? { ...t, ...patch } : t)));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problem || busy) return;
    setBusy(true);
    try {
      const dataset = await api.createDataset({
        name: finalName,
        title: title.trim(),
        modality: ["image"],
        project: "MMOHighlights",
        tasks: Object.fromEntries(cleanTasks.map((t) => [t.name.trim(), { type: t.type }])),
        classes: Object.fromEntries(
          cleanTasks.map((t) => [
            t.name.trim(),
            [...new Set(t.classes.split(",").map((c) => c.trim()).filter(Boolean))],
          ]),
        ),
      });
      void qc.invalidateQueries({ queryKey: queryKeys.datasets });
      if (sourceReady(source)) {
        try {
          const r = await runImport(dataset.name, source, (done, total) => setProgress([done, total]));
          if (r) toast.success(`Uploaded ${formatNumber(r.added)} images`, { description: r.errors[0] });
        } catch (err) {
          toast.error(`Dataset created, but the import failed: ${errorMessage(err)}`);
        }
      }
      onOpenChange(false);
      reset();
      router.push(`/d/${dataset.name}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[640px]">
        <form onSubmit={submit} className="flex flex-col gap-5">
          <DialogHeader>
            <DialogTitle>New dataset</DialogTitle>
            <DialogDescription>
              Creates <span className="font-mono">datasets/{finalName || "<name>"}/</span> in the uniform layout. Label
              here, then cut <span className="font-mono">v1</span> when you&apos;re ready.
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Title">
              <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="FFXIV raid UI" />
            </Field>
            <Field label="Folder name">
              <Input
                value={finalName}
                onChange={(e) => {
                  setNameTouched(true);
                  setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"));
                }}
                placeholder="ffxiv_raid_ui"
                className="font-mono text-sm"
              />
            </Field>
          </div>

          <Field
            label="Tasks"
            hint="Each task is one key in every sample's labels. Classes can be added later; released ones can't be removed."
          >
            <div className="flex flex-col gap-2">
              {tasks.map((t, i) => (
                <div key={i} className="flex gap-2">
                  <Input
                    value={t.name}
                    onChange={(e) => update(i, { name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
                    placeholder="task_name"
                    className="w-36 font-mono text-sm"
                  />
                  <Select value={t.type} onValueChange={(v) => update(i, { type: v as EditableType })}>
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EDITABLE_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {TYPE_NAMES[type]}
                          <span className="text-xs text-muted-foreground">{TYPE_HINTS[type]}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    value={t.classes}
                    onChange={(e) => update(i, { classes: e.target.value })}
                    placeholder="classes, comma separated"
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="Remove task"
                    onClick={() => setTasks((cur) => cur.filter((_, j) => j !== i))}
                  >
                    <XIcon />
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="w-fit"
                onClick={() => setTasks((cur) => [...cur, { name: "", type: "class", classes: "" }])}
              >
                <PlusIcon />
                Add task
              </Button>
            </div>
          </Field>

          <Field label="Images" hint="Optional now; you can add images from the dataset page too.">
            <ImportPanel value={source} onChange={setSource} />
          </Field>

          {progress ? (
            <div className="flex flex-col gap-1.5">
              <Progress value={(progress[0] / progress[1]) * 100} />
              <span className="text-xs text-muted-foreground tnum">
                Uploading {formatNumber(progress[0])} / {formatNumber(progress[1])}
              </span>
            </div>
          ) : null}

          <DialogFooter className="items-center">
            {problem && (title || nameTouched) ? <span className="mr-auto text-xs text-danger">{problem}</span> : null}
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={!!problem || busy}>
              {busy ? "Creating…" : "Create dataset"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
