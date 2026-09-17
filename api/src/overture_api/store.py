"""Loads the extracted Parquet into an in-process DuckDB and answers queries against it.

The whole San Francisco slice is about 8 MB, so it is held in memory rather than behind a
database server. That keeps the deployment to a single free-tier web service with no
attached storage, and every query below runs in single-digit milliseconds.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import duckdb


def _data_dir() -> Path:
    if env := os.environ.get("VALID_DATA_DIR"):
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True)
class PlaceRow:
    id: str
    name: str
    lon: float
    lat: float
    category: str | None
    category_root: str | None
    neighborhood: str | None
    address: str | None
    website: str | None
    phone: str | None
    brand_name: str | None
    confidence: float
    source_count: int
    source_datasets: list[str]
    counts: tuple[int, int, int, int, int]


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.dir = data_dir or _data_dir()
        missing = [f for f in ("places.parquet", "cells.parquet", "reviews.parquet",
                               "cell_categories.parquet", "meta.json")
                   if not (self.dir / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"missing extracted data in {self.dir}: {', '.join(missing)}. "
                "Run data-pipeline/extract.py then data-pipeline/synthesize.py."
            )
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self._db = duckdb.connect()
        for name in ("places", "cells", "reviews", "cell_categories"):
            self._db.execute(
                f"CREATE TABLE {name} AS SELECT * FROM '{self.dir / (name + '.parquet')}'")
        # No indexes are built. Two were, on cell_categories(category) and places(cx, cy),
        # under a comment claiming they served the site and search joins. They served
        # neither: places.cx is INTEGER against cells.cx BIGINT, so the planner inserts a
        # cast and scans both sides anyway, and the join the comment actually named is
        # places.id to reviews.id, which had no index at all. Timings with and without were
        # within noise on a dataset this size.
        self._local = threading.local()

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        """A cursor private to the calling thread.

        FastAPI runs synchronous handlers in a thread pool, and a single DuckDB connection
        shared across them corrupts in-flight results: 34 of 40 concurrent site requests
        returned HTTP 500 while the same requests issued one at a time all succeeded.
        Cursors share the database but keep their own execution state.
        """
        cursor = getattr(self._local, "cursor", None)
        if cursor is None:
            cursor = self._db.cursor()
            self._local.cursor = cursor
        return cursor

    @cached_property
    def categories(self) -> list[dict]:
        rows = self.con.execute("""
            SELECT category_root, category, count(*) AS n
            FROM places
            WHERE category IS NOT NULL AND category_root IS NOT NULL
            GROUP BY 1, 2 HAVING count(*) >= 10 ORDER BY category_root, n DESC
        """).fetchall()
        return [{"root": r, "key": c, "count": n} for r, c, n in rows]

    @cached_property
    def roots(self) -> list[dict]:
        rows = self.con.execute("""
            SELECT category_root, count(*) n FROM places
            WHERE category_root IS NOT NULL GROUP BY 1 ORDER BY n DESC
        """).fetchall()
        return [{"key": k, "count": n} for k, n in rows]

    @cached_property
    def neighborhoods(self) -> list[str]:
        rows = self.con.execute("""
            SELECT DISTINCT neighborhood FROM cells
            WHERE neighborhood IS NOT NULL ORDER BY 1
        """).fetchall()
        return [r[0] for r in rows]

    def search(self, *, q: str | None, root: str | None, category: str | None,
               neighborhood: str | None, min_reviews: int) -> list[PlaceRow]:
        """Return every place matching the filters, for ranking.

        Deliberately unbounded. Capping the scan would mean the top of the list depended on
        which arbitrary subset the database happened to return, and the reported match
        count would be a lie. The unfiltered case is the whole city and costs about 400 ms,
        which the cache in the route layer then hides on repeat views.
        """
        where, params = ["1=1"], []
        if q:
            # A search box is a literal-substring control, but ILIKE reads % and _ as
            # wildcards, so searching for "100%" matched "100" followed by anything and a
            # bare "%" returned the entire city. Businesses with a literal percent sign in
            # their name are real ("100% College Prep"), so escape rather than strip.
            pattern = (q.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_"))
            where.append("p.name ILIKE ? ESCAPE '\\'")
            params.append(f"%{pattern}%")
        if root:
            where.append("p.category_root = ?")
            params.append(root)
        if category:
            where.append("p.category = ?")
            params.append(category)
        if neighborhood:
            where.append("c.neighborhood = ?")
            params.append(neighborhood)
        where.append("(r.s1 + r.s2 + r.s3 + r.s4 + r.s5) >= ?")
        params.append(min_reviews)

        rows = self.con.execute(f"""
            SELECT p.id, p.name, p.lon, p.lat, p.category, p.category_root,
                   c.neighborhood, p.address, p.website, p.phone, p.brand_name,
                   p.confidence, p.source_count, p.source_datasets,
                   r.s1, r.s2, r.s3, r.s4, r.s5
            FROM places p
            JOIN reviews r ON r.id = p.id
            LEFT JOIN cells c ON c.cx = p.cx AND c.cy = p.cy
            WHERE {' AND '.join(where)}
        """, params).fetchall()

        return [PlaceRow(*r[:14], counts=(r[14], r[15], r[16], r[17], r[18])) for r in rows]

    def place(self, place_id: str) -> PlaceRow | None:
        rows = self.con.execute("""
            SELECT p.id, p.name, p.lon, p.lat, p.category, p.category_root,
                   c.neighborhood, p.address, p.website, p.phone, p.brand_name,
                   p.confidence, p.source_count, p.source_datasets,
                   r.s1, r.s2, r.s3, r.s4, r.s5
            FROM places p
            JOIN reviews r ON r.id = p.id
            LEFT JOIN cells c ON c.cx = p.cx AND c.cy = p.cy
            WHERE p.id = ?
        """, [place_id]).fetchall()
        if not rows:
            return None
        r = rows[0]
        return PlaceRow(*r[:14], counts=(r[14], r[15], r[16], r[17], r[18]))
