import { ApiError } from "@/lib/api-error";
import { mockApi } from "@/lib/mocks";
import type {
  ChannelOut,
  GameOut,
  HealthOut,
  RecordingDetailOut,
  RecordingLabels,
  RecordingOut,
  RecordingPage,
  RecordingQuery,
  TierOut,
  TierUpdate,
} from "@/lib/types";

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

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
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(0, "Can't reach the recorder backend.");
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

  if (res.status === 204 || res.status === 202) {
    // 202 may or may not carry a body; callers of these endpoints ignore it.
    return undefined as T;
  }
  return (await res.json()) as T;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

const httpApi = {
  listChannels: () => request<ChannelOut[]>("/api/channels"),
  addChannel: (url: string) =>
    request<ChannelOut>("/api/channels", { method: "POST", body: JSON.stringify({ url }) }),
  removeChannel: (id: string, stopRecording = false) =>
    request<void>(`/api/channels/${id}${stopRecording ? "?stop_recording=true" : ""}`, {
      method: "DELETE",
    }),

  listRecordings: (q: RecordingQuery) =>
    request<RecordingPage>(
      `/api/recordings${query({
        status: q.status,
        game_id: q.game_id,
        tier_id: q.tier_id,
        page: q.page ?? 1,
        page_size: q.page_size ?? 20,
      })}`,
    ),
  getRecording: (id: string) => request<RecordingDetailOut>(`/api/recordings/${id}`),
  stopRecording: (id: string) => request<void>(`/api/recordings/${id}/stop`, { method: "POST" }),
  updateLabels: (id: string, labels: RecordingLabels) =>
    request<RecordingOut>(`/api/recordings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(labels),
    }),

  listGames: () => request<GameOut[]>("/api/games"),
  createGame: (name: string) =>
    request<GameOut>("/api/games", { method: "POST", body: JSON.stringify({ name }) }),
  createTier: (gameId: number, name: string) =>
    request<TierOut>("/api/tiers", {
      method: "POST",
      body: JSON.stringify({ game_id: gameId, name }),
    }),
  updateTier: (id: number, patch: TierUpdate) =>
    request<TierOut>(`/api/tiers/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  health: () => request<HealthOut>("/api/health"),
};

export type Api = typeof httpApi;

export const api: Api = USE_MOCKS ? mockApi : httpApi;
