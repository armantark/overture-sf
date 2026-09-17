"""Tests for the ranking methods.

These check the properties that make the methods worth offering as a choice: that thin
evidence is penalised, that more evidence converges on the plain average, and that the
methods actually disagree. A test asserting a hard-coded score to six decimals would pass
just as well with the maths wrong, so the assertions are about behaviour.
"""

import math
from pathlib import Path

import pytest

from overture_api.scoring import (
    BY_KEY,
    CORPUS_MEAN,
    METHODS,
    Sample,
    imdb,
    raw,
    score,
    shrunk_rate,
    steamdb,
    variance_weighted,
    wilson,
)

THIN_PERFECT = Sample((0, 0, 0, 0, 5))       # five reviews, all five stars
THICK_GOOD = Sample((2, 3, 10, 60, 120))     # 195 reviews averaging 4.5
UNANIMOUS = Sample((0, 0, 0, 0, 120))        # 120 reviews, all five stars
DIVISIVE = Sample((60, 0, 0, 0, 60))         # 120 reviews, half ones and half fives
STEADY = Sample((0, 0, 0, 120, 0))           # 120 reviews, all four stars
EMPTY = Sample((0, 0, 0, 0, 0))

CORRECTING = [m.key for m in METHODS if m.key != "raw"]


@pytest.mark.parametrize("key", CORRECTING)
def test_thin_evidence_scores_below_its_own_average(key):
    """The whole point: five perfect reviews must not outrank a well-reviewed place."""
    assert score(THIN_PERFECT, key) < THIN_PERFECT.mean


@pytest.mark.parametrize("key", CORRECTING)
def test_thin_perfect_loses_to_thick_good(key):
    assert score(THIN_PERFECT, key) < score(THICK_GOOD, key)


@pytest.mark.parametrize("key", CORRECTING)
def test_more_evidence_moves_toward_the_plain_average(key):
    """Every correction should fade as the sample grows, not persist forever."""
    thin_gap = abs(score(THIN_PERFECT, key) - THIN_PERFECT.mean)
    thick_gap = abs(score(UNANIMOUS, key) - UNANIMOUS.mean)
    assert thick_gap < thin_gap


@pytest.mark.parametrize("key", [m.key for m in METHODS])
def test_scores_stay_on_the_star_scale(key):
    for sample in (THIN_PERFECT, THICK_GOOD, UNANIMOUS, DIVISIVE, STEADY, EMPTY):
        assert 1.0 <= score(sample, key) <= 5.0


def test_variance_method_separates_divisive_from_steady():
    """Both average 3.0 and 4.0 respectively; only this method should notice the split."""
    assert variance_weighted(DIVISIVE) < DIVISIVE.mean - 0.3
    assert variance_weighted(STEADY) > STEADY.mean - 0.2


def test_divisive_and_steady_are_indistinguishable_to_the_raw_average():
    """Guards the claim the UI makes about why the choice of method matters."""
    balanced = Sample((30, 0, 0, 0, 30))     # mean 3.0
    mediocre = Sample((0, 0, 60, 0, 0))      # mean 3.0
    assert raw(balanced) == raw(mediocre)
    assert variance_weighted(balanced) < variance_weighted(mediocre)


def test_unanimous_thin_sample_is_not_perfect():
    """Zero observed spread in a tiny sample is not evidence of certainty."""
    assert variance_weighted(THIN_PERFECT) < 4.5


def test_wilson_rewards_consistency_over_a_higher_mean():
    """A wall of fours beats a mix that averages higher but has real negatives."""
    mixed = Sample((20, 0, 0, 0, 100))       # mean 4.33, but a sixth are one-star
    assert mixed.mean > STEADY.mean
    assert wilson(STEADY) > wilson(mixed)


def test_methods_actually_disagree():
    """If every method ranked identically the picker would be decoration."""
    ranked = {
        key: sorted(["thin", "thick", "divisive"],
                    key=lambda n: -score({"thin": THIN_PERFECT, "thick": THICK_GOOD,
                                          "divisive": DIVISIVE}[n], key))
        for key in BY_KEY
    }
    assert len({tuple(v) for v in ranked.values()}) > 1


