// Shared label/format helpers.

const SMALL_WORDS = new Set(['and', 'of', 'the', 'for', 'in', 'at'])

export function humanize(key: string | null | undefined): string {
  if (!key) return ''
  return key
    .split('_')
    .map((w, i) => (i > 0 && SMALL_WORDS.has(w) ? w : w[0].toUpperCase() + w.slice(1)))
    .join(' ')
}

// "Art Museum · Presidio Terrace", skipping whichever half is missing;
// honest fallback when Overture knows neither.
export function describePlace(
  category: string | null,
  neighborhood: string | null,
): string {
  const parts = [category ? humanize(category) : null, neighborhood].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'San Francisco'
}

export function formatScore(n: number): string {
  return n.toFixed(2)
}

export function formatInt(n: number): string {
  return n.toLocaleString('en-US')
}

// Plural-aware category phrase: "coffee shops", "bakeries".
export function pluralize(key: string): string {
  const words = humanize(key).split(' ')
  const last = words[words.length - 1]
  let plural: string
  if (last.endsWith('y') && !/[aeiou]y$/.test(last)) plural = last.slice(0, -1) + 'ies'
  // Twelve Overture categories are already plural — orthodontics, public relations, trusts —
  // and the sibilant rule below turned them into "orthodonticses".
  else if (last.endsWith('s')) plural = last
  else if (/(x|z|ch|sh)$/.test(last)) plural = last + 'es'
  else plural = last + 's'
  words[words.length - 1] = plural
  return words.join(' ').toLowerCase()
}

// "1 ratings" read as a bug to anyone who noticed it.
export function ratingCount(n: number): string {
  return `${formatInt(n)} ${n === 1 ? 'rating' : 'ratings'}`
}

export function confidenceLabel(c: number): string {
  return `${Math.round(c * 100)}%`
}
