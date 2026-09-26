import { ApiError } from "@/lib/api-error";
import type {
  Annotation,
  AnnotationDoc,
  BulkRequest,
  ExportRequest,
  ExportResult,
  Health,
  ImageRow,
  Job,
  Project,
  ProjectCreate,
  ProjectPatch,
  ProjectSummary,
  UploadResult,
} from "@/lib/types";

export { ApiError, errorMessage } from "@/lib/api-error";

function detailFromBody(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{loc, msg, type}, ...]
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  const isForm = init?.body instanceof FormData;
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body && !isForm ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Can't reach the labeler backend.");
  }

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detailFromBody(body, `Request failed (${res.status}).`));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Encodes each path segment; image names may contain folders. */
export function filePath(file: string): string {
  return file.split("/").map(encodeURIComponent).join("/");
}

export function imageUrl(slug: string, file: string): string {
  return `/api/projects/${slug}/files/${filePath(file)}`;
}

export function thumbUrl(slug: string, file: string): string {
  return `/api/projects/${slug}/thumbs/${filePath(file)}`;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  health: () => request<Health>("/api/health"),

  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (body: ProjectCreate) =>
    request<Project>("/api/projects", { method: "POST", body: json(body) }),
  getProject: (slug: string) => request<Project>(`/api/projects/${slug}`),
  updateProject: (slug: string, body: ProjectPatch) =>
    request<Project>(`/api/projects/${slug}`, { method: "PATCH", body: json(body) }),

  listImages: (slug: string) => request<ImageRow[]>(`/api/projects/${slug}/images`),
  getAnnotation: (slug: string, file: string) =>
    request<Annotation>(`/api/projects/${slug}/annotations/${filePath(file)}`),
  saveAnnotation: (slug: string, file: string, doc: AnnotationDoc) =>
    request<Annotation>(`/api/projects/${slug}/annotations/${filePath(file)}`, {
      method: "PUT",
      body: json(doc),
    }),
  bulk: (slug: string, body: BulkRequest) =>
    request<{ updated: number }>(`/api/projects/${slug}/bulk`, { method: "POST", body: json(body) }),

  startImport: (slug: string, source: string) =>
    request<Job>(`/api/projects/${slug}/imports`, { method: "POST", body: json({ source }) }),
  listImports: (slug: string) => request<Job[]>(`/api/projects/${slug}/imports`),
  upload: (slug: string, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
    return request<UploadResult>(`/api/projects/${slug}/uploads`, { method: "POST", body: form });
  },

  exportProject: (slug: string, body: ExportRequest) =>
    request<ExportResult>(`/api/projects/${slug}/exports`, { method: "POST", body: json(body) }),
};
