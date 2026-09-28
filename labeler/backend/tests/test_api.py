import json
import time
from datetime import date

from app.store import LocalStore
from app.vendor.dataset_format import assign_split
from tests.conftest import BASE_IMAGES, NEW_DATASET, png, sid, validate

TODAY = date.today().isoformat()


def wait_import(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/imports/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("import did not finish")


def new_dataset(client, frames) -> dict[str, str]:
    assert client.post("/api/datasets", json=NEW_DATASET).status_code == 201
    job = client.post("/api/datasets/raid_ui/imports", json={"source": str(frames)}).json()
    assert wait_import(client, job["id"])["state"] == "done"
    names = {r["name"]: r["id"] for r in client.get("/api/datasets/raid_ui/samples").json()}
    # f001.png and its byte-identical copy are one sample; the import keeps whichever it reads first.
    if "copy_of_f001.png" in names:
        names["f001.png"] = names.pop("copy_of_f001.png")
    return names


def box(cls="boss_hp_bar", xyxy=(10, 5, 30, 15)):
    return {"class": cls, "xyxy": list(xyxy)}


def test_create_dataset_writes_labeling_area_only(client, bucket: LocalStore):
    r = client.post("/api/datasets", json=NEW_DATASET)
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["base_release"], d["latest"], d["next_release"]) == (None, None, "v1")
    root = "datasets/raid_ui"
    project = json.loads(bucket.read(f"{root}/labeling/project.json"))
    assert project["base_release"] is None and project["card"]["title"] == "FFXIV raid UI"
    assert json.loads(bucket.read(f"{root}/labeling/classes.json"))["ui"] == ["boss_hp_bar", "cast_bar"]
    assert bucket.read(f"{root}/dataset.json") is None  # only once v1 is cut

    assert client.post("/api/datasets", json=NEW_DATASET).status_code == 409
    assert client.post("/api/datasets", json={**NEW_DATASET, "name": "Bad Name"}).status_code == 422
    listed = client.get("/api/datasets").json()
    assert [(s["name"], s["labeling"], s["latest"]) for s in listed] == [("raid_ui", True, None)]


def test_import_names_files_by_content_id(client, frames, bucket: LocalStore):
    names = new_dataset(client, frames)
    assert set(names) == {"f001.png", "풀 2.png", "f003.png"}  # the byte-identical copy is the same sample
    i = names["풀 2.png"]
    assert bucket.read(f"datasets/raid_ui/raw/labeler/{TODAY}/{i}.png") == png(color=(90, 20, 20))
    s = client.get(f"/api/datasets/raid_ui/samples/{i}").json()
    assert (s["image"], s["new"], s["meta"]["original_path"]) == (
        f"raw/labeler/{TODAY}/{i}.png",
        True,
        "풀 2.png",
    )
    assert client.get(f"/api/datasets/raid_ui/samples/{i}/image").content == png(color=(90, 20, 20))
    assert client.get(f"/api/datasets/raid_ui/samples/{i}/thumb").headers["content-type"] == "image/webp"

    r = client.post("/api/datasets/raid_ui/uploads", files=[("files", ("again.png", png(), "image/png"))])
    assert r.json() == {"added": 0, "skipped": 1, "errors": []}


def test_save_validates_and_normalizes(client, frames):
    i = new_dataset(client, frames)["f001.png"]
    url = f"/api/datasets/raid_ui/samples/{i}"
    body = {
        "status": "todo",
        "labels": {
            "fight_state": {"type": "class", "value": "in_combat"},
            "ui": {"type": "bbox", "value": [box(xyxy=(40, 20, -5, 3))]},
            "tags": {"type": "multilabel", "value": ["blurry", "blurry"]},
        },
    }
    saved = client.put(url, json=body).json()
    assert saved["labels"]["ui"]["value"] == [{"class": "boss_hp_bar", "xyxy": [0, 3, 40, 20]}]
    assert saved["labels"]["tags"]["value"] == ["blurry"]

    bad = [
        {"labels": {"ui": {"type": "bbox", "value": [box(cls="boss")]}}},
        {"labels": {"fight_state": {"type": "class", "value": "dancing"}}},
        {"labels": {"fight_state": {"type": "multilabel", "value": ["wipe"]}}},
        {"labels": {"nope": {"type": "class", "value": "x"}}},
        {"labels": {"ui": {"type": "bbox", "value": [box(xyxy=(100, 100, 120, 120))]}}},
        {"status": "finished"},
    ]
    for b in bad:
        assert client.put(url, json=b).status_code == 422, b

    rows = {r["id"]: r for r in client.get("/api/datasets/raid_ui/samples").json()}
    assert rows[i]["objects"] == 1 and rows[i]["labels"]["fight_state"] == "in_combat"
    stats = client.get("/api/datasets/raid_ui").json()["stats"]
    assert stats["class_counts"]["ui"] == {"boss_hp_bar": 1}
    assert (stats["total"], stats["new"], stats["todo"], stats["edited_not_done"]) == (3, 3, 3, 1)


