// In-memory fixtures used when NEXT_PUBLIC_USE_MOCKS=1. All channel names are fictional.
// Mutations change the fixtures and emit the same events the backend's /api/events stream would.

import { ApiError } from "@/lib/api-error";
import type { Api } from "@/lib/api";
import type {
  ChannelOut,
  ChatMinuteOut,
  GameOut,
  GameRef,
  HealthOut,
  Platform,
  RecordingDetailOut,
  RecordingLabels,
  RecordingOut,
  RecordingPage,
  RecordingQuery,
  SegmentOut,
  TierOut,
  TierUpdate,
} from "@/lib/types";
import { isActiveRecording } from "@/lib/types";

const SEC = 1000;
const MIN = 60 * SEC;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const SEGMENT_S = 300;
const MAX_CHANNELS = 10;

const BUCKET = "mmohighlights";
const PREFIX = "archives";

// ---------------------------------------------------------------------------
// Fixture construction

const T0 = Date.now();
const iso = (ms: number) => new Date(ms).toISOString();

let uuidCounter = 0;
function uuid(): string {
  uuidCounter++;
  const hex = (uuidCounter * 2654435761).toString(16).padStart(8, "0").slice(-8);
  return `${hex}-4a1b-4c2d-9e3f-${String(uuidCounter).padStart(12, "0")}`;
}

