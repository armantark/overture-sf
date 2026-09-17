import { useState } from 'react'
import type { Method } from '../types'

interface Props {
  methods: Method[]
  value: string
  onChange: (key: string) => void
}

// The hero control on Side A: every method is a labelled option, and the
// one-line blurb (verbatim from the API) follows the hovered/selected option.
export function MethodPicker({ methods, value, onChange }: Props) {
  const [hovered, setHovered] = useState<string | null>(null)
  const shown = methods.find((m) => m.key === (hovered ?? value))

  return (
    <div className="method-picker">
      <div className="method-picker-label" id="method-picker-label">
        Rank by
      </div>
      <div
        className="method-options"
        role="radiogroup"
        aria-labelledby="method-picker-label"
        onMouseLeave={() => setHovered(null)}
      >
        {methods.map((m) => (
          <button
            key={m.key}
            type="button"
            role="radio"
            aria-checked={m.key === value}
            className={`method-option${m.key === value ? ' is-active' : ''}`}
            onClick={() => onChange(m.key)}
            onMouseEnter={() => setHovered(m.key)}
            onFocus={() => setHovered(m.key)}
            onBlur={() => setHovered(null)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="method-blurb" aria-live="polite">
        {shown?.blurb ?? ''}
      </p>
    </div>
  )
}
