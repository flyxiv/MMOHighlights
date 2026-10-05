"""make_sheets.py <frames_dir> <out_dir>

Tiles a video's frames (sorted by name = by time) into 4x4 contact sheets of 480x270 tiles,
each stamped with its frame index, for labeling by eye. Writes <out_dir>/sheet_NNN.jpg and
<out_dir>/index.json: {"frames": [file names in index order], "per_sheet": 16}.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS, TW, TH = 4, 4, 480, 270
PER = COLS * ROWS

frames_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
frames = sorted(p.name for p in frames_dir.glob("*.jpg"))
font = ImageFont.truetype("arialbd.ttf", 40)

for s in range(0, len(frames), PER):
    sheet = Image.new("RGB", (COLS * TW, ROWS * TH), "black")
    draw = ImageDraw.Draw(sheet)
    for k, name in enumerate(frames[s : s + PER]):
        x, y = (k % COLS) * TW, (k // COLS) * TH
        with Image.open(frames_dir / name) as im:
            sheet.paste(im.convert("RGB").resize((TW - 4, TH - 4)), (x + 2, y + 2))
        draw.rectangle([x + 2, y + 2, x + 92, y + 50], fill="yellow")
        draw.text((x + 8, y + 4), str(s + k), fill="black", font=font)
    sheet.save(out_dir / f"sheet_{s // PER:03d}.jpg", quality=80)

(out_dir / "index.json").write_text(json.dumps({"frames": frames, "per_sheet": PER}))
print(f"{len(frames)} frames -> {(len(frames) + PER - 1) // PER} sheets in {out_dir}")
