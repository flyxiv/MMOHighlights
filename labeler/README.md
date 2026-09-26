# Image Labeling

A fast, keyboard-first labeler for classic vision tasks: image classification, object detection
(boxes) and segmentation (polygons). Built because Label Studio was too slow for thousands of raid
frames ([#4](https://github.com/flyxiv/MMOHighlights/issues/4)). The design is on the "Image
Labeling" page of the [Figma file](https://www.figma.com/design/cCxNd3KwRKz1WepAoguxNF)
([#5](https://github.com/flyxiv/MMOHighlights/issues/5)).

- `backend/`: FastAPI on port 8100
- `frontend/`: Next.js + shadcn/ui on port 3100, proxies `/api` to the backend

## Where data lives

Every project is a folder in `gs://ai-datasets-jyn/`:

```
<project>/project.json             name, tasks, classes, label groups
<project>/manifest.json            every image with its width and height
<project>/images/<file>            the images
<project>/annotations/<file>.json  labels for one image
<project>/exports/<format>-<time>/ YOLO or COCO exports
```

The bucket is the source of truth. The backend keeps a local cache (images, thumbnails and a SQLite
index of all labels), so filtering, saving and moving between images don't wait on the network.
Saves land in the index immediately, and a background worker pushes them to the bucket within about
a second. If the bucket can't be reached, labels stay queued on the PC and the top bar says so. When
a project is opened, only annotation files that changed in the bucket are downloaded.

## Run it

One-time setup:

```powershell
gcloud auth application-default login   # an account that can read and write gs://ai-datasets-jyn
cd labeler\backend;  uv sync
cd ..\frontend;      npm install
```

Copy `backend\.env.example` to `backend\.env`. Keep `LABELER_CACHE_DIR` on an ASCII path such as
`C:\Users\Public\mmohl-labeler`.

Everyday:

```powershell
cd labeler\backend;  uv run uvicorn app.main:app --host 127.0.0.1 --port 8100
cd labeler\frontend; npm run dev        # or: npm run build; npm start
```

Then open http://localhost:3100.

To work offline, set `LABELER_STORAGE` to a local folder. It uses the same layout as the bucket.

## Labeling

Create a project, pick its tasks, classes and label groups, and point it at images. Images can
come from a folder on this PC, a `gs://` prefix (for example frames under `gs://mmohighlights/`),
or a browser upload. Images are copied into the project folder.

Every action has a key (press `?` in the app for the full list):

| Key | Action |
| --- | --- |
| `V` `B` `P` `H` | Select, box, polygon, pan tool (hold `Space` to pan with any tool) |
| `1`–`9` | Change the selected object's class; with nothing selected, set the class for new shapes |
| `Q` `W` `E` `R` `T`… | Set the image class (first label group with up to 8 options) |
| `D` / `A` | Save as done and go to the next image / go to the previous image |
| `F` | Flag the image for review |
| `Enter` | Accept model suggestions; closes a polygon while drawing |
| `C` | Copy the objects from the previous image |
| `G` | Grid view: select many thumbnails, then press `Q`… to classify them all at once |
| Arrow keys | Move the selected object 1 px (10 px with `Shift`) |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo |

If a box is drawn with no class set, a picker opens next to it: press `1`–`9`, `Enter`, or `Tab` to
reuse the last class.

## Model suggestions

The **Pre-label** button stays disabled until a model is connected. Predictions can already be
imported. They show up as dashed suggestions, and pressing `Enter` accepts them:

```http
POST /api/projects/<project>/predictions
{"predictions": [{"file": "f0001.jpg",
  "objects": [{"class_name": "boss_hp_bar", "bbox": [596, 48, 728, 36], "score": 0.97}]}]}
```

`bbox` is `[x, y, width, height]` in image pixels. Polygons use `"points": [[x, y], ...]`. Images
already marked done are left alone.

## Export

**Export** in the top bar writes to `<project>/exports/`. By default only images marked done are
included.

- **YOLO**: `data.yaml` plus `labels/<image>.txt`, and `classifications.csv` when the project has
  label groups. Projects with segmentation use the YOLO-seg polygon format. To train, copy
  `images/` next to `labels/`.
- **COCO**: `annotations.json`. Category ids are class id + 1. Image-level labels are stored in
  each image's `labels` field.

Unaccepted model suggestions are never exported.

## Tests

```powershell
cd labeler\backend;  uv run pytest; uv run ruff check .
cd labeler\frontend; npm run lint; npm run typecheck
```
