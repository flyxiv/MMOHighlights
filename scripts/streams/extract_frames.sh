#!/usr/bin/env bash
# extract_frames.sh <file.mp4> [src_dir] [gcs_dir]
# Takes one frame per 30 s bucket (first keyframe after each mark, decoding keyframes only) into
# /e/tmp/rwf_frames/<stem>/ plus a labeler frames.json sidecar {file: {source, t_s}}.
# Uses <src_dir>/<file> if present; otherwise copies it from <gcs_dir> and deletes it afterwards.
f="$1"; stem="${f%.mp4}"
SRC_DIR=${2:-/e/tmp/rwf_streams}
OUT=/e/tmp/rwf_frames/$stem
GCS=${3:-gs://ai_datasets_jyn/wow_rwf_streams/liquid}
REL=${GCS#gs://ai_datasets_jyn/}/$f

[ -f "$OUT/frames.json" ] && { echo "FRAMES_SKIP $stem (already extracted)"; exit 0; }
in="$SRC_DIR/$f"; fetched=0
if [ ! -f "$in" ]; then
  gcloud storage cp "$GCS/$f" "$in" >/dev/null 2>&1 </dev/null || { echo "FRAMES_FAIL $stem: GCS copy failed"; rm -f "$in"; exit 1; }
  fetched=1
fi
rm -rf "$OUT"; mkdir -p "$OUT/tmp"
ffmpeg -hide_banner -nostdin -skip_frame nokey -i "$in" \
  -vf "select='isnan(prev_selected_t)+gt(floor(t/30)\,floor(prev_selected_t/30))',showinfo" \
  -fps_mode vfr -q:v 2 "$OUT/tmp/%06d.jpg" 2> "$OUT/ffmpeg.log"
rc=$?
[ "$fetched" = 1 ] && rm -f "$in"
[ $rc -ne 0 ] && { echo "FRAMES_FAIL $stem: ffmpeg exit $rc (see $OUT/ffmpeg.log)"; exit 1; }

# showinfo prints "n: <k> ... pts_time:<t>" for the k-th written frame (file number k+1).
grep -o "n: *[0-9]* .*pts_time:[0-9.]*" "$OUT/ffmpeg.log" | sed -E 's/^n: *([0-9]+) .*pts_time:([0-9.]+)$/\1 \2/' |
while read -r n t; do
  sec=$(printf "%.0f" "$t")
  name=$(printf "%s_t%05d.jpg" "$stem" "$sec")
  mv "$OUT/tmp/$(printf %06d $((n + 1))).jpg" "$OUT/$name"
  printf '%s\t%s\n' "$name" "$t"
done | awk -F'\t' -v rel="$REL" 'BEGIN{printf "{"} {printf "%s\n  \"%s\": {\"source\": \"%s\", \"t_s\": %.3f}", (NR>1?",":""), $1, rel, $2} END{print "\n}"}' > "$OUT/frames.json"
left=$(ls "$OUT/tmp" | wc -l); rmdir "$OUT/tmp" 2>/dev/null
count=$(ls "$OUT"/*.jpg 2>/dev/null | wc -l)
[ "$left" -ne 0 ] && { echo "FRAMES_FAIL $stem: $left frames without timestamps"; exit 1; }
rm -f "$OUT/ffmpeg.log"
echo "FRAMES_DONE $stem $count frames"
