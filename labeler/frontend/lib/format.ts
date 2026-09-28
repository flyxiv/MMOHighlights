import { COLORS, type Color, type Dataset, type LabelType } from "@/lib/types";

const nf = new Intl.NumberFormat("en-US");

export function formatNumber(n: number): string {
  return nf.format(n);
}

export function labelColor(color: Color): string {
  return `var(--label-${color})`;
}

/** Text on a solid label colour: dark on the light hues, white otherwise. */
export function labelInk(color: Color): string {
  return color === "amber" || color === "cyan" || color === "green" ? "#18181b" : "#ffffff";
}

export const TYPE_NAMES: Record<LabelType, string> = {
  class: "Class",
  multilabel: "Tags",
  bbox: "Boxes",
  polygon: "Polygons",
  mask: "Mask",
  keypoints: "Keypoints",
  span: "Spans",
  scalar: "Number",
  text: "Text",
  ref: "Reference",
};

/** Colour of a class: its position in the task's vocabulary, so it's stable across sessions. */
export function classColor(dataset: Pick<Dataset, "classes">, task: string, cls: string): Color | null {
  const i = dataset.classes[task]?.indexOf(cls) ?? -1;
  return i >= 0 ? COLORS[i % COLORS.length] : null;
}

export const UNKNOWN_COLOR = "#a1a1aa";

export function colorOf(color: Color | null): string {
  return color ? labelColor(color) : UNKNOWN_COLOR;
}

/** Hotkeys for the classes of the first image-level task with up to 8 of them. */
export const GROUP_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i"] as const;

/** Image-level tasks with this many classes or fewer render as chips; more become a select. */
export const CHIP_LIMIT = 8;

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 10);
}
