import { describe, expect, it } from 'vitest'
import { aggregatePoints, mergeMultiSeriesRows } from './statisticsData'

describe('统计时间聚合', () => {
  it('K 线保留开高低收以及零值，不用平均值代替收盘', () => {
    const points = [10, 30, 0, 20].map((value, index) => ({time: `2026-09-13 10:0${index}:00`, value}))
    expect(aggregatePoints(points, 60)).toEqual([{time: '2026-09-13 10:00:00', open: 10, close: 20, low: 0, high: 30}])
  })
  it('日聚合按本地自然日分桶，原始视图保留同一时刻的多次记录', () => {
    const points = [{time: '2026-09-13 23:59:00', value: 1}, {time: '2026-09-14 00:01:00', value: 2}, {time: '2026-09-14 00:01:00', value: 3}]
    expect(aggregatePoints(points, 1440)).toHaveLength(2)
    expect(aggregatePoints(points, 0)).toHaveLength(3)
  })
})

describe('多数据源行合并', () => {
  it('按时间戳将多个数据源对齐合并并降序排列', () => {
    const seriesList = [
      {key: 'oil', label: '石油', points: [{time: '2026-09-20 12:00:00', value: 1000, source: '出击'}, {time: '2026-09-20 13:00:00', value: 900, source: '出击'}]},
      {key: 'coin', label: '物资', points: [{time: '2026-09-20 12:00:00', value: 50000, source: '出击'}, {time: '2026-09-20 14:00:00', value: 60000, source: '委托'}]},
      {key: 'cube', label: '魔方', points: [{time: '2026-09-20 13:00:00', value: 300, source: '出击'}]},
    ]
    const rows = mergeMultiSeriesRows(seriesList)
    expect(rows).toEqual([
      ['2026-09-20 14:00:00', '—', 60000, '—', '委托'],
      ['2026-09-20 13:00:00', 900, '—', 300, '出击'],
      ['2026-09-20 12:00:00', 1000, 50000, '—', '出击'],
    ])
  })

  it('支持时间范围过滤', () => {
    const seriesList = [
      {key: 'oil', label: '石油', points: [{time: '2026-09-20 10:00:00', value: 100}, {time: '2026-09-20 12:00:00', value: 200}]},
    ]
    const rows = mergeMultiSeriesRows(seriesList, '2026-09-20T11:00')
    expect(rows).toHaveLength(1)
    expect(rows[0][0]).toBe('2026-09-20 12:00:00')
  })
})

