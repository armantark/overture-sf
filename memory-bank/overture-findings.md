# Overture data findings (probed 2026-08-19)

Release used: `2026-07-22.0` at `s3://overturemaps-us-west-2/release/2026-07-22.0`.
Query path: DuckDB + `spatial` + `httpfs`, `SET s3_region='us-west-2'`, filter on the
`bbox` struct columns (`bbox.xmin` etc.) so the reader prunes row groups.

SF bounding box used for probes: lon -122.517..-122.355, lat 37.70..37.84.

| theme / type | rows in SF bbox |
| --- | --- |
| places / place | 52,521 |
| transportation / segment | 55,518 |
| buildings / building | 171,386 |
| divisions / division_area | 29 |

Places column highlights: `taxonomy` (primary + hierarchy array), `basic_category`,
`confidence`, `operating_status`, `brand.wikidata`, `websites`, `socials`, `phones`,
`addresses[]`, `sources[]` with per-source confidence.

Quality signals worth exploiting:
- `operating_status`: 33,774 open, 950 permanently_closed, 17,797 null.
- `brand.wikidata` present on only 325 SF places, so it is a weak chain detector on its own.
- 46,272 of 52,521 places have `confidence >= 0.5`; 46,795 have a website.
- Top categories: restaurant 5,326, personal_or_beauty_service 1,934,
  fashion_and_apparel_store 1,802, home_service 1,705.

## Release-to-release diff, measured 2026-08-19

Only two releases are on S3: `2026-07-22.0` and `2026-08-19.0`. Overture prunes older
ones, so exactly one month-over-month comparison is possible today.

SF bbox, July to August:

| signal | count |
| --- | --- |
| places in July | 52,521 |
| places in August | 59,030 |
| ids new in August | 8,033 |
| ids gone from August | 1,524 |
| any `operating_status` change | 3,265 |
| `open` to `permanently_closed` | 15 |
| primary-name changes | 1,657 |

**The volume is misleading.** Inspecting the new ids shows they are dominated by
individual people rather than storefronts: "Tiffany Tran", "Jessica Lauren Potter",
"Stephanie Salazar Shewey", "Pierre King". These look like solo practitioners and real
estate agents ingested as places, and many arrive already marked `permanently_closed`.
That is ingest churn, not neighborhood churn, so a "what opened on your block" product
built directly on this diff would show meaningless pins to a resident.

Only 15 places flipped from open to closed in a month, which confirms `operating_status`
cannot carry a closures product on its own.

`len(sources)` is only ever 2 or 3 (23,942 places with 2, 35,088 with 3), so
"multi-source agreement" has almost no dynamic range and is a weak confidence axis.

## Neighborhood boundaries are not usable for aggregation

`divisions/division_area` gives 29 polygons for the SF box, but the set is patchy and
oddly weighted: it includes tiny plazas such as "Apple Mini Park", "50 Beale Street Plaza"
and "A.P. Giannini Plaza", while large, well-known neighborhoods such as the Mission,
SoMa and the Richmond have no polygon at all. The `division` point layer has better
coverage (54 neighborhood points, 40 microhood points) but points carry no boundary.

Decision: aggregate to a regular grid instead of to neighborhoods, so coverage is complete
and uniform, and use the neighborhood points only to attach a human-readable label to each
cell. Ranking neighborhoods directly would silently omit most of the city.

## Extraction output (2026-08-19.0)

`data-pipeline/extract.py` writes 56,933 places, 3,323 grid cells at 200 m, plus per-cell
category counts and 85 neighborhood label points, totalling about 4 MB of Parquet.

Two corrections were needed before the numbers meant anything:

1. The taxonomy roots must be read off the data. Guessed names matched nothing silently.
2. DuckDB spatial's spheroid measures and `ST_Transform` are broken in this build, so
   distances and areas are computed by scaling degrees to metres with `ST_Scale`.

Sanity checks after the fixes: median street length per 200 m cell is 1,249 m and median
building footprint area is 11,349 m2 against a 40,000 m2 cell, or 28 percent coverage.
The densest single cell is Stonestown Galleria at 156 storefronts, which is a shopping
mall and therefore correct rather than a labelling bug.

