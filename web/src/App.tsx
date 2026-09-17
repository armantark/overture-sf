import { useEffect, useState } from 'react'
import type { Meta } from './types'
import { fetchMeta } from './api'
import { CompareView } from './components/CompareView'
import { SitesView } from './components/SitesView'
import { ErrorBoundary } from './components/ErrorBoundary'

type Tab = 'compare' | 'sites'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('compare')

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title-block">
          <h1 className="app-title">Thin Evidence</h1>
          <p className="app-subtitle">
            San Francisco places, ranked honestly — built on Overture Maps
            {meta ? ` (release ${meta.release})` : ''}
          </p>
        </div>
        <nav className="tabs" aria-label="Views">
          <button
            type="button"
            className={`tab${tab === 'compare' ? ' is-active' : ''}`}
            onClick={() => setTab('compare')}
            aria-pressed={tab === 'compare'}
          >
            Compare
          </button>
          <button
            type="button"
            className={`tab${tab === 'sites' ? ' is-active' : ''}`}
            onClick={() => setTab('sites')}
            aria-pressed={tab === 'sites'}
          >
            Where to open
          </button>
        </nav>
      </header>

      {tab === 'compare' && (
        <div className="synthetic-note" role="note">
          <span className="synthetic-badge">Synthetic ratings</span>
          <span>
            Overture records what exists, not what anyone thought of it. The ratings and
            review counts below are generated deterministically from each place's real
            Overture id — the locations, categories and source data are real; the stars are
            a stand-in so the ranking methods have something to chew on.
          </span>
        </div>
      )}

      {error && (
        <div className="app-error" role="alert">
          Could not reach the API: {error}. Make sure the backend is running on port 8000.
        </div>
      )}
      {!meta && !error && <div className="app-loading">Loading dataset metadata…</div>}

      {meta && (
        <main className="app-main">
          <ErrorBoundary key={tab}>
            {tab === 'compare' ? <CompareView meta={meta} /> : <SitesView meta={meta} />}
          </ErrorBoundary>
        </main>
      )}
    </div>
  )
}
