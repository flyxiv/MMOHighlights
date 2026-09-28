"use client";

import { useEditor, type Draft } from "@/lib/editor-store";
import { clampBoxToImage, polygonBBox, roundBox, translateObject } from "@/lib/geometry";
import { newId } from "@/lib/format";
import type { EditorDoc, LabelObject, Point, Status } from "@/lib/types";

const editor = () => useEditor.getState();

function objectFromShape(shape: Draft, cls: string): LabelObject {
  const base = { id: newId(), task: shape.task, cls, source: "manual" as const, accepted: true };
  if (shape.type === "polygon") {
    const points = shape.points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10] as Point);
    return { ...base, type: "polygon", points, bbox: polygonBBox(points) };
  }
  return { ...base, type: "box", bbox: roundBox(shape.bbox) };
}

/** Add a finished shape: with the active class right away, or via the class picker. */
export function addShape(shape: Draft) {
  const { activeTask, activeClass, edit, select, setDraft, setLastClass } = editor();
  if (activeClass === null || activeTask !== shape.task) {
    setDraft(shape);
    return;
  }
  const obj = objectFromShape(shape, activeClass);
  edit((d) => ({ ...d, objects: [...d.objects, obj] }));
  setLastClass(shape.task, activeClass);
  select(obj.id);
}

export function commitDraft(cls: string) {
  const { draft, edit, select, setDraft, setLastClass } = editor();
  if (!draft) return;
  const obj = objectFromShape(draft, cls);
  edit((d) => ({ ...d, objects: [...d.objects, obj] }));
  setLastClass(draft.task, cls);
  setDraft(null);
  select(obj.id);
}

export function finishPolygon(task: string) {
  const { polyPoints, setPolyPoints } = editor();
  if (polyPoints.length < 3) return false;
  setPolyPoints([]);
  addShape({ type: "polygon", points: polyPoints, task });
  return true;
}

/** Number keys and class rows: re-class the selected object, or pick the class for new shapes. */
export function applyClass(task: string, cls: string) {
  const { selectedId, doc, edit, activeTask, activeClass, setActiveTask, setActiveClass, setLastClass } = editor();
  const selected = doc?.objects.find((o) => o.id === selectedId);
  if (selected && selected.task === task) {
    edit((d) => ({
      ...d,
      objects: d.objects.map((o) => (o.id === selected.id ? { ...o, cls, accepted: true } : o)),
    }));
    setLastClass(task, cls);
    return;
  }
  if (activeTask !== task) setActiveTask(task);
  setActiveClass(activeTask === task && activeClass === cls ? null : cls);
}

/** Toggle an image-level class (class task) or tag (multilabel task). */
export function toggleChoice(task: string, value: string, multi: boolean) {
  editor().edit((d) => {
    const choices = { ...d.choices };
    const cur = choices[task];
    if (multi) {
      const list = Array.isArray(cur) ? cur : [];
      const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
      if (next.length) choices[task] = next;
      else delete choices[task];
    } else if (cur === value) delete choices[task];
    else choices[task] = value;
    return { ...d, choices };
  });
}

export function setChoice(task: string, value: string | null) {
  editor().edit((d) => {
    const choices = { ...d.choices };
    if (value === null) delete choices[task];
    else choices[task] = value;
    return { ...d, choices };
  });
}

export function acceptSuggestions(ids?: string[]) {
  const { doc, edit } = editor();
  if (!doc?.objects.some((o) => !o.accepted && (!ids || ids.includes(o.id)))) return false;
  edit((d) => ({
    ...d,
    objects: d.objects.map((o) => (!o.accepted && (!ids || ids.includes(o.id)) ? { ...o, accepted: true } : o)),
  }));
  return true;
}

export function deleteObject(id: string) {
  editor().edit((d) => ({ ...d, objects: d.objects.filter((o) => o.id !== id) }));
}

export function deleteSelected() {
  const { selectedId, locked } = editor();
  if (!selectedId || locked[selectedId]) return false;
  deleteObject(selectedId);
  return true;
}

export function nudgeSelected(dx: number, dy: number, iw: number, ih: number) {
  const { selectedId, locked, edit } = editor();
  if (!selectedId || locked[selectedId]) return;
  edit((d) => ({
    ...d,
    objects: d.objects.map((o) => (o.id === selectedId ? translateObject(o, dx, dy, iw, ih) : o)),
  }));
}

export function setSelectedBox(bbox: [number, number, number, number], iw: number, ih: number) {
  const { selectedId, edit } = editor();
  const fixed = roundBox(clampBoxToImage(bbox, iw, ih));
  if (!selectedId || fixed[2] < 1 || fixed[3] < 1) return;
  edit((d) => ({
    ...d,
    objects: d.objects.map((o) => (o.id === selectedId && o.type === "box" ? { ...o, bbox: fixed } : o)),
  }));
}

export function setStatus(status: Status) {
  editor().edit((d: EditorDoc) => (d.status === status ? d : { ...d, status }));
}

/** Append another image's accepted objects (new ids), e.g. from the previous frame. */
export function pasteObjects(objects: LabelObject[], iw: number, ih: number) {
  const copies = objects
    .filter((o) => o.accepted)
    .map((o) => ({ ...translateObject(o, 0, 0, iw, ih), id: newId(), source: "manual" as const, score: null }));
  if (!copies.length) return 0;
  editor().edit((d) => ({ ...d, objects: [...d.objects, ...copies] }));
  return copies.length;
}

export function cycleSelection(step: 1 | -1) {
  const { doc, selectedId, hidden, select } = editor();
  const visible = doc?.objects.filter((o) => !hidden[o.id]) ?? [];
  if (!visible.length) return;
  const i = visible.findIndex((o) => o.id === selectedId);
  const next = i === -1 ? (step === 1 ? 0 : visible.length - 1) : (i + step + visible.length) % visible.length;
  select(visible[next].id);
}
