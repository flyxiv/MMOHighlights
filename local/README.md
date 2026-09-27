# Hosting on this Windows PC

Runs Postgres, the recorder backend and the page on this machine. The page is at
http://localhost:3000 and only listens on 127.0.0.1. Recordings upload to
`gs://mmohighlights/archives/`.

The recorder only works while the PC is on and awake. Turn off sleep in
Settings → System → Power, or streams will have gaps.

## One-time setup

1. Tools: Python 3.12 + uv, Node 22, ffmpeg, and the PostgreSQL 17 binaries in
   `C:\Users\Public\mmohl-pg\pgsql`, with a cluster in `...\data` on port 5433 that has a
   `recorder` user and database. The paths can be changed in `local\config.ps1`.
2. `cd backend; uv sync` and `cd frontend; npm install`.
3. Bucket access: `gcloud auth application-default login`, signed in as an account that can write
   to the bucket. The backend finds these credentials automatically.
4. Twitch (optional): put `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` in `backend\.env`.
5. Start at login: `powershell -ExecutionPolicy Bypass -File local\install-autostart.ps1`

## Shared database (Supabase) and other PCs

Set `DATABASE_URL` in `backend\.env` to the Supabase **session pooler** string, with
`postgresql+asyncpg://` in place of `postgresql://`. The scripts then skip the local Postgres.
TLS is on automatically for remote hosts.

Only one PC records. On any other PC:

1. Install uv and Node, clone the repo, `cd backend; uv sync` and `cd frontend; npm install`.
2. Copy `backend\.env`; the recording PC's Twitch keys aren't needed there.
3. Create `local\config.ps1` containing `$Role = 'viewer'`.
4. Run `local\start.ps1`, and optionally `local\install-autostart.ps1`.

A viewer serves the page from the shared database. It shows the same channels, recordings and
labels, and updates live. You can add channels and edit labels there, and the recording PC picks
up new channels on its next check. Stopping a recording must be done on the recording PC, which
runs the recorder processes; a viewer says so if you try.

## Everyday

| Do                  | Command                                                            |
| ------------------- | ------------------------------------------------------------------ |
| Start now           | `powershell -ExecutionPolicy Bypass -File local\start.ps1`         |
| Stop                | `powershell -ExecutionPolicy Bypass -File local\stop.ps1`          |
| After pulling code  | stop, delete `frontend\.next`, start (the page is rebuilt)         |
| Remove autostart    | `Unregister-ScheduledTask MMOHighlightsRecorder`                   |

Logs are in `C:\Users\Public\mmohl-pg\logs` (`backend.log`, `frontend.log`, `hosting.log`).
Segments wait in `...\spool` until they're uploaded.

The scheduled task runs `start.ps1` at login and every 5 minutes. It only starts what isn't
running, so a crashed backend is back within 5 minutes. When the backend restarts, a stream that
is still live continues in the same recording.
