// Shared number and date formatters for the charts
export function formatDate(iso) {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatTick(iso) {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
}

export const usd = (v) =>
  `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

// Axis labels: whole dollars, compact only for large values so ticks stay distinct
export const usdCompact = (v) => {
  const opts = Math.abs(v) >= 100000
    ? { notation: 'compact', maximumFractionDigits: 1 }
    : { maximumFractionDigits: 0 }
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, opts)}`
}
