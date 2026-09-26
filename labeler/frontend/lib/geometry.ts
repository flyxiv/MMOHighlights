import type { BBox, LabelObject, Point } from "@/lib/types";

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

export function boxFromPoints(a: Point, b: Point): BBox {
  const x = Math.min(a[0], b[0]);
  const y = Math.min(a[1], b[1]);
  return [x, y, Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
}

export function polygonBBox(points: Point[]): BBox {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return [x, y, Math.max(...xs) - x, Math.max(...ys) - y];
}

export function roundBox([x, y, w, h]: BBox): BBox {
  const x0 = Math.round(x);
  const y0 = Math.round(y);
  return [x0, y0, Math.round(x + w) - x0, Math.round(y + h) - y0];
}

export function pointInPolygon([px, py]: Point, pts: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The object under an image point: the smallest one containing it, so nested boxes stay reachable. */
export function hitObject(objects: LabelObject[], p: Point, tolerance: number): LabelObject | null {
  let best: LabelObject | null = null;
  let bestArea = Infinity;
  for (const o of objects) {
    const [x, y, w, h] = o.bbox;
    const inBox =
      p[0] >= x - tolerance && p[0] <= x + w + tolerance && p[1] >= y - tolerance && p[1] <= y + h + tolerance;
    if (!inBox) continue;
    if (o.type === "polygon" && o.points && !pointInPolygon(p, o.points)) continue;
    const area = w * h;
    if (area < bestArea) {
      best = o;
      bestArea = area;
    }
  }
  return best;
}

/** Resize handles, clockwise from top-left: 0 TL, 1 T, 2 TR, 3 R, 4 BR, 5 B, 6 BL, 7 L. */
export function handlePoints([x, y, w, h]: BBox): Point[] {
  return [
    [x, y],
    [x + w / 2, y],
    [x + w, y],
    [x + w, y + h / 2],
    [x + w, y + h],
    [x + w / 2, y + h],
    [x, y + h],
    [x, y + h / 2],
  ];
}

export const HANDLE_CURSORS = [
  "nwse-resize",
  "ns-resize",
  "nesw-resize",
  "ew-resize",
  "nwse-resize",
  "ns-resize",
  "nesw-resize",
  "ew-resize",
];

/** Move one handle to p, keeping the opposite side fixed; flips cleanly past the other edge. */
export function resizeBox(orig: BBox, handle: number, p: Point): BBox {
  let [x0, y0] = [orig[0], orig[1]];
  let [x1, y1] = [orig[0] + orig[2], orig[1] + orig[3]];
  if (handle === 0 || handle === 6 || handle === 7) x0 = p[0];
  if (handle === 2 || handle === 3 || handle === 4) x1 = p[0];
  if (handle === 0 || handle === 1 || handle === 2) y0 = p[1];
  if (handle === 4 || handle === 5 || handle === 6) y1 = p[1];
  return boxFromPoints([x0, y0], [x1, y1]);
}

export function clampBoxToImage([x, y, w, h]: BBox, iw: number, ih: number): BBox {
  const x0 = clamp(x, 0, iw);
  const y0 = clamp(y, 0, ih);
  return [x0, y0, clamp(x + w, 0, iw) - x0, clamp(y + h, 0, ih) - y0];
}

/** Move an object by (dx, dy), stopping at the image edges. */
export function translateObject(o: LabelObject, dx: number, dy: number, iw: number, ih: number): LabelObject {
  const [x, y, w, h] = o.bbox;
  const cdx = clamp(dx, -x, iw - (x + w));
  const cdy = clamp(dy, -y, ih - (y + h));
  if (o.type === "polygon" && o.points) {
    const points = o.points.map(([px, py]) => [px + cdx, py + cdy] as Point);
    return { ...o, points, bbox: polygonBBox(points) };
  }
  return { ...o, bbox: [x + cdx, y + cdy, w, h] };
}
