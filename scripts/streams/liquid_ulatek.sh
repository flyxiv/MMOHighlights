#!/usr/bin/env bash
# Download each Liquid Ula'tek live VOD in 1080p, upload to GCS, verify, cut 30 s frames, delete local.
DIR=/e/tmp/rwf_streams
DEST=gs://ai_datasets_jyn/wow_rwf_streams/liquid
mkdir -p "$DIR"; cd "$DIR" || exit 1
# Single-instance lock: a second runner would write into the same partial files.
mkdir .batch.lock 2>/dev/null || { echo "FAIL another batch is already running (remove $DIR/.batch.lock if stale)"; exit 1; }
trap 'rmdir "$DIR/.batch.lock"' EXIT
while IFS='|' read -r name id; do
  f="curse_of_ulatek_${name}.mp4"
  if gcloud storage ls "$DEST/$f" >/dev/null 2>&1 </dev/null; then echo "SKIP $f (already in GCS)"; bash "$(dirname "$0")/extract_frames.sh" "$f" </dev/null; continue; fi
  # A 12h VOD is ~16 GB and merging briefly needs ~2x that.
  free=$(df -BG --output=avail "$DIR" | tail -1 | tr -dc 0-9)
  if [ "$free" -lt 40 ]; then echo "FAIL only ${free}G free on E:, stopping"; exit 1; fi
  echo "START $f ($id)"
  for attempt in 1 2; do
    uvx --with deno --from "yt-dlp[default]@latest" yt-dlp -q --no-warnings \
      -f "299+140/bv*[height=1080][vcodec^=avc1]+ba[ext=m4a]" --merge-output-format mp4 -N 8 \
      -o "$f" "https://www.youtube.com/watch?v=$id" >> "dl_${name}.log" 2>&1 </dev/null
    [ -f "$f" ] && break
    rm -f curse_of_ulatek_${name}.*
  done
  if [ ! -f "$f" ]; then echo "FAIL download $f (see $DIR/dl_${name}.log)"; continue; fi
  h=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$f" </dev/null)
  if [ "$h" != "1080" ]; then echo "FAIL $f height=$h, keeping local for inspection"; continue; fi
  gcloud storage cp "$f" "$DEST/$f" > "up_${name}.log" 2>&1 </dev/null
  lsz=$(stat -c %s "$f"); rsz=$(gcloud storage ls -l "$DEST/$f" 2>/dev/null </dev/null | awk 'NR==1{print $1}')
  [ "$lsz" = "$rsz" ] && bash "$(dirname "$0")/extract_frames.sh" "$f" </dev/null
  if [ "$lsz" = "$rsz" ]; then rm -f "$f" "dl_${name}.log" "up_${name}.log"; echo "DONE $f ${lsz} bytes, local deleted"
  else echo "FAIL upload $f local=$lsz remote=$rsz, keeping local"; fi
done <<'LIST'
day2|yJoG2KHwB20
day4|-O4nq-NggO4
day5|tdUmXYGY8o0
day6|G0_TFJPw2uk
day7|z1HaZ-tagJM
day8|y7m6Aod8sHw
day9|tyhSE1b18N4
day10|maYA0oR-tBI
day11|9-4nZ_HAW2o
day12|fqQaV1l8poM
day13|yLVdcZgr7cg
day14|vDbPZqkxapk
day15|j2ssPQVwXAo
day16|gDyeI2JvPUI
day16_part2|bLFAU4iNm90
day17|7GfnGVMNexI
LIST
echo ALL_FINISHED
