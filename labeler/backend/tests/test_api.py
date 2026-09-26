import json
import time

from app.store import LocalStore
from tests.conftest import PROJECT, png


def wait_import(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/imports/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("import did not finish")


def setup_project(client, frames) -> str:
    slug = client.post("/api/projects", json=PROJECT).json()["slug"]
    job = client.post(f"/api/projects/{slug}/imports", json={"source": str(frames)}).json()
    assert wait_import(client, job["id"])["state"] == "done"
    return slug


def box(oid="a", class_id=0, bbox=(10, 5, 20, 10), **kw):
    return {"id": oid, "class_id": class_id, "bbox": list(bbox), **kw}


def test_create_project_writes_project_folder(client, bucket: LocalStore):
    r = client.post("/api/projects", json=PROJECT)
    assert r.status_code == 201
    p = r.json()
    assert p["slug"] == "ffxiv-raid-ui"
    assert [(c["id"], c["name"], c["color"]) for c in p["classes"]] == [
        (0, "boss_hp_bar", "red"),
        (1, "cast_bar", "orange"),
    ]
    assert p["storage_uri"].endswith("ffxiv-raid-ui")
    stored = json.loads(bucket.read("ffxiv-raid-ui/project.json"))
    assert stored["groups"][0]["options"] == ["Pre-pull", "In combat", "Wipe"]
    assert json.loads(bucket.read("ffxiv-raid-ui/manifest.json")) == {"images": []}

    assert client.post("/api/projects", json=PROJECT).status_code == 409
    listed = client.get("/api/projects").json()
    assert [s["slug"] for s in listed] == ["ffxiv-raid-ui"]


def test_import_folder(client, frames, bucket: LocalStore):
    slug = client.post("/api/projects", json=PROJECT).json()["slug"]
    job = client.post(f"/api/projects/{slug}/imports", json={"source": str(frames)}).json()
    job = wait_import(client, job["id"])
    assert (job["state"], job["total"], job["added"], job["skipped"]) == ("done", 3, 3, 0)

    rows = client.get(f"/api/projects/{slug}/images").json()
    assert [(r["file"], r["width"], r["height"], r["status"]) for r in rows] == [
        ("f001.png", 64, 36, "todo"),
        ("f002.png", 64, 36, "todo"),
        ("pull2/f003.png", 1920, 1080, "todo"),
    ]
    assert bucket.read(f"{slug}/images/pull2/f003.png") is not None
    manifest = json.loads(bucket.read(f"{slug}/manifest.json"))
    assert len(manifest["images"]) == 3
    assert json.loads(bucket.read(f"{slug}/project.json"))["image_count"] == 3

    # Importing again skips what's already there.
    again = wait_import(
        client, client.post(f"/api/projects/{slug}/imports", json={"source": str(frames)}).json()["id"]
    )
    assert (again["added"], again["skipped"]) == (0, 3)

    assert client.post(f"/api/projects/{slug}/imports", json={"source": "C:/nope/nowhere"}).status_code == 422


def test_upload_and_serve(client):
    slug = client.post("/api/projects", json=PROJECT).json()["slug"]
    r = client.post(
        f"/api/projects/{slug}/uploads",
        files=[("files", ("a.png", png(), "image/png")), ("files", ("b.txt", b"x", "text/plain"))],
    )
    assert r.json() == {"added": 1, "skipped": 0, "errors": ["b.txt: not an image file"]}
    img = client.get(f"/api/projects/{slug}/files/a.png")
    assert img.status_code == 200 and img.content == png()
    thumb = client.get(f"/api/projects/{slug}/thumbs/a.png")
    assert thumb.headers["content-type"] == "image/webp"
    assert client.get(f"/api/projects/{slug}/files/missing.png").status_code == 404
    assert client.get(f"/api/projects/{slug}/files/..%2Fproject.json").status_code in (404, 422)


def test_save_annotation_validates_and_clamps(client, frames):
    slug = setup_project(client, frames)
    url = f"/api/projects/{slug}/annotations/f001.png"
    assert client.get(url).json()["objects"] == []

    body = {
        "status": "todo",
        "labels": {"fight_state": "In combat"},
        "objects": [
            box("a", 0, (-5, -5, 20, 20)),  # clamped to the 64x36 image
            {"id": "p", "class_id": 1, "type": "polygon", "points": [[1, 1], [30, 2], [80, 30]]},
        ],
    }
    saved = client.put(url, json=body).json()
    assert saved["objects"][0]["bbox"] == [0, 0, 15, 15]
    assert saved["objects"][1]["bbox"] == [1, 1, 63, 29]
    assert client.get(url).json()["labels"] == {"fight_state": "In combat"}

    bad = [
        {"objects": [box(class_id=9)]},
        {"labels": {"fight_state": "Dancing"}},
        {"labels": {"phase": "P1"}},
        {"objects": [box(bbox=(100, 100, 5, 5))]},
        {"objects": [{"id": "p", "class_id": 0, "type": "polygon", "points": [[1, 1], [2, 2]]}]},
        {"objects": [box("a"), box("a")]},
    ]
    for b in bad:
        assert client.put(url, json=b).status_code == 422, b

    rows = {r["file"]: r for r in client.get(f"/api/projects/{slug}/images").json()}
    assert rows["f001.png"]["objects"] == 2
    stats = client.get(f"/api/projects/{slug}").json()["stats"]
    assert stats["class_counts"] == {"0": 1, "1": 1}


def test_sync_pushes_to_bucket_and_another_cache_pulls(make_client, frames, bucket: LocalStore):
    with make_client("cache-a") as a:
        slug = setup_project(a, frames)
        a.put(f"/api/projects/{slug}/annotations/f002.png", json={"status": "done", "objects": [box()]})
        assert a.get(f"/api/projects/{slug}").json()["pending_sync"] == 1
        a.app.state.labeler.push_pending()
        assert a.get(f"/api/projects/{slug}").json()["pending_sync"] == 0
    stored = json.loads(bucket.read(f"{slug}/annotations/f002.png.json"))
    assert stored["status"] == "done"

    with make_client("cache-b") as b:
        rows = {r["file"]: r for r in b.get(f"/api/projects/{slug}/images").json()}
        assert rows["f002.png"]["status"] == "done" and rows["f002.png"]["objects"] == 1
        # Serving an image this cache has never seen downloads it from the bucket.
        assert b.get(f"/api/projects/{slug}/files/f001.png").status_code == 200


def test_unpushed_edit_survives_pull(make_client, frames):
    with make_client("cache-a") as a:
        slug = setup_project(a, frames)
        a.put(f"/api/projects/{slug}/annotations/f001.png", json={"objects": [box("remote")]})
        a.app.state.labeler.push_pending()
    with make_client("cache-b") as b:
        b.get(f"/api/projects/{slug}")
        b.put(f"/api/projects/{slug}/annotations/f001.png", json={"objects": [box("local")]})
    # Restart with the same cache: the pull must not overwrite the edit that wasn't pushed yet.
    with make_client("cache-b") as b:
        assert b.get(f"/api/projects/{slug}/annotations/f001.png").json()["objects"][0]["id"] == "local"


def test_bulk_labels_and_status(client, frames):
    slug = setup_project(client, frames)
    r = client.post(
        f"/api/projects/{slug}/bulk",
        json={"files": ["f001.png", "f002.png"], "labels": {"fight_state": "Wipe"}, "status": "review"},
    )
    assert r.json() == {"updated": 2}
    rows = {r["file"]: r for r in client.get(f"/api/projects/{slug}/images").json()}
    assert rows["f001.png"]["labels"] == {"fight_state": "Wipe"}
    assert rows["f002.png"]["status"] == "review"
    assert rows["pull2/f003.png"]["labels"] == {}
    client.post(f"/api/projects/{slug}/bulk", json={"files": ["f001.png"], "labels": {"fight_state": None}})
    assert client.get(f"/api/projects/{slug}/annotations/f001.png").json()["labels"] == {}
    assert client.post(f"/api/projects/{slug}/bulk", json={"files": ["zzz.png"]}).status_code == 404


def test_classes_can_be_added_but_used_ones_not_deleted(client, frames):
    slug = setup_project(client, frames)
    client.put(f"/api/projects/{slug}/annotations/f001.png", json={"objects": [box(class_id=1)]})
    p = client.patch(
        f"/api/projects/{slug}",
        json={"classes": [{"id": 0, "name": "boss_hp_bar"}, {"id": 1, "name": "cast_bar"}, {"name": "boss"}]},
    ).json()
    assert [(c["id"], c["name"]) for c in p["classes"]] == [(0, "boss_hp_bar"), (1, "cast_bar"), (2, "boss")]
    assert p["classes"][2]["color"] == "amber"

    r = client.patch(f"/api/projects/{slug}", json={"classes": [{"id": 0, "name": "boss_hp_bar"}]})
    assert r.status_code == 409 and "cast_bar" in r.json()["detail"]
    ok = client.patch(f"/api/projects/{slug}", json={"classes": [{"id": 1, "name": "cast_bar"}]})
    assert ok.status_code == 200


def test_predictions_become_suggestions(client, frames):
    slug = setup_project(client, frames)
    client.put(f"/api/projects/{slug}/annotations/f002.png", json={"status": "done", "objects": [box()]})
    r = client.post(
        f"/api/projects/{slug}/predictions",
        json={
            "predictions": [
                {
                    "file": "f001.png",
                    "objects": [{"class_name": "cast_bar", "bbox": [1, 1, 10, 10], "score": 0.9}],
                },
                {"file": "f002.png", "objects": [{"class_id": 0, "bbox": [1, 1, 10, 10]}]},
            ]
        },
    )
    assert r.json() == {"updated": 1, "skipped": 1}
    ann = client.get(f"/api/projects/{slug}/annotations/f001.png").json()
    assert [(o["class_id"], o["source"], o["accepted"], o["score"]) for o in ann["objects"]] == [
        (1, "model", False, 0.9)
    ]
    row = next(r for r in client.get(f"/api/projects/{slug}/images").json() if r["file"] == "f001.png")
    assert (row["objects"], row["suggested"]) == (0, 1)


def test_export_yolo_and_coco(client, frames, bucket: LocalStore):
    slug = setup_project(client, frames)
    assert client.post(f"/api/projects/{slug}/exports", json={"format": "yolo"}).status_code == 422

    client.put(
        f"/api/projects/{slug}/annotations/pull2/f003.png",
        json={
            "status": "done",
            "labels": {"fight_state": "In combat"},
            "objects": [
                box("a", 1, (960, 540, 192, 108)),
                box("s", 0, (0, 0, 10, 10), source="model", accepted=False),
            ],
        },
    )
    client.put(f"/api/projects/{slug}/annotations/f001.png", json={"status": "done", "objects": []})
    client.put(f"/api/projects/{slug}/annotations/f002.png", json={"status": "todo", "objects": [box()]})

    y = client.post(f"/api/projects/{slug}/exports", json={"format": "yolo"}).json()
    assert (y["images"], y["objects"]) == (2, 1)
    folder = y["uri"][len(str(bucket.root)) + 1 :].replace("\\", "/")
    assert bucket.read(f"{folder}/labels/pull2/f003.txt").decode() == "1 0.550000 0.550000 0.100000 0.100000"
    assert bucket.read(f"{folder}/labels/f001.txt") == b""
    assert b'1: "cast_bar"' in bucket.read(f"{folder}/data.yaml")
    assert b"In combat" in bucket.read(f"{folder}/classifications.csv")

    c = client.post(
        f"/api/projects/{slug}/exports", json={"format": "coco", "include_unfinished": True}
    ).json()
    assert c["images"] == 3
    folder = c["uri"][len(str(bucket.root)) + 1 :].replace("\\", "/")
    doc = json.loads(bucket.read(f"{folder}/annotations.json"))
    assert [cat["id"] for cat in doc["categories"]] == [1, 2]
    assert sorted(a["category_id"] for a in doc["annotations"]) == [1, 2]


def test_unknown_project_is_404(client):
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/..%2F..").status_code == 404
