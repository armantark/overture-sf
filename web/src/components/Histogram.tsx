interface Props {
  histogram: [number, number, number, number, number]
  size?: 'sm' | 'lg'
}

// Compact five-bar sparkline: the shape of the ratings is the argument.
export function Histogram({ histogram, size = 'sm' }: Props) {
  const max = Math.max(...histogram, 1)
  const width = size === 'sm' ? 44 : 160
  const height = size === 'sm' ? 18 : 44
  const barW = width / 5
  const title = histogram
    .map((n, i) => `${i + 1} star: ${n}`)
    .join(', ')
  return (
    <svg
      className={`histogram histogram-${size}`}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`Rating distribution — ${title}`}
    >
      {histogram.map((n, i) => {
        const h = n === 0 ? 1.5 : Math.max(2, (n / max) * height)
        return (
          <rect
            key={i}
            x={i * barW + 1}
            y={height - h}
            width={barW - 2}
            height={h}
            rx={1}
            className={n === 0 ? 'histogram-bar histogram-bar-empty' : 'histogram-bar'}
          />
        )
      })}
    </svg>
  )
}
