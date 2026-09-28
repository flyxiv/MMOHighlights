# Image Labeling

A fast, keyboard-first labeler for classic vision tasks: image classes and tags, boxes and polygons.
Built because Label Studio was too slow for thousands of raid frames
([#4](https://github.com/flyxiv/MMOHighlights/issues/4)). The design is on the "Image Labeling" page
of the [Figma file](https://www.figma.com/design/cCxNd3KwRKz1WepAoguxNF)
([#5](https://github.com/flyxiv/MMOHighlights/issues/5)).

- `backend/`: FastAPI on port 8100
- `frontend/`: Next.js + shadcn/ui on port 3100, proxies `/api` to the backend
- `local/`: scripts that host both on this PC

## Data: the uniform dataset layout

The labeler reads and writes datasets in `gs://ai_datasets_jyn/datasets/<name>/`, in the uniform
layout defined by `datasets/STRUCTURE.md` on RaidDesigner's `flyxiv/data-merge` branch. That file is
the source of truth. In short:

```
datasets/<name>/
  dataset.json                   card: tasks, versions, latest
  raw/labeler/<date>/<id>.<ext>  images added in the labeler (id = sha256[:16] of the file)
  releases/vN/                   immutable: manifest.jsonl, classes.json, splits/, stats.json
  labeling/                      the labeler's working area, never read by training
    project.json                 base_release, tasks, card draft before v1
    classes.json                 full vocabulary for the next release
    labels/<id>.json             complete labels + status for every touched sample
```

- **Labels.** Labels use the manifest format, `{task: {type, value}}`, with class names (not ids).
  Boxes are absolute-pixel `xyxy`. The labeler edits `class`, `multilabel`, `bbox` and `polygon`
  tasks. Tasks of any other type (`span`, `text`, `scalar`, …) are kept untouched and shown
  read-only.
- **Status.** Each sample is `todo`, `review`, `done` or `excluded`. Only `done` samples carry
  their labels into a release, marked `meta.reviewed`. Other samples keep their released labels,
  and `excluded` samples are dropped.
- **Cutting a release.** **Cut vN** in the top bar writes `releases/vN/` from the base release plus
  `labeling/`, then points `dataset.json`'s `latest` at it. Released classes can't be renamed,
  reordered or removed; new ones are appended. A release is never modified afterwards.
- **Shared rules.** Validation, splits and release cutting come from RaidDesigner's
  `datasets/tools/dataset_format.py`, vendored at `backend/app/vendor/`. To update it after the
  spec changes, run `uv run python scripts/vendor_dataset_format.py`. The tests check every release
  they cut with data-merge's own `validate_release.py`.

The bucket is the source of truth. The backend keeps a local cache (images, thumbnails and a SQLite
index of the base manifest and `labeling/`), so filtering, saving and moving between images don't
wait on the network. Saves land in the index first, and a background worker writes
`labeling/labels/<id>.json` to the bucket within about a second. If the bucket can't be reached,
labels stay queued on the PC and the top bar says so.

## Run it

One-time setup:

```powershell
gcloud.cmd auth application-default login   # an account that can read and write gs://ai_datasets_jyn
cd labeler\backend;  uv sync
cd ..\frontend;      npm install
```

PowerShell blocks `gcloud.ps1` on this PC ("running scripts is disabled on this system"), which is
why the command above calls `gcloud.cmd`.

### Hosting on this PC

`local\` runs the backend and a production build of the page in the background. Only this PC can
reach it (it listens on 127.0.0.1), at http://localhost:3100. Cache, logs and launchers live in
`C:\Users\Public\mmohl-labeler`.

| Do | Command |
| --- | --- |
| Start now | `powershell -ExecutionPolicy Bypass -File labeler\local\start.ps1` |
| Stop | `powershell -ExecutionPolicy Bypass -File labeler\local\stop.ps1` |
| Start at login | `powershell -ExecutionPolicy Bypass -File labeler\local\install-autostart.ps1` |
| After pulling code | stop, delete `labeler\frontend\.next`, start (the page is rebuilt) |
| Remove autostart | `Unregister-ScheduledTask MMOHighlightsLabeler` |

The scheduled task runs `start.ps1` at login and every 5 minutes. The script starts only what isn't
already running, so a crashed server comes back within 5 minutes. Settings such as `$Storage` or the
ports can be overridden in `local\config.ps1`, which isn't committed.

### Development

```powershell
cd labeler\backend;  uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload
cd labeler\frontend; npm run dev
```

Stop the hosted copy first, because it uses the same ports. To work offline, set
`LABELER_STORAGE` to a local folder; the folder is treated like the bucket root and holds
`datasets/`.

## Labeling

- **Open a dataset.** Opening an existing dataset starts its `labeling/` area from the latest
  release.
- **New dataset.** **New dataset** creates one with only a `labeling/` area; `dataset.json` appears
  when you cut `v1`.
- **Add images.** Images can come from a folder on this PC, a `gs://` prefix (for example
  `gs://ai_datasets_jyn/archive/<old bucket>/`), or a browser upload. They're copied to
  `raw/labeler/`, and duplicates are skipped by content.
- **Frames cut from a video.** Put a `frames.json` next to the frames:
  `{"<file name>": {"parent_id": "<16-hex id of the video sample>", "source": "raw/vod/xeno_5.mkv", "t_s": 812.5}}`.
  The labeler copies `parent_id`, `source` and `t_s` into each frame's `meta`, and they carry into
  releases. Frames not listed import without a parent. This works for folder imports, `gs://`
  imports and uploads (pick the folder).

Every action has a key (press `?` in the app for the full list):

| Key | Action |
| --- | --- |
| `V` `B` `P` `H` | Select, box, polygon, pan tool (hold `Space` to pan with any tool) |
| `1`–`9` | Change the selected object's class; with nothing selected, set the class for new shapes |
| `Q` `W` `E` `R` `T`… | Set the image class (first class/tags task with up to 8 classes) |
| `D` / `A` | Mark done and go to the next image / go to the previous image |
| `F` / `X` | Flag for review / exclude from releases |
| `Enter` | Accept model suggestions; closes a polygon while drawing |
| `C` | Copy the objects from the previous image |
| `G` | Grid view: select many thumbnails, press `Q`… to set a class and `D` to mark them done |
| Arrow keys | Move the selected object 1 px (10 px with `Shift`) |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |

If a shape is drawn with no class set, a picker opens next to it: press `1`–`9`, `Enter`, or `Tab`
to reuse the last class.

## Model suggestions

The **Pre-label** button stays disabled until a model is connected. Predictions can already be
imported. They're stored as `suggestions` in `labeling/labels/<id>.json`, which is never released.
They show up as dashed shapes, and pressing `Enter` accepts them:

```http
POST /api/datasets/<name>/predictions
{"predictions": [{"id": "3f9a1c0b7d2e44a1",
  "suggestions": {"ui": {"type": "bbox", "value": [{"class": "boss_hp_bar", "xyxy": [412, 18, 1508, 46], "score": 0.97}]}}}]}
```

Samples already marked done are left alone.

## Tests

```powershell
cd labeler\backend;  uv run pytest; uv run ruff check .
cd labeler\frontend; npm run lint; npm run typecheck
```
