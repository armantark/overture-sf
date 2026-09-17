#!/usr/bin/env bash
# End-to-end smoke test, driven through a real browser via PinchTab.
#
# Why a browser rather than jsdom: every serious defect this project has shipped was
# invisible to the unit tests and to a clean `npm run build`. The ranked list white-screened
# on a re-render, the map never drew a tile because a worker chunk was missing from the
# bundle, and the whole result list collapsed to nothing on a narrow viewport. None of those
# are reachable without rendering the real bundle against the real API.
#
# Each check below exists because that exact thing broke at least once.
#
#   ./tooling/smoke.sh                      # against http://127.0.0.1:8000
#   ./tooling/smoke.sh https://example.app  # against a deployment
#
# A non-loopback target must be in PinchTab's allowlist first:
#   pinchtab config set security.allowedDomains "$(pinchtab config get security.allowedDomains),your.host"
#   pinchtab server restart
set -uo pipefail

BASE="${1:-http://127.0.0.1:8000}"
PASS=0
FAIL=0

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }

check() { # check <name> <expected> <actual>
  if [[ "$3" == "$2" ]]; then pass "$1"; else fail "$1" "expected '$2', got '$3'"; fi
}

echo "Smoke testing ${BASE}"

# --- API-level checks, which need no browser ---------------------------------------
echo
echo "API"

code=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/api/health")
check "health responds" "200" "$code"

# Regression: the catch-all route served any file on disk, so this returned /etc/passwd.
# Assert on what must never come back rather than on which refusal you get: the app answers
# with its index.html, while a deployment behind a proxy that rejects the path outright
# answers with a 400 page. Both are fine; the file contents are not.
body=$(curl -s --path-as-is "${BASE}/../../../../../../etc/passwd")
if [[ "$body" == *"root:"* || "$body" == *"/bin/sh"* ]]; then
  fail "path traversal is refused" "the file came back"
else
  pass "path traversal is refused"
fi

# Regression: the search box passed % and _ into an ILIKE pattern, so "%" matched the city.
total=$(curl -s "${BASE}/api/health" | python3 -c 'import sys,json;print(json.load(sys.stdin)["places"])')
wild=$(curl -s -G --data-urlencode 'q=%' --data 'limit=1' "${BASE}/api/search" \
       | python3 -c 'import sys,json;print(json.load(sys.stdin)["matched"])')
if [[ "$wild" -lt "$total" ]]; then
  pass "search treats % as literal text (${wild} of ${total})"
else
  fail "search treats % as literal text" "matched all ${wild}"
fi

# Regression: cell_categories covered only storefront roots, so most categories reported
# zero competitors everywhere and the tool invented openings that did not exist.
comp=$(curl -s "${BASE}/api/sites?category=health_care&limit=20" \
       | python3 -c 'import sys,json;print(sum(r["competitors"] for r in json.load(sys.stdin)["results"]))')
if [[ "$comp" -gt 0 ]]; then
  pass "a dense category reports real competitors (${comp})"
else
  fail "a dense category reports real competitors" "summed to zero"
fi

# Regression: the "undersupplied" figure was the page size, identical for every category.
a=$(curl -s "${BASE}/api/sites?category=coffee_shop&limit=60" | python3 -c 'import sys,json;print(json.load(sys.stdin)["undersupplied"])')
b=$(curl -s "${BASE}/api/sites?category=escape_room&limit=60" | python3 -c 'import sys,json;print(json.load(sys.stdin)["undersupplied"])')
if [[ "$a" != "$b" ]]; then
  pass "undersupplied is a real count, not the page size (${a} vs ${b})"
else
  fail "undersupplied is a real count" "both categories reported ${a}"
fi

# --- Browser checks ----------------------------------------------------------------
echo
echo "Browser"

if ! command -v pinchtab >/dev/null 2>&1; then
  echo "  pinchtab not installed; skipping browser checks"
  echo
  echo "${PASS} passed, ${FAIL} failed (browser checks skipped)"
  [[ "$FAIL" -eq 0 ]] || exit 1
  exit 0
fi

export PINCHTAB_SESSION="$(pinchtab session create --agent-id smoke 2>/dev/null | tail -1)"
# Cache-bust the document. A cached index.html points at a previous bundle hash, so the
# browser happily runs OLD code against a NEW server and every check below passes against
# code that is no longer shipped. This cost a real debugging detour: a fix verified as
# "still broken" was actually correct, and the browser was three builds behind.
pinchtab nav "${BASE}/?smoke=$RANDOM$RANDOM" >/dev/null 2>&1
sleep 16

