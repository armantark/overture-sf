"""Tests for the data pipeline's determinism claim.

The README states that regenerating the synthetic reviews produces byte-identical output and
that this "is checked, not assumed". Until this file existed, nothing checked it. The whole
defence of shipping synthetic ratings rests on reproducibility, so the claim needs a test
rather than a memory of having run it twice by hand.

Regenerating all 56,933 histograms takes about a minute, so this reproduces a sample and
compares it against what was actually shipped.
"""

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "data-pipeline"))

import numpy as np  # noqa: E402

from synthesize import (  # noqa: E402
    CATEGORY_QUALITY,
    CATEGORY_VOLUME,
    DEFAULT_QUALITY,
    DEFAULT_VOLUME,
    seed_for,
    star_probabilities,
)


def regenerate(place_id, root, confidence, source_count):
    """The generator's inner loop, reproduced exactly."""
    rng = np.random.default_rng(seed_for(place_id))
    mean_q, concentration = CATEGORY_QUALITY.get(root, DEFAULT_QUALITY)
    quality = rng.beta(mean_q * concentration, (1 - mean_q) * concentration)
    popularity = (0.45 + 1.1 * float(confidence or 0.5)) * (1.0 + 0.55 * ((source_count or 2) - 2))
    median = CATEGORY_VOLUME.get(root, DEFAULT_VOLUME) * popularity
    n = int(rng.lognormal(mean=np.log(max(median, 1.0)), sigma=0.95))
    n = int(np.clip(n, 0, 4000))
    return rng.multinomial(n, star_probabilities(quality)).tolist() if n else [0, 0, 0, 0, 0]


def test_shipped_reviews_reproduce_from_the_shipped_places():
    """The README's central defence of the synthetic data. Sampled, not exhaustive."""
    rows = duckdb.connect().execute(f"""
        SELECT p.id, p.category_root, p.confidence, p.source_count,
               r.s1, r.s2, r.s3, r.s4, r.s5
        FROM '{DATA / "places.parquet"}' p
        JOIN '{DATA / "reviews.parquet"}' r ON r.id = p.id
        ORDER BY p.id
        LIMIT 400
    """).fetchall()
    assert rows, "no data to check"
    for place_id, root, conf, srcs, *shipped in rows:
        assert regenerate(place_id, root, conf, srcs) == list(shipped), place_id


def test_the_seed_is_stable_across_processes():
    """Python's hash() is salted per process and would give different reviews on every
    restart, so the seed must come from a stable digest."""
    assert seed_for("abc-123") == seed_for("abc-123")
    assert seed_for("abc-123") != seed_for("abc-124")
    # Pinned so a change to the seeding scheme is a deliberate, visible act.
    assert seed_for("abc-123") == 8382482502496457251


def test_star_probabilities_stay_j_shaped():
    """A symmetric bell would make the histograms implausible and leave the
    variance-penalising method with nothing to separate."""
    p = star_probabilities(0.82)
    assert p.argmax() == 4, "five stars should be the mode"
    assert p[0] > 0.01, "there must be a complaint tail"
    assert abs(p.sum() - 1.0) < 1e-9