## Null fields are the dominant failure mode for the interface

Across the 213 distinct places surfaced by the seven ranking methods over the same query,
`brand` is null in 193, `website` in 33, `phone` in 30, `category` and `category_root` in 9,
`address` in 8 and `neighborhood` in 3. Null is the common case, not the exception.

This matters more than it looks because the ranking methods return substantially different
result sets: measured against the default `steamdb` top 50, `raw` and `bayesian` share no
places at all, and `wilson` shares only five. Any field a renderer fails to guard will
therefore appear the moment a user switches method, not on first load.

## The site-selection demand proxy is unexamined and the answer depends on it

`expected = city_rate * activity`, where `activity` is `place_count`: every Overture place
in the cell, across all thirteen taxonomy roots. Measured composition of the highest-activity
cells shows what that actually counts:

| cell | total | storefronts | dominant roots |
| --- | --- | --- | --- |
| Financial District | 667 | 106 | services_and_business 309, health_care 94 |
| Union Square | 563 | 193 | health_care 261, shopping 89 |
| Transbay | 524 | 138 | services_and_business 199, health_care 76 |

So the headline "452 businesses here, 0 coffee shops" is counting law offices, dentists and
the solo-practitioner entries that pollute this dataset as if they were coffee demand.

Swapping `place_count` for `storefront_count` gives a **completely disjoint** top five:

- by `place_count`: Dogpatch, Pacific Heights, Union Square, Financial District
- by `storefront_count`: Chinatown, Union Square, Balboa Terrace

Neither is obviously wrong — office workers plausibly drive coffee demand better than
neighbouring shops do — but the result is entirely determined by an unargued choice, and the
interface's wording ("businesses here") implies storefronts to a reader. This needs either a
stated justification or an explicit control, not silence.

## QA pass, 2026-08-19: six defects found and fixed, three left open

Found by an independent adversarial audit plus runtime probing. Every one was invisible to
the test suite, which passed throughout.

Fixed:

1. **Result cache grew without bound.** 81 MB to 6.3 GB across 128 distinct queries, because
   each entry retained all 56,933 serialised results (~50 MB). Would have OOM-killed the free
   instance. Now retains only the servable page; same queries settle at 251 MB.
2. **False block recommendations for 738 of 1,325 categories.** `cell_categories` covered only
   five storefront roots while the interface offered every category, so absence of data read
   as absence of competitors. `health_care` reported "0 competitors, room for 16.9" where the
   real count is four.
3. **Concurrent requests failed.** One DuckDB connection shared across FastAPI's thread pool
   failed 34 of 40 concurrent requests; sequential ones all passed. Each thread now gets its
   own cursor.
4. **The search box was a pattern language.** `%` returned all 56,933 places. Escaped, so
   "100% College Prep" is still findable.
5. **IMDb blended toward 3.6** while calling it the corpus average, which is 3.99.
6. **Two claims the code did not honour.** The Bayesian blurb promised it "notices divisive
   places", which a posterior mean cannot do, and the README credited shrinkage with driving
   the block ranking when it produces the saturation figure.

Open, deliberately:

- **Street length and building area are attributed by centroid**, so a road crossing ten cells
  credits its whole length to one. The shipped maximum is 9,984 m of street inside a 200 m
  cell. These are displayed as per-cell context and are not clipped.
- **The detail panel can mislabel a score** if the ranking method changes while its request is
  in flight.
- **The demand proxy remains unargued**, per the section above.

## Round 2 (workflow), 2026-08-19: 21 candidates, 15 survived, 6 refuted

Five lenses (frontend UX, frontend correctness, statistics, operational limits, reviewer
attack), each candidate then handed to a separate checker instructed to refute it. Six died
there, including "busy-cell recommendations use a citywide baseline from a different cell
population", which I would otherwise have acted on. Separating proposer from checker paid.

Fixed and deployed:

1. **Arbitrary file read.** The SPA catch-all joined the request path onto the web directory,
   so `GET /../../../../etc/passwd` returned the real file with 200. The live instance was
   shielded only by Koyeb's edge proxy returning 400 — infrastructure luck, not a defence.
2. **The block finder overclaimed.** `Math.max(1, Math.round(expected))` turned a predicted
   0.19 businesses into "usually support 1"; for `escape_room` all 60 rows have expected
   <= 0.19, so the page was false top to bottom.
3. **"60 blocks are undersupplied" was the page size**, identical for all 640 categories. The
   real figures differ: coffee_shop 512, escape_room 684, bakery 598.
4. **Compare was invisible on a phone.** Two panes split a fixed height and the list computed
   to roughly nothing. Verified the rule change by injecting old against new declarations:
   list height 276 px under the old rules, 2,846 px under the new.
5. Map-dot clicks fetched with the mount-time ranking method; detail responses were unordered
   and could reopen a closed panel; a failed detail fetch closed it silently; closing dropped
   focus to `<body>`; block rows looked clickable and did nothing; the complements strip
   rendered a label with no chips for 338 of 640 categories; "1 ratings".

**Open design question — the complements figure is mostly a density artifact.** Busy blocks
contain more of everything, so co-occurrence partly measures shared preference for footfall.
Conditioning the citywide baseline on comparably busy blocks collapses coffee's top lifts
from 6.4x, 6.0x and 5.9x to 1.59x, 1.14x and 1.08x. The docstring now says so; the interface
still implies affinity.

Also measured: the README claimed an unfiltered rank takes "about 400 ms"; it is 990 ms cold,
3 ms warm, 80 ms filtered, 115 ms for blocks. Corrected in the README.

Unexamined surfaces the coverage critique named: the frontend has no tests and there is no CI
at all, so on a fresh clone nothing runs; and `useBaseMap.ts` hard-codes a single third-party
tile host with no error path, so if OpenFreeMap is down while the work is being reviewed the
map is simply blank.

## Round 3 (workflow), 2026-08-19: 10 candidates, 7 survived, 3 refuted

Four lenses on surfaces the earlier rounds never opened: pipeline internals, container and
deployment, a claim-by-claim audit of prose against behaviour, and API abuse. Nine agents
rather than the previous thirty-eight, with verification batched per lens.

**The worst defect of all three rounds, and it was semantic rather than mechanical.** The
block finder measured how busy a street is with `place_count`, every Overture record in the
cell. Overture lists individual clinicians and office tenants as places, so the top
recommendation for a coffee shop was UCSF Mission Bay: 452 "businesses" of which 436 were
`health_care` rows such as "Dr. Yvonne Wu, MD" and "UCSF Blood Draw Lab", and exactly **one**
was a shopfront. Second place was a building of plastic surgeons. `storefront_count` was
already computed and shipped in `cells.parquet` and referenced nowhere in the API.

Switching exposure to storefronts returns Chinatown (146 shopfronts of 221 places), Union
Square and Cow Hollow. `MIN_ACTIVITY = 15` places became `MIN_STOREFRONTS = 10`, which 588
of 3,323 cells clear.

Two earlier rounds missed this because they checked code against itself. Nobody had asked
what the model's variables *mean*.

Other survivors, all fixed:

- The README table introduced as "all measured" mixed July figures with the shipped August
  data and was internally impossible: it claimed 950 permanently closed places when
  extraction filters them out, and its buckets summed to 52,521 against the 56,933 stated two
  lines above. Actual: 41,529 open, 15,404 null, 350 with `brand.wikidata`.
- **No place in this extract has more than one non-Overture provider.** All 56,933 carry
  exactly one; `source_count` reads 2 or 3 purely because `Overture` and sometimes
  `Overture-signals` are appended. The README's honesty section claimed review volume came
  from independent providers corroborating each other, which is false.
- `min_reviews` was a free integer in the cache key, so rotating it minted unlimited keys
  against 128 slots: 40 trivial GETs cost 17.7 s of server time and pushed the health check
  from 10 ms to 0.77 s. Only the five offered thresholds are accepted now; the same 40
  requests take 0.6 s. Snapping off-ladder values down was tried first and rejected, because
  asking for 200 would have quietly returned places with 100 reviews.
