import { useEffect, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
// MapLibre v6 parses tiles in a web worker shipped as two files
// (maplibre-gl-worker.mjs + maplibre-gl-shared.mjs). Importing with
// ?worker&url makes Vite bundle the worker with its imports and emit one
// self-contained file; a plain ?url import 404s on the shared chunk and the
// map never draws a tile.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'

maplibregl.setWorkerUrl(workerUrl)

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'

// If the tile host is unreachable the map draws nothing and the app looks broken, which is
// the worst way to fail in front of someone evaluating it. Everything that matters — the
// ranked list, the markers, the block circles — works without a basemap, so detect the
// failure and let the view say so rather than showing an unexplained blank rectangle.
const BASEMAP_TIMEOUT_MS = 12000

// Creates the map and returns it as state so consumers re-attach their
// handlers to the live instance (React StrictMode mounts effects twice in
// dev; a ref-based map would leave listeners on the removed first map).
export function useBaseMap(
  containerRef: React.RefObject<HTMLDivElement | null>,
  bbox: [number, number, number, number] | null,
) {
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const [basemapFailed, setBasemapFailed] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    setBasemapFailed(false)
    const m = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: [-122.435, 37.77],
      zoom: 11.6,
      attributionControl: { compact: true },
    })
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    // Detect failure from the one-shot 'style.load' event, not from isStyleLoaded().
    // isStyleLoaded() reports false whenever tiles are still streaming, so using it here
    // flagged a perfectly healthy map as offline within seconds of every load.
    let styleReady = false
    const onStyleLoad = () => {
      styleReady = true
      setBasemapFailed(false)
    }
    // MapLibre reports tile and style failures through 'error' rather than throwing, and a
    // host that merely hangs never reports at all, so the timer covers that case too.
    const onError = () => {
      if (!styleReady) setBasemapFailed(true)
    }
    m.on('style.load', onStyleLoad)
    m.on('error', onError)
    const timer = window.setTimeout(() => {
      if (!styleReady) setBasemapFailed(true)
    }, BASEMAP_TIMEOUT_MS)
    // Deliberate debug handle: lets a browser console verify tiles actually load
    // (window.__map.isStyleLoaded()).
    ;(window as unknown as { __map?: maplibregl.Map }).__map = m
    setMap(m)
    return () => {
      window.clearTimeout(timer)
      m.off('style.load', onStyleLoad)
      m.off('error', onError)
      m.remove()
      setMap(null)
    }
  }, [containerRef])

  useEffect(() => {
    if (!map || !bbox) return
    map.fitBounds(
      [
        [bbox[0], bbox[1]],
        [bbox[2], bbox[3]],
      ],
      { padding: 24, duration: 0 },
    )
  }, [map, bbox])

  return { map, basemapFailed }
}
