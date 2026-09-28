import { newId } from "@/lib/format";
import type {
  Dataset,
  EditorDoc,
  LabelObject,
  Labels,
  Point,
  Sample,
  SampleSave,
  Status,
  TaskSpec,
} from "@/lib/types";

/** Tasks the editor can change, by kind, in the dataset's declared order. */
export function taskGroups(tasks: Record<string, TaskSpec>) {
  const entries = Object.entries(tasks);
  return {
    choices: entries.filter(([, s]) => s.type === "class" || s.type === "multilabel").map(([t]) => t),
    shapes: entries.filter(([, s]) => s.type === "bbox" || s.type === "polygon").map(([t]) => t),
    other: entries.filter(([, s]) => !["class", "multilabel", "bbox", "polygon"].includes(s.type)).map(([t]) => t),
  };
}

type Item = { class: string; xyxy?: number[]; points?: number[][]; score?: number };

function objectsOf(labels: Labels, tasks: Record<string, TaskSpec>, accepted: boolean): LabelObject[] {
  const out: LabelObject[] = [];
  for (const [task, lab] of Object.entries(labels)) {
    const type = tasks[task]?.type;
    if ((type !== "bbox" && type !== "polygon") || !Array.isArray(lab.value)) continue;
    for (const it of lab.value as Item[]) {
      const base = {
        id: newId(),
        task,
        cls: it.class,
        source: accepted ? ("manual" as const) : ("model" as const),
        score: it.score ?? null,
        accepted,
      };
      if (type === "bbox" && it.xyxy) {
        const [x1, y1, x2, y2] = it.xyxy;
        out.push({ ...base, type: "box", bbox: [x1, y1, x2 - x1, y2 - y1] });
      } else if (type === "polygon" && it.points) {
        const points = it.points.map(([x, y]) => [x, y] as Point);
        const xs = points.map((p) => p[0]);
        const ys = points.map((p) => p[1]);
        const x = Math.min(...xs);
        const y = Math.min(...ys);
        out.push({ ...base, type: "polygon", points, bbox: [x, y, Math.max(...xs) - x, Math.max(...ys) - y] });
      }
    }
  }
  return out;
}

export function docFromSample(sample: Sample, dataset: Dataset): EditorDoc {
  const choices: EditorDoc["choices"] = {};
  for (const [task, lab] of Object.entries(sample.labels)) {
    const type = dataset.tasks[task]?.type;
    if (type === "class" && typeof lab.value === "string") choices[task] = lab.value;
    if (type === "multilabel" && Array.isArray(lab.value)) choices[task] = lab.value as string[];
  }
  return {
    status: sample.status,
    choices,
    objects: [...objectsOf(sample.labels, dataset.tasks, true), ...objectsOf(sample.suggestions, dataset.tasks, false)],
  };
}

const r1 = (v: number) => Math.round(v * 10) / 10;

function item(o: LabelObject): Item {
  const extra = o.accepted || o.score == null ? {} : { score: o.score };
  if (o.type === "polygon" && o.points) return { class: o.cls, points: o.points.map(([x, y]) => [r1(x), r1(y)]), ...extra };
  const [x, y, w, h] = o.bbox;
  return { class: o.cls, xyxy: [r1(x), r1(y), r1(x + w), r1(y + h)], ...extra };
}

/**
 * The editable part of the sample in manifest format. A task with no value is left out ("not
 * labeled for this task"), except shape tasks on a done image: an empty list there means
 * "checked, nothing to box".
 */
export function saveFromDoc(doc: EditorDoc, tasks: Record<string, TaskSpec>): SampleSave {
  const { choices, shapes } = taskGroups(tasks);
  const labels: Labels = {};
  const suggestions: Labels = {};
  for (const task of choices) {
    const v = doc.choices[task];
    if (v === undefined || (Array.isArray(v) && !v.length)) continue;
    labels[task] = { type: tasks[task].type, value: v };
  }
  for (const task of shapes) {
    const type = tasks[task].type;
    const mine = doc.objects.filter((o) => o.task === task);
    const accepted = mine.filter((o) => o.accepted).map(item);
    const suggested = mine.filter((o) => !o.accepted).map(item);
    if (accepted.length || doc.status === "done") labels[task] = { type, value: accepted };
    if (suggested.length) suggestions[task] = { type, value: suggested };
  }
  return { status: doc.status as Status, labels, suggestions };
}

/** Values to show in the image list for a saved doc. */
export function rowLabels(doc: EditorDoc): Record<string, string | string[]> {
  return Object.fromEntries(
    Object.entries(doc.choices).filter(([, v]) => v !== undefined && (!Array.isArray(v) || v.length)),
  );
}

/** A human summary of a label the editor can't change (span, text, scalar…). */
export function describeLabel(value: unknown, type: string): string {
  if (type === "text" || type === "class") return String(value);
  if (type === "scalar") return String(value);
  if (Array.isArray(value)) return `${value.length} ${type === "span" ? "spans" : "items"}`;
  if (value && typeof value === "object" && "path" in value) return String((value as { path: string }).path);
  return JSON.stringify(value);
}
