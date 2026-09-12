import type { DimensionCoverage } from '../core/dashboard'

const SIZE = 340
const CENTER = SIZE / 2
const RADIUS = 108
// Horizontal room for the vertex labels, so they live inside the element's own
// box. Relying on overflow put them 29px into the column beside the chart.
const PAD = 70
const RINGS = [0.25, 0.5, 0.75, 1]

/**
 * The one chart in the app. Hand-drawn SVG rather than a chart library: the
 * shape is the data, and the axes, legend and tooltips a library brings are
 * exactly what the spec leaves out.
 *
 * Six vertices, one per dimension, each at covered/total of that dimension.
 */
export function Radar({ coverage }: { coverage: DimensionCoverage[] }) {
  const axes = coverage.length
  if (axes < 3) return null

  const point = (index: number, ratio: number): [number, number] => {
    // Start at twelve o'clock and go clockwise, so the first axis reads first.
    const angle = (Math.PI * 2 * index) / axes - Math.PI / 2
    return [CENTER + Math.cos(angle) * RADIUS * ratio, CENTER + Math.sin(angle) * RADIUS * ratio]
  }

  const polygon = (ratios: number[]) =>
    ratios.map((ratio, index) => point(index, ratio).join(',')).join(' ')

  return (
    <svg
      className="radar"
      viewBox={`${-PAD} 0 ${SIZE + PAD * 2} ${SIZE}`}
      role="img"
      aria-label="Skills radar"
    >
      {RINGS.map((ring) => (
        <polygon
          key={ring}
          className="radar-ring"
          points={polygon(coverage.map(() => ring))}
        />
      ))}

      {coverage.map((entry, index) => {
        const [x, y] = point(index, 1)
        return <line key={entry.dimension} className="radar-spoke" x1={CENTER} y1={CENTER} x2={x} y2={y} />
      })}

      <polygon className="radar-area" points={polygon(coverage.map((entry) => entry.ratio))} />

      {coverage.map((entry, index) => {
        const [x, y] = point(index, entry.ratio)
        return <circle key={entry.dimension} className="radar-dot" cx={x} cy={y} r={2.5} />
      })}

      {coverage.map((entry, index) => {
        const [x, y] = point(index, 1.17)
        return (
          <text
            key={entry.dimension}
            className="radar-label"
            x={x}
            y={y}
            textAnchor={anchorFor(x)}
            dominantBaseline="middle"
          >
            {entry.dimension}
          </text>
        )
      })}
    </svg>
  )
}

/** Labels left of the centre read outward, so they never sit on the shape. */
function anchorFor(x: number): 'start' | 'middle' | 'end' {
  if (Math.abs(x - CENTER) < 6) return 'middle'
  return x > CENTER ? 'start' : 'end'
}
