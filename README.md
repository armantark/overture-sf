# Overture SF — ranking under thin evidence

**One sentence:** Search San Francisco's businesses and rank them by a statistical method
you choose, then flip the same question around and ask which city blocks are busy enough to
support a business nobody has opened there yet.

**Hosting:** the public instance ran on Koyeb's free tier for the assessment and has since
been retired, because that tier allows one free service and a later project now holds the slot.
Everything below runs locally, and `tooling/deploy.sh` redeploys the same container in one
command. The service starts in 1.2 s and loads its whole dataset in 0.15 s.

Built on [Overture Maps](https://overturemaps.org) open data, release `2026-08-19.0`.

---

## Why this

The brief was one line, so the first real decision was what not to build. Three ideas were
measured against the data before one was chosen, and two were dropped because the data would
not honestly support them.

**Dropped — a neighbourhood churn tracker.** Overture's stable GERS ids make month-over-month
diffing exact, which is genuinely impossible on Google or Yelp at any price. So I measured it:
between the July and August releases, San Francisco gained 8,033 ids and lost 1,524. That
sounds like a product until you read the names. The new arrivals are overwhelmingly individual
people — solo real-estate agents and practitioners being ingested as "places" — and many arrive
already marked `permanently_closed`. Exactly 15 places flipped from open to closed all month.
A resident opening a "what changed on your block" map would see meaningless pins. Ingest churn
is not neighbourhood churn.

**Dropped — a walkability score.** Overture's 55,518 street segments make real network-based
isochrones possible rather than crow-flies circles. But WalkScore owns that mental slot, and
"ours is computed from open data" is an engineering virtue, not a user benefit.

**Built — ranking under thin evidence.** Every listings product in the world sorts by average
rating, and the average is wrong in a specific, well-understood way: a place with five
five-star reviews outranks a place with four hundred reviews averaging 4.5. There is a century
of statistics about this and essentially no consumer product exposes it. Making the correction
visible — letting you watch a list reorder as you switch from a raw average to a Wilson lower
bound — is a real idea that happens to have a second, stranger use.

Because the same shrinkage logic applies to city blocks. A block with one shop and ten metres
of street frontage reports a shop density an order of magnitude above the busiest street in
the city, and it means nothing. Shrinking that estimate toward the city-wide rate is what
produces the saturation figure shown against each block. The ranking itself is the plain
gap between the businesses a block's activity predicts and the ones actually there, which
keeps it consistent with the sentence on screen — and means bigger, busier blocks legitimately
dominate, because they are where the larger absolute opportunity is. One engine, two sides.

## The honest part: the ratings are synthetic

**Overture contains no ratings, no reviews, no hours and no prices.** It is a map of what
exists, not a map of what anyone thought of it. The comparison side of this product needs a
rating sample to rank, so the app generates one. This is the single biggest compromise in the
project and the app says so on every screen that shows a score.

Three things keep it from being a lie:

1. **It is deterministic.** The seed is each place's stable Overture GERS id, so the same
   place gets the same reviews on every run and every machine. Regenerating the file twice
   produces byte-identical output; that is checked, not assumed.
2. **It is driven by real signals.** Review volume comes from Overture's own `confidence`
   score and from whether Overture attached one of its `Overture-signals` records, which is
   its own indication that a place has engagement data behind it. The rating profile comes
   from the real category. Nothing is invented that could have been read from the data.

   An earlier draft of this section claimed the volume came from "how many independent
   providers list the place", which is not true and is worth correcting rather than quietly
   deleting: **no place in this extract has more than one non-Overture provider.** All
   56,933 carry exactly one, and the `sources` array only ever has two or three entries
   because `Overture` and sometimes `Overture-signals` are added alongside it. There is no
   cross-provider corroboration in this data to measure.
3. **It is quarantined.** The site-selection half never reads the file. A test enforces this.
   The half of the product that makes a claim about the real world runs entirely on real data.

The resulting distribution is J-shaped like real review data — 40.3% five-star, 4.5%
one-star, mean 3.99 — because a symmetric bell would produce histograms no user would believe and would
leave the variance-penalising method with nothing to find.

If this were a real product the next step would be joining Overture's GERS ids to a licensed
review source. The ranking engine would not change.

## What the data actually supports, and where it does not

Findings from probing the live release, all measured rather than assumed:

| | |
| --- | --- |
| Places in the SF box | 56,933 after dropping permanently closed |
| Street segments | 55,518 |
| Building footprints | 171,386 |
| `operating_status` populated | 41,529 open, 15,404 null (closed rows are filtered out during extraction) |
| `brand.wikidata` populated | 350 of 56,933 |
| Providers per place | exactly one, every time |

Three traps this rules out, which is why they are not features:

- **Chain versus independent analysis.** `brand.wikidata` is present on 325 places out of
  52,521. Any such feature would silently classify 99% of the city as independent.
- **A trust or provenance explorer.** Every place has exactly one external provider, with
  `Overture` and sometimes `Overture-signals` alongside it, so there is no cross-provider
  agreement to display at all.
- **Neighbourhood-level aggregation.** Overture's SF `division_area` set has 29 polygons, and
  they include "Apple Mini Park" and "50 Beale Street Plaza" while the Mission, SoMa and the
  Richmond have no polygon at all. Ranking by neighbourhood would quietly drop most of the
  city, so the app aggregates to a uniform 200 m grid and uses neighbourhood points only as
  human-readable labels.

## How it works

```
data-pipeline/extract.py      Overture GeoParquet on S3  ->  places / cells / categories
data-pipeline/synthesize.py   deterministic review histograms, seeded by GERS id
api/src/overture_api/scoring.py  the seven ranking methods, and the rate shrinkage
api/src/overture_api/sites.py    block ranking; reads only real data
api/src/overture_api/store.py    loads ~5 MB of Parquet into an in-process DuckDB
api/src/overture_api/main.py     HTTP API, and static host for the built frontend
web/                          Vite + React + MapLibre interface
```

Extraction reads the cloud-hosted GeoParquet directly over S3 with DuckDB, filtering on the
`bbox` struct so row groups are pruned rather than downloaded. The whole San Francisco slice
comes out at about 5 MB, which is small enough to ship inside the container image. That is why
this deploys as a single free-tier web service with no database and no attached disk.

Ranking happens in Python against the tested scoring module rather than being reimplemented in
SQL, so the formulas have exactly one implementation. An unfiltered search scores all 56,933
places in about 990 ms and is then cached, so repeat views cost about 3 ms. A filtered search
is about 80 ms and a block query about 115 ms. Those are measured on the machine this was
built on, not estimated.

## Running it

```bash
# 1. Extract the data (needs network; takes about three minutes)
cd data-pipeline && uv run extract.py && uv run synthesize.py

# 2. Run the API
cd ../api && uv run uvicorn overture_api.main:app --app-dir src --reload

# 3. Run the interface
cd ../web && npm install && npm run dev
```

Tests:

```bash
cd api && uv run pytest
```

The whole thing also builds as one container, which is how it is deployed:

```bash
docker build -t overture-sf . && docker run -p 8000:8000 overture-sf
```

## What a second pass found

After the first build was deployed I ran a structured review over it: five independent
reviewers on different lenses, every candidate defect then handed to a separate checker whose
instructions were to refute it rather than confirm it. Six of twenty-one candidates died at
that stage, including one I would otherwise have acted on.

The most serious survivor was a security hole of my own making. The catch-all route serving
the frontend joined the request path onto the web directory and returned whatever it landed
on, so `GET /../../../../etc/passwd` served the real file with a 200. The deployed instance
happened to be shielded by its edge proxy rejecting the request — luck, not a defence.

The rest clustered around a theme worth naming: the interface asserting things the data does
not support. Block headlines rounded a predicted 0.19 businesses up to "usually support 1",
so for a rare category every row on the page was false. "60 blocks are undersupplied" was the
page size, identical for all 640 categories. The competitor count matches only the exact
Overture label, so a block with a cafe could read "0 coffee shops" with nothing saying why.
And the co-occurrence figure is weaker than it looked: conditioning its baseline on
comparably busy blocks collapses coffee's top lifts from 6.4x to 1.59x, because busy blocks
contain more of everything. That last one is documented rather than papered over.

## What I would fix next

Three bugs in this build were invisible to the test suite and to a clean `npm run build`,
and only turned up by driving the deployed bundle in a real browser. They are worth naming
because they say more about the engineering than the parts that worked first time.

Switching the ranking method white-screened the entire app. Each method returns an almost
completely different set of places — `raw` and `bayesian` share none of the default view's
top fifty — and nine of those places have no category at all, which the row renderer did not
expect. The fix guards every nullable field and adds an error boundary, so a single bad row
now degrades to a readable message instead of a blank page.

The map never drew a single tile. It looked exactly like the familiar "headless browsers have
no WebGL" limitation, and that explanation was wrong: WebGL was available. MapLibre 6 splits
its tile parser across a small worker entry and a much larger sibling chunk, and the build
silently emitted neither, so the worker 404'd, the vector source never loaded, and the map sat
blank while reporting no error. Emitting the worker alone was still not enough, because it
immediately imports the sibling.

The lesson I would carry forward is that a green test suite said nothing useful about any of
these. All three lived in the gap between "the build succeeds" and "a person can use it".

## The weakest part of this, stated plainly

The block metric is asserted, never validated. `gap = city_rate x storefronts - competitors`
declares a block underserved when it holds fewer of a category than its shopfront count
implies at the city-wide rate. That makes shopfront count the only proxy for demand, and it
treats every absence as an opportunity rather than as evidence that somebody already tried
and the trade does not work there.

There is no demand-side input at all: no residents, no daytime population, no footfall, no
incomes. There is no rent term, which matters more than the rest put together, because high
shopfront density and high rent are close to the same variable — so the tool will reliably
point at the most expensive blocks in the city and call them opportunities. Overture's
coverage also varies by category, so a low competitor count can mean thin data rather than
thin supply.

And nothing here tests any of it against an outcome. There is no backtest against real
openings and closures, no holdout, and no interval on any gap. The honest summary is that
this is a fast, carefully-caveated interface over a plausible heuristic that has not been
shown to predict anything. With a licensed source of openings and closures you could
actually test whether high-gap blocks see more openings, and that is the first thing I would
build next.

## Trade-offs and cuts

- **Synthetic ratings.** Described above. The largest compromise, made deliberately, and
  contained by determinism, real-signal inputs and strict separation from the real-data half.
- **Street length is clipped to each cell, not attributed to a midpoint.** Crediting a whole
  road segment to whichever cell held its centre let a 200 m square claim 9,984 m of street.
  Each segment is now intersected with every cell it crosses, which conserves total length and
  drops the maximum to 3,693 m, with nothing above 4,000 m where there were nine such cells.
  The median barely moved, from 1,249 m to 1,212 m — the tail was wrong, not the typical case.
- **A 200 m grid instead of real parcels or blocks.** Overture has building footprints but no
  parcel or block geometry, and reconstructing blocks from the street graph was not worth the
  complexity for a ranking that a grid already answers. The cost is that a "block" sometimes
  straddles a real street.
- **Shopfront count as a demand proxy.** Foot traffic is the number that matters and no open
  dataset has it, so the stand-in is how many walk-in businesses a block already holds.

  The first version counted every Overture place instead, which sounds more complete and was
  badly wrong. Overture lists individual clinicians and office tenants as places, so the tool's
  top recommendation for a coffee shop was UCSF Mission Bay: 452 "businesses", of which 436
  were rows like "Dr. Yvonne Wu, MD" and one was a shopfront. Second place was a building of
  plastic surgeons. Restricting the count to shopping, food and drink, lifestyle services,
  arts and recreation returns Chinatown, Union Square and Cow Hollow.

  It is still a proxy. A block full of shops is not the same as a block full of people, and
  nothing here measures anyone walking past.
- **Neighbourhood names are the nearest named point, not a boundary.** Overture's usable SF
  neighbourhood geometry is 85 points, so a cell takes the closest name. That is a Voronoi
  partition, and it disagrees with a real boundary for a large minority of places. A cell is
  now labelled only when its nearest name is clearly nearer than the runner-up, which leaves
  614 of 3,472 unlabelled and stops Stonestown Galleria being filed under "Balboa Terrace" on
  a sub-metre margin. It is still an approximation and the filter says "areas", not
  neighbourhoods.
- **Shopfronts are counted from listings, with a confidence floor.** Overture rows are
  listings, not premises, and 38 "shops" share one private-mailbox address on Market Street.
  Requiring Overture's own confidence of at least 0.5 keeps 93% of shopfronts, leaves genuine
  malls intact, and halves that cluster. A cap per address was the obvious alternative and
  was rejected: real malls legitimately have ninety.
- **San Francisco only.** The pipeline takes a bounding box and nothing in it is
  SF-specific, so any city is a re-run. The one exception is a short exclusion list of
  Overture "microhoods" that are actually plazas, which was read off the SF data.
- **One month of data.** Overture keeps only the two most recent releases on S3, so
  historical trend features were never on the table.
- **No routing or isochrones.** The street network is extracted and used for frontage, but
  turn-by-turn walk times were cut as scope that served no question the product asks.
