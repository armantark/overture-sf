# Project Brief

## What this is

A take-home assessment assigned 2026-08-19. The brief is one line:
"Build a web app product on top of this data. Anything you want," where the data is
Overture Maps. The vagueness is deliberate and is itself part of what is assessed.

Graded on four things, in the assigner's own words:

- Product sense — would someone use it?
- UX and craft — would they know how to use it?
- Engineering quality — when used, does it work?
- Judgment — "Don't just tell Claude to build something cool."

## The product

Two sides of one question: how do you rank things when the evidence is thin?

- **Compare.** Search San Francisco businesses and rank them by a scoring method the user
  chooses, from a raw average through Wilson lower bounds and Bayesian smoothing. The point
  is visible: a place with five five-star reviews should not outrank one with four hundred
  reviews averaging 4.5, and switching methods makes that legible.
- **Where to open.** Pick a category and see which blocks carry more activity than their
  count of that business predicts. "452 businesses here, no coffee shops; blocks this busy
  usually support four."

Both sides run on the same shrinkage machinery, one over star histograms and one over
measured place counts.

## The synthetic data decision

Overture has no ratings, reviews, hours or prices. The owner chose to generate synthetic
reviews and label them clearly, after being warned that fabricated data is the sharpest
risk against the judgment criterion. Three things contain that risk:

1. Generation is deterministic, seeded from each place's stable Overture GERS id, so the
   output is byte-identical across runs.
2. It is driven by real signals — Overture `confidence`, source count and category — so
   nothing is invented that could have been read from the data.
3. The site-selection half never reads it, and a test enforces that, so the half of the
   product that makes a real-world claim runs entirely on real data.

## Deliverables

A deployed URL, the repository including extraction scripts, and a short README with the
pitch, the reasoning, and the trade-offs and cuts.

## Delivered 2026-08-19

- Live: https://overture-sf-armantark-ff579391.koyeb.app
- Repo: https://github.com/armantark/overture-sf (private)
- Submission zip: `~/Desktop/overture-sf-submission.zip`, 5.5 MB, source and data only.
  Excludes `.git` and `memory-bank/` so the package reads as a clean deliverable rather
  than a working notebook.

**Standing constraint:** the Koyeb free tier allows one free instance and it is now taken by
`overture-sf/web`. `acol/web` was paused on 2026-08-19 to free that slot. Resuming `acol`
will take the take-home deployment down. Restore it with `koyeb services resume acol/web`
after the assessment is finished, and pause or delete `overture-sf/web` first.
