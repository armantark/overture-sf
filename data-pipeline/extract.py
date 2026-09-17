"""Extract the San Francisco slice of Overture Maps into local Parquet files.

Everything the deployed app serves comes from this script. It reads the cloud-hosted
GeoParquet directly over S3 so there is no intermediate download step, and it writes
three files: the places themselves, a grid of cells with the context needed to rank
them for site selection, and a small metadata file recording exactly which release the
data came from.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import duckdb

S3_RELEASE_ROOT = "s3://overturemaps-us-west-2/release"

# Roughly two city blocks. Small enough that a recommendation points at somewhere you
# could actually walk, large enough that counts inside a cell are not all zero or one.
CELL_METERS = 200

# Overture's taxonomy covers freight brokers and holding companies alongside cafes. Site
# selection only makes sense for businesses that trade with walk-in customers, so the
# storefront ranking is restricted to these roots of the taxonomy hierarchy. The names are
# taken from the data itself rather than the docs, because several plausible-sounding
# roots ("retail", "eat_and_drink") do not exist and silently match nothing.
# Overture's own conflation-quality score, used as a floor on what counts as a shopfront.
#
# Without it, clusters of barely-corroborated listings at a single registered address count
# as a shopping street: 38 "shops" share 548 Market St, a private mailbox, with names like
# "ShopBase" and "hoodiefamily.com". Confidence separates those cleanly from genuine retail
# — that address averages 0.486 against 0.851 for Stonestown Galleria and 0.849 city-wide —
# where a cap on listings per address would not, because real malls legitimately have dozens.
# At 0.5 this keeps 93% of shopfronts and 88 of Stonestown's 90 while halving the mailbox.
STOREFRONT_CONFIDENCE = 0.5

STOREFRONT_ROOTS = (
    "food_and_drink",
    "shopping",
    "lifestyle_services",
    "arts_and_entertainment",
    "sports_and_recreation",
)


# Overture files these as "microhood" alongside genuine neighborhoods like Chinatown and
# North Beach, but they are single plazas and building forecourts a few dozen metres
# across. Left in, they win the nearest-point label for most of downtown, so a cell in the
# Financial District comes back labelled "Apple Mini Park". The list is exhaustive for the
# SF box and was read off the data, not guessed.
NON_NEIGHBORHOOD_LABELS = (
    "303 Second Street Plaza", "50 Beale Street Plaza", "560 Mission Street Plaza",
    "5th Street Plaza", "A.P. Giannini Plaza", "Apple Mini Park", "Bush Plaza",
    "Eagle Plaza", "Foundry Square", "Hallidie Plaza", "Margaret Douglas Plaza",
    "Piazza Angelo", "Portsmouth Square", "United Nations Plaza",
    "Yerba Buena Public Square",
)

# Beyond this, the nearest named point says nothing useful about where a cell actually is.
#
# These labels are not boundaries. Overture's usable SF neighbourhood geometry is 85 points,
# so a cell takes the name of whichever is closest, which is a Voronoi partition and
# disagrees with a real boundary check for roughly a third of places. Since the label also
# drives a user-facing filter rather than only a caption, a cell now has to be both close to
# its winner and clearly closer to it than to the runner-up; otherwise it goes unlabelled and
# is shown as San Francisco. Stonestown Galleria was labelled "Balboa Terrace" on a margin of
# under a metre.
# Tightening the distance as well was tried and reverted: at 700 m it left roughly half the
# cells unlabelled, including most of the top recommendations, and "Unnamed area" against the
# headline result is worse for a reader than an approximate name. The margin alone is what
# removes the genuinely ambiguous cases, at a cost of 614 unlabelled cells of 3,472.
MAX_LABEL_DISTANCE_M = 1500
MIN_LABEL_MARGIN = 1.05


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    con.execute("SET preserve_insertion_order=false;")
    return con


def with_retries(con, sql: str, label: str, attempts: int = 4):
    """S3 reads of this size fail intermittently, and a failure halfway through a
    multi-minute scan is expensive to redo by hand."""
    for attempt in range(1, attempts + 1):
        try:
            return con.execute(sql)
        except Exception as exc:  # noqa: BLE001 - surfaced to the operator below
            if attempt == attempts:
                raise
            wait = 2 ** attempt
            print(f"  {label}: attempt {attempt} failed ({exc}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", default="2026-08-19.0")
    ap.add_argument("--bbox", default="-122.517,37.70,-122.355,37.84",
                    help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--out", default="../data")
    args = ap.parse_args()

    minlon, minlat, maxlon, maxlat = (float(v) for v in args.bbox.split(","))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    base = f"{S3_RELEASE_ROOT}/{args.release}"
    bbox_filter = (
        f"bbox.xmin > {minlon} AND bbox.xmax < {maxlon} "
        f"AND bbox.ymin > {minlat} AND bbox.ymax < {maxlat}"
    )

    # Cell size in degrees. Longitude degrees shrink with latitude, so the lon step is
    # computed at the middle of the box to keep cells close to square on the ground.
    mid_lat = (minlat + maxlat) / 2
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(mid_lat))
    lat_step = CELL_METERS / m_per_deg_lat
    lon_step = CELL_METERS / m_per_deg_lon

    con = connect()
    con.execute(f"CREATE MACRO cell_x(lon) AS floor((lon - {minlon}) / {lon_step});")
    con.execute(f"CREATE MACRO cell_y(lat) AS floor((lat - {minlat}) / {lat_step});")

    print(f"Release {args.release}, bbox {args.bbox}")

    print("Reading places...")
    with_retries(con, f"""
        CREATE TABLE places AS
        SELECT
            id,
            names.primary                       AS name,
            ST_X(geometry)                      AS lon,
            ST_Y(geometry)                      AS lat,
            taxonomy.primary                    AS category,
            taxonomy.hierarchy                  AS category_path,
            CASE WHEN taxonomy.hierarchy IS NULL OR len(taxonomy.hierarchy) = 0
                 THEN NULL ELSE taxonomy.hierarchy[1] END AS category_root,
            basic_category,
            confidence,
            operating_status,
            websites[1]                         AS website,
            phones[1]                           AS phone,
            addresses[1].freeform               AS address,
            addresses[1].postcode               AS postcode,
            brand.names.primary                 AS brand_name,
            brand.wikidata                      AS brand_wikidata,
            len(sources)                        AS source_count,
            list_distinct(list_transform(sources, s -> s.dataset)) AS source_datasets,
            cell_x(ST_X(geometry))::INT         AS cx,
            cell_y(ST_Y(geometry))::INT         AS cy
        FROM read_parquet('{base}/theme=places/type=place/*')
        WHERE {bbox_filter}
          AND names.primary IS NOT NULL
          AND (operating_status IS DISTINCT FROM 'permanently_closed')
    """, "places")
    n_places = con.execute("SELECT count(*) FROM places").fetchone()[0]
    print(f"  {n_places:,} places")

    print("Reading buildings (footprint area per cell)...")
    with_retries(con, f"""
        CREATE TABLE building_cells AS
        SELECT
            cell_x(ST_X(ST_Centroid(geometry)))::INT AS cx,
            cell_y(ST_Y(ST_Centroid(geometry)))::INT AS cy,
            count(*)                                  AS building_count,
            sum(ST_Area(ST_Scale(geometry, {m_per_deg_lon}, {m_per_deg_lat}))) AS building_area_m2
        FROM read_parquet('{base}/theme=buildings/type=building/*')
        WHERE {bbox_filter}
        GROUP BY 1, 2
    """, "buildings")
    print(f"  {con.execute('SELECT count(*) FROM building_cells').fetchone()[0]:,} cells with buildings")

    print("Reading transportation (walkable street length per cell)...")
    with_retries(con, f"""
        CREATE TABLE segments AS
        SELECT geometry
        FROM read_parquet('{base}/theme=transportation/type=segment/*')
        WHERE {bbox_filter}
          AND subtype = 'road'
          AND class NOT IN ('motorway', 'trunk')
    """, "transportation")

    # Clip each segment to every cell it crosses, rather than crediting its whole length to
    # whichever cell happens to contain its midpoint. A road spanning ten cells otherwise
    # contributes nothing to nine of them and all of itself to the tenth, which is how a
    # 200 m square came to claim 9,984 m of street. Total length is unchanged by this; what
    # changes is where it is counted.
    n_x = int((maxlon - minlon) / lon_step) + 1
    n_y = int((maxlat - minlat) / lat_step) + 1
    con.execute(f"""
        CREATE TABLE grid AS
        SELECT cx, cy,
               ST_MakeEnvelope({minlon} + cx * {lon_step}, {minlat} + cy * {lat_step},
                               {minlon} + (cx + 1) * {lon_step},
                               {minlat} + (cy + 1) * {lat_step}) AS geom
        FROM (SELECT unnest(generate_series(0, {n_x})) AS cx)
        CROSS JOIN (SELECT unnest(generate_series(0, {n_y})) AS cy)
    """)
    con.execute(f"""
        CREATE TABLE street_cells AS
        SELECT g.cx, g.cy,
               sum(ST_Length(ST_Scale(ST_Intersection(s.geometry, g.geom),
                                      {m_per_deg_lon}, {m_per_deg_lat}))) AS street_len_m
        FROM segments s JOIN grid g ON ST_Intersects(s.geometry, g.geom)
        GROUP BY 1, 2
    """)
    print(f"  {con.execute('SELECT count(*) FROM street_cells').fetchone()[0]:,} cells with streets")

    print("Reading neighborhood labels...")
    excluded = ", ".join(f"'{n.replace(chr(39), chr(39) * 2)}'" for n in NON_NEIGHBORHOOD_LABELS)
    with_retries(con, f"""
        CREATE TABLE hoods AS
        SELECT names.primary AS name, subtype,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM read_parquet('{base}/theme=divisions/type=division/*')
        WHERE {bbox_filter}
          AND subtype IN ('neighborhood', 'microhood', 'macrohood')
          AND names.primary IS NOT NULL
          AND names.primary NOT IN ({excluded})
    """, "divisions")
    print(f"  {con.execute('SELECT count(*) FROM hoods').fetchone()[0]:,} neighborhood points")

    # Every cell that contains anything at all, with the storefront counts that site
    # selection ranks on. Cells with no streets are water or parkland and are dropped.
    roots = ", ".join(f"'{r}'" for r in STOREFRONT_ROOTS)
    con.execute(f"""
        CREATE TABLE cells AS
        WITH place_agg AS (
            SELECT cx, cy,
                   count(*)                                                    AS place_count,
                   count(*) FILTER (category_root IN ({roots})
                                    AND confidence >= {STOREFRONT_CONFIDENCE})  AS storefront_count
            FROM places GROUP BY 1, 2
        ),
        joined AS (
            SELECT
                COALESCE(p.cx, b.cx, s.cx) AS cx,
                COALESCE(p.cy, b.cy, s.cy) AS cy,
                COALESCE(p.place_count, 0)       AS place_count,
                COALESCE(p.storefront_count, 0)  AS storefront_count,
                COALESCE(b.building_count, 0)    AS building_count,
                COALESCE(b.building_area_m2, 0)  AS building_area_m2,
                COALESCE(s.street_len_m, 0)      AS street_len_m
            FROM place_agg p
            FULL OUTER JOIN building_cells b USING (cx, cy)
            FULL OUTER JOIN street_cells  s USING (cx, cy)
        )
        SELECT j.*,
               ({minlon} + (j.cx + 0.5) * {lon_step})::DOUBLE AS lon,
               ({minlat} + (j.cy + 0.5) * {lat_step})::DOUBLE AS lat
        FROM joined j
        WHERE j.street_len_m > 0
    """)

    # Attach the nearest neighborhood point purely as a label. Overture's neighborhood
    # polygons are too patchy in SF to assign cells by containment.
    con.execute(f"""
        CREATE TABLE cells_labelled AS
        WITH ranked AS (
            SELECT c.cx, c.cy, h.name,
                   sqrt(((h.lon - c.lon) * {m_per_deg_lon}) ^ 2
                      + ((h.lat - c.lat) * {m_per_deg_lat}) ^ 2) AS d,
                   row_number() OVER (
                       PARTITION BY c.cx, c.cy
                       ORDER BY ((h.lon - c.lon) * {m_per_deg_lon}) ^ 2
                              + ((h.lat - c.lat) * {m_per_deg_lat}) ^ 2
                   ) AS rn
            FROM cells c CROSS JOIN hoods h
        ),
        best AS (
            SELECT cx, cy,
                   max(name) FILTER (rn = 1) AS name,
                   max(d)    FILTER (rn = 1) AS d1,
                   max(d)    FILTER (rn = 2) AS d2
            FROM ranked WHERE rn <= 2 GROUP BY 1, 2
        )
        SELECT c.*,
               CASE WHEN b.d1 <= {MAX_LABEL_DISTANCE_M}
                     AND (b.d2 IS NULL OR b.d2 >= {MIN_LABEL_MARGIN} * b.d1)
                    THEN b.name END AS neighborhood
        FROM cells c LEFT JOIN best b ON b.cx = c.cx AND b.cy = c.cy
    """)
    n_cells = con.execute("SELECT count(*) FROM cells_labelled").fetchone()[0]
    print(f"  {n_cells:,} grid cells")

    # Counts per category per cell, so the API can answer "how many of X are already here"
    # without shipping every place to the client.
    #
    # Every category, not just the storefront roots. Restricting this table while the
    # interface offered all 1,325 categories meant 738 of them had no competitor rows at
    # all, and the API read that absence as genuine absence: asking where to open a
    # health_care business reported a block with "0 competitors" and a gap of 16.9 when
    # 1,437 such places exist in the city.
    con.execute("""
        CREATE TABLE cell_categories AS
        SELECT cx, cy, category_root, category, count(*) AS n
        FROM places
        WHERE category IS NOT NULL
        GROUP BY 1, 2, 3, 4
    """)

    con.execute(f"COPY places TO '{out}/places.parquet' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY cells_labelled TO '{out}/cells.parquet' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY hoods TO '{out}/neighborhoods.parquet' (FORMAT parquet, COMPRESSION zstd)")
    con.execute(f"COPY cell_categories TO '{out}/cell_categories.parquet' (FORMAT parquet, COMPRESSION zstd)")

    meta = {
        "release": args.release,
        "bbox": [minlon, minlat, maxlon, maxlat],
        "cell_meters": CELL_METERS,
        "lon_step": lon_step,
        "lat_step": lat_step,
        "storefront_roots": list(STOREFRONT_ROOTS),
        "storefront_confidence_floor": STOREFRONT_CONFIDENCE,
        "label_max_distance_m": MAX_LABEL_DISTANCE_M,
        "label_min_margin": MIN_LABEL_MARGIN,
        "counts": {"places": n_places, "cells": n_cells},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nWrote {out}/places.parquet, cells.parquet, cell_categories.parquet, meta.json")


if __name__ == "__main__":
    main()
