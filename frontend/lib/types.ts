// Mirrors backend/app/schemas.py. UUIDs and datetimes arrive as strings
// (datetimes in ISO 8601).

export type UUID = string;
export type ISODateTime = string;

export type Platform = "twitch" | "youtube" | "chzzk";
export type ChannelStatus = "offline" | "live" | "error";
export type RecordingStatus = "recording" | "ending" | "finalizing" | "completed" | "failed";
export type SegmentStatus = "pending" | "uploading" | "uploaded" | "failed";

export interface TierOut {
  id: number;
  game_id: number;
  name: string;
  archived: boolean;
}

export interface GameOut {
  id: number;
  name: string;
  tiers: TierOut[];
}

export interface GameRef {
  id: number;
  name: string;
}

export interface ChannelOut {
  id: UUID;
  platform: Platform;
  platform_id: string;
  url: string;
  display_name: string;
  thumbnail_url: string | null;
  status: ChannelStatus;
  live_title: string | null;
  live_category: string | null;
  /** Set while live. */
  live_started_at: ISODateTime | null;
  last_live_ended_at: ISODateTime | null;
  last_checked_at: ISODateTime | null;
  check_failures: number;
  last_error: string | null;
  default_game: GameRef | null;
  default_tier: TierOut | null;
  /** Title and labels of the running recording, or of the most recent one when offline. */
  last_recording_title: string | null;
  last_recording_game: GameRef | null;
  last_recording_tier: TierOut | null;
  active_recording_id: UUID | null;
  created_at: ISODateTime;
}

export interface ChannelCreate {
  url: string;
}

export interface ChannelRef {
  id: UUID;
  platform: Platform;
  display_name: string;
  thumbnail_url: string | null;
}

export type LabelsSource = "manual" | "channel_default" | "suggested";

export interface RecordingOut {
  id: UUID;
  channel: ChannelRef;
  title: string;
  status: RecordingStatus;
  started_at: ISODateTime;
  ended_at: ISODateTime | null;
  duration_s: number;
  bytes_recorded: number;
  chat_messages: number;
  /** Closed video segments. */
  segments_closed: number;
  /** Uploaded video segments. */
  segments_uploaded: number;
  gcs_uri: string;
  gcs_console_url: string;
  game: GameRef | null;
  tier: TierOut | null;
  labels_source: LabelsSource | null;
  last_error: string | null;
  purged_at: ISODateTime | null;
  delete_at: ISODateTime;
}

export interface SegmentOut {
  kind: "video" | "chat";
  seq: number;
  start_s: number | null;
  end_s: number | null;
  size_bytes: number;
  status: SegmentStatus;
  attempts: number;
  uploaded_at: ISODateTime | null;
}

export interface ChatMinuteOut {
  minute: number;
  messages: number;
  unique_chatters: number;
  paid_messages: number;
}

export interface RecordingDetailOut extends RecordingOut {
  platform_stream_id: string | null;
  quality: string | null;
  chat_offset_s: number;
  segments: SegmentOut[];
  chat_minutes: ChatMinuteOut[];
}

export interface RecordingPage {
  items: RecordingOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface RecordingLabels {
  game_id: number | null;
  tier_id: number | null;
}

export interface GameCreate {
  name: string;
}

export interface TierCreate {
  game_id: number;
  name: string;
}

export interface TierUpdate {
  name?: string | null;
  archived?: boolean | null;
}

export interface HealthOut {
  poll_last_run_at: ISODateTime | null;
  next_poll_in_s: number | null;
  spool_free_bytes: number;
  upload_backlog: number;
  tracked_count: number;
  max_channels: number;
  live_count: number;
  recording_count: number;
  chat_messages_active: number;
  bytes_active: number;
}

/** Query parameters of GET /api/recordings. */
export interface RecordingQuery {
  status?: "active" | "completed";
  game_id?: number | null;
  tier_id?: number | null;
  page?: number;
  page_size?: number;
}

export const ACTIVE_STATUSES: readonly RecordingStatus[] = ["recording", "ending", "finalizing"];

export function isActiveRecording(status: RecordingStatus): boolean {
  return ACTIVE_STATUSES.includes(status);
}
