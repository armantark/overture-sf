"""Where should you open one of these?

Runs entirely on measured Overture data. No synthetic ratings are read here, so the half
of the product that makes a claim about the real world does not depend on invented numbers.

The question is deliberately narrow. Not "which block is best", which no open dataset can
answer, but "which blocks carry more activity than their number of these businesses would
suggest". That is a gap the data genuinely supports, and it is the shape of the question a
prospective owner or a commercial broker actually asks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import shrunk_rate

# How many walk-in businesses a block needs before it counts as a commercial block at all.
# Below this are back lots, freeway margins and parkland, where a recommendation would be
# technically defensible and practically useless. 553 of 3,472 cells clear it.
MIN_STOREFRONTS = 10

# Competitor counts must cover every category, or the tool reports "none here" for
# businesses that are plainly there. Complements are a different question — "what else
# would I be next to?" — and only walk-in trade is a useful answer. Without this the top
# neighbours of a coffee shop come back as internet service providers and immigration
# lawyers, which is true of downtown and useless to someone opening a cafe.
COMPLEMENT_ROOTS = (
    "food_and_drink",
    "shopping",
    "lifestyle_services",
    "arts_and_entertainment",
    "sports_and_recreation",
)


@dataclass(frozen=True)
class SiteResult:
    cx: int
    cy: int
    lon: float
    lat: float
    neighborhood: str | None
    storefronts: int
    places: int
    competitors: int
    expected: float
    gap: float
    saturation: float
    street_len_m: float
    building_area_m2: float


def rank_sites(store, category: str, *, limit: int = 60) -> dict:
    con = store.con

    # Exposure is the count of walk-in businesses, not of every Overture record.
    #
    # Using the raw place count made the tool recommend hospitals. Its top block for a coffee
    # shop was UCSF Mission Bay: 452 "businesses", of which 436 were health_care rows like
    # "Dr. Yvonne Wu, MD" and "UCSF Blood Draw Lab". Overture lists individual clinicians and
    # office tenants as places, so a medical building outranks a shopping street on a measure
    # meant to stand for passing trade. Counting storefronts instead returns Chinatown, Union
    # Square and Cow Hollow, which is what the question was asking.
    total_activity, = con.execute("SELECT sum(storefront_count) FROM cells").fetchone()
    total_category, = con.execute(
        "SELECT count(*) FROM places WHERE category = ?", [category]).fetchone()
    if not total_category:
        return {"category": category, "city_rate": 0.0, "results": [], "complements": []}

    # How many of this category a typical unit of activity supports, city-wide.
    city_rate = total_category / total_activity

    median_activity, = con.execute(
        f"SELECT median(storefront_count) FROM cells WHERE storefront_count >= {MIN_STOREFRONTS}"
    ).fetchone()

    rows = con.execute("""
        SELECT c.cx, c.cy, c.lon, c.lat, c.neighborhood, c.storefront_count, c.place_count,
               c.street_len_m, c.building_area_m2,
               COALESCE(cc.n, 0) AS competitors
        FROM cells c
        LEFT JOIN cell_categories cc
               ON cc.cx = c.cx AND cc.cy = c.cy AND cc.category = ?
        WHERE c.storefront_count >= ?
    """, [category, MIN_STOREFRONTS]).fetchall()

    results = []
    for cx, cy, lon, lat, hood, storefronts, places, street, area, competitors in rows:
        expected = city_rate * storefronts
        rate_hat = shrunk_rate(observed=competitors, exposure=storefronts,
                               prior_rate=city_rate, strength=median_activity)
        results.append(SiteResult(
            cx=cx, cy=cy, lon=float(lon), lat=float(lat), neighborhood=hood,
            storefronts=storefronts, places=places, competitors=competitors,
            expected=round(expected, 2), gap=round(expected - competitors, 2),
            saturation=round(rate_hat / city_rate, 2),
            street_len_m=round(street or 0.0), building_area_m2=round(area or 0.0),
        ))

    # Sort on the unrounded value. `gap` is rounded to two decimals for display, and sorting
    # on that left ties at the page boundary broken by DuckDB scan order, which is grid
    # position: for 562 of 640 categories rows 60 and 61 had an identical rounded gap.
    results.sort(key=lambda r: -(city_rate * r.storefronts - r.competitors))
    # How many blocks are actually undersupplied, as opposed to how many fit on the page.
    # The interface said "60 blocks where X are undersupplied" for every category, because
    # 60 is the page size.
    undersupplied = sum(1 for r in results if r.gap > 0)
    return {
        "category": category,
        "city_rate": city_rate,
        "undersupplied": undersupplied,
        "results": results[:limit],
        "complements": complements_for(store, category),
    }


def complements_for(store, category: str, *, limit: int = 6) -> list[dict]:
    """Which categories share a block with this one more often than chance would predict.

    Derived from co-occurrence in the data rather than from a hand-written list of
    "cafes go with bookshops", so it holds up when the city or the category changes.

    Lift is computed on how many *blocks* a category appears in, not how many outlets it
    has, which stops a handful of very dense downtown cells from dominating through sheer
    outlet count.

    It does not remove the density confound, and the honest reading is that there is no
    affinity signal here at all. Busy blocks contain more of everything, so two categories
    co-occur largely because both favour footfall. Conditioning the citywide baseline on
    comparably busy blocks takes the three categories this returns for coffee — menswear,
    steakhouses and lounges, at 4.29x, 4.26x and 4.15x unconditioned — down to 0.74x, 0.83x
    and 0.78x. All three fall *below* one: controlling for how busy a block is, they are
    slightly less likely than chance to share it with a coffee shop.

    So this is strictly "what else is on these blocks", which is true, and not "these
    businesses go together", which the data does not support. The interface says the former
    and lists the categories alphabetically, because ordering them by lift would assert a
    ranking that a bootstrap does not reproduce.

    (An earlier version of this note quoted 6.4x collapsing to 1.59x. Those came from before
    the walk-in root restriction below and no longer describe what this function computes.)
    """
    rows = store.con.execute("""
        WITH target AS (
            SELECT DISTINCT cx, cy FROM cell_categories WHERE category = ?
        ),
        nearby AS (
            SELECT cc.category, count(*) AS blocks
            FROM cell_categories cc JOIN target t ON t.cx = cc.cx AND t.cy = cc.cy
            WHERE cc.category <> ? AND cc.category_root IN {roots}
            GROUP BY 1
        ),
        citywide AS (
            SELECT category, count(DISTINCT (cx, cy)) AS blocks
            FROM cell_categories WHERE category_root IN {roots} GROUP BY 1
        ),
        totals AS (
            SELECT (SELECT count(*) FROM target) AS target_blocks,
                   (SELECT count(DISTINCT (cx, cy)) FROM cell_categories
                    WHERE category_root IN {roots}) AS all_blocks
        )
        SELECT nearby.category, nearby.blocks,
               (nearby.blocks / totals.target_blocks)
                   / (citywide.blocks / totals.all_blocks) AS lift
        FROM nearby JOIN citywide USING (category), totals
        -- 20 shared blocks is the support floor. It constrains the co-occurrence count,
        -- not how common the neighbour is city-wide, so it mainly excludes categories too
        -- rare to say anything about; dropping it to 15 admits umbrella categories and
        -- rewrites most of the answer, which is itself a sign of how thin this signal is.
        WHERE nearby.blocks >= 20
        ORDER BY lift DESC
        LIMIT ?
    """.replace("{roots}", str(COMPLEMENT_ROOTS)), [category, category, limit]).fetchall()
    return [{"category": c, "blocks": int(n), "lift": round(l, 2)} for c, n, l in rows]