/** Deterministic PRNG so fixtures look the same on every reload. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

const games: GameOut[] = [
  {
    id: 1,
    name: "WoW",
    tiers: [
      { id: 1, game_id: 1, name: "Curse of U'latek", archived: false },
      { id: 2, game_id: 1, name: "Mythic+ Season 3", archived: false },
    ],
  },
  {
    id: 2,
    name: "FFXIV",
    tiers: [
      { id: 3, game_id: 2, name: "Kefka Ultimate", archived: false },
      { id: 4, game_id: 2, name: "Heavyweight Savage", archived: false },
      { id: 5, game_id: 2, name: "Omega Protocol Ultimate", archived: true },
    ],
  },
];
let nextGameId = 3;
let nextTierId = 6;

const gameRef = (id: number): GameRef => {
  const g = games.find((x) => x.id === id)!;
  return { id: g.id, name: g.name };
};
const tierRef = (id: number): TierOut => {
  for (const g of games) {
    const t = g.tiers.find((x) => x.id === id);
    if (t) return { ...t };
  }
  throw new Error(`unknown tier ${id}`);
};

interface ChannelSeed {
  platform: Platform;
  platform_id: string;
  url: string;
  display_name: string;
}

function makeChannel(seed: ChannelSeed, extra: Partial<ChannelOut> = {}): ChannelOut {
  return {
    id: uuid(),
    platform: seed.platform,
    platform_id: seed.platform_id,
    url: seed.url,
    display_name: seed.display_name,
    thumbnail_url: null,
    status: "offline",
    live_title: null,
    live_category: null,
    live_started_at: null,
    last_live_ended_at: null,
    last_checked_at: iso(T0 - 4 * SEC),
    check_failures: 0,
    last_error: null,
    default_game: null,
    default_tier: null,
    last_recording_title: null,
    last_recording_game: null,
    last_recording_tier: null,
    active_recording_id: null,
    created_at: iso(T0 - 40 * DAY),
    ...extra,
  };
}

const channels: ChannelOut[] = [
  makeChannel(
    {
      platform: "twitch",
      platform_id: "raidcaller_jin",
      url: "https://twitch.tv/raidcaller_jin",
      display_name: "raidcaller_jin",
    },
    { default_game: gameRef(2), default_tier: tierRef(3) },
  ),
  makeChannel({
    platform: "chzzk",
    platform_id: "8a1f3c9e5b7d4e2fa0c1d2e3f4a5b6c7",
    url: "https://chzzk.naver.com/8a1f3c9e5b7d4e2fa0c1d2e3f4a5b6c7",
    display_name: "노을레이드",
  }),
  makeChannel({
    platform: "youtube",
    platform_id: "UCaetherwatch000000000",
    url: "https://youtube.com/@aetherwatch",
    display_name: "Aether Watch",
  }),
  makeChannel(
    {
      platform: "twitch",
      platform_id: "tankdiff_mina",
      url: "https://twitch.tv/tankdiff_mina",
      display_name: "tankdiff_mina",
    },
    { last_live_ended_at: iso(T0 - 3 * HOUR - 12 * MIN) },
  ),
  makeChannel(
    {
      platform: "chzzk",
      platform_id: "c02b77d1e9f84a3b8c6d5e4f3a2b1c0d",
      url: "https://chzzk.naver.com/c02b77d1e9f84a3b8c6d5e4f3a2b1c0d",
      display_name: "은하길드",
    },
    { last_live_ended_at: iso(T0 - 2 * DAY - 2 * HOUR) },
  ),
  makeChannel(
    {
      platform: "youtube",
      platform_id: "UCdpscheck0000000000000",
      url: "https://youtube.com/@dpscheck",
      display_name: "dpscheck",
    },
    {
      status: "error",
      check_failures: 3,
      last_error: "Last check timed out. Retrying every 30 s",
      last_checked_at: iso(T0 - 64 * SEC),
      last_live_ended_at: iso(T0 - 95 * DAY + 4 * HOUR),
    },
  ),
  makeChannel(
    {
      platform: "twitch",
      platform_id: "healbot_sora",
      url: "https://twitch.tv/healbot_sora",
      display_name: "healbot_sora",
    },
    { created_at: iso(T0 - 1 * DAY) },
  ),
];

const byName = (name: string) => channels.find((c) => c.display_name === name)!;

interface RecordingSeed {
  channel: string;
  title: string;
  status: RecordingOut["status"];
  startedAgo: number;
  durationS: number;
  bytes: number;
  chat: number;
  game?: number;
  tier?: number;
  lastError?: string;
  purgedAgo?: number;
  quality?: string;
}

const records: RecordingDetailOut[] = [];

function datePath(ms: number) {
  return new Date(ms).toISOString().slice(0, 10);
}

function makeRecording(seed: RecordingSeed): RecordingDetailOut {
  const ch = byName(seed.channel);
  const id = uuid();
  const startedMs = T0 - seed.startedAgo;
  const active = isActiveRecording(seed.status);
  const endedMs = active ? null : startedMs + seed.durationS * SEC;
  const path = `${PREFIX}/${ch.platform}/${ch.platform_id}/${datePath(startedMs)}_${id.slice(0, 8)}`;
  const closed = Math.floor(seed.durationS / SEGMENT_S);
  const rec: RecordingDetailOut = {
    id,
    channel: {
      id: ch.id,
      platform: ch.platform,
      display_name: ch.display_name,
      thumbnail_url: ch.thumbnail_url,
    },
    title: seed.title,
    status: seed.status,
    started_at: iso(startedMs),
    ended_at: endedMs === null ? null : iso(endedMs),
    duration_s: seed.durationS,
    bytes_recorded: seed.purgedAgo ? 0 : seed.bytes,
    chat_messages: seed.chat,
    segments_closed: closed,
    segments_uploaded: active ? Math.max(0, closed - 1) : closed,
    gcs_uri: `gs://${BUCKET}/${path}/`,
    gcs_console_url: `https://console.cloud.google.com/storage/browser/${BUCKET}/${path}`,
    game: seed.game ? gameRef(seed.game) : null,
    tier: seed.tier ? tierRef(seed.tier) : null,
    labels_source: seed.game ? "manual" : null,
    last_error: seed.lastError ?? null,
    purged_at: seed.purgedAgo ? iso(T0 - seed.purgedAgo) : null,
    delete_at: iso((endedMs ?? T0) + 90 * DAY),
    platform_stream_id: `${ch.platform === "youtube" ? "v" : ""}${(startedMs / 1000).toFixed(0)}`,
    quality: seed.quality ?? (ch.platform === "youtube" ? "1080p60 · 6.0 Mbps" : "1080p60 · 8.0 Mbps"),
    chat_offset_s: ch.platform === "twitch" ? 8.4 : ch.platform === "chzzk" ? 5.1 : 11.2,
    segments: [],
    chat_minutes: [],
  };
  rec.segments = buildSegments(rec);
  rec.chat_minutes = buildChatMinutes(rec);
  return rec;
}

function buildSegments(rec: RecordingDetailOut): SegmentOut[] {
  const active = isActiveRecording(rec.status);
  const segs: SegmentOut[] = [];
  const total = rec.segments_closed + (active ? 1 : 0);
  const perSeg = rec.segments_closed > 0 ? rec.bytes_recorded / Math.max(1, rec.segments_closed) : 0;
  const failedSeqs = rec.status === "failed" ? new Set([total - 2, total - 1]) : new Set<number>();
  for (let seq = 0; seq < total; seq++) {
    const writing = active && seq === rec.segments_closed;
    const uploading = !writing && seq >= rec.segments_uploaded && active;
    const failed = failedSeqs.has(seq);
    const start = seq * SEGMENT_S;
    const end = writing ? null : Math.min(rec.duration_s, (seq + 1) * SEGMENT_S);
    const uploadedAt = iso(new Date(rec.started_at).getTime() + (start + SEGMENT_S + 20) * SEC);
    for (const kind of ["video", "chat"] as const) {
      const status: SegmentOut["status"] = writing
        ? "pending"
        : failed
          ? "failed"
          : uploading
            ? "uploading"
            : "uploaded";
      segs.push({
        kind,
        seq,
        start_s: start,
        end_s: end,
        size_bytes: Math.round(kind === "video" ? perSeg : perSeg / 900),
        status,
        attempts: failed ? 5 : status === "uploaded" ? 1 : status === "uploading" ? 1 : 0,
        uploaded_at: status === "uploaded" ? uploadedAt : null,
      });
    }
  }
  return segs;
}

function buildChatMinutes(rec: RecordingDetailOut): ChatMinuteOut[] {
  const n = Math.max(1, Math.floor(rec.duration_s / 60));
  const rand = rng(n * 31 + rec.chat_messages);
  const peaks = [0.18, 0.52, 0.81].map((f) => Math.min(n - 1, Math.round(f * n)));
  const weights: number[] = [];
  for (let m = 0; m < n; m++) {
    let w = 0.7 + rand() * 0.6;
    peaks.forEach((p, i) => {
      const dist = Math.abs(m - p);
      const height = [3.4, 2.6, 3.0][i];
      if (dist <= 2) w += height * (1 - dist * 0.35);
    });
    weights.push(w);
  }
  const sum = weights.reduce((a, b) => a + b, 0);
  return weights.map((w, minute) => {
    const messages = Math.round((w / sum) * rec.chat_messages);
    return {
      minute,
      messages,
      unique_chatters: Math.round(messages * (0.35 + rand() * 0.15)),
      paid_messages: rand() < 0.08 ? 1 + Math.floor(rand() * 4) : 0,
    };
  });
}

// Active recordings.
records.push(
  makeRecording({
    channel: "raidcaller_jin",
    title: "Kefka Ultimate prog — day 3",
    status: "recording",
    startedAgo: 1 * HOUR + 12 * MIN + 40 * SEC,
    durationS: 4360,
    bytes: 4.1e9,
    chat: 18204,
    game: 2,
    tier: 3,
  }),
  makeRecording({
    channel: "노을레이드",
    title: "레이드 클리어 방송",
    status: "ending",
    startedAgo: 5 * HOUR + 51 * MIN,
    durationS: 5 * 3600 + 48 * 60 + 2,
    bytes: 19.7e9,
    chat: 96511,
    game: 1,
    tier: 1,
  }),
  makeRecording({
    channel: "Aether Watch",
    title: "Patch 8.1 first look — all new jobs",
    status: "recording",
    startedAgo: 22 * MIN + 15 * SEC,
    durationS: 1335,
    bytes: 1.3e9,
    chat: 2240,
    game: 2,
  }),
);
// The "ending" recording went offline 3 minutes ago.
records[1].ended_at = iso(T0 - 3 * MIN);

// Completed recordings.
records.push(
  makeRecording({
    channel: "tankdiff_mina",
    title: "Kefka Ultimate farm night",
    status: "completed",
    startedAgo: 3 * HOUR + 12 * MIN + (4 * 3600 + 2 * 60 + 51) * SEC,
    durationS: 4 * 3600 + 2 * 60 + 51,
    bytes: 13.9e9,
    chat: 41388,
    game: 2,
    tier: 3,
  }),
  makeRecording({
    channel: "은하길드",
    title: "신규 레이드 공략",
    status: "completed",
    startedAgo: 2 * DAY + 8 * HOUR + 11 * MIN,
    durationS: 6 * 3600 + 11 * 60 + 7,
    bytes: 21.3e9,
    chat: 128904,
    game: 1,
    tier: 1,
  }),
  makeRecording({
    channel: "raidcaller_jin",
    title: "Kefka Ultimate prog — day 2",
    status: "completed",
    startedAgo: 2 * DAY + 10 * HOUR,
    durationS: 5 * 3600 + 26 * 60 + 40,
    bytes: 18.8e9,
    chat: 52117,
    game: 2,
    tier: 3,
  }),
  makeRecording({
    channel: "Aether Watch",
    title: "Live letter recap",
    status: "failed",
    startedAgo: 4 * DAY + 3 * HOUR,
    durationS: 3 * 3600 + 3 * 60 + 12,
    bytes: 3.6e9,
    chat: 5902,
    game: 2,
    lastError: "2 segments lost. Upload failed after 5 attempts.",
  }),
  makeRecording({
    channel: "노을레이드",
    title: "주말 레이드",
    status: "completed",
    startedAgo: 36 * DAY + 2 * HOUR,
    durationS: 7 * 3600 + 45 * 60 + 19,
    bytes: 27.0e9,
    chat: 143550,
    game: 1,
    tier: 1,
  }),
  makeRecording({
    channel: "dpscheck",
    title: "Week 1 clears",
    status: "completed",
    startedAgo: 95 * DAY,
    durationS: 3 * 3600 + 40 * 60,
    bytes: 11.2e9,
    chat: 22015,
    game: 1,
    purgedAgo: 5 * DAY,
  }),
);
// Expired recordings were purged; their deletion date is in the past.
records[records.length - 1].delete_at = iso(T0 - 5 * DAY);

// Wire the channels to their recordings.
function syncChannelFromRecordings(ch: ChannelOut) {
  const own = records
    .filter((r) => r.channel.id === ch.id)
    .sort((a, b) => b.started_at.localeCompare(a.started_at));
  const active = own.find((r) => isActiveRecording(r.status));
  const latest = active ?? own[0];
  ch.active_recording_id = active?.id ?? null;
  ch.last_recording_title = latest?.title ?? null;
  ch.last_recording_game = latest?.game ?? null;
  ch.last_recording_tier = latest?.tier ?? null;
  if (active && ch.status !== "error") {
    ch.status = "live";
    ch.live_title = active.title;
    ch.live_started_at = active.started_at;
  }
}
channels.forEach(syncChannelFromRecordings);
// 노을레이드's recording is "ending": the channel is still reported live during the grace period.
byName("노을레이드").live_started_at = records[1].started_at;

// ---------------------------------------------------------------------------
// Event emitter (stands in for GET /api/events)

export type MockEventHandler = (event: string, data: unknown) => void;
const handlers = new Set<MockEventHandler>();
let ticker: ReturnType<typeof setInterval> | null = null;
let tickCount = 0;

function emit(event: string, data: unknown) {
  const payload = structuredClone(data);
  handlers.forEach((h) => h(event, payload));
}

function toOut(rec: RecordingDetailOut): RecordingOut {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { segments, chat_minutes, platform_stream_id, quality, chat_offset_s, ...out } = rec;
  return out;
}

function tick() {
  tickCount++;
  const now = Date.now();
  for (const rec of records) {
    if (rec.status !== "recording") continue;
    const rand = rng(now + rec.chat_messages);
    rec.duration_s = (now - new Date(rec.started_at).getTime()) / 1000;
    rec.bytes_recorded += Math.round(2 * (0.9e6 + rand() * 0.2e6));
    const newMsgs = Math.round(rand() * 40);
    rec.chat_messages += newMsgs;
    const closed = Math.floor(rec.duration_s / SEGMENT_S);
    if (closed !== rec.segments_closed) {
      rec.segments_closed = closed;
      rec.segments = buildSegments(rec);
    }
    if (rec.segments_uploaded < rec.segments_closed && rand() < 0.3) {
      rec.segments_uploaded = rec.segments_closed;
      rec.segments = buildSegments(rec);
    }
    const last = rec.chat_minutes[rec.chat_minutes.length - 1];
    const minute = Math.floor(rec.duration_s / 60);
    if (last && last.minute === minute) last.messages += newMsgs;
    else rec.chat_minutes.push({ minute, messages: newMsgs, unique_chatters: newMsgs, paid_messages: 0 });
    emit("recording.updated", toOut(rec));
  }
  // Simulate the 30 s poller touching every healthy channel.
  const sincePoll = now % (30 * SEC);
  if (sincePoll < 2 * SEC) {
    for (const ch of channels) {
      if (ch.check_failures >= 3) continue;
      ch.last_checked_at = iso(now - sincePoll);
      emit("channel.updated", ch);
    }
  }
  if (tickCount % 5 === 0) emit("health", buildHealth());
}

export const mockEvents = {
  subscribe(handler: MockEventHandler): () => void {
    handlers.add(handler);
    if (!ticker) ticker = setInterval(tick, 2000);
    handler("health", buildHealth());
    return () => {
      handlers.delete(handler);
      if (handlers.size === 0 && ticker) {
        clearInterval(ticker);
        ticker = null;
      }
    };
  },
};

// ---------------------------------------------------------------------------
// API implementation

function delay<T>(value: T, ms = 180 + Math.random() * 220): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(structuredClone(value)), ms));
}

function fail(status: number, detail: string): Promise<never> {
  return new Promise((_, reject) => setTimeout(() => reject(new ApiError(status, detail)), 250));
}

function buildHealth(): HealthOut {
  const now = Date.now();
  const sincePoll = now % (30 * SEC);
  const active = records.filter((r) => isActiveRecording(r.status));
  return {
    poll_last_run_at: iso(now - sincePoll),
    next_poll_in_s: (30 * SEC - sincePoll) / 1000,
    spool_free_bytes: 281e9,
    upload_backlog: active.reduce((n, r) => n + (r.segments_closed - r.segments_uploaded), 0),
    tracked_count: channels.length,
    max_channels: MAX_CHANNELS,
    live_count: channels.filter((c) => c.status === "live").length,
    recording_count: active.length,
    chat_messages_active: active.reduce((n, r) => n + r.chat_messages, 0),
    bytes_active: active.reduce((n, r) => n + r.bytes_recorded, 0),
  };
}

function parseChannelUrl(raw: string): { platform: Platform; id: string; name: string; url: string } | null {
  let u: URL;
  try {
    u = new URL(/^https?:\/\//i.test(raw.trim()) ? raw.trim() : `https://${raw.trim()}`);
  } catch {
    return null;
  }
  const host = u.hostname.replace(/^(www|m)\./, "");
  const parts = u.pathname.split("/").filter(Boolean);
  if (host === "twitch.tv" && parts[0] && /^\w{3,25}$/.test(parts[0])) {
    const id = parts[0].toLowerCase();
    return { platform: "twitch", id, name: id, url: `https://twitch.tv/${id}` };
  }
  if (host === "youtube.com" && parts[0]?.startsWith("@")) {
    const handle = parts[0].slice(1);
    return { platform: "youtube", id: `UC${handle}`, name: handle, url: `https://youtube.com/@${handle}` };
  }
  if (host === "youtube.com" && parts[0] === "channel" && parts[1]) {
    return { platform: "youtube", id: parts[1], name: parts[1], url: `https://youtube.com/channel/${parts[1]}` };
  }
  if ((host === "chzzk.naver.com") && parts[0] && /^[0-9a-f]{32}$/i.test(parts[parts[0] === "live" ? 1 : 0] ?? "")) {
    const id = parts[parts[0] === "live" ? 1 : 0];
    return { platform: "chzzk", id, name: `치지직 ${id.slice(0, 6)}`, url: `https://chzzk.naver.com/${id}` };
  }
  return null;
}

function findRecording(id: string): RecordingDetailOut {
  const rec = records.find((r) => r.id === id);
  if (!rec) throw new ApiError(404, "Recording not found.");
  return rec;
}

function finishRecording(rec: RecordingDetailOut) {
  rec.status = "finalizing";
  rec.ended_at ??= iso(Date.now());
  emit("recording.updated", toOut(rec));
  setTimeout(() => {
    rec.status = "completed";
    rec.segments_closed = Math.ceil(rec.duration_s / SEGMENT_S);
    rec.segments_uploaded = rec.segments_closed;
    rec.segments = buildSegments(rec);
    rec.delete_at = iso(new Date(rec.ended_at!).getTime() + 90 * DAY);
    emit("recording.updated", toOut(rec));
    const ch = channels.find((c) => c.id === rec.channel.id);
    if (ch) {
      syncChannelFromRecordings(ch);
      emit("channel.updated", ch);
    }
    emit("health", buildHealth());
  }, 3500);
}

export const mockApi: Api = {
  listChannels: () => delay(channels),

  addChannel: (url: string) => {
    const parsed = parseChannelUrl(url);
    if (!parsed) {
      return fail(422, "That isn't a Twitch, YouTube or Chzzk channel URL.");
    }
    if (/notfound/i.test(parsed.id)) {
      return fail(422, `No ${parsed.platform === "youtube" ? "YouTube" : parsed.platform === "chzzk" ? "Chzzk" : "Twitch"} channel exists at that URL.`);
    }
    const existing = channels.find((c) => c.platform === parsed.platform && c.platform_id === parsed.id);
    if (existing) return fail(409, `${existing.display_name} is already tracked.`);
    if (channels.length >= MAX_CHANNELS) {
      return fail(422, `You can track up to ${MAX_CHANNELS} channels. Remove one to add another.`);
    }
    const ch = makeChannel(
      { platform: parsed.platform, platform_id: parsed.id, url: parsed.url, display_name: parsed.name },
      { created_at: iso(Date.now()), last_checked_at: iso(Date.now()) },
    );
    channels.push(ch);
    setTimeout(() => {
      emit("channel.updated", ch);
      emit("health", buildHealth());
    }, 400);
    return delay(ch);
  },

  removeChannel: (id: string, stopRecording = false) => {
    const idx = channels.findIndex((c) => c.id === id);
    if (idx < 0) return fail(404, "Channel not found.");
    const ch = channels[idx];
    const active = records.find((r) => r.channel.id === id && isActiveRecording(r.status));
    if (active && !stopRecording) {
      return fail(409, `${ch.display_name} is recording. Stop the recording before removing the channel.`);
    }
    channels.splice(idx, 1);
    if (active) finishRecording(active);
    setTimeout(() => {
      emit("channel.removed", { id });
      emit("health", buildHealth());
    }, 300);
    return delay(undefined);
  },

  listRecordings: (q: RecordingQuery) => {
    let items = [...records];
    if (q.status === "active") items = items.filter((r) => isActiveRecording(r.status));
    if (q.status === "completed") items = items.filter((r) => !isActiveRecording(r.status));
    if (q.game_id != null) items = items.filter((r) => r.game?.id === q.game_id);
    if (q.tier_id != null) items = items.filter((r) => r.tier?.id === q.tier_id);
    items.sort((a, b) => b.started_at.localeCompare(a.started_at));
    const page = q.page ?? 1;
    const pageSize = q.page_size ?? 20;
    const result: RecordingPage = {
      items: items.slice((page - 1) * pageSize, page * pageSize).map(toOut),
      total: items.length,
      page,
      page_size: pageSize,
    };
    return delay(result);
  },

  getRecording: (id: string) => {
    try {
      return delay(findRecording(id));
    } catch (e) {
      return Promise.reject(e);
    }
  },

  stopRecording: (id: string) => {
    const rec = records.find((r) => r.id === id);
    if (!rec) return fail(404, "Recording not found.");
    if (!isActiveRecording(rec.status)) return fail(409, "This recording has already stopped.");
    finishRecording(rec);
    return delay(undefined);
  },

  updateLabels: (id: string, labels: RecordingLabels) => {
    const rec = records.find((r) => r.id === id);
    if (!rec) return fail(404, "Recording not found.");
    const game = labels.game_id == null ? null : games.find((g) => g.id === labels.game_id);
    if (labels.game_id != null && !game) return fail(422, "Unknown game.");
    const tier = labels.tier_id == null ? null : game?.tiers.find((t) => t.id === labels.tier_id);
    if (labels.tier_id != null && !tier) return fail(422, "That tier doesn't belong to the selected game.");
    rec.game = game ? { id: game.id, name: game.name } : null;
    rec.tier = tier ? { ...tier } : null;
    rec.labels_source = game || tier ? "manual" : null;
    const ch = channels.find((c) => c.id === rec.channel.id);
    if (ch) {
      syncChannelFromRecordings(ch);
      emit("channel.updated", ch);
    }
    emit("recording.updated", toOut(rec));
    return delay(toOut(rec));
  },

  listGames: () => delay(games),

  createGame: (name: string) => {
    if (games.some((g) => g.name.toLowerCase() === name.trim().toLowerCase())) {
      return fail(409, `${name} already exists.`);
    }
    const g: GameOut = { id: nextGameId++, name: name.trim(), tiers: [] };
    games.push(g);
    return delay(g);
  },

  createTier: (gameId: number, name: string) => {
    const game = games.find((g) => g.id === gameId);
    if (!game) return fail(422, "Unknown game.");
    const trimmed = name.trim();
    if (!trimmed) return fail(422, "Tier name can't be empty.");
    if (game.tiers.some((t) => t.name.toLowerCase() === trimmed.toLowerCase())) {
      return fail(409, `${game.name} already has a tier called “${trimmed}”.`);
    }
    const tier: TierOut = { id: nextTierId++, game_id: gameId, name: trimmed, archived: false };
    game.tiers.push(tier);
    return delay(tier);
  },

  updateTier: (id: number, patch: TierUpdate) => {
    for (const g of games) {
      const t = g.tiers.find((x) => x.id === id);
      if (t) {
        if (patch.name != null) t.name = patch.name;
        if (patch.archived != null) t.archived = patch.archived;
        return delay(t);
      }
    }
    return fail(404, "Tier not found.");
  },

  health: () => delay(buildHealth(), 80),
};
