"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ClassPicker } from "@/components/labeler/class-picker";
import { Kbd } from "@/components/ui/kbd";
import { addShape, commitDraft, finishPolygon } from "@/lib/actions";
import { imageUrl, thumbUrl } from "@/lib/api";
import { MAX_SCALE, MIN_SCALE, useEditor } from "@/lib/editor-store";
import { classColor, colorOf, labelInk } from "@/lib/format";
import {
  boxFromPoints,
  clamp,
  clampBoxToImage,
  HANDLE_CURSORS,
  handlePoints,
  hitObject,
  resizeBox,
  translateObject,
} from "@/lib/geometry";
import type { BBox, Color, Dataset, LabelObject, Point, Sample } from "@/lib/types";
import type { Tool } from "@/lib/editor-store";

type Interaction =
  | { kind: "pan"; sx: number; sy: number; x0: number; y0: number }
  | { kind: "draw"; start: Point }
  | { kind: "move"; start: Point; orig: LabelObject }
  | { kind: "resize"; handle: number; orig: LabelObject }
  | { kind: "vertex"; index: number; orig: LabelObject };

const HANDLE_PX = 6; // pointer tolerance around a handle, in screen pixels
const MIN_DRAG_PX = 4;
const CLOSE_POLYGON_PX = 8;

/** The shape task a drawing tool adds to: the active task if it has the right type, else the first one that does. */
export function drawTaskFor(dataset: Dataset, tool: Tool, activeTask: string | null): string | null {
  const type = tool === "box" ? "bbox" : tool === "polygon" ? "polygon" : null;
  if (!type) return null;
  if (activeTask && dataset.tasks[activeTask]?.type === type) return activeTask;
  return Object.entries(dataset.tasks).find(([, s]) => s.type === type)?.[0] ?? null;
}

