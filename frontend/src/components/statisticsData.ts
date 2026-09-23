import type { Scalar, StatPoint } from '../api/types'

export function aggregatePoints(points: StatPoint[], minutes: number) {
  const buckets = new Map<string, {time: string; open: number; close: number; low: number; high: number}>()
  for (const [index, point] of points.entries()) {
    const date = new Date(point.time.replace(' ', 'T'))
    if (!Number.isFinite(date.getTime()) || !Number.isFinite(point.value)) continue
    if (minutes === 1440) date.setHours(0, 0, 0, 0)
    else if (minutes) date.setMinutes(Math.floor(date.getMinutes() / minutes) * minutes, 0, 0)
    const key = minutes ? String(date.getTime()) : String(index)
    const previous = buckets.get(key)
    if (previous) { previous.close = point.value; previous.low = Math.min(previous.low, point.value); previous.high = Math.max(previous.high, point.value) }
    else buckets.set(key, {time: minutes ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:00` : point.time, open: point.value, close: point.value, low: point.value, high: point.value})
  }
  return [...buckets.values()]
}

export function downloadCsv(name: string, rows: Scalar[][]) {
  const escape = (value: Scalar) => {
    let text = value == null ? '' : String(value)
    // 文本单元格禁用公式解释，保留数值负号的正常语义。
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`
    return `"${text.replaceAll('"', '""')}"`
  }
  const url = URL.createObjectURL(new Blob(['\uFEFF' + rows.map(row => row.map(escape).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'}))
  const link = document.createElement('a'); link.href = url; link.download = `${name}.csv`; link.click(); URL.revokeObjectURL(url)
}

export function mergeMultiSeriesRows(
  seriesList: {key: string; label: string; points: StatPoint[]}[],
  from = '',
  to = '',
): Scalar[][] {
  const timeMap = new Map<string, {values: Record<string, number>; source: string}>()
  for (const s of seriesList) {
    for (const p of s.points) {
      const t = p.time.replace(' ', 'T')
      if (from && t < from) continue
      if (to && t > `${to}:59.999`) continue
      const existing = timeMap.get(p.time)
      if (existing) {
        existing.values[s.key] = p.value
        if (!existing.source && p.source) existing.source = p.source
      } else {
        timeMap.set(p.time, {values: {[s.key]: p.value}, source: p.source ?? ''})
      }
    }
  }
  const sortedTimes = [...timeMap.keys()].sort((a, b) => b.localeCompare(a))
  return sortedTimes.map(time => {
    const entry = timeMap.get(time)!
    return [
      time,
      ...seriesList.map(s => (entry.values[s.key] != null ? entry.values[s.key] : '—')),
      entry.source || '—',
    ]
  })
}

