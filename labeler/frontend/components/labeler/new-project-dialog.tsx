"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, MousePointer2Icon, PentagonIcon, PlusIcon, SquareDashedIcon, TagIcon, XIcon } from "lucide-react";
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
import { api, errorMessage } from "@/lib/api";
import { formatNumber, labelColor } from "@/lib/format";
import { queryKeys } from "@/lib/queries";
import { COLORS, type LabelGroup, type Task } from "@/lib/types";
import { cn } from "@/lib/utils";

const TASKS: { task: Task | "keypoints"; title: string; sub: string; Icon: typeof TagIcon }[] = [
  { task: "classification", title: "Image classification", sub: "One or more label groups per image", Icon: TagIcon },
  { task: "detection", title: "Object detection", sub: "Axis-aligned boxes · YOLO / COCO export", Icon: SquareDashedIcon },
  { task: "segmentation", title: "Segmentation", sub: "Polygons per object · COCO export", Icon: PentagonIcon },
  { task: "keypoints", title: "Keypoints", sub: "Skeleton points per object", Icon: MousePointer2Icon },
];

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-medium">{label}</span>
      {hint ? <span className="-mt-1 text-xs text-muted-foreground">{hint}</span> : null}
      {children}
    </div>
  );
}

interface GroupDraft {
  name: string;
  options: string;
}

