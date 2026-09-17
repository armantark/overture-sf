"""Generate the synthetic review histograms the ranking demo runs on.

Overture carries no ratings, reviews, hours or prices — it is a map of what exists, not a
map of what anyone thought of it. The comparison half of this product needs a rating
sample to rank, so this script fabricates one. That is a real limitation and the app says
so on every screen that shows a score.

Three properties keep this honest:

1. It is deterministic. The seed is the place's Overture GERS id, so the same place gets
   the same reviews on every run, on every machine, and after every monthly release.
2. It is driven by real signals. How well-known a place is comes from its Overture
   `confidence` and source count, and its rating profile comes from its real category.
   Nothing is drawn from thin air that could have been read from the data.
3. It is separable. The site-selection half of the product never reads this file, so the
   half that makes a recommendation about the real world runs entirely on real data.

None of that makes the ratings true. It makes them reproducible and clearly labelled.
"""

import argparse
import hashlib
from pathlib import Path

import duckdb
import numpy as np

# Rating culture differs by category in ways anyone who has read reviews will recognise:
# people are harsh on utilities and generous about places they chose to visit. Values are
# (mean latent quality 0-1, spread), used as a Beta prior per category root.
CATEGORY_QUALITY = {
    "food_and_drink": (0.82, 9.0),
    "shopping": (0.80, 9.0),
    "arts_and_entertainment": (0.86, 10.0),
    "sports_and_recreation": (0.85, 10.0),
    "lifestyle_services": (0.79, 8.0),
    "health_care": (0.76, 7.0),
    "services_and_business": (0.72, 6.0),
    "travel_and_transportation": (0.68, 6.0),
    "lodging": (0.76, 8.0),
    "community_and_government": (0.70, 6.0),
    "education": (0.80, 8.0),
    "cultural_and_historic": (0.88, 11.0),
    "geographic_entities": (0.82, 8.0),
}
DEFAULT_QUALITY = (0.76, 8.0)

# Typical review counts differ by an order of magnitude between a restaurant and an
# accountant's office. This is the median count before the popularity multiplier.
CATEGORY_VOLUME = {
    "food_and_drink": 90,
    "arts_and_entertainment": 60,
    "shopping": 35,
    "sports_and_recreation": 30,
    "lodging": 55,
    "lifestyle_services": 25,
    "health_care": 18,
    "cultural_and_historic": 40,
    "education": 15,
    "community_and_government": 12,
    "travel_and_transportation": 20,
    "services_and_business": 10,
}
DEFAULT_VOLUME = 12

STAR_VALUES = np.array([1, 2, 3, 4, 5])


def seed_for(place_id: str) -> int:
    """A stable 64-bit seed from the GERS id. Python's hash() is salted per process and
    would give different reviews on every restart."""
    return int.from_bytes(hashlib.blake2b(place_id.encode(), digest_size=8).digest(), "big")


# Bin midpoints on a 0-1 quality scale, one per star.
STAR_MIDPOINTS = (STAR_VALUES - 0.5) / 5.0

# How sharply opinion clusters. Higher means more agreement among reviewers.
OPINION_CONCENTRATION = 6.0

# Even loved places collect complaints, and this floor is what gives the
# variance-penalising method something to find.
COMPLAINT_TAIL = np.array([0.045, 0.015, 0.010, 0.0, 0.0])


def star_probabilities(quality: float) -> np.ndarray:
    """Turn a latent quality in 0-1 into a distribution over one to five stars.

    Real rating distributions are strongly J-shaped: mostly fives, a thin tail of ones,
    and comparatively few twos and threes. A symmetric bell would produce histograms no
    user would find plausible, and would leave the variance-penalising method with almost
    nothing to distinguish, since disagreement in real data lives in that one-star tail.

    The shape comes from a Beta density evaluated at the five bin midpoints, which is
    naturally skewed rather than symmetric, plus an explicit floor of complaints.
    """
    a = 1.0 + OPINION_CONCENTRATION * quality
    b = 1.0 + OPINION_CONCENTRATION * (1.0 - quality)
    weights = STAR_MIDPOINTS ** (a - 1.0) * (1.0 - STAR_MIDPOINTS) ** (b - 1.0)
    weights = weights / weights.sum() + COMPLAINT_TAIL
    return weights / weights.sum()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="../data")
    args = ap.parse_args()
    data = Path(args.data).resolve()

    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT id, category_root, confidence, source_count
        FROM '{data}/places.parquet'
    """).fetchall()

    ids, hist = [], np.zeros((len(rows), 5), dtype=np.int32)
    for i, (place_id, root, confidence, source_count) in enumerate(rows):
        rng = np.random.default_rng(seed_for(place_id))

        mean_q, concentration = CATEGORY_QUALITY.get(root, DEFAULT_QUALITY)
        quality = rng.beta(mean_q * concentration, (1 - mean_q) * concentration)

        # Overture's confidence, plus whether it attached one of its own `Overture-signals`
        # records, stand in for how well-known a place is.
        #
        # This is deliberately not described as cross-provider corroboration: no place in
        # this extract has more than one non-Overture provider, so `source_count` only ever
        # reads 2 or 3 and the difference is purely whether that signals record exists.
        popularity = (0.45 + 1.1 * float(confidence or 0.5)) * (1.0 + 0.55 * ((source_count or 2) - 2))
        median = CATEGORY_VOLUME.get(root, DEFAULT_VOLUME) * popularity
        n = int(rng.lognormal(mean=np.log(max(median, 1.0)), sigma=0.95))
        n = int(np.clip(n, 0, 4000))

        ids.append(place_id)
        if n:
            hist[i] = rng.multinomial(n, star_probabilities(quality))

    con.execute("CREATE TABLE r (id VARCHAR, s1 INT, s2 INT, s3 INT, s4 INT, s5 INT)")
    con.executemany("INSERT INTO r VALUES (?,?,?,?,?,?)",
                    [(pid, *counts.tolist()) for pid, counts in zip(ids, hist)])
    con.execute(f"COPY r TO '{data}/reviews.parquet' (FORMAT parquet, COMPRESSION zstd)")

    total = int(hist.sum())
    reviewed = int((hist.sum(axis=1) > 0).sum())
    mean_star = float((hist * STAR_VALUES).sum() / total)
    print(f"Wrote {data}/reviews.parquet")
    print(f"  {len(ids):,} places, {reviewed:,} with at least one review")
    print(f"  {total:,} synthetic reviews, mean {mean_star:.2f} stars")


if __name__ == "__main__":
    main()
