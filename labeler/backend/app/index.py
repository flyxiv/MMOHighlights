"""Local SQLite copy of each dataset's base release and its labeling/ work area.

- samples: the base release's manifest.jsonl, one row per sample (read-only here).
- work: labeling/labels/<id>.json files. Saves land here first and the sync worker pushes them to
  the bucket; a row whose rev is ahead of pushed_rev hasn't reached the bucket yet.
"""

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    name TEXT PRIMARY KEY,
    card TEXT,              -- dataset.json, or null before the first release
    project TEXT NOT NULL,  -- labeling/project.json
    classes TEXT NOT NULL,  -- labeling/classes.json
    base_classes TEXT NOT NULL,
    manifest_key TEXT       -- base release + manifest generation that samples was loaded from
);
CREATE TABLE IF NOT EXISTS samples (
    dataset TEXT NOT NULL,
    id TEXT NOT NULL,
    split TEXT NOT NULL,
    image TEXT,
    data TEXT NOT NULL,     -- the manifest line
    objects INTEGER NOT NULL,
    lsum TEXT NOT NULL,
    reviewed INTEGER NOT NULL,
    PRIMARY KEY (dataset, id)
);
CREATE TABLE IF NOT EXISTS work (
    dataset TEXT NOT NULL,
    id TEXT NOT NULL,
    data TEXT NOT NULL,     -- labeling/labels/<id>.json
    status TEXT NOT NULL,
    image TEXT,             -- only for images that aren't in the base release
    objects INTEGER NOT NULL,
    suggested INTEGER NOT NULL,
    lsum TEXT NOT NULL,
    generation TEXT,
    rev INTEGER NOT NULL DEFAULT 0,
    pushed_rev INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dataset, id)
);
CREATE INDEX IF NOT EXISTS work_dirty ON work (dataset) WHERE rev > pushed_rev;
CREATE TABLE IF NOT EXISTS dims (
    dataset TEXT NOT NULL,
    id TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    PRIMARY KEY (dataset, id)
);
"""

SHAPES = ("bbox", "polygon")
CHOICES = ("class", "multilabel")


@dataclass
class Pending:
    dataset: str
    id: str
    data: str
    rev: int


def summarize(labels: dict[str, Any]) -> tuple[int, str]:
    """(number of shapes, json of the class/multilabel values) for the image list."""
    objects = 0
    lsum = {}
    for task, lab in labels.items():
        if not isinstance(lab, dict):
            continue
        if lab.get("type") in SHAPES and isinstance(lab.get("value"), list):
            objects += len(lab["value"])
        elif lab.get("type") in CHOICES:
            lsum[task] = lab.get("value")
    return objects, json.dumps(lsum, ensure_ascii=False)


def _work_columns(data: dict) -> tuple:
    objects, lsum = summarize(data.get("labels", {}))
    suggested, _ = summarize(data.get("suggestions", {}))
    image = (data.get("files") or {}).get("image")
    return data.get("status", "todo"), image if isinstance(image, str) else None, objects, suggested, lsum


class Index:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _q(self, sql: str, args: Iterable = ()) -> list[tuple]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(args)))

    def _x(self, sql: str, args: Iterable = ()) -> int:
        with self._lock:
            return self._conn.execute(sql, tuple(args)).rowcount

    # ---- datasets

    def put_dataset(
        self, name: str, *, card: dict | None, project: dict, classes: dict, base_classes: dict
    ) -> None:
        self._x(
            """
            INSERT INTO datasets (name, card, project, classes, base_classes) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET card = excluded.card, project = excluded.project,
                classes = excluded.classes, base_classes = excluded.base_classes
            """,
            (
                name,
                json.dumps(card) if card else None,
                json.dumps(project),
                json.dumps(classes),
                json.dumps(base_classes),
            ),
        )

    def dataset(self, name: str) -> dict | None:
        rows = self._q("SELECT card, project, classes, base_classes FROM datasets WHERE name = ?", (name,))
        if not rows:
            return None
        card, project, classes, base_classes = rows[0]
        return {
            "card": json.loads(card) if card else None,
            "project": json.loads(project),
            "classes": json.loads(classes),
            "base_classes": json.loads(base_classes),
        }

    def set_project(self, name: str, project: dict) -> None:
        self._x("UPDATE datasets SET project = ? WHERE name = ?", (json.dumps(project), name))

    def set_classes(self, name: str, classes: dict) -> None:
        self._x("UPDATE datasets SET classes = ? WHERE name = ?", (json.dumps(classes), name))

    def manifest_key(self, name: str) -> str | None:
        rows = self._q("SELECT manifest_key FROM datasets WHERE name = ?", (name,))
        return rows[0][0] if rows else None

    # ---- base release

    def set_samples(self, name: str, lines: list[dict], key: str | None) -> None:
        rows = []
        for s in lines:
            objects, lsum = summarize(s.get("labels", {}))
            image = (s.get("files") or {}).get("image")
            reviewed = int(bool((s.get("meta") or {}).get("reviewed")))
            rows.append(
                (
                    name,
                    s["id"],
                    s.get("split", "unsplit"),
                    image if isinstance(image, str) else None,
                    json.dumps(s, ensure_ascii=False),
                    objects,
                    lsum,
                    reviewed,
                )
            )
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM samples WHERE dataset = ?", (name,))
                self._conn.executemany("INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                self._conn.execute("UPDATE datasets SET manifest_key = ? WHERE name = ?", (key, name))
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def base_sample(self, name: str, sid: str) -> dict | None:
        rows = self._q("SELECT data FROM samples WHERE dataset = ? AND id = ?", (name, sid))
        return json.loads(rows[0][0]) if rows else None

    def base_samples(self, name: str) -> list[dict]:
        rows = self._q("SELECT data FROM samples WHERE dataset = ? ORDER BY rowid", (name,))
        return [json.loads(r[0]) for r in rows]

    def sample_ids(self, name: str) -> set[str]:
        base = {r[0] for r in self._q("SELECT id FROM samples WHERE dataset = ?", (name,))}
        return base | {r[0] for r in self._q("SELECT id FROM work WHERE dataset = ?", (name,))}

    # ---- labeling/labels

    def work(self, name: str, sid: str) -> dict | None:
        rows = self._q("SELECT data FROM work WHERE dataset = ? AND id = ?", (name, sid))
        return json.loads(rows[0][0]) if rows else None

    def all_work(self, name: str) -> list[dict]:
        return [json.loads(r[0]) for r in self._q("SELECT data FROM work WHERE dataset = ?", (name,))]

    def save_work(self, name: str, sid: str, data: dict) -> None:
        """A local edit: stored now, pushed to the bucket later."""
        self._x(
            """
            INSERT INTO work (dataset, id, data, status, image, objects, suggested, lsum, rev)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (dataset, id) DO UPDATE SET
                data = excluded.data, status = excluded.status, image = excluded.image,
                objects = excluded.objects, suggested = excluded.suggested, lsum = excluded.lsum,
                rev = work.rev + 1
            """,
            (name, sid, json.dumps(data, ensure_ascii=False), *_work_columns(data)),
        )

    def put_remote_work(self, name: str, sid: str, data: dict, generation: str) -> None:
        """A copy pulled from the bucket. Ignored if there's a local edit that hasn't been pushed."""
        self._x(
            """
            INSERT INTO work (dataset, id, data, status, image, objects, suggested, lsum, generation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (dataset, id) DO UPDATE SET
                data = excluded.data, status = excluded.status, image = excluded.image,
                objects = excluded.objects, suggested = excluded.suggested, lsum = excluded.lsum,
                generation = excluded.generation
            WHERE work.rev = work.pushed_rev
            """,
            (name, sid, json.dumps(data, ensure_ascii=False), *_work_columns(data), generation),
        )

    def generations(self, name: str) -> dict[str, tuple[str | None, bool]]:
        """id -> (generation last seen in the bucket, has unpushed edits)."""
        rows = self._q("SELECT id, generation, rev, pushed_rev FROM work WHERE dataset = ?", (name,))
        return {r[0]: (r[1], r[2] > r[3]) for r in rows}

    def delete_work_if_clean(self, name: str, sid: str) -> None:
        self._x("DELETE FROM work WHERE dataset = ? AND id = ? AND rev = pushed_rev", (name, sid))

    def pending(self, limit: int = 200) -> list[Pending]:
        rows = self._q("SELECT dataset, id, data, rev FROM work WHERE rev > pushed_rev LIMIT ?", (limit,))
        return [Pending(*r) for r in rows]

    def pending_count(self, name: str | None = None) -> int:
        if name is None:
            return self._q("SELECT COUNT(*) FROM work WHERE rev > pushed_rev")[0][0]
        return self._q("SELECT COUNT(*) FROM work WHERE dataset = ? AND rev > pushed_rev", (name,))[0][0]

    def mark_pushed(self, p: Pending, generation: str) -> None:
        # Only this revision; an edit made during the upload stays pending.
        self._x(
            "UPDATE work SET pushed_rev = ?, generation = ? WHERE dataset = ? AND id = ? AND pushed_rev < ?",
            (p.rev, generation, p.dataset, p.id, p.rev),
        )

    # ---- image sizes measured from the files (for samples whose meta has none)

    def dims(self, name: str, sid: str) -> tuple[int, int] | None:
        rows = self._q("SELECT width, height FROM dims WHERE dataset = ? AND id = ?", (name, sid))
        return (rows[0][0], rows[0][1]) if rows else None

    def put_dims(self, name: str, sid: str, w: int, h: int) -> None:
        self._x("INSERT OR REPLACE INTO dims VALUES (?, ?, ?, ?)", (name, sid, w, h))

    # ---- image list

    def rows(self, name: str) -> list[tuple]:
        """Every sample with an image: base release first (manifest order), then new images by id.

        (id, image, split, base objects, base lsum, reviewed, base data,
         work status, work objects, work suggested, work lsum, work data)
        """
        base = self._q(
            """
            SELECT s.id, s.image, s.split, s.objects, s.lsum, s.reviewed, s.data,
                   w.status, w.objects, w.suggested, w.lsum, w.data
            FROM samples s LEFT JOIN work w ON w.dataset = s.dataset AND w.id = s.id
            WHERE s.dataset = ? AND s.image IS NOT NULL ORDER BY s.rowid
            """,
            (name,),
        )
        new = self._q(
            """
            SELECT w.id, w.image, 'unsplit', 0, '{}', 0, NULL,
                   w.status, w.objects, w.suggested, w.lsum, w.data
            FROM work w WHERE w.dataset = ? AND w.image IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM samples s WHERE s.dataset = w.dataset AND s.id = w.id)
            ORDER BY w.id
            """,
            (name,),
        )
        return base + new