export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [tasks, setTasks] = useState<Task[]>(["classification", "detection"]);
  const [classes, setClasses] = useState<string[]>([]);
  const [classInput, setClassInput] = useState("");
  const [groups, setGroups] = useState<GroupDraft[]>([{ name: "", options: "" }]);
  const [source, setSource] = useState<ImportSource>(EMPTY_SOURCE);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);

  const reset = () => {
    setName("");
    setTasks(["classification", "detection"]);
    setClasses([]);
    setClassInput("");
    setGroups([{ name: "", options: "" }]);
    setSource(EMPTY_SOURCE);
    setProgress(null);
  };

  const toggleTask = (t: Task) =>
    setTasks((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));

  const addClasses = (raw: string) => {
    const names = raw.split(",").map((s) => s.trim()).filter(Boolean);
    setClasses((cur) => [...cur, ...names.filter((n) => !cur.includes(n))]);
    setClassInput("");
  };

  const usesShapes = tasks.includes("detection") || tasks.includes("segmentation");
  const cleanGroups: LabelGroup[] = groups
    .map((g) => ({ name: g.name.trim(), options: g.options.split(",").map((o) => o.trim()).filter(Boolean) }))
    .filter((g) => g.name && g.options.length);
  const canSubmit = name.trim() && tasks.length > 0 && !busy;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    try {
      const pending = classInput.trim() ? [...classes, ...classInput.split(",").map((s) => s.trim()).filter(Boolean)] : classes;
      const project = await api.createProject({
        name: name.trim(),
        tasks,
        classes: usesShapes ? pending.map((n) => ({ name: n })) : [],
        groups: tasks.includes("classification") ? cleanGroups : [],
      });
      void qc.invalidateQueries({ queryKey: queryKeys.projects });
      if (sourceReady(source)) {
        try {
          const r = await runImport(project.slug, source, (done, total) => setProgress([done, total]));
          if (r) toast.success(`Uploaded ${formatNumber(r.added)} images`, { description: r.errors[0] });
        } catch (err) {
          toast.error(`Project created, but the import failed: ${errorMessage(err)}`);
        }
      }
      onOpenChange(false);
      reset();
      router.push(`/p/${project.slug}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-[600px]">
        <form onSubmit={submit} className="flex flex-col gap-5">
          <DialogHeader>
            <DialogTitle>New labeling project</DialogTitle>
            <DialogDescription>
              Point at a folder of frames and choose what to label. Labels save per image as you work.
            </DialogDescription>
          </DialogHeader>

          <Field label="Name">
            <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="ffxiv-raid-ui" />
          </Field>

          <Field label="Images" hint="Optional now; you can add images from the project page too.">
            <ImportPanel value={source} onChange={setSource} />
          </Field>

          <Field label="Tasks" hint="Pick one or more. Each adds its own panel to the inspector and its own export format.">
            <div className="grid grid-cols-2 gap-3">
              {TASKS.map(({ task, title, sub, Icon }) => {
                const disabled = task === "keypoints";
                const on = !disabled && tasks.includes(task as Task);
                return (
                  <button
                    type="button"
                    key={task}
                    disabled={disabled}
                    onClick={() => toggleTask(task as Task)}
                    aria-pressed={on}
                    className={cn(
                      "flex items-start gap-2.5 rounded-lg border p-3 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                      on ? "border-primary bg-accent ring-1 ring-primary" : "hover:bg-accent/50",
                      disabled && "opacity-50",
                    )}
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input",
                        on && "border-primary bg-primary text-primary-foreground",
                      )}
                    >
                      {on ? <CheckIcon className="size-3" /> : null}
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        <Icon className="size-4 text-muted-foreground" />
                        {title}
                        {disabled ? (
                          <span className="rounded-sm bg-muted px-1.5 text-xs font-normal text-muted-foreground">Later</span>
                        ) : null}
                      </span>
                      <span className="text-xs text-muted-foreground">{sub}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Field>

          {usesShapes ? (
            <Field label="Classes" hint="What you draw boxes or polygons around. Keys 1–9 pick them in order.">
              <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-input p-1.5 focus-within:ring-[3px] focus-within:ring-ring/50">
                {classes.map((c, i) => (
                  <span key={c} className="inline-flex items-center gap-1.5 rounded-md border py-0.5 pr-1 pl-2 text-xs">
                    <span className="size-2 rounded-[2px]" style={{ background: labelColor(COLORS[i % COLORS.length]) }} />
                    {c}
                    <button
                      type="button"
                      onClick={() => setClasses((cur) => cur.filter((x) => x !== c))}
                      aria-label={`Remove ${c}`}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <XIcon className="size-3" />
                    </button>
                  </span>
                ))}
                <input
                  value={classInput}
                  onChange={(e) => setClassInput(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === ",") && classInput.trim()) {
                      e.preventDefault();
                      addClasses(classInput);
                    } else if (e.key === "Backspace" && !classInput && classes.length) {
                      setClasses((cur) => cur.slice(0, -1));
                    }
                  }}
                  placeholder={classes.length ? "Add class" : "boss_hp_bar, cast_bar, party_list…"}
                  className="h-6 min-w-32 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground"
                />
              </div>
            </Field>
          ) : null}

          {tasks.includes("classification") ? (
            <Field
              label="Label groups"
              hint="Questions with one answer per image. The first group with up to 8 options gets keys Q W E R T…"
            >
              <div className="flex flex-col gap-2">
                {groups.map((g, i) => (
                  <div key={i} className="flex gap-2">
                    <Input
                      value={g.name}
                      onChange={(e) => setGroups((cur) => cur.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                      placeholder="fight_state"
                      className="w-36"
                    />
                    <Input
                      value={g.options}
                      onChange={(e) =>
                        setGroups((cur) => cur.map((x, j) => (j === i ? { ...x, options: e.target.value } : x)))
                      }
                      placeholder="Pre-pull, In combat, Wipe, Kill, Cutscene"
                      className="flex-1"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label="Remove group"
                      onClick={() => setGroups((cur) => cur.filter((_, j) => j !== i))}
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
                  onClick={() => setGroups((cur) => [...cur, { name: "", options: "" }])}
                >
                  <PlusIcon />
                  Add group
                </Button>
              </div>
            </Field>
          ) : null}

          {progress ? (
            <div className="flex flex-col gap-1.5">
              <Progress value={(progress[0] / progress[1]) * 100} />
              <span className="text-xs text-muted-foreground tnum">
                Uploading {formatNumber(progress[0])} / {formatNumber(progress[1])}
              </span>
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {busy ? "Creating…" : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
