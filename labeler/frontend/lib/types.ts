// Mirrors labeler/backend/app/schemas.py.

export const COLORS = ["red", "orange", "amber", "green", "cyan", "blue", "violet", "pink"] as const;
export type Color = (typeof COLORS)[number];
export type Task = "classification" | "detection" | "segmentation";
export type Status = "todo" | "done" | "review";

export interface LabelClass {
  id: number;
  name: string;
  color: Color;
}

export interface LabelGroup {
  name: string;
  options: string[];
}

export interface Stats {
  total: number;
  done: number;
  review: number;
  todo: number;
  class_counts: Record<string, number>;
}

export interface Project {
  slug: string;
  name: string;
  created_at: string;
  tasks: Task[];
  classes: LabelClass[];
  groups: LabelGroup[];
  image_count: number;
  storage_uri: string;
  stats: Stats;
  pending_sync: number;
}

export interface ProjectSummary {
  slug: string;
  name: string;
  tasks: Task[];
  created_at: string;
  image_count: number;
  classes: number;
  done: number | null;
}

export interface ClassIn {
  id?: number;
  name: string;
  color?: Color;
}

export interface ProjectCreate {
  name: string;
  tasks: Task[];
  classes: ClassIn[];
  groups: LabelGroup[];
}

export interface ProjectPatch {
  name?: string;
  tasks?: Task[];
  classes?: ClassIn[];
  groups?: LabelGroup[];
}

export type BBox = [number, number, number, number];
export type Point = [number, number];

export interface LabelObject {
  id: string;
  class_id: number;
  type: "box" | "polygon";
  bbox: BBox;
  points?: Point[] | null;
  source: "manual" | "model";
  score?: number | null;
  accepted: boolean;
}

export interface AnnotationDoc {
  status: Status;
  labels: Record<string, string>;
  objects: LabelObject[];
}

export interface Annotation extends AnnotationDoc {
  file: string;
  updated_at: string | null;
}

export interface ImageRow {
  file: string;
  width: number;
  height: number;
  status: Status;
  objects: number;
  suggested: number;
  labels: Record<string, string>;
}

export interface Job {
  id: string;
  slug: string;
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
  files: string[];
  labels?: Record<string, string | null>;
  status?: Status;
}

export interface ExportRequest {
  format: "yolo" | "coco";
  include_unfinished: boolean;
}

export interface ExportResult {
  uri: string;
  format: string;
  images: number;
  objects: number;
}

export interface Health {
  storage: string;
  pending_sync: number;
  last_sync_error: string | null;
}
