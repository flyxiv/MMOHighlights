// Mirrors labeler/backend/app/schemas.py. Label data follows the uniform dataset format
// (datasets/STRUCTURE.md in RaidDesigner): {task: {type, value}}, class names, absolute-pixel xyxy.

export const COLORS = ["red", "orange", "amber", "green", "cyan", "blue", "violet", "pink"] as const;
export type Color = (typeof COLORS)[number];

export type LabelType =
  | "class"
  | "multilabel"
  | "bbox"
  | "polygon"
  | "mask"
  | "keypoints"
  | "span"
  | "scalar"
  | "text"
  | "ref";
export const EDITABLE_TYPES = ["class", "multilabel", "bbox", "polygon"] as const;
export type EditableType = (typeof EDITABLE_TYPES)[number];
export type Status = "todo" | "review" | "done" | "excluded";

export interface TaskSpec {
  type: LabelType;
  unit?: string | null;
  description?: string | null;
}

export interface Stats {
  total: number;
  todo: number;
  review: number;
  done: number;
  excluded: number;
  new: number;
  edited_not_done: number;
  class_counts: Record<string, Record<string, number>>;
}

export interface Dataset {
  name: string;
  title: string;
  description: string | null;
  tasks: Record<string, TaskSpec>;
  classes: Record<string, string[]>;
  base_release: string | null;
  latest: string | null;
  releases: string[];
  next_release: string;
  storage_uri: string;
  stats: Stats;
  pending_sync: number;
}

export interface DatasetSummary {
  name: string;
  title: string;
  tasks: Record<string, TaskSpec>;
  latest: string | null;
  samples: number | null;
  labeling: boolean;
  created: string | null;
}

export interface DatasetCreate {
  name: string;
  title: string;
  description?: string;
  modality?: string[];
  license?: string;
  project?: string;
  tags?: string[];
  tasks: Record<string, TaskSpec>;
  classes: Record<string, string[]>;
}

export interface LabelingPatch {
  tasks?: Record<string, TaskSpec>;
  classes?: Record<string, string[]>;
}

/** A label as stored: {type, value}. */
export interface Label {
  type: LabelType;
  value: unknown;
}
export type Labels = Record<string, Label>;

export interface SampleRow {
  id: string;
  name: string;
  status: Status;
  objects: number;
  suggested: number;
  labels: Record<string, string | string[]>;
  split: string;
  new: boolean;
  reviewed: boolean;
}

export interface Sample {
  id: string;
  name: string;
  image: string;
  width: number;
  height: number;
  status: Status;
  labels: Labels;
  suggestions: Labels;
  split: string;
  new: boolean;
  meta: Record<string, unknown>;
  updated_at: string | null;
}

export interface SampleSave {
  status: Status;
  labels: Labels;
  suggestions: Labels;
}

// ---- editor model

export type BBox = [number, number, number, number]; // x, y, width, height (converted from xyxy)
export type Point = [number, number];

export interface LabelObject {
  id: string;
  task: string;
  cls: string;
  type: "box" | "polygon";
  bbox: BBox;
  points?: Point[] | null;
  source: "manual" | "model";
  score?: number | null;
  accepted: boolean;
}

export interface EditorDoc {
  status: Status;
  /** class tasks -> value, multilabel tasks -> values */
  choices: Record<string, string | string[]>;
  objects: LabelObject[];
}

export interface Job {
  id: string;
  dataset: string;
  state: "running" | "done" | "failed";
  source: string;
  total: number;
  processed: number;
  added: number;
  skipped: number;
  errors: string[];
  message: string | null;
}

export interface UploadResult {
  added: number;
  skipped: number;
  errors: string[];
}

export interface BulkRequest {
  ids: string[];
  labels?: Record<string, string | string[] | null>;
  status?: Status;
}

export interface ReleaseResult {
  version: string;
  uri: string;
  samples: number;
  reviewed: number;
  splits: Record<string, number>;
  warnings: string[];
}

export interface Health {
  storage: string;
  pending_sync: number;
  last_sync_error: string | null;
}
