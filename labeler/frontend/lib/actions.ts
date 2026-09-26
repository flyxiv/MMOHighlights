"use client";

import { useEditor, type Draft } from "@/lib/editor-store";
import { clampBoxToImage, polygonBBox, roundBox, translateObject } from "@/lib/geometry";
import { newId } from "@/lib/format";
import type { AnnotationDoc, LabelObject } from "@/lib/types";

const editor = () => useEditor.getState();

function objectFromShape(shape: Draft, classId: number): LabelObject {
  if (shape.type === "polygon") {
    const points = shape.points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10] as [number, number]);
    return {
      id: newId(),
      class_id: classId,
      type: "polygon",
      points,
      bbox: polygonBBox(points),
      source: "manual",
      accepted: true,
    };
  }
  return { id: newId(), class_id: classId, type: "box", bbox: roundBox(shape.bbox), source: "manual", accepted: true };
}

/** Add a finished shape: with the active class right away, or via the class picker. */
export function addShape(shape: Draft) {
  const { activeClassId, edit, select, setDraft, setLastClass } = editor();
  if (activeClassId === null) {
    setDraft(shape);
    return;
  }
  const obj = objectFromShape(shape, activeClassId);
  edit((d) => ({ ...d, objects: [...d.objects, obj] }));
  setLastClass(activeClassId);
  select(obj.id);
}

export function commitDraft(classId: number) {
  const { draft, edit, select, setDraft, setLastClass } = editor();
  if (!draft) return;
  const obj = objectFromShape(draft, classId);
  edit((d) => ({ ...d, objects: [...d.objects, obj] }));
  setLastClass(classId);
  setDraft(null);
  select(obj.id);
}

export function finishPolygon() {
  const { polyPoints, setPolyPoints } = editor();
  if (polyPoints.length < 3) return false;
  setPolyPoints([]);
  addShape({ type: "polygon", points: polyPoints });
  return true;
}

/** Number keys and class rows: re-class the selected object, or pick the class for new shapes. */
export function applyClass(classId: number) {
  const { selectedId, doc, edit, activeClassId, setActiveClass, setLastClass } = editor();
  const selected = doc?.objects.find((o) => o.id === selectedId);
  if (selected) {
    edit((d) => ({
      ...d,
      objects: d.objects.map((o) => (o.id === selected.id ? { ...o, class_id: classId, accepted: true } : o)),
    }));
    setLastClass(classId);
    return;
  }
  setActiveClass(activeClassId === classId ? null : classId);
}

export function toggleLabel(group: string, value: string) {
  editor().edit((d) => {
    const labels = { ...d.labels };
    if (labels[group] === value) delete labels[group];
    else labels[group] = value;
    return { ...d, labels };
  });
}

export function setLabel(group: string, value: string | null) {
  editor().edit((d) => {
    const labels = { ...d.labels };
    if (value === null) delete labels[group];
    else labels[group] = value;
    return { ...d, labels };
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

export function setStatus(status: AnnotationDoc["status"]) {
  editor().edit((d) => (d.status === status ? d : { ...d, status }));
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
