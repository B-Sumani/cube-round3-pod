/**
 * Formatting and display helpers
 */

export function formatCurrency(amount) {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return '—'
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

export function formatTimestamp(isoString) {
  if (!isoString) return '—'
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return String(isoString)
    return d.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short',
    })
  } catch {
    return String(isoString)
  }
}

export function formatDuration(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function truncateHash(hash, head = 8, tail = 6) {
  if (!hash) return '—'
  if (typeof hash !== 'string') return String(hash)
  if (hash.length <= head + tail) return hash
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`
}

export function sanitizeText(str) {
  if (str === null || str === undefined) return ''
  return String(str)
}
