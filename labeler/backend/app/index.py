"""Local SQLite copy of every project's image list and labels.

Saves land here first (instant) and are pushed to the bucket by the sync worker. A row whose `rev` is
ahead of `pushed_rev` has not reached the bucket yet.
"""

import json
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    slug TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
    slug TEXT NOT NULL,
    file TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    PRIMARY KEY (slug, file)
);
CREATE TABLE IF NOT EXISTS annotations (
    slug TEXT NOT NULL,
    file TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL,
    n_objects INTEGER NOT NULL,
    n_suggested INTEGER NOT NULL,
    labels TEXT NOT NULL,
    class_counts TEXT NOT NULL,
    generation TEXT,
    rev INTEGER NOT NULL DEFAULT 0,
    pushed_rev INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (slug, file)
);
CREATE INDEX IF NOT EXISTS annotations_dirty ON annotations (slug) WHERE rev > pushed_rev;
"""


@dataclass
class Pending:
    slug: str
    file: str
    data: str
    rev: int


def _summary(data: dict) -> tuple[str, int, int, str, str]:
    objects = data.get("objects", [])
    accepted = [o for o in objects if o.get("accepted", True)]
    counts = Counter(str(o["class_id"]) for o in accepted)
    return (
        data.get("status", "todo"),
        len(accepted),
        len(objects) - len(accepted),
        json.dumps(data.get("labels", {}), ensure_ascii=False),
        json.dumps(counts),
    )


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

    # ---- projects

    def put_project(self, slug: str, data: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (slug, data) VALUES (?, ?)"
                " ON CONFLICT (slug) DO UPDATE SET data = excluded.data",
                (slug, json.dumps(data, ensure_ascii=False)),
            )

    def get_project(self, slug: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT data FROM projects WHERE slug = ?", (slug,)).fetchone()
        return json.loads(row[0]) if row else None

    # ---- images

    def set_images(self, slug: str, images: list[tuple[str, int, int]]) -> None:
        """Replace the project's image list (from the bucket's manifest)."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM images WHERE slug = ?", (slug,))
                self._conn.executemany(
                    "INSERT INTO images (slug, file, width, height) VALUES (?, ?, ?, ?)",
                    [(slug, f, w, h) for f, w, h in images],
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def add_image(self, slug: str, file: str, width: int, height: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO images (slug, file, width, height) VALUES (?, ?, ?, ?)",
                (slug, file, width, height),
            )

    def image(self, slug: str, file: str) -> tuple[int, int] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT width, height FROM images WHERE slug = ? AND file = ?", (slug, file)
            ).fetchone()
        return (row[0], row[1]) if row else None

    def image_files(self, slug: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._conn.execute("SELECT file FROM images WHERE slug = ?", (slug,))}

    def manifest(self, slug: str) -> list[tuple[str, int, int]]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT file, width, height FROM images WHERE slug = ? ORDER BY file", (slug,)
                )
            )

    def image_rows(self, slug: str) -> list[tuple]:
        """(file, width, height, status, n_objects, n_suggested, labels_json) sorted by file."""
        with self._lock:
            return list(
                self._conn.execute(
                    """
                    SELECT i.file, i.width, i.height, COALESCE(a.status, 'todo'),
                           COALESCE(a.n_objects, 0), COALESCE(a.n_suggested, 0), COALESCE(a.labels, '{}')
                    FROM images i LEFT JOIN annotations a ON a.slug = i.slug AND a.file = i.file
                    WHERE i.slug = ? ORDER BY i.file
                    """,
                    (slug,),
                )
            )

    # ---- annotations

    def get_annotation(self, slug: str, file: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM annotations WHERE slug = ? AND file = ?", (slug, file)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_annotation(self, slug: str, file: str, data: dict) -> None:
        """A local edit: stored now, pushed to the bucket later."""
        s = _summary(data)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO annotations
                    (slug, file, data, status, n_objects, n_suggested, labels, class_counts, rev)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT (slug, file) DO UPDATE SET
                    data = excluded.data, status = excluded.status, n_objects = excluded.n_objects,
                    n_suggested = excluded.n_suggested, labels = excluded.labels,
                    class_counts = excluded.class_counts, rev = annotations.rev + 1
                """,
                (slug, file, json.dumps(data, ensure_ascii=False), *s),
            )

    def put_remote_annotation(self, slug: str, file: str, data: dict, generation: str) -> bool:
        """A copy pulled from the bucket. Ignored if there's a local edit that hasn't been pushed."""
        s = _summary(data)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO annotations
                    (slug, file, data, status, n_objects, n_suggested, labels, class_counts, generation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (slug, file) DO UPDATE SET
                    data = excluded.data, status = excluded.status, n_objects = excluded.n_objects,
                    n_suggested = excluded.n_suggested, labels = excluded.labels,
                    class_counts = excluded.class_counts, generation = excluded.generation
                WHERE annotations.rev = annotations.pushed_rev
                """,
                (slug, file, json.dumps(data, ensure_ascii=False), *s, generation),
            )
            return cur.rowcount > 0

    def generations(self, slug: str) -> dict[str, tuple[str | None, bool]]:
        """file -> (generation last seen in the bucket, has unpushed edits)."""
        with self._lock:
            return {
                r[0]: (r[1], r[2] > r[3])
                for r in self._conn.execute(
                    "SELECT file, generation, rev, pushed_rev FROM annotations WHERE slug = ?", (slug,)
                )
            }

    def delete_annotation_if_clean(self, slug: str, file: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM annotations WHERE slug = ? AND file = ? AND rev = pushed_rev", (slug, file)
            )

    def pending(self, limit: int = 200) -> list[Pending]:
        with self._lock:
            return [
                Pending(*r)
                for r in self._conn.execute(
                    "SELECT slug, file, data, rev FROM annotations WHERE rev > pushed_rev LIMIT ?", (limit,)
                )
            ]

    def pending_count(self, slug: str | None = None) -> int:
        with self._lock:
            if slug is None:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM annotations WHERE rev > pushed_rev"
                ).fetchone()[0]
            return self._conn.execute(
                "SELECT COUNT(*) FROM annotations WHERE slug = ? AND rev > pushed_rev", (slug,)
            ).fetchone()[0]

    def mark_pushed(self, p: Pending, generation: str) -> None:
        # Only this revision; an edit made during the upload stays pending.
        with self._lock:
            self._conn.execute(
                "UPDATE annotations SET pushed_rev = ?, generation = ?"
                " WHERE slug = ? AND file = ? AND pushed_rev < ?",
                (p.rev, generation, p.slug, p.file, p.rev),
            )

    def annotations(self, slug: str) -> dict[str, dict]:
        with self._lock:
            return {
                r[0]: json.loads(r[1])
                for r in self._conn.execute("SELECT file, data FROM annotations WHERE slug = ?", (slug,))
            }

    def stats(self, slug: str) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM images WHERE slug = ?", (slug,)).fetchone()[0]
            by_status = dict(
                self._conn.execute(
                    """
                    SELECT a.status, COUNT(*) FROM annotations a
                    JOIN images i ON i.slug = a.slug AND i.file = a.file
                    WHERE a.slug = ? GROUP BY a.status
                    """,
                    (slug,),
                ).fetchall()
            )
            counts: Counter[int] = Counter()
            for (cc,) in self._conn.execute(
                """
                SELECT a.class_counts FROM annotations a JOIN images i ON i.slug = a.slug AND i.file = a.file
                WHERE a.slug = ?
                """,
                (slug,),
            ):
                for k, v in json.loads(cc).items():
                    counts[int(k)] += v
        done = by_status.get("done", 0)
        review = by_status.get("review", 0)
        return {
            "total": total,
            "done": done,
            "review": review,
            "todo": total - done - review,
            "class_counts": dict(counts),
        }
