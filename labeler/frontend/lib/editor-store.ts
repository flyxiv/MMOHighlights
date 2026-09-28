"use client";

import { create } from "zustand";
import type { BBox, EditorDoc, Point } from "@/lib/types";

export type Tool = "select" | "box" | "polygon" | "pan";
export type ViewMode = "single" | "grid";

/** A shape that has been drawn but has no class yet (the class picker is open). */
export type Draft = { type: "box"; bbox: BBox; task: string } | { type: "polygon"; points: Point[]; task: string };

export interface View {
  scale: number;
  x: number;
  y: number;
}

const HISTORY_LIMIT = 200;
export const MIN_SCALE = 0.05;
export const MAX_SCALE = 32;

interface EditorState {
  file: string | null;
  doc: EditorDoc | null;
  /** Bumped on every edit; the autosave compares it with savedVersion. */
  version: number;
  savedVersion: number;
  saving: boolean;
  saveError: string | null;
  past: EditorDoc[];
  future: EditorDoc[];

  selectedId: string | null;
  tool: Tool;
  /** Shape task that number keys and the classes list refer to. */
  activeTask: string | null;
  /** Class (in activeTask) given to new shapes without asking. Null opens the class picker. */
  activeClass: string | null;
  lastClass: { task: string; cls: string } | null;
  draft: Draft | null;
  /** Points of a polygon being drawn (polygon tool). */
  polyPoints: Point[];
  hidden: Record<string, true>;
  locked: Record<string, true>;
  showObjects: boolean;

  view: View;
  viewport: { width: number; height: number };
  /** Bumped to ask the canvas to fit the image. */
  fitRequest: number;

  viewMode: ViewMode;
  shortcutsOpen: boolean;

  load: (file: string, doc: EditorDoc) => void;
  edit: (fn: (doc: EditorDoc) => EditorDoc) => void;
  undo: () => void;
  redo: () => void;
  markSaved: (version: number) => void;
  setSaving: (saving: boolean, error?: string | null) => void;

  select: (id: string | null) => void;
  setTool: (tool: Tool) => void;
  setActiveTask: (task: string | null) => void;
  setActiveClass: (cls: string | null) => void;
  setLastClass: (task: string, cls: string) => void;
  setDraft: (draft: Draft | null) => void;
  setPolyPoints: (points: Point[]) => void;
  toggleHidden: (id: string) => void;
  toggleLocked: (id: string) => void;
  toggleShowObjects: () => void;

  setView: (view: View) => void;
  setViewport: (width: number, height: number) => void;
  zoomAt: (factor: number, cx?: number, cy?: number) => void;
  requestFit: () => void;

  setViewMode: (mode: ViewMode) => void;
  setShortcutsOpen: (open: boolean) => void;
}

export const useEditor = create<EditorState>((set, get) => ({
  file: null,
  doc: null,
  version: 0,
  savedVersion: 0,
  saving: false,
  saveError: null,
  past: [],
  future: [],
  selectedId: null,
  tool: "select",
  activeTask: null,
  activeClass: null,
  lastClass: null,
  draft: null,
  polyPoints: [],
  hidden: {},
  locked: {},
  showObjects: true,
  view: { scale: 1, x: 0, y: 0 },
  viewport: { width: 0, height: 0 },
  fitRequest: 0,
  viewMode: "single",
  shortcutsOpen: false,

  load: (file, doc) =>
    set((s) => ({
      file,
      doc,
      version: 0,
      savedVersion: 0,
      saveError: null,
      past: [],
      future: [],
      selectedId: null,
      draft: null,
      polyPoints: [],
      hidden: {},
      locked: {},
      fitRequest: s.fitRequest + 1,
    })),

  edit: (fn) =>
    set((s) => {
      if (!s.doc) return {};
      const next = fn(s.doc);
      if (next === s.doc) return {};
      const selectedId =
        s.selectedId && next.objects.some((o) => o.id === s.selectedId) ? s.selectedId : null;
      return {
        doc: next,
        past: [...s.past.slice(-HISTORY_LIMIT + 1), s.doc],
        future: [],
        version: s.version + 1,
        selectedId,
      };
    }),

  undo: () =>
    set((s) => {
      if (!s.doc || !s.past.length) return {};
      const prev = s.past[s.past.length - 1];
      return { doc: prev, past: s.past.slice(0, -1), future: [s.doc, ...s.future], version: s.version + 1 };
    }),

  redo: () =>
    set((s) => {
      if (!s.doc || !s.future.length) return {};
      const [next, ...rest] = s.future;
      return { doc: next, past: [...s.past, s.doc], future: rest, version: s.version + 1 };
    }),

  markSaved: (version) => set((s) => ({ savedVersion: Math.max(s.savedVersion, version) })),
  setSaving: (saving, error = null) => set({ saving, saveError: error }),

  select: (id) => set({ selectedId: id }),
  setTool: (tool) => set({ tool, draft: null, polyPoints: [] }),
  setActiveTask: (activeTask) =>
    set((s) => (s.activeTask === activeTask ? {} : { activeTask, activeClass: null })),
  setActiveClass: (activeClass) => set({ activeClass }),
  setLastClass: (task, cls) => set({ lastClass: { task, cls } }),
  setDraft: (draft) => set({ draft }),
  setPolyPoints: (polyPoints) => set({ polyPoints }),
  toggleHidden: (id) =>
    set((s) => {
      const hidden = { ...s.hidden };
      if (hidden[id]) delete hidden[id];
      else hidden[id] = true;
      return { hidden, selectedId: hidden[id] && s.selectedId === id ? null : s.selectedId };
    }),
  toggleLocked: (id) =>
    set((s) => {
      const locked = { ...s.locked };
      if (locked[id]) delete locked[id];
      else locked[id] = true;
      return { locked };
    }),
  toggleShowObjects: () => set((s) => ({ showObjects: !s.showObjects })),

  setView: (view) => set({ view }),
  setViewport: (width, height) => set({ viewport: { width, height } }),
  zoomAt: (factor, cx, cy) => {
    const { view, viewport } = get();
    const x0 = cx ?? viewport.width / 2;
    const y0 = cy ?? viewport.height / 2;
    const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
    const k = scale / view.scale;
    set({ view: { scale, x: x0 - (x0 - view.x) * k, y: y0 - (y0 - view.y) * k } });
  },
  requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),

  setViewMode: (viewMode) => set({ viewMode }),
  setShortcutsOpen: (shortcutsOpen) => set({ shortcutsOpen }),
}));

export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}
