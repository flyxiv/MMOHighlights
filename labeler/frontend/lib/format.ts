import type { Color, Task } from "@/lib/types";

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

export const TASK_NAMES: Record<Task, string> = {
  classification: "Classification",
  detection: "Detection",
  segmentation: "Segmentation",
};

export function tasksLabel(tasks: Task[]): string {
  return tasks.map((t) => TASK_NAMES[t]).join(" + ");
}

/** Hotkeys for the options of the first chip-style label group. */
export const GROUP_KEYS = ["q", "w", "e", "r", "t", "y", "u", "i"] as const;

/** Groups with this many options or fewer render as chips; more become a select. */
export const CHIP_LIMIT = 8;

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 10);
}
