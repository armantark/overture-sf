export interface Method {
  key: string
  label: string
  blurb: string
}

export interface Category {
  root: string
  key: string
  count: number
}

export interface Root {
  key: string
  count: number
}

export interface Meta {
  release: string
  bbox: [number, number, number, number]
  cellMeters: number
  counts: { places: number; cells: number }
  methods: Method[]
  defaultMethod: string
  roots: Root[]
  categories: Category[]
  neighborhoods: string[]
  ratingsAreSynthetic: boolean
}

export interface Ratings {
  synthetic: boolean
  count: number
  mean: number
  histogram: [number, number, number, number, number]
  score: number
  method: string
}

export interface Place {
  id: string
  name: string
  lon: number
  lat: number
  category: string | null
  categoryRoot: string | null
  neighborhood: string | null
  address: string | null
  website: string | null
  phone: string | null
  brand: string | null
  overture: {
    confidence: number
    sourceCount: number
    sources: string[]
  }
  ratings: Ratings
}

export interface SearchResponse {
  method: string
  matched: number
  returned: number
  ratingsAreSynthetic: boolean
  results: Place[]
}

export interface PlaceDetailResponse extends Place {
  allScores: Record<string, number>
}

export interface Complement {
  category: string
  blocks: number
  lift: number
}

export interface SiteResult {
  lon: number
  lat: number
  neighborhood: string | null
  storefronts: number
  places: number
  competitors: number
  expected: number
  gap: number
  saturation: number
  streetMetres: number
  buildingAreaM2: number
}

export interface SitesResponse {
  category: string
  cityRate: number
  cellMeters: number
  usesSyntheticData: boolean
  undersupplied: number
  complements: Complement[]
  results: SiteResult[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