def test_first_release_of_a_new_dataset(client, frames, bucket: LocalStore):
    names = new_dataset(client, frames)
    done, junk, todo = names["f001.png"], names["풀 2.png"], names["f003.png"]
    label = {"fight_state": {"type": "class", "value": "wipe"}, "ui": {"type": "bbox", "value": [box()]}}
    client.put(f"/api/datasets/raid_ui/samples/{done}", json={"status": "done", "labels": label})
    client.put(f"/api/datasets/raid_ui/samples/{junk}", json={"status": "excluded"})
    client.put(f"/api/datasets/raid_ui/samples/{todo}", json={"status": "review", "labels": label})

    r = client.post("/api/datasets/raid_ui/releases", json={"notes": "first pass"})
    assert r.status_code == 201, r.text
    assert (r.json()["version"], r.json()["samples"], r.json()["reviewed"]) == ("v1", 2, 1)
    out = validate(bucket, "raid_ui")
    assert "2 samples" in out

    root = "datasets/raid_ui"
    card = json.loads(bucket.read(f"{root}/dataset.json"))
    assert (card["latest"], card["versions"]["v1"]["notes"], card["title"]) == (
        "v1",
        "first pass",
        "FFXIV raid UI",
    )
    lines = {
        x["id"]: x for x in map(json.loads, bucket.read(f"{root}/releases/v1/manifest.jsonl").splitlines())
    }
    assert set(lines) == {done, todo}
    assert lines[done]["labels"] == label and lines[done]["meta"]["reviewed"] is True
    assert lines[todo]["labels"] == {}  # not done: a new image releases unlabeled
    assert lines[done]["files"] == {"image": f"raw/labeler/{TODAY}/{done}.png"}
    assert lines[done]["split"] == assign_split("raid_ui", done)
    assert json.loads(bucket.read(f"{root}/labeling/project.json"))["base_release"] == "v1"

    d = client.get("/api/datasets/raid_ui").json()
    assert (d["base_release"], d["latest"], d["releases"], d["next_release"]) == ("v1", "v1", ["v1"], "v2")
    rows = {r["id"]: r for r in client.get("/api/datasets/raid_ui/samples").json()}
    assert not rows[done]["new"] and rows[done]["status"] == "done"
    assert rows[junk]["status"] == "excluded"  # still in labeling/, still listed


