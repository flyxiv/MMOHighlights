# MMOHighlights

Records live streams from Twitch, YouTube and Chzzk so highlights can be cut from them later.

Tracked channels are checked every 30 seconds. When one goes live, the recorder captures the
stream (capped at 1080p) and its chat, and uploads both to `gs://mmohighlights/archives/` in
5-minute segments while the stream is still running. Recordings are labelled with a game
(WoW, FFXIV) and a content tier (e.g. Kefka Ultimate, Curse of U'latek), and kept for 90 days.

| Folder      | What                                                                       |
| ----------- | -------------------------------------------------------------------------- |
| `backend/`  | FastAPI service: poller, recorder (streamlink → ffmpeg), chat logger, uploader, API |
| `frontend/` | Next.js + shadcn/ui page: tracked channels, recordings, labels             |
| `deploy/`   | Docker Compose for one VM, bucket lifecycle rule, setup steps              |

Design: [Figma](https://www.figma.com/design/cCxNd3KwRKz1WepAoguxNF) · Issue [#1](https://github.com/flyxiv/MMOHighlights/issues/1)

## What ends up in the bucket

```
gs://mmohighlights/archives/<platform>/<channel id>/<YYYY-MM-DD>/<recording id>/
  seg_00000.ts …          5-minute MPEG-TS video segments (no re-encoding)
  chat_00000.jsonl.gz …   chat for the same 5 minutes, one JSON object per message
  index.m3u8              HLS playlist; the folder plays as a VOD
  manifest.json           title, times, game/tier labels, segment list
```

Each chat line has `t`, the second on the recording's video timeline the message belongs to
(already corrected for the video being a few seconds behind chat):

```json
{"t": 1834.52, "at": "2026-09-25T13:02:11.520+00:00", "user": "viewer", "text": "KEKW that wipe",
 "kind": "message", "badges": ["subscriber/12"], "amount": null}
```

`kind` is `message`, `paid` (bits, Super Chat, Chzzk donation; `amount` in the platform's unit),
`subscription`, or `gap` (chat connection dropped; missing chat is not a quiet stretch).
Per-minute message counts are also in the `chat_minutes` table.

## Local development

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, ffmpeg and PostgreSQL.

```sh
# backend
cd backend
cp .env.example .env           # set DATABASE_URL; STORAGE_BACKEND=local skips GCS
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# frontend (another terminal)
cd frontend
npm install
npm run dev                    # http://localhost:3000, /api is proxied to :8000
NEXT_PUBLIC_USE_MOCKS=1 npm run dev   # or run the page on fixture data, no backend
```

Tests: `cd backend && uv run pytest`. Database tests use `TEST_DATABASE_URL` (default
`postgresql+asyncpg://recorder:recorder@localhost:5433/recorder_test?ssl=disable`); its schema is
reset on every run. The end-to-end test records a generated video through the real ffmpeg
pipeline, so ffmpeg must be on `PATH`.

Twitch channels need `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`. YouTube and Chzzk work without
credentials, through the same unofficial endpoints their web players use, which can change without
notice.

Hosting on a Windows PC: see [local/README.md](local/README.md). On a cloud VM: see
[deploy/README.md](deploy/README.md).
