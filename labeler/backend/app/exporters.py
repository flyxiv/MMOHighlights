"""Training-set exports. Only accepted objects are written; unaccepted model suggestions are left out.

Each exporter returns ({relative path: (bytes, content type)}, number of objects written).
Images are not copied; the export points at the project's images/ folder.
"""

import csv
import io
import json
from pathlib import PurePosixPath

from app.schemas import Project

ExportFiles = dict[str, tuple[bytes, str]]
Images = list[tuple[str, int, int, dict]]  # file, width, height, annotation


def _accepted(ann: dict) -> list[dict]:
    return [o for o in ann.get("objects", []) if o.get("accepted", True)]


def _box_points(bbox) -> list[tuple[float, float]]:
    x, y, w, h = bbox
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _classifications_csv(project: Project, images: Images) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["file", *(g.name for g in project.groups)])
    for f, _w, _h, ann in images:
        labels = ann.get("labels", {})
        writer.writerow([f, *(labels.get(g.name, "") for g in project.groups)])
    return buf.getvalue().encode("utf-8")


def yolo(project: Project, images: Images, images_uri: str) -> tuple[ExportFiles, int]:
    """labels/<image path without extension>.txt, one line per object, coordinates normalized to 0–1.

    Projects with segmentation use the YOLO-seg polygon format (boxes become 4-point polygons);
    otherwise every object is written as a box (polygons as their bounding box).
    """
    seg = "segmentation" in project.tasks
    files: ExportFiles = {}
    n = 0
    for f, w, h, ann in images:
        lines = []
        for o in _accepted(ann):
            if seg:
                pts = o["points"] if o.get("type") == "polygon" else _box_points(o["bbox"])
                coords = " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in pts)
                lines.append(f"{o['class_id']} {coords}")
            else:
                x, y, bw, bh = o["bbox"]
                lines.append(
                    f"{o['class_id']} {(x + bw / 2) / w:.6f} {(y + bh / 2) / h:.6f} {bw / w:.6f} {bh / h:.6f}"
                )
            n += 1
        # An image without objects still gets an (empty) file: it's a negative example.
        files[f"labels/{PurePosixPath(f).with_suffix('.txt')}"] = ("\n".join(lines).encode(), "text/plain")

    names = "\n".join(f"  {c.id}: {json.dumps(c.name)}" for c in project.classes)
    data_yaml = (
        f"# Exported from the MMOHighlights labeler, project {project.slug}.\n"
        f"# Images: {images_uri}/  Download them into images/ next to labels/ to train.\n"
        "path: .\n"
        "train: images\n"
        "val: images\n"
        f"names:\n{names}\n"
    )
    files["data.yaml"] = (data_yaml.encode(), "text/yaml")
    files["images.txt"] = ("\n".join(f for f, *_ in images).encode(), "text/plain")
    if project.groups:
        files["classifications.csv"] = (_classifications_csv(project, images), "text/csv")
    return files, n


def _area(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def coco(project: Project, images: Images, images_uri: str) -> tuple[ExportFiles, int]:
    """annotations.json in COCO format. Category ids are class id + 1 (COCO reserves 0).

    Image-level labels go in each image's non-standard "labels" field.
    """
    out_images, out_anns = [], []
    for i, (f, w, h, ann) in enumerate(images, start=1):
        out_images.append({"id": i, "file_name": f, "width": w, "height": h, "labels": ann.get("labels", {})})
        for o in _accepted(ann):
            x, y, bw, bh = o["bbox"]
            if o.get("type") == "polygon":
                pts = [tuple(p) for p in o["points"]]
                seg = [[c for p in pts for c in p]]
                area = _area(pts)
            else:
                seg, area = [], bw * bh
            out_anns.append(
                {
                    "id": len(out_anns) + 1,
                    "image_id": i,
                    "category_id": o["class_id"] + 1,
                    "bbox": [x, y, bw, bh],
                    "area": area,
                    "iscrowd": 0,
                    "segmentation": seg,
                }
            )
    doc = {
        "info": {"description": f"MMOHighlights labeler export of {project.slug}", "images": images_uri},
        "images": out_images,
        "annotations": out_anns,
        "categories": [{"id": c.id + 1, "name": c.name} for c in project.classes],
        "label_groups": [g.model_dump() for g in project.groups],
    }
    files: ExportFiles = {
        "annotations.json": (json.dumps(doc, ensure_ascii=False).encode(), "application/json")
    }
    if project.groups:
        files["classifications.csv"] = (_classifications_csv(project, images), "text/csv")
    return files, len(out_anns)
