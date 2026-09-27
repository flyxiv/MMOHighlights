const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function toMs(value: string | number | Date): number {
  if (typeof value === "number") return value;
  if (value instanceof Date) return value.getTime();
  return new Date(value).getTime();
}

/** Clock-style duration: "1:12:40", "0:22:15". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

/** Compact duration for badges: "1h 12m", "22m", "45 s". */
export function formatShortDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h === 0) return `${m}m`;
  if (h >= 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  return `${h}h ${m}m`;
}

/** Minute offset as "h:mm", e.g. minute 18 -> "0:18", minute 75 -> "1:15". */
export function formatMinuteOffset(minute: number): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

/** Decimal (SI) byte sizes: "4.1 GB", "281 GB", "512 MB". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit++;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

/** "4 s ago", "3 min ago", "3h ago", "2d ago". */
export function formatRelative(value: string | number | Date, now: number): string {
  const diff = Math.max(0, now - toMs(value));
  if (diff < MINUTE) return `${Math.floor(diff / SECOND)} s ago`;
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} min ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  return `${Math.floor(diff / DAY)}d ago`;
}

/** Future relative in days: "in 88 days", "in 1 day", "today". */
export function formatInDays(value: string | number | Date, now: number): string {
  const diff = toMs(value) - now;
  if (diff <= 0) return "today";
  const days = Math.ceil(diff / DAY);
  if (days <= 1) return diff < DAY / 2 ? "today" : "in 1 day";
  return `in ${days} days`;
}

export function daysSince(value: string | number | Date, now: number): number {
  return (now - toMs(value)) / DAY;
}

/** Local date + time: "Sep 25, 09:14". */
export function formatDateTime(value: string | number | Date): string {
  const d = new Date(toMs(value));
  const date = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${date}, ${time}`;
}

/** Local date: "Sep 20". */
export function formatDate(value: string | number | Date): string {
  return new Date(toMs(value)).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function secondsBetween(from: string | number | Date, to: number): number {
  return Math.max(0, (to - toMs(from)) / SECOND);
}

/** "+8.4 s (video behind chat)". Positive offset means the video lags the chat. */
export function formatChatOffset(offsetS: number): string {
  const abs = Math.abs(offsetS).toFixed(1);
  if (Math.abs(offsetS) < 0.05) return "0.0 s (in sync)";
  return offsetS > 0 ? `+${abs} s (video behind chat)` : `−${abs} s (video ahead of chat)`;
}

/** Initials for avatar fallbacks. Hangul/CJK names use their first character. */
export function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const first = trimmed[0];
  if (/[^\u0000-ɏ]/.test(first)) return first;
  const words = trimmed.split(/[\s_\-.]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

/**
 * Elapsed recording time. While status is "recording" it ticks from started_at;
 * otherwise the server's duration_s is authoritative.
 */
export function recordingElapsed(
  rec: { status: string; started_at: string; duration_s: number },
  now: number,
): number {
  if (rec.status === "recording" && now) {
    return Math.max(rec.duration_s, secondsBetween(rec.started_at, now));
  }
  return rec.duration_s;
}
