"""Integration tests against the real extracted San Francisco data.

These run over the actual Parquet rather than fixtures, because most of the ways this API
can be wrong involve the data itself: a join that silently drops rows, a filter that
matches a category name that does not exist, a ranking that puts thin evidence on top.
"""

import pytest
from fastapi.testclient import TestClient

from overture_api.main import app, store

client = TestClient(app)


@pytest.fixture(scope="module")
def meta():
    return client.get("/api/meta").json()


def test_health_reports_the_release_it_loaded():
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["places"] > 50_000
    assert body["release"].startswith("2026-")


def test_meta_offers_every_control_the_client_needs(meta):
    assert len(meta["methods"]) >= 5
    assert meta["defaultMethod"] in {m["key"] for m in meta["methods"]}
    assert len(meta["categories"]) > 100
    assert len(meta["neighborhoods"]) > 50
    assert meta["ratingsAreSynthetic"] is True


def test_search_returns_results_sorted_by_the_chosen_method():
    body = client.get("/api/search", params={"root": "food_and_drink", "limit": 50}).json()
    scores = [r["ratings"]["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


def test_changing_the_method_changes_the_ranking():
    """If it did not, the method picker would be decoration."""
    params = {"category": "restaurant", "limit": 25}
    raw = client.get("/api/search", params={**params, "method": "raw"}).json()
    wilson = client.get("/api/search", params={**params, "method": "wilson"}).json()
    assert [r["id"] for r in raw["results"]] != [r["id"] for r in wilson["results"]]


def test_raw_ranking_surfaces_thinner_evidence_than_wilson():
    """The product claim: naive averages reward places with too few reviews."""
    params = {"category": "restaurant", "limit": 25}
    raw = client.get("/api/search", params={**params, "method": "raw"}).json()
    wilson = client.get("/api/search", params={**params, "method": "wilson"}).json()
    raw_reviews = sum(r["ratings"]["count"] for r in raw["results"])
    wilson_reviews = sum(r["ratings"]["count"] for r in wilson["results"])
    assert wilson_reviews > raw_reviews


def test_every_result_is_flagged_as_synthetic():
    body = client.get("/api/search", params={"q": "pizza", "limit": 10}).json()
    assert body["ratingsAreSynthetic"] is True
    assert all(r["ratings"]["synthetic"] for r in body["results"])


def test_filters_actually_narrow_the_result_set(meta):
    hood = "Mission"
    broad = client.get("/api/search", params={"root": "food_and_drink"}).json()
    narrow = client.get("/api/search",
                        params={"root": "food_and_drink", "neighborhood": hood}).json()
    assert 0 < narrow["matched"] < broad["matched"]
    assert all(r["neighborhood"] == hood for r in narrow["results"])


def test_min_reviews_filter_is_respected():
    body = client.get("/api/search", params={"root": "shopping", "min_reviews": 100}).json()
    assert body["matched"] > 0
    assert all(r["ratings"]["count"] >= 100 for r in body["results"])


def test_search_with_no_matches_is_empty_rather_than_an_error():
    body = client.get("/api/search", params={"q": "zzzzznotabusiness"})
    assert body.status_code == 200
    assert body.json()["matched"] == 0


def test_unknown_method_is_rejected():
    assert client.get("/api/search", params={"method": "nonsense"}).status_code == 400


def test_place_detail_shows_all_methods_disagreeing():
    first = client.get("/api/search", params={"category": "restaurant", "limit": 1}).json()
    place_id = first["results"][0]["id"]
    body = client.get(f"/api/places/{place_id}").json()
    assert body["id"] == place_id
    assert len(set(body["allScores"].values())) > 1
    assert body["overture"]["sourceCount"] >= 2


def test_missing_place_is_a_404():
    assert client.get("/api/places/does-not-exist").status_code == 404


def test_sites_never_reads_synthetic_data():
    body = client.get("/api/sites", params={"category": "coffee_shop"}).json()
    assert body["usesSyntheticData"] is False
    assert "ratings" not in str(body)


def test_sites_ranks_by_the_gap_and_explains_it():
    body = client.get("/api/sites", params={"category": "coffee_shop", "limit": 40}).json()
    gaps = [r["gap"] for r in body["results"]]
    assert gaps == sorted(gaps, reverse=True)
    top = body["results"][0]
    # The headline claim on screen is "this block supports N, it has M".
    assert top["expected"] > top["competitors"]
    assert top["storefronts"] >= 10


def test_sites_does_not_recommend_empty_back_lots():
    body = client.get("/api/sites", params={"category": "bakery", "limit": 60}).json()
    assert all(r["storefronts"] >= 10 for r in body["results"])
    assert all(r["streetMetres"] > 0 for r in body["results"])


def test_sites_does_not_recommend_hospital_campuses():
    """Exposure counted every Overture record, and Overture lists individual clinicians as
    places, so the top block for a coffee shop was UCSF Mission Bay: 452 "businesses" of
    which 436 were health_care rows like "Dr. Yvonne Wu, MD".

    The test is on absolute storefront count rather than on the storefront share, because a
    mixed downtown block with 193 shops and 261 doctors is a perfectly good place to open a
    cafe. What must not happen is a block ranking on records that are not shopfronts at all.
    """
    body = client.get("/api/sites", params={"category": "coffee_shop", "limit": 20}).json()
    crowded_but_empty = [
        r for r in body["results"]
        if r["places"] > 400 and r["storefronts"] < 20
    ]
    assert not crowded_but_empty, f"recommended a non-retail campus: {crowded_but_empty[:1]}"
    assert all(r["storefronts"] >= 10 for r in body["results"])


def test_sites_for_an_unknown_category_is_a_404():
    assert client.get("/api/sites", params={"category": "not_a_category"}).status_code == 404


def test_complements_are_derived_not_hardcoded():
    coffee = client.get("/api/sites", params={"category": "coffee_shop"}).json()["complements"]
    hardware = client.get("/api/sites", params={"category": "bakery"}).json()["complements"]
    assert coffee and hardware
    assert all(c["lift"] > 1.0 and c["blocks"] >= 20 for c in coffee)
    assert {c["category"] for c in coffee} != {c["category"] for c in hardware}


def test_coordinates_are_numbers_not_strings():
    """DuckDB hands back DECIMAL for computed columns, which serialises as a JSON string
    and silently breaks the map."""
    body = client.get("/api/sites", params={"category": "bar", "limit": 5}).json()
    for r in body["results"]:
        assert isinstance(r["lon"], float) and isinstance(r["lat"], float)
    hits = client.get("/api/search", params={"q": "bar", "limit": 5}).json()["results"]
    for r in hits:
        assert isinstance(r["lon"], float) and isinstance(r["lat"], float)


def test_unfiltered_search_considers_every_place():
    """A capped scan would rank an arbitrary subset and misreport the total."""
    total = client.get("/api/health").json()["places"]
    body = client.get("/api/search", params={"limit": 1}).json()
    assert body["matched"] == total


def test_cache_does_not_retain_the_whole_ranked_set():
    """Caching every ranked place held ~50 MB per entry and grew the process to gigabytes
    across distinct queries. Rank everything; keep only what a request can ask for."""
    from overture_api.main import MAX_LIMIT, ranked_results

    ranked_results.cache_clear()
    matched, retained = ranked_results(None, None, None, None, "raw", 0)
    assert matched > 50_000, "must still rank the whole city"
    assert len(retained) <= MAX_LIMIT, "must not retain the tail nobody can request"


def test_match_count_survives_the_bounded_cache():
    total = client.get("/api/health").json()["places"]
    body = client.get("/api/search", params={"limit": 1}).json()
    assert body["matched"] == total
    assert body["returned"] == 1


def test_search_treats_wildcards_as_literal_text():
    """The search box is a substring control, not a pattern language. A bare "%" once
    returned all 56,933 places."""
    total = client.get("/api/health").json()["places"]
    for wildcard in ("%", "_", "%%"):
        body = client.get("/api/search", params={"q": wildcard, "limit": 1}).json()
        assert body["matched"] < total, f"{wildcard!r} behaved as a wildcard"


def test_percent_in_a_name_is_still_findable():
    """Businesses really are named things like "100% College Prep"."""
    body = client.get("/api/search", params={"q": "100%", "limit": 10}).json()
    assert body["matched"] > 0
    assert all("100%" in r["name"] for r in body["results"])


def test_odd_input_does_not_crash_the_search():
    for q in ("\\", "'", '"', "--", ";DROP TABLE places;", "café", "日本語", "x" * 2000):
        r = client.get("/api/search", params={"q": q, "limit": 1})
        assert r.status_code == 200, f"{q[:20]!r} returned {r.status_code}"


def test_concurrent_requests_do_not_corrupt_each_other():
    """A single DuckDB connection shared across FastAPI's thread pool failed 34 of 40
    concurrent site requests while the same requests one at a time all succeeded."""
    import concurrent.futures

    def hit(_):
        return client.get("/api/sites", params={"category": "coffee_shop", "limit": 5}).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(hit, range(40)))
    assert set(codes) == {200}, f"got {sorted(set(codes))}"


def test_place_detail_rejects_an_unknown_method():
    first = client.get("/api/search", params={"limit": 1}).json()["results"][0]
    r = client.get(f"/api/places/{first['id']}", params={"method": "nonsense"})
    assert r.status_code == 400


def test_every_offered_category_has_competitor_data(meta):
    """The competitor table once covered only five storefront roots while the interface
    offered all of them, so 738 categories reported "0 competitors" where hundreds existed
    and the recommendation was simply false."""
    offered = {c["key"] for c in meta["categories"]}
    have = {r[0] for r in store.con.execute(
        "SELECT DISTINCT category FROM cell_categories").fetchall()}
    assert not (offered - have), f"{len(offered - have)} categories have no competitor data"


def test_a_dense_category_never_reports_zero_competitors_everywhere():
    """The shape of the old bug: plenty of these exist, yet every block claimed none."""
    body = client.get("/api/sites", params={"category": "health_care", "limit": 20}).json()
    assert sum(r["competitors"] for r in body["results"]) > 0


def test_static_route_cannot_escape_the_web_directory():
    """`GET /../../../../etc/passwd` once returned the real file with a 200. Joining
    user-supplied text onto a base directory does not keep the result inside it."""
    import os
    from pathlib import Path as _Path

    from fastapi.testclient import TestClient as _TestClient

    web = _Path(__file__).resolve().parents[2] / "web" / "dist"
    if not (web / "index.html").exists():
        pytest.skip("frontend not built")

    os.environ["VALID_WEB_DIR"] = str(web)
    import importlib

    import overture_api.main as main_module
    reloaded = importlib.reload(main_module)
    spa_client = _TestClient(reloaded.app)

    # Assert on what must never come back rather than on which refusal arrives: the app
    # answers with index.html, and a path that normalises under /api/ is a 404 instead.
    for attack in ("../../../../../../etc/passwd", "../../data/meta.json",
                   "../api/src/overture_api/main.py"):
        body = spa_client.get(f"/{attack}").text
        assert "root:" not in body, f"{attack} leaked a system file"
        assert "def " not in body, f"{attack} leaked source"
        assert "bbox" not in body, f"{attack} leaked data"


def test_sites_reports_how_many_blocks_are_undersupplied_not_the_page_size():
    """The interface read "60 blocks where X are undersupplied" for all 640 categories,
    because 60 was the limit."""
    body = client.get("/api/sites", params={"category": "coffee_shop", "limit": 60}).json()
    assert body["undersupplied"] >= len(body["results"])
    rare = client.get("/api/sites", params={"category": "escape_room", "limit": 60}).json()
    assert rare["undersupplied"] != body["undersupplied"]


def test_review_filter_accepts_only_the_offered_thresholds():
    """min_reviews was a free integer in the cache key, so a caller rotating it minted
    unlimited keys and every request paid for a fresh full scan of all 56,933 places.

    It rejects rather than snapping: snapping 200 down to 100 would have returned places
    the caller explicitly filtered out.
    """
    for good in (0, 10, 25, 50, 100):
        assert client.get("/api/search", params={"min_reviews": good, "limit": 1}).status_code == 200
    for bad in (37, 200, 1, 4999):
        assert client.get("/api/search", params={"min_reviews": bad}).status_code == 400


def test_blank_filters_do_not_create_separate_cache_entries():
    from overture_api.main import blank_to_none

    assert blank_to_none("") is None
    assert blank_to_none(None) is None
    assert blank_to_none("bakery") == "bakery"


def test_unknown_api_paths_are_404_not_the_app_shell():
    """/api/searchh returned the HTML app with a 200, so a typo looked like it worked."""
    r = client.get("/api/searchh")
    assert r.status_code == 404