- An unknown `/api/` path returned the app shell with a 200.

Refuted by the checker: the lockfile fallbacks silently floating dependencies, the uncapped
worker having no memory stop, and `/docs` plus missing security headers.

**Correction to an earlier note.** Round 2 recorded the centroid attribution of street length
as a significant defect. Prototyping the proper clip shows total length is preserved exactly
(463,150 m either way) and the count of cells over 1,200 m barely moves (194 against 200), so
more than 1,200 m of street inside a 200 m cell is normal for San Francisco rather than an
artifact. The real error is confined to the tail, where a long segment credits its whole
length to one cell.

## Round 4 (workflow), 2026-08-19: 9 candidates, 4 survived, 5 refuted — all low

Three lenses on the semantic layer: are the seven scoring methods numerically what they
claim; does the complements feature support its own presentation; do the eligibility
constants materially change what a user is told. Seven agents.

Nothing above low severity survived, and three of the four findings were narration rather
than logic. That is the shape of a mined-out seam.

- **The complements docstring quoted lifts the shipped code cannot produce.** It claimed
  coffee's top lifts collapse from 6.4x, 6.0x and 5.9x to 1.59x, 1.14x and 1.08x under
  density conditioning. Those came from before the walk-in root restriction was added. The
  real figures are worse for the feature: the three categories actually displayed
  (menswear, steakhouse, lounge) sit at 4.29x, 4.26x and 4.15x unconditioned and **0.74x,
  0.83x and 0.78x conditioned — all below one.** Controlling for how busy a block is, they
  are slightly *less* likely than chance to share it with a coffee shop.
- The chips were ordered by lift, which a 400-run block bootstrap reproduces in **0 of 400**
  resamples. They are now alphabetical, so the strip claims co-presence rather than a
  ranking.
- Laplace was advertised as "the gentlest correction" while being the harsher of the two
  smoothers, moving further from the observed mean on 92% of histograms.
- The `blocks >= 20` support floor had no justification comment.

Refuted, usefully: that Wilson's rescaling is incoherent, that the shrinkage docs claim a
ranking effect they cannot have, that `MIN_STOREFRONTS` silently drives the headline, that
mall tenants wrongly count as shopfronts, and that the top ranking is an artifact of the
200 m cell size.

**Pattern worth naming across rounds 3 and 4:** the recurring defect in this project is not
broken code, it is prose that kept describing a computation after the computation moved —
the README data table, the "independent providers" claim, and this docstring. Narrated code
needs its narration re-verified whenever the code changes.

## Round 5 (workflow), 2026-08-19: 7 candidates, 3 survived, 4 refuted — the process converged

Last unexamined territory: `extract.py` (never reviewed by any round, and every prior finding
had treated its output as ground truth), the synthetic generator, and the gap metric itself.

Yield across all rounds: **6, 15, 7, 4, 3**. The generator lens returned nothing. The
synthesis called it converged and recommended shipping, which is the right read: reviewers
had moved from arguing whether findings exist to arguing how bad they are.

Fixed:

1. **Neighbourhood labels are a Voronoi partition, and they drive a filter.** Overture's
   usable SF geometry is 85 points, so a cell takes the nearest name; this disagrees with a
   real boundary for a large minority of places, and Stonestown Galleria was filed under
   "Balboa Terrace" on a sub-metre margin, so filtering by that name returned mall tenants.
   A cell now needs its nearest name to be clearly nearer than the runner-up (margin 1.05).

   **Tightening the distance as well was tried and reverted.** At 700 m it left 1,612 of
   3,323 cells unlabelled including most top recommendations, and "Unnamed area" against the
   headline result is worse for a reader than an approximate name. The margin alone does the
   work, at 518 unlabelled against the original 323.