js() {
  local out
  out=$(pinchtab eval "$1" 2>/dev/null | tail -1)
  if [[ -z "$out" ]]; then
    sleep 1
    out=$(pinchtab eval "$1" 2>/dev/null | tail -1)
  fi
  printf '%s' "$out"
}

# Poll rather than sleeping a fixed time. Asserting at a fixed moment made this suite report
# a healthy map as broken, because isStyleLoaded() flips true somewhere between 16 and 20
# seconds depending on the network.
wait_true() { # wait_true <expression> [tries]
  local tries="${2:-12}"
  for _ in $(seq 1 "$tries"); do
    [[ "$(js "$1")" == "true" ]] && return 0
    sleep 2
  done
  return 1
}

# Prove the browser is running the bundle the server is serving, before trusting anything.
served=$(curl -s "$BASE/" | grep -oE 'assets/index-[A-Za-z0-9_-]+\.js' | head -1 | sed 's|assets/||')
loaded=$(js "(document.querySelector('script[src*=assets]')||{}).src" | sed 's|.*/||')
if [[ -n "$served" && "$served" == "$loaded" ]]; then
  pass "browser is running the served bundle (${served})"
else
  fail "browser is running the served bundle" "server serves '${served}', browser loaded '${loaded}'"
fi

title=$(js "document.title")
if [[ "$title" == *"Thin Evidence"* ]]; then pass "app renders"; else fail "app renders" "title was ${title}"; fi

rows=$(js "document.querySelectorAll('.result-row').length")
if [[ "${rows:-0}" -gt 0 ]]; then pass "ranked list renders (${rows} rows)"; else fail "ranked list renders" "no rows"; fi

# Regression: the map drew nothing because MapLibre's worker chunk was missing from dist,
# so the style never parsed and no layer ever existed.
if wait_true "!!(window.__map && window.__map.getStyle() && window.__map.getStyle().layers.length > 10)" 15; then
  layers=$(js "window.__map.getStyle().layers.length")
  pass "basemap style parses (${layers} layers)"
else
  fail "basemap style parses" "no layers after 30s"
fi

# Regression: the offline notice keyed off isStyleLoaded(), which is false whenever tiles are
# streaming, so it declared a healthy map broken seconds after every load.
banner=$(js "!!document.querySelector('.map-offline')")
check "no false 'tiles unavailable' notice" "false" "$banner"

# Regression: switching ranking method unmounted the entire React tree, because each method
# surfaces a different set of places and some of them have no category.
for method in "Wilson lower bound" "Raw average" "Bayesian" "IMDb weighted" "Laplace" "Variance-penalised" "Shrinkage"; do
  pinchtab click "text:${method}" >/dev/null 2>&1
  if wait_true "document.querySelectorAll('.result-row').length > 0" 6; then
    pass "method '${method}' keeps the list rendered"
  else
    fail "method '${method}' keeps the list rendered" "list stayed empty"
  fi
done

# Regression: null category fields rendered as the literal string "null".
nulls=$(js "document.querySelector('.list-pane').textContent.includes('null')")
check "no literal 'null' in the list" "false" "$nulls"

# Regression: closing the detail panel stranded keyboard focus on <body>.
pinchtab click "css:.result-row" >/dev/null 2>&1
if wait_true "!!document.querySelector('[role=dialog]')"; then
  pass "detail panel opens as a dialog"
else
  fail "detail panel opens as a dialog" "no [role=dialog] appeared"
fi

# Leave the panel closed, or it covers the view switch below.
pinchtab click "css:.detail-close" >/dev/null 2>&1
sleep 2

pinchtab click "text:Where to open" >/dev/null 2>&1
if wait_true "document.querySelectorAll('.site-row').length > 0"; then
  sites=$(js "document.querySelectorAll('.site-row').length")
  pass "block list renders (${sites} rows)"
else
  fail "block list renders" "no rows appeared"
fi

# Regression: a block predicted to support 0.19 businesses was described as supporting 1.
overclaim=$(js "(() => { const s=document.querySelector('.site-headline'); return !!(s && /usually support/.test(s.textContent)); })()")
check "block headline does not round a fraction up to one" "false" "$overclaim"

echo
echo "${PASS} passed, ${FAIL} failed"
[[ "$FAIL" -eq 0 ]] || exit 1
