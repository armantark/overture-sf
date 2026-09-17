"""HTTP surface for the app, and the static host for the built frontend.

One service serves both, so the whole thing deploys as a single free-tier web service with
one URL and no CORS configuration to get wrong.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .scoring import DEFAULT_METHOD, METHODS, Sample, score
from .sites import rank_sites
from .store import PlaceRow, Store

app = FastAPI(
    title="Overture SF",
    description=(
        "Search San Francisco businesses from Overture Maps and rank them with "
        "confidence-aware scoring, or find blocks underserved by a given category. "
        "Ratings are synthetic and clearly labelled; the site-selection endpoints use "
        "only real Overture data."
    ),
    version="1.0.0",
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

store = Store()

# How many results the client can ask for at once.
MAX_LIMIT = 200

# The review-count filter is a coarse control offered as a fixed set of thresholds, and only
# those are accepted. Left as a free integer it is part of the cache key, so a caller
# rotating it mints unlimited distinct keys against 128 slots and every request pays for a
# fresh full scan: 40 trivial GETs took 17.7 s of server time and pushed the health check
# from 10 ms to 0.77 s.
REVIEW_THRESHOLDS = (0, 10, 25, 50, 100)


def check_min_reviews(value: int) -> int:
    """Accept only the offered thresholds.

    Snapping an arbitrary number down to the nearest one was the first attempt, and it was
    worse than the problem: asking for 200 would quietly return places with 100 reviews,
    silently ignoring the filter the caller asked for. Rejecting is honest and bounds the
    key space just as well.
    """
    if value not in REVIEW_THRESHOLDS:
        raise HTTPException(
            400, f"min_reviews must be one of {', '.join(str(t) for t in REVIEW_THRESHOLDS)}")
    return value


def blank_to_none(value: str | None) -> str | None:
    """An empty string and None mean the same thing here but are distinct cache keys."""
    return value or None


@lru_cache(maxsize=128)
def ranked_results(q, root, category, neighborhood, method, min_reviews) -> tuple[int, tuple]:
    """Filter, score and sort, returning the match count and only the servable page.

    Cached because the underlying data never changes for the life of the process, and the
    interface re-issues the same handful of queries as the user flips between methods.

    Only the first `MAX_LIMIT` results are retained. Caching the entire ranked set instead
    held about 50 MB per entry, because an unfiltered query ranks all 56,933 places, and
    128 distinct queries grew the process from 81 MB to 6.3 GB. Every place is still
    scored and sorted; what is dropped is the tail no request can ask for.
    """
    candidates = store.search(q=q, root=root, category=category,
                              neighborhood=neighborhood, min_reviews=min_reviews)
    ranked = sorted(candidates, key=lambda p: -score(Sample(p.counts), method))
    return len(ranked), tuple(serialise(p, method) for p in ranked[:MAX_LIMIT])


def serialise(p: PlaceRow, method: str) -> dict:
    sample = Sample(p.counts)
    return {
        "id": p.id,
        "name": p.name,
        "lon": p.lon,
        "lat": p.lat,
        "category": p.category,
        "categoryRoot": p.category_root,
        "neighborhood": p.neighborhood,
        "address": p.address,
        "website": p.website,
        "phone": p.phone,
        "brand": p.brand_name,
        "overture": {
            "confidence": p.confidence,
            "sourceCount": p.source_count,
            "sources": list(p.source_datasets or []),
        },
        "ratings": {
            "synthetic": True,
            "count": sample.n,
            "mean": round(sample.mean, 2),
            "histogram": list(p.counts),
            "score": round(score(sample, method), 3),
            "method": method,
        },
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "release": store.meta["release"],
            "places": store.meta["counts"]["places"]}


@app.get("/api/meta")
def meta() -> dict:
    """Everything the client needs to build its filter controls."""
    return {
        "release": store.meta["release"],
        "bbox": store.meta["bbox"],
        "cellMeters": store.meta["cell_meters"],
        "counts": store.meta["counts"],
        "methods": [{"key": m.key, "label": m.label, "blurb": m.blurb} for m in METHODS],
        "defaultMethod": DEFAULT_METHOD,
        "roots": store.roots,
        "categories": store.categories,
        "neighborhoods": store.neighborhoods,
        "ratingsAreSynthetic": True,
    }


@app.get("/api/search")
def search(
    q: str | None = Query(None, description="Substring of the business name"),
    root: str | None = Query(None, description="Overture taxonomy root"),
    category: str | None = Query(None, description="Overture taxonomy category"),
    neighborhood: str | None = None,
    method: str = Query(DEFAULT_METHOD, description="Ranking method"),
    min_reviews: int = Query(0, ge=0, le=5000,
                             description="One of 0, 10, 25, 50, 100"),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
) -> dict:
    if method not in {m.key for m in METHODS}:
        raise HTTPException(400, f"unknown ranking method: {method}")

    matched, top = ranked_results(
        blank_to_none(q), blank_to_none(root), blank_to_none(category),
        blank_to_none(neighborhood), method, check_min_reviews(min_reviews))
    return {
        "method": method,
        "matched": matched,
        "returned": min(matched, limit),
        "ratingsAreSynthetic": True,
        "results": list(top[:limit]),
    }


@app.get("/api/places/{place_id}")
def place(place_id: str, method: str = DEFAULT_METHOD) -> dict:
    if method not in {m.key for m in METHODS}:
        raise HTTPException(400, f"unknown ranking method: {method}")
    row = store.place(place_id)
    if row is None:
        raise HTTPException(404, "no such place")
    body = serialise(row, method)
    # A detail view is the one place worth showing every method at once, because the
    # disagreement between them is the argument for offering the choice at all.
    body["allScores"] = {m.key: round(score(Sample(row.counts), m.key), 3) for m in METHODS}
    return body


@app.get("/api/sites")
def sites(
    category: str = Query(..., description="Category you are thinking of opening"),
    limit: int = Query(60, ge=1, le=MAX_LIMIT),
) -> dict:
    out = rank_sites(store, category, limit=limit)
    if not out["results"] and out["city_rate"] == 0.0:
        raise HTTPException(404, f"no places in category {category!r}")
    return {
        "category": out["category"],
        "cityRate": out["city_rate"],
        "undersupplied": out["undersupplied"],
        "cellMeters": store.meta["cell_meters"],
        "usesSyntheticData": False,
        "complements": out["complements"],
        "results": [
            {
                "lon": r.lon, "lat": r.lat, "neighborhood": r.neighborhood,
                "storefronts": r.storefronts, "places": r.places,
                "competitors": r.competitors,
                "expected": r.expected, "gap": r.gap, "saturation": r.saturation,
                "streetMetres": r.street_len_m, "buildingAreaM2": r.building_area_m2,
            }
            for r in out["results"]
        ],
    }


# Serve the built frontend when it exists, so one service covers the whole product. In
# development the frontend runs on its own dev server and this is simply absent.
_web = Path(os.environ.get("VALID_WEB_DIR",
                           Path(__file__).resolve().parents[3] / "web" / "dist")).resolve()
if (_web / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_web / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        """Serve the built frontend, falling back to index.html for client-side routes.

        The candidate path is resolved and confirmed to sit inside the web directory before
        anything is returned. Without that check `GET /../../../../etc/passwd` served the
        real file with a 200: joining user-supplied text onto a base path does not keep the
        result under that base. The deployed instance happened to be shielded by its edge
        proxy rejecting the request, which is luck rather than a defence.
        """
        # An unmatched API path is a client error, not a client-side route. Returning the
        # app shell with a 200 for /api/searchh makes a typo look like a working request.
        if full_path.startswith("api/"):
            raise HTTPException(404, "no such endpoint")
        candidate = (_web / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_web):
            return FileResponse(candidate)
        return FileResponse(_web / "index.html")