export function LabelCanvas({ dataset, image }: { dataset: Dataset; image: Sample }) {
  const doc = useEditor((s) => s.doc);
  const selectedId = useEditor((s) => s.selectedId);
  const tool = useEditor((s) => s.tool);
  const draft = useEditor((s) => s.draft);
  const polyPoints = useEditor((s) => s.polyPoints);
  const hidden = useEditor((s) => s.hidden);
  const locked = useEditor((s) => s.locked);
  const showObjects = useEditor((s) => s.showObjects);
  const view = useEditor((s) => s.view);
  const viewport = useEditor((s) => s.viewport);
  const fitRequest = useEditor((s) => s.fitRequest);
  const lastClass = useEditor((s) => s.lastClass);
  const activeTask = useEditor((s) => s.activeTask);

  const containerRef = useRef<HTMLDivElement>(null);
  const interaction = useRef<Interaction | null>(null);
  const [preview, setPreview] = useState<LabelObject | null>(null);
  const [drawBox, setDrawBox] = useState<BBox | null>(null);
  const [cursor, setCursor] = useState<Point | null>(null);
  const [hoverCursor, setHoverCursor] = useState<string | null>(null);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [panning, setPanning] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const iw = image.width;
  const ih = image.height;
  const colorFor = useCallback((o: LabelObject) => classColor(dataset, o.task, o.cls), [dataset]);
  const drawTask = drawTaskFor(dataset, tool, activeTask);

  // ---- viewport size and fitting

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      useEditor.getState().setViewport(entry.contentRect.width, entry.contentRect.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitKey = useRef<string>("");
  useLayoutEffect(() => {
    if (!viewport.width || !viewport.height) return;
    const key = `${fitRequest}:${image.id}`;
    if (fitKey.current === key) return;
    fitKey.current = key;
    const pad = 32;
    const scale = clamp(
      Math.min((viewport.width - pad * 2) / iw, (viewport.height - pad * 2) / ih),
      MIN_SCALE,
      MAX_SCALE,
    );
    useEditor.getState().setView({
      scale,
      x: (viewport.width - iw * scale) / 2,
      y: (viewport.height - ih * scale) / 2,
    });
  }, [fitRequest, viewport.width, viewport.height, iw, ih, image.id]);

  useEffect(() => setLoaded(false), [image.id]);

  // ---- coordinate helpers

  const toImage = useCallback(
    (clientX: number, clientY: number): Point => {
      const rect = containerRef.current!.getBoundingClientRect();
      return [(clientX - rect.left - view.x) / view.scale, (clientY - rect.top - view.y) / view.scale];
    },
    [view],
  );
  const sx = (x: number) => x * view.scale + view.x;
  const sy = (y: number) => y * view.scale + view.y;
  const clampPoint = (p: Point): Point => [clamp(p[0], 0, iw), clamp(p[1], 0, ih)];

  const objects = useMemo(() => {
    const list = doc?.objects ?? [];
    return preview ? list.map((o) => (o.id === preview.id ? preview : o)) : list;
  }, [doc, preview]);
  const visible = useMemo(() => (showObjects ? objects.filter((o) => !hidden[o.id]) : []), [objects, hidden, showObjects]);
  const selected = visible.find((o) => o.id === selectedId) ?? null;

  // ---- wheel zoom (non-passive so the page doesn't scroll)

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      useEditor.getState().zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // ---- hold Space to pan with any tool

  useEffect(() => {
    const typing = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !typing(e.target)) {
        e.preventDefault();
        setSpaceHeld(true);
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") setSpaceHeld(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  // ---- hit testing

  const hitHandle = (clientX: number, clientY: number): number | null => {
    if (!selected || locked[selected.id]) return null;
    const rect = containerRef.current!.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const pts = selected.type === "polygon" && selected.points ? selected.points : handlePoints(selected.bbox);
    for (let i = 0; i < pts.length; i++) {
      if (Math.abs(sx(pts[i][0]) - px) <= HANDLE_PX && Math.abs(sy(pts[i][1]) - py) <= HANDLE_PX) return i;
    }
    return null;
  };

  // ---- pointer handling

  const onPointerDown = (e: React.PointerEvent) => {
    if (!doc) return;
    const state = useEditor.getState();
    if (state.draft) {
      state.setDraft(null); // clicking away discards an unclassified shape
      return;
    }
    containerRef.current!.setPointerCapture(e.pointerId);
    const p = toImage(e.clientX, e.clientY);

    if (e.button === 1 || tool === "pan" || spaceHeld) {
      interaction.current = { kind: "pan", sx: e.clientX, sy: e.clientY, x0: view.x, y0: view.y };
      setPanning(true);
      return;
    }
    if (e.button !== 0) return;

    if (tool === "box") {
      interaction.current = { kind: "draw", start: clampPoint(p) };
      setDrawBox([...clampPoint(p), 0, 0]);
      return;
    }
    if (tool === "polygon") {
      const pts = state.polyPoints;
      if (pts.length >= 3) {
        const [fx, fy] = pts[0];
        if (Math.hypot(sx(fx) - (e.clientX - containerRef.current!.getBoundingClientRect().left), sy(fy) - (e.clientY - containerRef.current!.getBoundingClientRect().top)) <= CLOSE_POLYGON_PX) {
          if (drawTask) finishPolygon(drawTask);
          return;
        }
      }
      state.setPolyPoints([...pts, clampPoint(p)]);
      return;
    }

    // select tool
    const handle = hitHandle(e.clientX, e.clientY);
    if (handle !== null && selected) {
      interaction.current =
        selected.type === "polygon"
          ? { kind: "vertex", index: handle, orig: selected }
          : { kind: "resize", handle, orig: selected };
      return;
    }
    const hit = hitObject(visible, p, 3 / view.scale);
    if (hit) {
      state.select(hit.id);
      if (!locked[hit.id]) interaction.current = { kind: "move", start: p, orig: hit };
      return;
    }
    state.select(null);
    interaction.current = { kind: "pan", sx: e.clientX, sy: e.clientY, x0: view.x, y0: view.y };
    setPanning(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = toImage(e.clientX, e.clientY);
    setCursor(p[0] >= 0 && p[1] >= 0 && p[0] <= iw && p[1] <= ih ? p : null);
    const it = interaction.current;
    if (!it) {
      if (tool === "select" && !spaceHeld) {
        const h = hitHandle(e.clientX, e.clientY);
        if (h !== null && selected) setHoverCursor(selected.type === "polygon" ? "crosshair" : HANDLE_CURSORS[h]);
        else {
          const hit = hitObject(visible, p, 3 / view.scale);
          setHoverCursor(hit && !locked[hit.id] ? "move" : hit ? "pointer" : null);
        }
      }
      return;
    }
    if (it.kind === "pan") {
      useEditor.getState().setView({ ...view, x: it.x0 + e.clientX - it.sx, y: it.y0 + e.clientY - it.sy });
    } else if (it.kind === "draw") {
      setDrawBox(boxFromPoints(it.start, clampPoint(p)));
    } else {
      setPreview(dragResult(it, p));
    }
  };

  /** Where a move/resize/vertex drag puts the object when the pointer is at p. */
  const dragResult = (it: Extract<Interaction, { orig: LabelObject }>, p: Point): LabelObject => {
    if (it.kind === "move") return translateObject(it.orig, p[0] - it.start[0], p[1] - it.start[1], iw, ih);
    if (it.kind === "resize") return { ...it.orig, bbox: clampBoxToImage(resizeBox(it.orig.bbox, it.handle, p), iw, ih) };
    const points = it.orig.points!.map((q, i) => (i === it.index ? clampPoint(p) : q));
    return { ...it.orig, points, bbox: boundsOf(points) };
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const it = interaction.current;
    interaction.current = null;
    setPanning(false);
    if (!it) return;
    const state = useEditor.getState();
    // Computed from this event, not from state: a quick release can arrive before the last move rendered.
    const p = toImage(e.clientX, e.clientY);
    if (it.kind === "draw") {
      const box = boxFromPoints(it.start, clampPoint(p));
      setDrawBox(null);
      if (box && box[2] * view.scale >= MIN_DRAG_PX && box[3] * view.scale >= MIN_DRAG_PX) {
        if (drawTask) addShape({ type: "box", bbox: box, task: drawTask });
      } else {
        // A click with the box tool selects what's under it.
        const hit = hitObject(visible, p, 3 / view.scale);
        state.select(hit?.id ?? null);
      }
      return;
    }
    if (it.kind === "move" || it.kind === "resize" || it.kind === "vertex") {
      const next = dragResult(it, p);
      if (JSON.stringify(next) !== JSON.stringify(it.orig) && next.bbox[2] >= 1 && next.bbox[3] >= 1) {
        state.edit((d) => ({ ...d, objects: d.objects.map((o) => (o.id === next.id ? next : o)) }));
      }
      setPreview(null);
    }
  };

  // ---- rendering

  const s = view.scale;
  const cursorStyle =
    panning ? "grabbing" : spaceHeld || tool === "pan" ? "grab" : tool === "box" || tool === "polygon" ? "crosshair" : hoverCursor ?? "default";

  const suggestions = (doc?.objects ?? []).filter((o) => !o.accepted).length;


  const draftBox = draft ? (draft.type === "box" ? draft.bbox : null) : null;
  const draftPoly = draft?.type === "polygon" ? draft.points : null;
  const draftBounds = draftBox ?? (draftPoly ? boundsOf(draftPoly) : null);

  return (
    <div
      ref={containerRef}
      className="relative min-h-0 flex-1 touch-none overflow-hidden bg-canvas select-none"
      style={{ cursor: cursorStyle }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerLeave={() => setCursor(null)}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div
        className="absolute top-0 left-0 origin-top-left shadow-[0_4px_16px_rgba(0,0,0,0.18)]"
        style={{ width: iw, height: ih, transform: `translate(${view.x}px, ${view.y}px) scale(${s})` }}
      >
        {/* The thumbnail shows instantly while the full image loads. */}
        {!loaded ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumbUrl(dataset.name, image.id)} alt="" draggable={false} className="absolute inset-0 size-full blur-[1px]" />
        ) : null}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          key={image.id}
          src={imageUrl(dataset.name, image.id)}
          alt={image.name}
          draggable={false}
          onLoad={() => setLoaded(true)}
          className="absolute inset-0 size-full"
          style={{ imageRendering: s >= 3 ? "pixelated" : "auto", opacity: loaded ? 1 : 0 }}
        />
      </div>

      <svg className="pointer-events-none absolute inset-0 size-full overflow-visible">
        {visible.map((o) => (
          <Shape key={o.id} o={o} color={colorFor(o)} selected={o.id === selectedId} sx={sx} sy={sy} s={s} />
        ))}
        {selected && !locked[selected.id] ? <Handles o={selected} color={colorFor(selected)} sx={sx} sy={sy} /> : null}

        {drawBox ? (
          <rect x={sx(drawBox[0])} y={sy(drawBox[1])} width={drawBox[2] * s} height={drawBox[3] * s} className="fill-white/10 stroke-white" strokeWidth={1.5} strokeDasharray="6 4" />
        ) : null}
        {draftBox ? (
          <rect x={sx(draftBox[0])} y={sy(draftBox[1])} width={draftBox[2] * s} height={draftBox[3] * s} className="fill-white/10 stroke-white" strokeWidth={1.5} strokeDasharray="6 4" />
        ) : null}
        {draftPoly ? (
          <polygon points={draftPoly.map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ")} className="fill-white/10 stroke-white" strokeWidth={1.5} strokeDasharray="6 4" />
        ) : null}

        {tool === "polygon" && polyPoints.length ? (
          <g>
            <polyline
              points={[...polyPoints, ...(cursor ? [cursor] : [])].map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ")}
              className="fill-white/10 stroke-white"
              strokeWidth={1.5}
              strokeDasharray="6 4"
            />
            {polyPoints.map(([x, y], i) => (
              <circle key={i} cx={sx(x)} cy={sy(y)} r={i === 0 ? 5 : 3} className="fill-white stroke-black/60" strokeWidth={1} />
            ))}
          </g>
        ) : null}

        {(tool === "box" || tool === "polygon") && cursor && !panning ? (
          <g className="stroke-white/60" strokeWidth={1}>
            <line x1={0} x2="100%" y1={sy(cursor[1])} y2={sy(cursor[1])} />
            <line y1={0} y2="100%" x1={sx(cursor[0])} x2={sx(cursor[0])} />
          </g>
        ) : null}
      </svg>

      {/* Class tags sit in HTML so text renders crisply at any zoom. */}
      {visible.map((o) => {
        const color = colorFor(o);
        return (
          <div
            key={o.id}
            className="pointer-events-none absolute rounded-t px-1.5 py-px text-xs leading-4 font-medium whitespace-nowrap"
            style={{
              left: sx(o.bbox[0]) - 0.75,
              top: sy(o.bbox[1]) - 18,
              background: colorOf(color),
              color: color ? labelInk(color) : "#18181b",
              opacity: o.accepted ? 1 : 0.85,
            }}
          >
            {o.cls}
            {!o.accepted && o.score != null ? ` · ${o.score.toFixed(2)}` : ""}
          </div>
        );
      })}

      {drawBox ? (
        <div
          className="pointer-events-none absolute rounded-sm bg-foreground px-1.5 py-0.5 font-mono text-xs text-background"
          style={{ left: sx(drawBox[0] + drawBox[2]) + 6, top: sy(drawBox[1] + drawBox[3]) + 6 }}
        >
          {Math.round(drawBox[2])} × {Math.round(drawBox[3])}
        </div>
      ) : null}

      {cursor ? (
        <div className="pointer-events-none absolute top-3 left-3 rounded-sm border bg-background/90 px-2 py-1 font-mono text-xs text-muted-foreground tnum">
          x {Math.round(cursor[0])}&nbsp;&nbsp;y {Math.round(cursor[1])}
        </div>
      ) : null}

      {tool === "polygon" && polyPoints.length ? (
        <div className="pointer-events-none absolute top-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-sm border bg-background/90 px-2 py-1 text-xs text-muted-foreground">
          Click the first point or press <Kbd>Enter</Kbd> to close · <Kbd>Backspace</Kbd> undo point · <Kbd>Esc</Kbd> cancel
        </div>
      ) : null}

      {suggestions ? (
        <div className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-1.5 rounded-sm border bg-background/90 px-2 py-1 text-xs text-muted-foreground">
          Dashed = model suggestion. <Kbd>Enter</Kbd> accepts all
        </div>
      ) : null}

      {draft && draftBounds ? (
        <ClassPicker
          dataset={dataset}
          task={draft.task}
          lastClass={lastClass?.task === draft.task ? lastClass.cls : null}
          onPick={commitDraft}
          onCancel={() => useEditor.getState().setDraft(null)}
          style={pickerPosition(draftBounds, sx, sy, viewport)}
        />
      ) : null}
    </div>
  );
}

function boundsOf(points: Point[]): BBox {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
}

function pickerPosition(
  b: BBox,
  sx: (x: number) => number,
  sy: (y: number) => number,
  viewport: { width: number; height: number },
): React.CSSProperties {
  const W = 272;
  const H = 360;
  let left = sx(b[0] + b[2]) + 12;
  if (left + W > viewport.width - 8) left = sx(b[0]) - W - 12;
  left = clamp(left, 8, Math.max(8, viewport.width - W - 8));
  const top = clamp(sy(b[1] + b[3]) - H, 8, Math.max(8, viewport.height - H - 8));
  return { left, top };
}

function Shape({
  o,
  color: c,
  selected,
  sx,
  sy,
  s,
}: {
  o: LabelObject;
  color: Color | null;
  selected: boolean;
  sx: (x: number) => number;
  sy: (y: number) => number;
  s: number;
}) {
  const color = colorOf(c);
  const common = {
    fill: color,
    fillOpacity: selected ? 0.16 : 0.08,
    stroke: color,
    strokeWidth: selected ? 2 : 1.5,
    strokeDasharray: o.accepted ? undefined : "6 4",
  };
  if (o.type === "polygon" && o.points) {
    return <polygon points={o.points.map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ")} {...common} />;
  }
  const [x, y, w, h] = o.bbox;
  return <rect x={sx(x)} y={sy(y)} width={w * s} height={h * s} {...common} />;
}

function Handles({
  o,
  color: c,
  sx,
  sy,
}: {
  o: LabelObject;
  color: Color | null;
  sx: (x: number) => number;
  sy: (y: number) => number;
}) {
  const color = colorOf(c);
  const pts = o.type === "polygon" && o.points ? o.points : handlePoints(o.bbox);
  return (
    <g>
      {pts.map(([x, y], i) => (
        <rect key={i} x={sx(x) - 4} y={sy(y) - 4} width={8} height={8} rx={2} fill="#fff" stroke={color} strokeWidth={1.5} />
      ))}
    </g>
  );
}