def test_labeling_an_existing_release(client, released, bucket: LocalStore):
    a, b, c = released["a"], released["b"], released["c"]
    root = "datasets/ffxiv_frames"
    d = client.get("/api/datasets/ffxiv_frames").json()
    assert (d["base_release"], d["next_release"], d["stats"]["total"]) == ("v1", "v2", 3)
    # Opening it started the work area from the latest release.
    assert json.loads(bucket.read(f"{root}/labeling/classes.json")) == {"phase": ["p1", "p2"]}

    s = client.get(f"/api/datasets/ffxiv_frames/samples/{a}").json()
    assert s["labels"]["phase"]["value"] == "p1" and (s["width"], s["height"]) == (64, 36)
    assert client.get(f"/api/datasets/ffxiv_frames/samples/{c}").json()["width"] == 100  # measured

    # Add a bbox task and classes; released classes must stay first.
    r = client.patch(
        "/api/datasets/ffxiv_frames/labeling",
        json={
            "tasks": {"phase": {"type": "class"}, "caption": {"type": "text"}, "ui": {"type": "bbox"}},
            "classes": {"phase": ["p1", "p2", "p3"], "ui": ["boss_hp_bar"]},
        },
    )
    assert r.status_code == 200, r.text
    bad = client.patch("/api/datasets/ffxiv_frames/labeling", json={"classes": {"phase": ["p2", "p1"]}})
    assert bad.status_code == 409
    gone = client.patch("/api/datasets/ffxiv_frames/labeling", json={"tasks": {"ui": {"type": "bbox"}}})
    assert gone.status_code == 409  # phase/caption are released tasks

    # Editing a: the text task is kept, the whole label set lands in labels/<id>.json.
    body = {
        "status": "done",
        "labels": {"phase": {"type": "class", "value": "p3"}, "ui": {"type": "bbox", "value": [box()]}},
    }
    assert client.put(f"/api/datasets/ffxiv_frames/samples/{a}", json=body).status_code == 200
    client.app.state.labeler.push_pending()
    work = json.loads(bucket.read(f"{root}/labeling/labels/{a}.json"))
    assert work["labels"]["caption"] == {"type": "text", "value": "boss at 60%"}
    assert "files" not in work  # base samples don't repeat their files
    client.put(f"/api/datasets/ffxiv_frames/samples/{b}", json={"status": "excluded"})

    r = client.post("/api/datasets/ffxiv_frames/releases", json={})
    assert r.status_code == 201, r.text
    validate(bucket, "ffxiv_frames")
    lines = {
        x["id"]: x for x in map(json.loads, bucket.read(f"{root}/releases/v2/manifest.jsonl").splitlines())
    }
    assert set(lines) == {a, c}
    assert lines[a]["labels"]["phase"]["value"] == "p3" and lines[a]["meta"]["source"] == "vod/0412"
    assert lines[a]["split"] == "train"  # base samples keep their split
    assert lines[c]["split"] == assign_split("ffxiv_frames", c)  # unsplit ones get assigned
    assert json.loads(bucket.read(f"{root}/releases/v2/classes.json"))["phase"] == ["p1", "p2", "p3"]
    card = json.loads(bucket.read(f"{root}/dataset.json"))
    assert card["latest"] == "v2" and card["tasks"]["ui"] == {"type": "bbox"}
    # v1 is untouched.
    assert len(bucket.read(f"{root}/releases/v1/manifest.jsonl").splitlines()) == 3


def test_release_never_overwrites(client, released, bucket: LocalStore):
    client.get("/api/datasets/ffxiv_frames")
    bucket.write("datasets/ffxiv_frames/releases/v2/manifest.jsonl", b"", "application/x-ndjson")
    assert client.post("/api/datasets/ffxiv_frames/releases", json={}).status_code == 409


def test_sync_and_pull_on_another_machine(make_client, frames, bucket: LocalStore):
    with make_client("cache-a") as a:
        i = new_dataset(a, frames)["f001.png"]
        a.put(
            f"/api/datasets/raid_ui/samples/{i}",
            json={"status": "done", "labels": {"ui": {"type": "bbox", "value": [box()]}}},
        )
        assert a.get("/api/datasets/raid_ui").json()["pending_sync"] > 0
        a.app.state.labeler.push_pending()
        assert a.get("/api/datasets/raid_ui").json()["pending_sync"] == 0
    with make_client("cache-b") as b:
        rows = {r["id"]: r for r in b.get("/api/datasets/raid_ui/samples").json()}
        assert rows[i]["status"] == "done" and rows[i]["objects"] == 1
        assert b.get(f"/api/datasets/raid_ui/samples/{i}/image").status_code == 200
        b.put(f"/api/datasets/raid_ui/samples/{i}", json={"status": "review"})
    # Restart with the same cache: the pull must not overwrite the edit that wasn't pushed yet.
    with make_client("cache-b") as b:
        assert b.get(f"/api/datasets/raid_ui/samples/{i}").json()["status"] == "review"


def test_bulk_and_predictions(client, frames, bucket: LocalStore):
    names = new_dataset(client, frames)
    ids = list(names.values())
    r = client.post(
        "/api/datasets/raid_ui/bulk",
        json={"ids": ids[:2], "labels": {"fight_state": "wipe"}, "status": "review"},
    )
    assert r.json() == {"updated": 2}
    rows = {r["id"]: r for r in client.get("/api/datasets/raid_ui/samples").json()}
    assert rows[ids[0]]["labels"] == {"fight_state": "wipe"} and rows[ids[1]]["status"] == "review"
    assert (
        client.post("/api/datasets/raid_ui/bulk", json={"ids": ids[:1], "labels": {"ui": "x"}}).status_code
        == 422
    )
    assert client.post("/api/datasets/raid_ui/bulk", json={"ids": ["deadbeefdeadbeef"]}).status_code == 404

    pred = {"ui": {"type": "bbox", "value": [{**box(), "score": 0.9}]}}
    r = client.post(
        "/api/datasets/raid_ui/predictions", json={"predictions": [{"id": ids[2], "suggestions": pred}]}
    )
    assert r.json() == {"updated": 1, "skipped": 0}
    s = client.get(f"/api/datasets/raid_ui/samples/{ids[2]}").json()
    assert s["suggestions"]["ui"]["value"][0]["score"] == 0.9 and s["labels"] == {}

    client.put(f"/api/datasets/raid_ui/samples/{ids[2]}", json={"status": "done", "suggestions": pred})
    client.post("/api/datasets/raid_ui/releases", json={})
    validate(bucket, "raid_ui")
    manifest = bucket.read("datasets/raid_ui/releases/v1/manifest.jsonl").decode()
    assert "score" not in manifest  # suggestions are never released


