# Papercuts

- 2026-08-19 09:26 PDT — The assignment site sits behind Vercel deployment protection, so a
  plain fetch returns HTTP 401. Getting the brief needed a `POST` of `_vercel_password` to the
  root to collect the `_vercel_jwt` cookie before any page would load.
- 2026-08-19 09:27 PDT — `duckdb` is not installed as a CLI on this machine. Used the Python
  package under `uv` instead.
- 2026-08-19 09:48 PDT — DuckDB spatial `eb1e57c` (bundled with duckdb 1.5.5) is badly
  broken for measurement. `ST_Length_Spheroid` and `ST_Area_Spheroid` return `nan` for every
  input including simple literal geometries; `ST_Transform` returns `LINESTRING (inf inf, ...)`
  because the PROJ database is unusable; and `ST_Distance_Sphere` ignores latitude, returning
  1111.9 m for a 0.01 degree east-west line at 37.77 N where the true answer is 880.0 m.
  Worked around by projecting by hand with `ST_Scale(geometry, m_per_deg_lon, m_per_deg_lat)`
  and then using plain `ST_Length`/`ST_Area`, validated to 1e-9 against hand-computed values.
- 2026-08-19 09:45 PDT — Guessed Overture taxonomy roots (`eat_and_drink`, `retail`,
  `beauty_and_spa`) do not exist and matched nothing silently, undercounting storefronts by
  about 8x. The real roots are `food_and_drink`, `shopping`, `lifestyle_services`,
  `sports_and_recreation`, `arts_and_entertainment`. Always read the roots off the data.
- 2026-08-19 10:39 PDT — `npm run build` succeeding proved nothing: the built app rendered
  its first screen perfectly and then white-screened on the first click of a ranking method.
  Only driving the built bundle in a real browser caught it. The accessibility tree going
  from 761 nodes to 0, and the serialized DOM dropping to 413 bytes, is the signature of a
  React tree unmounting on a render error rather than a styling problem.
- 2026-08-19 10:37 PDT — A blank MapLibre canvas in headless Chrome looks exactly like the
  well-known "headless has no WebGL" limitation, and that reading was wrong here. Checking it
  took one line — `canvas.getContext('webgl2')` returned a live context and the canvas was
  820x413 — and the real cause was a missing worker asset that would have shipped broken.
  Never accept the headless-WebGL explanation without testing for WebGL first.
- 2026-08-19 10:52 PDT — `maplibre-gl@6.4.1` under `vite@8.2.0` with a stock config builds
  cleanly while failing to emit `maplibre-gl-worker.mjs` into `dist/assets`. The bundle still
  references it, so it 404s at runtime, the `openmaptiles` source never loads, and the map
  requests zero tiles and stays blank. Nothing in the build output warns about this. The tell
  is a request logged with status 0 for a `*-worker.mjs` file.
- 2026-08-19 10:56 PDT — Emitting `maplibre-gl-worker.mjs` alone is not enough. MapLibre 6
  splits the worker into the 18,592-byte entry plus a 482,036-byte `maplibre-gl-shared.mjs`
  sibling, and the worker's first statement is `import ... from"./maplibre-gl-shared.mjs"`.
  Ship the worker without the shared chunk and it serves 200, fires `onerror` on
  construction, and leaves the map permanently blank with no console error surfacing through
  MapLibre's own `error` event. `new Worker(url, {type:'module'})` in the console is the
  fastest way to prove a worker is failing rather than missing.
- 2026-08-19 10:38 PDT — A PinchTab screenshot taken immediately after a click caught the page
  mid-render and returned a blank image that looked identical to the real crash. Screenshot
  size is a useful tell: 52,890 bytes was the healthy page and 3,543 bytes the blank one.
- 2026-08-19 14:24 PDT — The first submission zip contained `cookies.txt`, which held the
  Vercel session JWT for the employer's own assignment site, plus `headers.txt` and a saved
  copy of their brief. All three were gitignored, so a `git status` check gave no warning; a
  zip of the working directory picks up ignored files. Always list a submission archive's
  contents before sending it.
- 2026-08-19 14:24 PDT — `zip -x "*/.git/*"` does not exclude a top-level `.git`. The pattern
  needs to be `.git/*`.
- 2026-08-19 16:52 PDT — A new test file guarded its numpy import with
  `pytest.importorskip("numpy")` and therefore skipped silently in the API environment, where
  numpy was not a dependency. The suite reported "69 passed, 1 skipped" and the claim the file
  existed to check was still unchecked. A skipped test is not a passing test.
- 2026-08-19 16:52 PDT — `sed -i '' "s/== [0-9]*/== $VALUE/"` matched zero digits and inserted
  the replacement *before* the existing expression, producing `== 8382482502496457251seed_for(...)`
  and a SyntaxError. Use an exact-string edit for code, not a regex with a `*` quantifier.
- 2026-08-19 17:01 PDT — A stray `cat >> file` with no input and no heredoc blocked on stdin
  and burned a 6m40s command timeout. Check for argument-less `cat` before chaining.
- 2026-08-19 18:04 PDT — Two of the smoke suite's own first-draft checks were wrong rather
  than the app being broken. `isStyleLoaded()` reads false whenever MapLibre is streaming
  tiles, so it cannot distinguish a broken basemap from a busy one; and an empty result from
  a hiccuping `pinchtab eval` fell through `${now:-0}` and was counted as zero rows, reporting
  a healthy 50-row list as collapsed. Assert on stable signals and retry empty evals.
- 2026-08-19 18:08 PDT — The traversal check asserted the response *was* index.html, which
  failed against production because Koyeb's proxy returns its own 400 page — a stricter
  refusal reported as a failure. Assert on what must not come back, not on which refusal.
- 2026-08-19 19:58 PDT — A live smoke run "passed" against a Koyeb deployment that was still
  serving the previous image: the check waited on a field name present in both builds, so it
  matched immediately and reported stale figures (361 undersupplied against the new 335).
  Roll-out took roughly two minutes after `koyeb services redeploy` returned. Always poll on a
  value that DIFFERS between the old and new build, never on one that merely exists in both.
- 2026-08-20 10:30 PDT — Spent a debugging detour concluding a correct fix "did not work",
  because PinchTab was serving a cached `index.html` pointing at an older bundle hash: the
  server served `index-DhqnrLNI.js` while the browser ran `index-Cwn1Uk2V.js`. Every browser
  check in the smoke suite would have passed against stale code. Fixed by cache-busting the
  document with a query parameter and adding an explicit check that the bundle the browser
  loaded is the one the server serves. Verify the build under test before trusting any
  browser assertion.