2. **Registered-address listings counted as shopfronts.** 38 "shops" share 548 Market St, a
   private mailbox, with names like "ShopBase" and "hoodiefamily.com". The suggested fix — a
   cap on listings per address — would have been wrong: the biggest clusters are real malls
   (90 at Stonestown, 64 at Westfield). Overture's own `confidence` separates them cleanly:
   0.486 at the mailbox against 0.851 at Stonestown and 0.849 city-wide. A floor of 0.5 keeps
   93% of shopfronts, leaves Stonestown at 88 of 90, and halves the mailbox cluster.
3. **The ranking sorted on a rounded gap**, so for 562 of 640 categories the page-1 boundary
   was decided by DuckDB scan order, which is grid position. Sorts on the unrounded value now.

Refuted: that the generator makes divisiveness impossible, that the J-shape does not hold,
that the gap ranking is merely the storefront ranking, and that the headline count is really
a function of `MIN_STOREFRONTS`.

**The honest weak point, now stated in the README.** The block metric has never been
validated against an outcome. It has no demand-side input and no rent term in particular, and
since shopfront density and rent are close to the same variable it will point at the most
expensive blocks in the city and call them opportunities. A backtest against real openings
and closures is the first thing that would settle it.

## Cold start on the free tier, measured 2026-08-20

Koyeb's free plan sleeps a deployment when idle — `koyeb services describe` shows the active
deployment in state SLEEPING. The first request after that costs **12.5 s** to first byte;
subsequent requests are 0.4-1.5 s.

None of it is the application. Measured locally: the service becomes ready **1.24 s** after
launch including `uv` overhead, and `Store()` loads all four Parquet files into DuckDB in
**0.15 s**. The delay is entirely the platform restoring the container.

Nothing to optimise in the code, so the README now warns about it rather than leaving a
reviewer staring at a blank page wondering if the link is dead. If the wait matters more than
it does here, an external uptime pinger every ten minutes would keep the instance awake.

## Street length now clipped per cell, 2026-08-20

The last known-open defect is closed. Segments were credited whole to the cell containing
their midpoint; they are now intersected with every cell they cross.

| | before | after |
| --- | --- | --- |
| median m per cell | 1,249 | 1,212 |
| p99 | 3,368 | 3,109 |
| max | 9,984 | 3,693 |
| cells claiming >4,000 m in a 200 m square | 9 | 0 |
| cells with any street | 3,323 | 3,472 |

Total length is conserved at 4,572,093 m, which is the right sanity check for a
redistribution. The median moving by 3% confirms the earlier finding that the typical cell
was always about right and only the tail was lying. Extraction takes 2m17s with the spatial
join, against roughly 2m before.

## Round 6 (workflow), 2026-08-20: 5 candidates, all 5 survived, one high

Two lenses reading end to end the surfaces prior rounds had only touched at bug sites:
`store.py` and the four unreviewed React components. Zero refutations, which is unusual and
justifies having run it.

- **[high] The detail panel captioned one method's score with another's name.** Round 2 fixed
  the *fetch* to use the live ranking method but left the *label* reading the picker, so
  switching method with the panel open showed the old number under the new name — contradicted
  by the seven-method table three lines below on the same screen. An incomplete fix that read
  as complete. The label now comes from `place.ratings.method` in the response, and the panel
  refetches on method change through the same request ticket.
- Two startup indexes were never used: `places.cx` is INTEGER against `cells.cx` BIGINT so the
  planner casts and scans both sides, and the join the comment actually named
  (`places.id` to `reviews.id`) had no index at all. Removed, with the comment.
- `pluralize()` produced "orthodonticses", "public relationses" and "trustses" for the 12 of
  640 categories already ending in s.
- The FLIP reorder measured viewport rects rather than `offsetTop`, so scrolling the list
  between searches animated every surviving row by the scroll distance.
- **The stale-figures bug recurred a third time**, within the hour: clipping street length
  changed the grid from 3,323 cells to 3,472, which silently falsified "588 of 3,323 cells
  clear it" and "518 of 3,323 unlabelled". Now 553 and 614 of 3,472.

`api/tests/test_documented_figures.py` now fails when a documented count drifts from the
shipped data, and was verified to fail by reintroducing the stale figure. That is the first
guard against the defect class that has appeared in every round since the third.