def test_empty_sample_never_crashes_or_returns_nan():
    for key in BY_KEY:
        value = score(EMPTY, key)
        assert not math.isnan(value)


def test_unknown_method_is_rejected():
    with pytest.raises(ValueError):
        score(THICK_GOOD, "definitely_not_a_method")


def test_imdb_pulls_toward_the_global_mean_for_few_votes():
    """Asserted as a property rather than a threshold: the previous version hard-coded a
    bound tied to the prior's value, so correcting the prior broke a passing test."""
    thin = Sample((0, 0, 0, 0, 2))
    assert abs(imdb(thin) - CORPUS_MEAN) < abs(imdb(thin) - thin.mean)
    assert imdb(Sample((0, 0, 0, 0, 2000))) > 4.9


def test_imdb_prior_matches_the_corpus():
    """The blurb promises a blend toward the corpus average, so the constant has to be it.
    It was 3.6 against a real corpus mean of 3.99."""
    import duckdb

    data = Path(__file__).resolve().parents[2] / "data" / "reviews.parquet"
    total, weighted = duckdb.connect().execute(f"""
        SELECT sum(s1 + s2 + s3 + s4 + s5),
               sum(1 * s1 + 2 * s2 + 3 * s3 + 4 * s4 + 5 * s5)
        FROM '{data}'
    """).fetchone()
    assert abs(CORPUS_MEAN - weighted / total) < 0.01


def test_steamdb_is_monotone_in_evidence():
    """Adding more of the same good reviews must never lower the score."""
    scores = [steamdb(Sample((0, 0, 0, 0, n))) for n in (1, 5, 25, 100, 1000)]
    assert scores == sorted(scores)


# A typical cell's exposure, so `strength` is on a comparable scale. Picking strength
# well below this is the mistake that makes the shrinkage decorative.
TYPICAL_EXPOSURE = 20.0


def test_shrunk_rate_tames_an_extreme_rate_from_almost_no_exposure():
    """One shop beside a stub of road reports a rate of 20 per unit. It must not stand."""
    raw_ratio = 1 / 0.05
    shrunk = shrunk_rate(observed=1, exposure=0.05,
                         prior_rate=2.0, strength=TYPICAL_EXPOSURE)
    assert raw_ratio == 20.0
    assert abs(shrunk - 2.0) < 0.1


def test_shrunk_rate_keeps_the_signal_when_exposure_is_real():
    """A genuinely dense block must still read as denser than the prior."""
    shrunk = shrunk_rate(observed=80, exposure=TYPICAL_EXPOSURE,
                         prior_rate=2.0, strength=TYPICAL_EXPOSURE)
    assert shrunk > 2.5


def test_well_evidenced_density_outranks_a_noisy_sliver():
    sliver = shrunk_rate(observed=1, exposure=0.05,
                         prior_rate=2.0, strength=TYPICAL_EXPOSURE)
    dense = shrunk_rate(observed=80, exposure=TYPICAL_EXPOSURE,
                        prior_rate=2.0, strength=TYPICAL_EXPOSURE)
    assert sliver < dense


def test_shrunk_rate_falls_back_to_the_prior_with_no_exposure():
    assert shrunk_rate(observed=0, exposure=0, prior_rate=2.0, strength=1.0) == 2.0


def test_laplace_is_not_the_gentlest_correction():
    """The blurb once called it the gentlest. Its pseudo-ratings pull toward 3.0 while the
    Bayesian prior pulls toward roughly 3.14, so on a good thin sample Laplace moves the
    score further from the observed mean, not less."""
    from overture_api.scoring import bayesian, laplace

    thin_good = Sample((0, 0, 0, 2, 8))
    assert abs(laplace(thin_good) - thin_good.mean) > abs(bayesian(thin_good) - thin_good.mean)
