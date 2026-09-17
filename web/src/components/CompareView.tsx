import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { Meta, Place, PlaceDetailResponse } from '../types'
import { fetchPlace, fetchSearch } from '../api'
import { useBaseMap } from '../hooks/useBaseMap'
import { humanize, describePlace, formatInt, formatScore, ratingCount } from '../format'
import { Histogram } from './Histogram'
import { MethodPicker } from './MethodPicker'
import { PlaceDetail } from './PlaceDetail'

const MIN_REVIEW_OPTIONS = [
  { value: 0, label: 'Any review count' },
  { value: 10, label: '10+ reviews' },
  { value: 25, label: '25+ reviews' },
  { value: 50, label: '50+ reviews' },
  { value: 100, label: '100+ reviews' },
]

interface Props {
  meta: Meta
}

export function CompareView({ meta }: Props) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [root, setRoot] = useState('')
  const [category, setCategory] = useState('')
  const [neighborhood, setNeighborhood] = useState('')
  const [minReviews, setMinReviews] = useState(0)
  const [method, setMethod] = useState(meta.defaultMethod)

  const [results, setResults] = useState<Place[] | null>(null)
  const [matched, setMatched] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [selected, setSelected] = useState<PlaceDetailResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchSearch({
      q: debouncedQ || undefined,
      root: root || undefined,
      category: category || undefined,
      neighborhood: neighborhood || undefined,
      method,
      min_reviews: minReviews || undefined,
      limit: 50,
    })
      .then((res) => {
        if (cancelled) return
        setResults(res.results)
        setMatched(res.matched)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
        setResults([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debouncedQ, root, category, neighborhood, method, minReviews])

  // The map's click handler is bound once at mount, so a plain closure over `method`
  // would fetch with whatever was selected then and label it with whatever is selected
  // now. A ref keeps the live value without rebinding the handler.
  const methodRef = useRef(method)
  methodRef.current = method

  // Only the newest request may write to the panel: two quick clicks previously let the
  // slower response win, and a request in flight during a close reopened the panel.
  const detailRequest = useRef(0)

  const openDetail = (id: string) => {
    const ticket = ++detailRequest.current
    setDetailError(null)
    setDetailLoading(true)
    fetchPlace(id, methodRef.current)
      .then((p) => {
        if (ticket === detailRequest.current) setSelected(p)
      })
      .catch((e) => {
        if (ticket !== detailRequest.current) return
        // Failing silently made clicking a row look like nothing happened at all.
        setDetailError(e instanceof Error ? e.message : 'Could not load this place.')
      })
      .finally(() => {
        if (ticket === detailRequest.current) setDetailLoading(false)
      })
  }

  const closeDetail = () => {
    detailRequest.current++
    setSelected(null)
    setDetailError(null)
    setDetailLoading(false)
  }

  // Changing method with the panel open must move the number, not just the caption.
  // Reuses the same ticket so a slow refetch cannot overwrite a newer selection.
  const selectedId = selected?.id
  useEffect(() => {
    if (!selectedId) return
    const ticket = ++detailRequest.current
    fetchPlace(selectedId, method)
      .then((p) => {
        if (ticket === detailRequest.current) setSelected(p)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [method, selectedId])

  const categoryOptions = useMemo(
    () => meta.categories.filter((c) => !root || c.root === root),
    [meta.categories, root],
  )

  // --- Map ----------------------------------------------------------------
  const mapContainer = useRef<HTMLDivElement | null>(null)
  const { map, basemapFailed } = useBaseMap(mapContainer, meta.bbox)
  const [mapLoaded, setMapLoaded] = useState(false)

  useEffect(() => {
    if (!map) return
    const init = () => {
      if (map.getSource('places')) {
        setMapLoaded(true)
        return
      }
      map.addSource('places', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.addLayer({
        id: 'places-halo',
        type: 'circle',
        source: 'places',
        paint: {
          'circle-radius': ['case', ['get', 'hl'], 13, 0],
          'circle-color': '#1b4fd8',
          'circle-opacity': 0.18,
        },
      })
      map.addLayer({
        id: 'places-dots',
        type: 'circle',
        source: 'places',
        paint: {
          'circle-radius': ['case', ['get', 'hl'], 8, 5.5],
          'circle-color': [
            'case',
            ['get', 'selected'],
            '#0f2fa0',
            ['get', 'hl'],
            '#1b4fd8',
            '#7c93e8',
          ],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#ffffff',
        },
      })
      map.on('mousemove', 'places-dots', (e: maplibregl.MapLayerMouseEvent) => {
        map.getCanvas().style.cursor = 'pointer'
        const f = e.features?.[0]
        if (f) setHoveredId(f.properties?.id ?? null)
      })
      map.on('mouseleave', 'places-dots', () => {
        map.getCanvas().style.cursor = ''
        setHoveredId(null)
      })
      map.on('click', 'places-dots', (e: maplibregl.MapLayerMouseEvent) => {
        const f = e.features?.[0]
        if (f?.properties?.id) openDetail(f.properties.id)
      })
      setMapLoaded(true)
    }
    if (map.isStyleLoaded()) init()
    else map.once('style.load', init)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map])

  // Push results into the map; refit when the result set changes.
  const resultsSignature = results?.map((r) => r.id).join(',') ?? ''
  useEffect(() => {
    if (!map || !mapLoaded) return
    const source = map.getSource('places') as maplibregl.GeoJSONSource | undefined
    if (!source) return
    source.setData({
      type: 'FeatureCollection',
      features: (results ?? []).map((p) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        properties: { id: p.id, hl: p.id === hoveredId, selected: p.id === selected?.id },
      })),
    })
    if ((results ?? []).length > 0) {
      const bounds = new maplibregl.LngLatBounds()
      for (const p of results ?? []) bounds.extend([p.lon, p.lat])
      map.fitBounds(bounds, { padding: 60, maxZoom: 14.5, duration: 400 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, resultsSignature, mapLoaded])

  // Highlight without refitting.
  useEffect(() => {
    if (!map || !mapLoaded) return
    const source = map.getSource('places') as maplibregl.GeoJSONSource | undefined
    if (!source || !results) return
    source.setData({
      type: 'FeatureCollection',
      features: results.map((p) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        properties: { id: p.id, hl: p.id === hoveredId, selected: p.id === selected?.id },
      })),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, hoveredId, selected?.id, mapLoaded])

  // --- FLIP reorder animation ---------------------------------------------
  const rowRefs = useRef(new Map<string, HTMLLIElement>())
  const prevTops = useRef(new Map<string, number>())
  useEffect(() => {
    const next = new Map<string, number>()
    rowRefs.current.forEach((el, id) => next.set(id, el.offsetTop))
    rowRefs.current.forEach((el, id) => {
      const prev = prevTops.current.get(id)
      if (prev === undefined) return
      const dy = prev - (next.get(id) ?? prev)
      if (Math.abs(dy) < 2) return
      el.style.transition = 'none'
      el.style.transform = `translateY(${dy}px)`
      requestAnimationFrame(() => {
        el.style.transition = 'transform 340ms cubic-bezier(.2,.7,.25,1)'
        el.style.transform = ''
      })
    })
    prevTops.current = next
  }, [results])

  const hasFilters = Boolean(debouncedQ || root || category || neighborhood || minReviews)

  return (
    <div className="compare-view">
      <div className="toolbar">
        <input
          type="search"
          className="search-input"
          placeholder="Search San Francisco businesses…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search businesses"
        />
        <select
          value={root}
          aria-label="Filter by category group"
          onChange={(e) => {
            setRoot(e.target.value)
            setCategory('')
          }}
        >
          <option value="">All category groups</option>
          {meta.roots.map((r) => (
            <option key={r.key} value={r.key}>
              {humanize(r.key)} ({formatInt(r.count)})
            </option>
          ))}
        </select>
        <select
          value={category}
          aria-label="Filter by category"
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {categoryOptions.map((c) => (
            <option key={c.key} value={c.key}>
              {humanize(c.key)} ({formatInt(c.count)})
            </option>
          ))}
        </select>
        <select
          value={neighborhood}
          aria-label="Filter by nearest named area"
          onChange={(e) => setNeighborhood(e.target.value)}
        >
          <option value="">All areas</option>
          {meta.neighborhoods.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <select
          value={minReviews}
          aria-label="Minimum review count"
          onChange={(e) => setMinReviews(Number(e.target.value))}
        >
          {MIN_REVIEW_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <MethodPicker methods={meta.methods} value={method} onChange={setMethod} />

      <div className="split">
        <section className="list-pane" aria-label="Ranked results">
          <div className="list-meta">
            {loading ? (
              <span>Searching…</span>
            ) : error ? (
              <span className="error-text">{error}</span>
            ) : (
              <span>
                <strong>{formatInt(matched)}</strong> {matched === 1 ? 'place' : 'places'}
                {hasFilters ? ' match' : ' in San Francisco'}
                {matched > (results?.length ?? 0) && results
                  ? ` — top ${results.length} shown`
                  : ''}
              </span>
            )}
          </div>

          {!loading && !error && results && results.length === 0 && (
            <div className="empty-state">
              <p className="empty-title">No places match.</p>
              <p>
                Try a different spelling, or clear a filter — some combinations (a rare
                category inside one neighborhood) genuinely have nothing in Overture.
              </p>
            </div>
          )}

          <ol className="result-list">
            {(results ?? []).map((p, i) => (
              <li
                key={p.id}
                ref={(el) => {
                  if (el) rowRefs.current.set(p.id, el)
                  else rowRefs.current.delete(p.id)
                }}
              >
                <button
                  type="button"
                  className={`result-row${p.id === hoveredId ? ' is-hovered' : ''}${
                    p.id === selected?.id ? ' is-selected' : ''
                  }`}
                  onMouseEnter={() => setHoveredId(p.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={() => openDetail(p.id)}
                >
                  <span className="result-rank">{i + 1}</span>
                  <span className="result-main">
                    <span className="result-name">{p.name}</span>
                    <span className="result-sub">
                      {describePlace(p.category, p.neighborhood)}
                    </span>
                  </span>
                  <span className="result-hist">
                    <Histogram histogram={p.ratings.histogram} />
                  </span>
                  <span className="result-score">
                    <span className="result-score-num">{formatScore(p.ratings.score)}</span>
                    <span className="result-score-sub">
                      {ratingCount(p.ratings.count)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {loading && (
            <div className="loading-rows" aria-hidden="true">
              {Array.from({ length: 8 }, (_, i) => (
                <div className="loading-row" key={i} />
              ))}
            </div>
          )}
        </section>

        <section className="map-pane" aria-label="Map of results">
          <div ref={mapContainer} className="map-container" />
          {basemapFailed && (
            <div className="map-offline" role="status">
              Background map tiles are unavailable right now. Everything else on this page
              still works.
            </div>
          )}

          {(selected || detailLoading || detailError) && (
            <PlaceDetail
              place={selected}
              loading={detailLoading && !selected}
              error={detailError}
              methods={meta.methods}
              activeMethod={method}
              onClose={closeDetail}
            />
          )}
        </section>
      </div>
    </div>
  )
}
