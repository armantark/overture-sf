import type { Meta, PlaceDetailResponse, SearchResponse, SitesResponse } from './types'
import { ApiError } from './types'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // keep the generic message
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

export const fetchMeta = () => get<Meta>('/api/meta')

export interface SearchParams {
  q?: string
  root?: string
  category?: string
  neighborhood?: string
  method?: string
  min_reviews?: number
  limit?: number
}

export function fetchSearch(p: SearchParams): Promise<SearchResponse> {
  const qs = new URLSearchParams()
  if (p.q) qs.set('q', p.q)
  if (p.root) qs.set('root', p.root)
  if (p.category) qs.set('category', p.category)
  if (p.neighborhood) qs.set('neighborhood', p.neighborhood)
  if (p.method) qs.set('method', p.method)
  if (p.min_reviews) qs.set('min_reviews', String(p.min_reviews))
  qs.set('limit', String(p.limit ?? 50))
  return get<SearchResponse>(`/api/search?${qs}`)
}

export const fetchPlace = (id: string, method: string) =>
  get<PlaceDetailResponse>(`/api/places/${encodeURIComponent(id)}?method=${encodeURIComponent(method)}`)

export const fetchSites = (category: string, limit = 60) =>
  get<SitesResponse>(`/api/sites?category=${encodeURIComponent(category)}&limit=${limit}`)
