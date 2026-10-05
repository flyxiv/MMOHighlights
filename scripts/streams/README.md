# Stream VODs

Scripts that gather RWF stream VODs into GCS and cut frames for labeling
([#8](https://github.com/flyxiv/MMOHighlights/issues/8)). Run them from Git Bash.

| Script | Does |
| --- | --- |
| `liquid_ulatek.sh` | Liquid's Curse of Ula'tek live VODs → `gs://ai_datasets_jyn/wow_rwf_streams/liquid/curse_of_ulatek_<day>.mp4` |
| `echo_fru.sh` | Echo x Mogtalk Futures Rewritten Ultimate VODs → `gs://ai_datasets_jyn/ffxiv_rwf_streams/echo/futures_rewritten_ultimate_<day>.mp4` |
| `extract_frames.sh <file.mp4> [src_dir] [gcs_dir]` | One frame per 30 s into `/e/tmp/rwf_frames/<stem>/` with a labeler `frames.json` |
| `make_sheets.py <frames_dir> <out_dir>` | 4×4 numbered contact sheets of those frames, for labeling by eye |

Each batch handles one VOD at a time: download 1080p h264 + AAC, check the height is 1080, upload,
compare the GCS size with the local size, cut frames, then delete the local file. A file that fails
a check is kept for inspection. VODs already in GCS are skipped (frames are still cut, copying the
file back from GCS), so a batch can be re-run. A lock directory stops two copies of one batch from
running at once.

## Requirements

- `uv`. yt-dlp runs as `uvx --with deno --from "yt-dlp[default]@latest" yt-dlp`, because YouTube
  needs a JS runtime and the installed Node (20.16) is too old for yt-dlp.
- `ffmpeg`/`ffprobe` and `gcloud` (logged in with write access to `gs://ai_datasets_jyn`).
- About 40 GB free on E: while a 12 h VOD downloads and merges.
- `make_sheets.py`: `uv run --no-project --with pillow python make_sheets.py ...`

## Coverage

- Liquid Ula'tek: days 2, 4–16, 16 part 2, 17. The race ended on day 17. Days 1 and 3 have no
  public VOD. The overnight `[REBROADCAST]` VODs replay the same day and are skipped; some are
  mislabelled, so the list uses the ~16:45 UTC live VOD of each day.
- Echo Ula'tek: no full live VODs are public (YouTube has only highlights, Twitch has no past
  broadcasts).
- Echo FRU: day 2 parts 1–3. Day 1 failed with a truncated read and still needs a re-run.
