import { ApiError } from "@/lib/api-error";
import type {
  BulkRequest,
  Dataset,
  DatasetCreate,
  DatasetSummary,
  Health,
  Job,
  LabelingPatch,
  ReleaseResult,
  Sample,
  SampleRow,
  SampleSave,
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

export function imageUrl(dataset: string, id: string): string {
  return `/api/datasets/${dataset}/samples/${id}/image`;
}

export function thumbUrl(dataset: string, id: string): string {
  return `/api/datasets/${dataset}/samples/${id}/thumb`;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  health: () => request<Health>("/api/health"),

  listDatasets: () => request<DatasetSummary[]>("/api/datasets"),
  createDataset: (body: DatasetCreate) => request<Dataset>("/api/datasets", { method: "POST", body: json(body) }),
  getDataset: (name: string) => request<Dataset>(`/api/datasets/${name}`),
  updateLabeling: (name: string, body: LabelingPatch) =>
    request<Dataset>(`/api/datasets/${name}/labeling`, { method: "PATCH", body: json(body) }),

  listSamples: (name: string) => request<SampleRow[]>(`/api/datasets/${name}/samples`),
  getSample: (name: string, id: string) => request<Sample>(`/api/datasets/${name}/samples/${id}`),
  saveSample: (name: string, id: string, body: SampleSave) =>
    request<Sample>(`/api/datasets/${name}/samples/${id}`, { method: "PUT", body: json(body) }),
  bulk: (name: string, body: BulkRequest) =>
    request<{ updated: number }>(`/api/datasets/${name}/bulk`, { method: "POST", body: json(body) }),

  startImport: (name: string, source: string) =>
    request<Job>(`/api/datasets/${name}/imports`, { method: "POST", body: json({ source }) }),
  listImports: (name: string) => request<Job[]>(`/api/datasets/${name}/imports`),
  upload: (name: string, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
    return request<UploadResult>(`/api/datasets/${name}/uploads`, { method: "POST", body: form });
  },

  cutRelease: (name: string, notes: string) =>
    request<ReleaseResult>(`/api/datasets/${name}/releases`, { method: "POST", body: json({ notes }) }),
};
