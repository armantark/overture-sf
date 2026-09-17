import { useEffect, useRef } from 'react'
import type { Method, PlaceDetailResponse } from '../types'
import { describePlace, formatScore, confidenceLabel, ratingCount } from '../format'
import { Histogram } from './Histogram'

interface Props {
  place: PlaceDetailResponse | null
  loading: boolean
  error?: string | null
  methods: Method[]
  activeMethod: string
  onClose: () => void
}

export function PlaceDetail({ place, loading, error, methods, activeMethod, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement | null>(null)
  // Closing used to drop focus to <body>, so returning to a row deep in the list meant
  // tabbing through everything above it again.
  const returnFocusTo = useRef<HTMLElement | null>(null)

  useEffect(() => {
    returnFocusTo.current = document.activeElement as HTMLElement | null
    return () => returnFocusTo.current?.focus?.()
  }, [])

  useEffect(() => {
    closeRef.current?.focus()
  }, [place?.id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const scoreEntries = place
    ? methods
        .filter((m) => place.allScores[m.key] !== undefined)
        .map((m) => ({ method: m, score: place.allScores[m.key] }))
    : []
  const maxScore = scoreEntries.length ? Math.max(...scoreEntries.map((s) => s.score)) : 5
  const minScore = scoreEntries.length ? Math.min(...scoreEntries.map((s) => s.score)) : 0
  const spread = maxScore - minScore

  return (
    <aside className="detail-panel" role="dialog" aria-modal="true" aria-label="Place details">
      <div className="detail-head">
        <button ref={closeRef} type="button" className="detail-close" onClick={onClose}>
          ← Back to list
        </button>
      </div>
      {error ? (
        <div className="detail-body">
          <p className="error-text">{error}</p>
          <p className="detail-sub">This place could not be loaded. Try another result.</p>
        </div>
      ) : loading || !place ? (
        <div className="detail-loading">Loading place…</div>
      ) : (
        <div className="detail-body">
          <h2 className="detail-name">{place.name}</h2>
          <p className="detail-sub">
            {describePlace(place.category, place.neighborhood)}
            {place.brand && place.brand !== place.name ? ` · ${place.brand}` : ''}
          </p>

          <div className="detail-scoreline">
            <span className="detail-score-num">{formatScore(place.ratings.score)}</span>
            <span className="detail-score-meta">
              {/* Label from the response, not from the picker. The number was computed by
                  whichever method was selected when this was fetched, so reading the live
                  selection here captioned one method's score with another's name. */}
              {methods.find((m) => m.key === place.ratings.method)?.label
                ?? place.ratings.method} ·{' '}
              {ratingCount(place.ratings.count)} · mean{' '}
              {formatScore(place.ratings.mean)}
            </span>
          </div>

          <div className="detail-hist">
            <Histogram histogram={place.ratings.histogram} size="lg" />
            <div className="detail-hist-axis">
              {[1, 2, 3, 4, 5].map((s) => (
                <span key={s}>{s}</span>
              ))}
            </div>
          </div>

          <section className="detail-section">
            <h3>All seven methods on this place</h3>
            <p className="detail-note">
              Same ratings, seven rulings
              {spread > 0.05
                ? ` — a ${formatScore(spread)}-star spread.`
                : ' — they broadly agree here.'}
            </p>
            <ul className="all-scores">
              {scoreEntries.map(({ method, score }) => (
                <li
                  key={method.key}
                  className={method.key === activeMethod ? 'is-active' : ''}
                >
                  <span className="all-scores-label" title={method.blurb}>
                    {method.label}
                  </span>
                  <span className="all-scores-bar-wrap">
                    <span
                      className="all-scores-bar"
                      style={{ width: `${(score / 5) * 100}%` }}
                    />
                  </span>
                  <span className="all-scores-num">{formatScore(score)}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="detail-section">
            <h3>What Overture actually knows</h3>
            <dl className="provenance">
              <div>
                <dt>Confidence</dt>
                <dd>{confidenceLabel(place.overture.confidence)}</dd>
              </div>
              <div>
                <dt>Listed by</dt>
                <dd>
                  {place.overture.sources.length}{' '}
                  {place.overture.sources.length === 1 ? 'source' : 'sources'} —{' '}
                  {place.overture.sources.join(', ')}
                </dd>
              </div>
              {place.address && (
                <div>
                  <dt>Address</dt>
                  <dd>{place.address}</dd>
                </div>
              )}
              {place.phone && (
                <div>
                  <dt>Phone</dt>
                  <dd>{place.phone}</dd>
                </div>
              )}
              {place.website && (
                <div>
                  <dt>Website</dt>
                  <dd>
                    <a href={place.website} target="_blank" rel="noreferrer">
                      {place.website.replace(/^https?:\/\//, '')}
                    </a>
                  </dd>
                </div>
              )}
            </dl>
          </section>
        </div>
      )}
    </aside>
  )
}
