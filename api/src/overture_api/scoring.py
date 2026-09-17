"""Confidence-aware ranking.

Every method here answers the same question — given a small, noisy sample, how good is
this thing really? — and they disagree in ways a user can feel. A place with five
five-star reviews beats everything under a raw average and falls sharply under Wilson.
Letting the user switch method is the point of the product, so each method has to be
explainable in one sentence.

The same machinery ranks two different things. For businesses the sample is a histogram
of star ratings. For city blocks the sample is a count of real Overture places, which is
also small and noisy, so the shrinkage logic applies unchanged and without inventing data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 95% two-sided normal quantile, used by the interval-based methods.
Z = 1.959963984540054

STARS = (1, 2, 3, 4, 5)
MIN_STAR, MAX_STAR = 1.0, 5.0

# A rating is "positive" at four stars or better. Wilson needs a binary outcome, and this
# is the split users actually make when scanning a listings page.
POSITIVE_THRESHOLD = 4


@dataclass(frozen=True)
class Sample:
    """A histogram of star ratings, indexed one through five."""

    counts: tuple[int, int, int, int, int]

    @property
    def n(self) -> int:
        return sum(self.counts)

    @property
    def total(self) -> int:
        return sum(star * c for star, c in zip(STARS, self.counts))

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else 0.0

    @property
    def positives(self) -> int:
        return sum(c for star, c in zip(STARS, self.counts) if star >= POSITIVE_THRESHOLD)

    @property
    def variance(self) -> float:
        """Population variance of the star values."""
        if self.n == 0:
            return 0.0
        m = self.mean
        return sum(c * (star - m) ** 2 for star, c in zip(STARS, self.counts)) / self.n


def raw(s: Sample) -> float:
    """The plain average, included so users can see what the others are correcting."""
    return s.mean if s.n else MIN_STAR


def wilson(s: Sample) -> float:
    """Lower bound of the 95% Wilson interval on the fraction of positive ratings.

    Rescaled from a 0-1 proportion back onto the star scale so it is comparable with the
    other methods on the same axis.
    """
    if s.n == 0:
        return MIN_STAR
    p = s.positives / s.n
    denom = 1 + Z * Z / s.n
    centre = p + Z * Z / (2 * s.n)
    margin = Z * math.sqrt((p * (1 - p) + Z * Z / (4 * s.n)) / s.n)
    lower = (centre - margin) / denom
    return MIN_STAR + lower * (MAX_STAR - MIN_STAR)


def steamdb(s: Sample, pull: float = 3.0) -> float:
    """Shrink the average toward the midpoint, hard at first and less as evidence grows.

    Easier to explain than Wilson on a five-star scale because it keeps the star units and
    simply says "we do not believe you yet".
    """
    if s.n == 0:
        return pull
    return s.mean - (s.mean - pull) * (2 ** -math.log10(s.n + 1))


def bayesian(s: Sample, prior: tuple[float, ...] = (0.5, 0.5, 1.0, 1.0, 0.5)) -> float:
    """Posterior mean under a Dirichlet prior over the whole star distribution.

    The prior is per-star rather than a single global average, so it can express a belief
    about the *shape* of an unknown place's ratings and not merely their mean.

    It does not, however, separate divisive places from consistent ones. Taking the
    posterior mean collapses the distribution back to one number, and two samples with the
    same size and mean score identically however differently their stars are spread. That
    separation is what `variance_weighted` is for.
    """
    post = [c + p for c, p in zip(s.counts, prior)]
    mass = sum(post)
    return sum(star * p for star, p in zip(STARS, post)) / mass


def laplace(s: Sample) -> float:
    """Add one observation of every star value.

    The simplest smoothing to describe, but not the mildest one here: its five pseudo-ratings
    pull toward 3.0, where the Bayesian prior's 3.5 pull toward 3.14, so Laplace moves further
    from the observed mean on 92% of the histograms in this dataset.
    """
    return bayesian(s, prior=(1.0, 1.0, 1.0, 1.0, 1.0))


# The mean of every rating in the corpus, measured rather than guessed. A prior that is not
# actually the population mean makes the method blend toward the wrong place while claiming
# to blend toward the city-wide average. `test_imdb_prior_matches_the_corpus` keeps the two
# in step if the data is ever regenerated.
CORPUS_MEAN = 3.99


def imdb(s: Sample, minimum_votes: float = 25.0, global_mean: float = CORPUS_MEAN) -> float:
    """The IMDb weighted rating: blend toward the corpus average until enough votes exist."""
    if s.n == 0:
        return global_mean
    w = s.n / (s.n + minimum_votes)
    return w * s.mean + (1 - w) * global_mean


def variance_weighted(s: Sample) -> float:
    """Average minus its own standard error, so divisive places are penalised.

    Two places can share a mean of 4.0 while one is unanimous and the other is half ones
    and half fives. This separates them; the mean-based methods cannot.

    The spread is measured on the Laplace-smoothed histogram rather than the raw one.
    Five identical five-star reviews have zero observed variance, but that is a fact about
    a tiny sample rather than evidence of certainty, and taking it at face value hands a
    perfect score to the thinnest possible record.
    """
    if s.n == 0:
        return MIN_STAR
    smoothed = Sample(tuple(c + 1 for c in s.counts))  # type: ignore[arg-type]
    stderr = math.sqrt(smoothed.variance / s.n)
    return max(MIN_STAR, s.mean - Z * stderr)


@dataclass(frozen=True)
class Method:
    key: str
    label: str
    blurb: str
    fn: object


METHODS: tuple[Method, ...] = (
    Method("steamdb", "Shrinkage",
           "Pulls thin evidence toward the middle, and lets go as reviews accumulate.", steamdb),
    Method("wilson", "Wilson lower bound",
           "The worst the positive share could plausibly be, at 95% confidence.", wilson),
    Method("bayesian", "Bayesian",
           "Smooths against a per-star prior rather than a single average.", bayesian),
    Method("variance_weighted", "Variance-penalised",
           "Subtracts about two standard errors, punishing disagreement and thin evidence.", variance_weighted),
    Method("imdb", "IMDb weighted",
           "Blends toward the corpus average until a place clears 25 reviews.", imdb),
    Method("laplace", "Laplace",
           "Adds one imaginary review of every star. The simplest to state, not the lightest.",
           laplace),
    Method("raw", "Raw average",
           "No correction at all. Shown so you can see what the others fix.", raw),
)

BY_KEY = {m.key: m for m in METHODS}
DEFAULT_METHOD = "steamdb"


def score(sample: Sample, method: str = DEFAULT_METHOD) -> float:
    try:
        return float(BY_KEY[method].fn(sample))
    except KeyError:
        raise ValueError(f"unknown scoring method: {method!r}") from None


def shrunk_rate(observed: float, exposure: float, prior_rate: float, strength: float) -> float:
    """Shrink an observed rate toward a prior when the exposure behind it is small.

    This is the site-selection counterpart to `steamdb`, and it runs on measured Overture
    counts rather than on anything generated. Without it a cell holding one shop beside a
    ten-metre stub of road reports a shops-per-metre rate an order of magnitude above the
    busiest street in the city, and tops the ranking on nothing.

    `strength` is expressed in the same units as `exposure` and acts as pseudo-exposure
    already observed at `prior_rate`. It therefore has to be comparable to a typical
    cell's exposure to do anything: a strength of 1 against a typical exposure of 20
    leaves the noise essentially untouched.
    """
    if exposure <= 0:
        return prior_rate
    return (observed + prior_rate * strength) / (exposure + strength)
