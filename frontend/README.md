# MMOHighlights · Live Recorder (frontend)

Single-user dashboard for the live-stream recorder: tracked Twitch / YouTube / Chzzk channels,
recordings in progress, completed recordings in `gs://mmohighlights/archives/`, and game / tier labels.

Next.js 15 (App Router) · TypeScript · Tailwind CSS v4 · shadcn/ui · TanStack Query v5 · SSE.

## Develop

```bash
npm install
cp .env.example .env.local      # adjust BACKEND_URL if the API isn't on :8000
npm run dev                     # http://localhost:3000
```

`/api/*` is rewritten to `${BACKEND_URL}/api/*`, so the browser only ever talks to the Next server.
Live updates come from `GET /api/events` (Server-Sent Events); the client reconnects on its own and
refetches everything after a reconnect.

## Mock mode

No backend needed — the data layer serves in-memory fixtures from `lib/mocks.ts`
(7 channels, 3 active and 6 completed recordings, WoW / FFXIV tiers) and mutations change them.
A fake event stream ticks the active recordings every 2 s.

```bash
NEXT_PUBLIC_USE_MOCKS=1 npm run dev
```

In mock mode, adding `https://twitch.tv/notfound_x` shows the "channel not found" error and any
non-channel URL shows the "unsupported URL" error.

## Build / lint

```bash
npm run lint
npm run build && npm start
```

## Layout

- `app/` — `layout.tsx` (fonts, theme), `providers.tsx` (Query, next-themes, toasts), `page.tsx`
- `components/recorder/` — dashboard sections, recording sheet, label picker, dialogs
- `components/ui/` — shadcn/ui primitives
- `lib/types.ts` — mirrors `backend/app/schemas.py`
- `lib/api.ts` — fetch wrappers (throw `ApiError` with the server's `detail`)
- `lib/queries.ts` — TanStack Query hooks · `lib/events.ts` — SSE → query cache
- `lib/format.ts` — durations, bytes, relative times · `lib/mocks.ts` — fixtures