def test_classes_in_use_cannot_be_deleted(client, frames):
    i = new_dataset(client, frames)["f001.png"]
    client.put(
        f"/api/datasets/raid_ui/samples/{i}",
        json={"labels": {"ui": {"type": "bbox", "value": [box("cast_bar")]}}},
    )
    r = client.patch("/api/datasets/raid_ui/labeling", json={"classes": {"ui": ["boss_hp_bar"]}})
    assert r.status_code == 409 and "cast_bar" in r.json()["detail"]
    ok = client.patch("/api/datasets/raid_ui/labeling", json={"classes": {"ui": ["cast_bar", "party_list"]}})
    assert ok.status_code == 200


def test_unknown_things_are_404(client):
    assert client.get("/api/datasets/nope").status_code == 404
    assert client.get("/api/datasets/..%2F..").status_code == 404
    assert client.get("/api/datasets/Bad").status_code == 404


def test_split_rule_matches_spec():
    # x = int(sha256(f"{name}:{id}")[:8], 16) / 0xFFFFFFFF; train < 0.8 <= val < 0.9 <= test
    assert assign_split("raid_ui", sid(BASE_IMAGES["a"])) in ("train", "val", "test")
    counts = {"train": 0, "val": 0, "test": 0}
    for n in range(2000):
        counts[assign_split("x", f"{n:016x}")] += 1
    assert 1500 < counts["train"] < 1700 and 120 < counts["val"] < 280


def test_frames_sidecar_links_frames_to_their_video(client, frames, bucket: LocalStore):
    vod = "ab" * 8
    (frames / "pull2" / "frames.json").write_text(
        json.dumps(
            {
                "f003.png": {"parent_id": vod, "source": "raw/vod/xeno_5.mkv", "t_s": 812.5},
                "copy_of_f001.png": {"parent_id": "NOT-HEX", "source": "raw/vod/x.mkv", "t_s": 1},
            }
        )
    )
    client.post("/api/datasets", json=NEW_DATASET)
    job = wait_import(
        client, client.post("/api/datasets/raid_ui/imports", json={"source": str(frames)}).json()["id"]
    )
    assert any("parent_id must be 16" in e for e in job["errors"])
    rows = {r["name"]: r["id"] for r in client.get("/api/datasets/raid_ui/samples").json()}
    meta = client.get(f"/api/datasets/raid_ui/samples/{rows['f003.png']}").json()["meta"]
    assert (meta["parent_id"], meta["source"], meta["t_s"]) == (vod, "raw/vod/xeno_5.mkv", 812.5)
    assert "parent_id" not in client.get(f"/api/datasets/raid_ui/samples/{rows['풀 2.png']}").json()["meta"]

    # Browser uploads send frames.json along with the images.
    sidecar = json.dumps({"up.png": {"parent_id": vod, "t_s": 3}}).encode()
    r = client.post(
        "/api/datasets/raid_ui/uploads",
        files=[
            ("files", ("clip/frames.json", sidecar, "application/json")),
            ("files", ("clip/up.png", png(color=(9, 9, 9)), "image/png")),
        ],
    )
    assert r.json() == {"added": 1, "skipped": 0, "errors": []}
    up = sid(png(color=(9, 9, 9)))
    assert client.get(f"/api/datasets/raid_ui/samples/{up}").json()["meta"]["t_s"] == 3.0

    # The link survives into the release.
    client.put(f"/api/datasets/raid_ui/samples/{rows['f003.png']}", json={"status": "done"})
    client.post("/api/datasets/raid_ui/releases", json={})
    validate(bucket, "raid_ui")
    line = next(
        x
        for x in map(json.loads, bucket.read("datasets/raid_ui/releases/v1/manifest.jsonl").splitlines())
        if x["id"] == rows["f003.png"]
    )
    assert line["meta"]["parent_id"] == vod and line["meta"]["t_s"] == 812.5
