import { useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { Meta, SiteResult, SitesResponse } from '../types'
import { fetchSites } from '../api'
import { useBaseMap } from '../hooks/useBaseMap'
import { humanize, pluralize, formatInt } from '../format'

interface Props {
  meta: Meta
}

const DEFAULT_CATEGORY = 'coffee_shop'

// Sequential scale for gap: pale amber (little unmet demand) to deep orange.
function gapColor(gap: number, maxGap: number): string {
  const t = maxGap > 0 ? Math.min(1, gap / maxGap) : 0
  const lerp = (a: number, b: number) => Math.round(a + (b - a) * t)
  return `rgb(${lerp(245, 196)}, ${lerp(230, 96)}, ${lerp(205, 28)})`
}

export function SitesView({ meta }: Props) {
  const [category, setCategory] = useState(DEFAULT_CATEGORY)
  const [data, setData] = useState<SitesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchSites(category)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
        setData(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [category])

  const categoryLabel = humanize(category)
  const plural = pluralize(category)

  const categoriesByRoot = useMemo(() => {
    const groups = new Map<string, { key: string; count: number }[]>()
    for (const c of meta.categories) {
      const list = groups.get(c.root) ?? []
      list.push({ key: c.key, count: c.count })
      groups.set(c.root, list)
    }
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [meta.categories])

  const maxGap = useMemo(
    () => Math.max(...(data?.results.map((r) => r.gap) ?? [1]), 0.01),
    [data],
  )

  // --- Map ---------------------------------------------------------------
  const mapContainer = useRef<HTMLDivElement | null>(null)
  const { map, basemapFailed } = useBaseMap(mapContainer, meta.bbox)
  const [mapLoaded, setMapLoaded] = useState(false)

  useEffect(() => {
    if (!map) return
    const init = () => {
      if (map.getSource('sites')) {
        setMapLoaded(true)
        return
      }
      map.addSource('sites', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.addLayer({
        id: 'sites-cells',
        type: 'circle',
        source: 'sites',
        paint: {
          'circle-radius': ['get', 'radius'],
          'circle-color': ['get', 'color'],
          'circle-opacity': ['case', ['get', 'hl'], 0.95, 0.72],
          'circle-stroke-width': ['case', ['get', 'hl'], 2, 1],
          'circle-stroke-color': ['case', ['get', 'hl'], '#3a2a05', '#ffffff'],
        },
      })
      map.on('mousemove', 'sites-cells', (e: maplibregl.MapLayerMouseEvent) => {
        map.getCanvas().style.cursor = 'pointer'
        const idx = e.features?.[0]?.properties?.idx
        if (typeof idx === 'number') setHoveredIdx(idx)
      })
      map.on('mouseleave', 'sites-cells', () => {
        map.getCanvas().style.cursor = ''
        setHoveredIdx(null)
      })
      setMapLoaded(true)
    }
    if (map.isStyleLoaded()) init()
    else map.once('style.load', init)
  }, [map])

  const resultsSignature = data ? `${data.category}:${data.results.length}` : ''
  useEffect(() => {
    if (!map || !mapLoaded) return
    const source = map.getSource('sites') as maplibregl.GeoJSONSource | undefined
    if (!source || !data) return
    source.setData({
      type: 'FeatureCollection',
      features: data.results.map((r, idx) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
        properties: {
          idx,
          hl: idx === hoveredIdx,
          color: gapColor(r.gap, maxGap),
          radius: 6 + Math.min(14, Math.sqrt(r.storefronts) * 0.9),
        },
      })),
    })
    if (data.results.length > 0) {
      const bounds = new maplibregl.LngLatBounds()
      for (const r of data.results) bounds.extend([r.lon, r.lat])
      map.fitBounds(bounds, { padding: 60, maxZoom: 13.5, duration: 400 })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, resultsSignature, mapLoaded])

  useEffect(() => {
    if (!map || !mapLoaded || !data) return
    const source = map.getSource('sites') as maplibregl.GeoJSONSource | undefined
    if (!source) return
    source.setData({
      type: 'FeatureCollection',
      features: data.results.map((r, idx) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
        properties: {
          idx,
          hl: idx === hoveredIdx,
          color: gapColor(r.gap, maxGap),
          radius: 6 + Math.min(14, Math.sqrt(r.storefronts) * 0.9),
        },
      })),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, hoveredIdx, mapLoaded])

  const scrollToRow = (idx: number) => {
    document
      .querySelector(`[data-site-idx="${idx}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  return (
    <div className="sites-view">
      <div className="toolbar">
        <label className="toolbar-label" htmlFor="site-category">
          Category
        </label>
        <select
          id="site-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          {categoriesByRoot.map(([rootKey, cats]) => (
            <optgroup key={rootKey} label={humanize(rootKey)}>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {humanize(c.key)} ({formatInt(c.count)})
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <span className="toolbar-note">
          Real data only — storefront counts, competitors and street length all come straight
          from Overture. No synthetic anything. Competitors count places carrying this exact
          Overture category, so a nearby shop filed under a different label is not counted.
        </span>
      </div>

      {data && !loading && data.complements.length > 0 && (
        <div className="complements">
          <span className="complements-label">
            Also found on {categoryLabel.toLowerCase()} blocks:
          </span>
          {/* Alphabetical, not by lift: a bootstrap reproduces the by-lift order in 0 of
              400 resamples, so ranking them would assert something the data cannot carry. */}
          {[...data.complements]
            .sort((a, b) => humanize(a.category).localeCompare(humanize(b.category)))
            .map((c) => (
            <span
              key={c.category}
              className="complement-chip"
              title={`Shares ${c.blocks} of the 200 m blocks that have ${plural}`}
            >
              {humanize(c.category)}
            </span>
            ))}
        </div>
      )}

      <div className="split">
        <section className="list-pane" aria-label="Underserved blocks">
          <div className="list-meta">
            {loading ? (
              <span>Scoring {formatInt(meta.counts.cells)} blocks…</span>
            ) : error ? (
              <span className="error-text">{error}</span>
            ) : data ? (
              <span>
                <strong>{formatInt(data.undersupplied)}</strong> blocks where {plural} are
                undersupplied
                {data.undersupplied > data.results.length && (
                  <> · showing the top {data.results.length}</>
                )}
              </span>
            ) : null}
          </div>

          {!loading && !error && data && data.results.length === 0 && (
            <div className="empty-state">
              <p className="empty-title">No underserved blocks found.</p>
              <p>
                Every busy block already has about as many {plural} as its shopfront count
                predicts — this category is well supplied across the city.
              </p>
            </div>
          )}

          <ol className="site-list">
            {(data?.results ?? []).map((r: SiteResult, idx) => (
              <li key={idx} data-site-idx={idx}>
                <button
                  type="button"
                  className={`site-row${idx === hoveredIdx ? ' is-hovered' : ''}`}
                  onMouseEnter={() => setHoveredIdx(idx)}
                  onMouseLeave={() => setHoveredIdx(null)}
                  onFocus={() => {
                    setHoveredIdx(idx)
                    scrollToRow(idx)
                  }}
                  onClick={() => {
                    setHoveredIdx(idx)
                    map?.flyTo({ center: [r.lon, r.lat], zoom: 15.5, duration: 600 })
                  }}
                >
                  <span
                    className="site-gap-chip"
                    style={{ background: gapColor(r.gap, maxGap) }}
                    aria-hidden="true"
                  />
                  <span className="site-main">
                    <span className="site-headline">
                      {formatInt(r.storefronts)} shops and eateries here, {r.competitors} tagged{' '}
                      {r.competitors === 1 ? categoryLabel.toLowerCase() : plural} — a street
                      this busy predicts {r.expected.toFixed(1)}.
                    </span>
                    <span className="site-sub">
                      {r.neighborhood ?? 'San Francisco'} · gap {r.gap.toFixed(1)} ·{' '}
                      {formatInt(Math.round(r.streetMetres))} m of street
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

        <section className="map-pane" aria-label="Map of underserved blocks">
          <div ref={mapContainer} className="map-container" />
          {basemapFailed && (
            <div className="map-offline" role="status">
              Background map tiles are unavailable right now. Everything else on this page
              still works.
            </div>
          )}

          <div className="map-legend">
            <span className="map-legend-title">Unmet demand (gap)</span>
            <span className="map-legend-scale">
              <span className="map-legend-swatch" style={{ background: gapColor(0, 1) }} />
              <span className="map-legend-swatch" style={{ background: gapColor(0.5, 1) }} />
              <span className="map-legend-swatch" style={{ background: gapColor(1, 1) }} />
            </span>
            <span className="map-legend-caption">
              0 → {maxGap.toFixed(1)} missing · circle size = shopfronts
            </span>
          </div>
        </section>
      </div>
    </div>
  )
}
