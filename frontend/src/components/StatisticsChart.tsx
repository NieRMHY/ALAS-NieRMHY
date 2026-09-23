import { Select } from './FormControls'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { StatSeries, StatisticsReport } from '../api/types'
import { Empty } from './ui'
import { StatisticsTable } from './StatisticsTable'
import { aggregatePoints, mergeMultiSeriesRows } from './statisticsData'
import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'

echarts.use([LineChart, CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent, CanvasRenderer])

const RESOURCE_PALETTE: Record<string, string> = {
  oil: '#10b981', coin: '#f59e0b', cube: '#0ea5e9', gem: '#f43f5e', pt: '#8b5cf6',
  core: '#06b6d4', medal: '#e11d48', merit: '#d97706', guild_coin: '#64748b',
  ap: '#3b82f6', asset: '#6366f1', distance: '#14b8a6', yellow_coins: '#eab308', purple_coins: '#a855f7',
}
const DEFAULT_PALETTE = ['#159b88', '#f59e0b', '#0ea5e9', '#ec4899', '#8b5cf6', '#10b981', '#f97316', '#6366f1', '#14b8a6']
type ChartMode = 'line' | 'candlestick'

function getSeriesColor(key: string, index: number, fallback?: string): string {
  return RESOURCE_PALETTE[key] ?? (index === 0 && fallback ? fallback : DEFAULT_PALETTE[index % DEFAULT_PALETTE.length])
}

/** 图表主体。紧凑主题把标题行与「放大查看」上提到页面工具栏（`heading=false`），
    并把报表附带的表格并进同一面板，避免同一页出现两个顶层区域。 */
export function StatisticsChart({series, tables = [], heading = true, expanded = false, onToggleExpanded, title, initialMode = 'line'}: {
  series: StatSeries[]
  tables?: StatisticsReport['tables']
  heading?: boolean
  expanded?: boolean
  onToggleExpanded: () => void
  /* 放大视图用当前分区的名字当标题：整页工具栏（含分区切换）被面板盖住后，
     只写「趋势与细节」就分不出看的是资源趋势还是委托收益。 */
  title?: string
  initialMode?: ChartMode
}) {
  const {ui, language, theme} = useApp()
  const [selectedKeys, setSelectedKeys] = useState<string[]>(() => {
    const active = series.find(item => item.points.length)?.key ?? series[0]?.key
    return active ? [active] : []
  })
  const [mode, setMode] = useState(initialMode)
  const [axisMode, setAxisMode] = useState<'separate' | 'unified'>('separate')
  const [bucket, setBucket] = useState(initialMode === 'candlestick' ? 60 : 0)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onToggleExpanded() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded, onToggleExpanded])

  const element = useRef<HTMLDivElement>(null)

  /* 全屏放大模式下根据固定视口计算高度；常规贯穿模式下沿用样式表定义的舒适高度。 */
  useLayoutEffect(() => {
    const canvas = element.current
    const panel = canvas?.closest<HTMLElement>('.statistics-chart')
    if (!canvas || !panel) return
    if (!expanded) {
      canvas.style.height = ''
      return
    }
    const resize = () => {
      let above = 0
      for (const child of panel.children) {
        if (child === canvas) break
        above += child.getBoundingClientRect().height
      }
      const panelBefore = panel.clientHeight
      const canvasBefore = canvas.getBoundingClientRect().height
      const next = Math.max(240, panelBefore - above)
      if (Math.abs(next - canvasBefore) < 1) return
      canvas.style.height = `${next}px`
      /* 面板跟着长高，说明它的高度由内容决定，此时写高会无限增高，于是退回原高度。 */
      if (panel.clientHeight > panelBefore + 1) canvas.style.height = `${canvasBefore}px`
    }
    resize()
    /* 面板高度、上方内容高度（换语言会让芯片换行）变化时都要重算。 */
    const observer = new ResizeObserver(resize)
    observer.observe(panel)
    for (const child of panel.children) if (child !== canvas) observer.observe(child)
    return () => observer.disconnect()
  }, [series, language, expanded])

  function toggleKey(key: string) {
    setSelectedKeys(prev => (prev.includes(key) ? (prev.length <= 1 ? prev : prev.filter(k => k !== key)) : [...prev, key]))
  }

  function selectOnly(key: string) {
    setSelectedKeys([key])
  }

  function setAsPrimary(key: string) {
    setSelectedKeys(prev => [key, ...prev.filter(k => k !== key)])
  }

  const selectedSeries = useMemo(() => {
    const filtered = series.filter(item => selectedKeys.includes(item.key))
    filtered.sort((a, b) => selectedKeys.indexOf(a.key) - selectedKeys.indexOf(b.key))
    return filtered.length ? filtered : (series[0] ? [series[0]] : [])
  }, [series, selectedKeys])

  const isSingle = selectedSeries.length === 1
  const isCandlestick = mode === 'candlestick'
  const effectiveBucket = isCandlestick && bucket === 0 ? 60 : bucket

  const seriesData = useMemo(() => {
    return selectedSeries.map((s, index) => {
      const points = s.points.filter(point => (!from || point.time.replace(' ', 'T') >= from) && (!to || point.time.replace(' ', 'T') <= `${to}:59.999`))
      const buckets = aggregatePoints(points, effectiveBucket)
      const values = points.map(p => p.value)
      return {
        series: s, points, buckets, values,
        latest: values.at(-1),
        change: values.length >= 2 ? (values.at(-1)! - values[0]) : 0,
        minimum: values.length ? Math.min(...values) : 0,
        maximum: values.length ? Math.max(...values) : 0,
        color: getSeriesColor(s.key, index),
        index,
      }
    })
  }, [selectedSeries, from, to, effectiveBucket])

  const categoryTimes = useMemo(() => {
    if (!isCandlestick) return []
    const set = new Set<string>()
    for (const item of seriesData) for (const b of item.buckets) set.add(b.time)
    return [...set].sort()
  }, [isCandlestick, seriesData])

  const hasPoints = seriesData.some(item => item.points.length > 0)
  useEffect(() => {
    const el = element.current
    return () => {
      if (el) echarts.getInstanceByDom(el)?.dispose()
    }
  }, [])

  const single = seriesData[0]

  useEffect(() => {
    if (!element.current || !hasPoints) return
    const container = element.current
    const chart = echarts.getInstanceByDom(container) ?? echarts.init(container, undefined, {locale: language.startsWith('zh') ? 'ZH' : 'EN'})

    function render() {
      const colors = getComputedStyle(document.documentElement)
      const text = colors.getPropertyValue('--text').trim() || '#82929f'
      const minimal = !usesMaterial(theme)
      const primary = minimal ? colors.getPropertyValue('--accent').trim() : '#159b88'
      const secondary = minimal ? colors.getPropertyValue('--secondary').trim() : '#de7861'
      const surface = colors.getPropertyValue('--surface').trim()
      const border = colors.getPropertyValue('--border').trim()
      const colorFor = (item: typeof seriesData[number]) => isSingle ? (minimal ? primary : item.color) : item.color

      let yAxes: any[] = []
      if (isSingle || axisMode === 'unified') {
        yAxes = [{type: 'value', scale: true, splitLine: {lineStyle: {color: border}}, axisLabel: {color: text}}]
      } else if (selectedSeries.length === 2) {
        const c0 = colorFor(seriesData[0]), c1 = colorFor(seriesData[1])
        yAxes = [
          {type: 'value', scale: true, position: 'left', splitLine: {lineStyle: {color: border}}, axisLine: {show: true, lineStyle: {color: c0}}, axisLabel: {color: c0}},
          {type: 'value', scale: true, position: 'right', splitLine: {show: false}, axisLine: {show: true, lineStyle: {color: c1}}, axisLabel: {color: c1}},
        ]
      } else {
        yAxes = seriesData.map((item, idx) => {
          const color = colorFor(item)
          if (idx === 0) return {type: 'value', scale: true, position: 'left', splitLine: {lineStyle: {color: border}}, axisLine: {show: true, lineStyle: {color}}, axisLabel: {color}}
          if (idx === 1) return {type: 'value', scale: true, position: 'right', splitLine: {show: false}, axisLine: {show: true, lineStyle: {color}}, axisLabel: {color}}
          return {type: 'value', scale: true, show: false, splitLine: {show: false}}
        })
      }

      const echartsSeries = seriesData.map(item => {
        const color = colorFor(item)
        if (isCandlestick) {
          const bucketMap = new Map(item.buckets.map(b => [b.time, b]))
          if (item.index === 0) {
            return {
              name: item.series.label, type: 'candlestick', yAxisIndex: 0,
              itemStyle: {color: primary, color0: secondary, borderColor: primary, borderColor0: secondary},
              data: categoryTimes.map(t => { const b = bucketMap.get(t); return b ? [b.open, b.close, b.low, b.high] : '-' }),
            }
          }
          return {
            name: item.series.label, type: 'line', yAxisIndex: isSingle || axisMode === 'unified' ? 0 : Math.min(item.index, yAxes.length - 1),
            showSymbol: item.points.length < 80, symbolSize: 5, connectNulls: true, lineStyle: {width: 2, color}, itemStyle: {color},
            data: categoryTimes.map(t => { const b = bucketMap.get(t); return b ? b.close : '-' }),
          }
        }
        return {
          name: item.series.label, type: 'line', yAxisIndex: isSingle || axisMode === 'unified' ? 0 : Math.min(item.index, yAxes.length - 1),
          showSymbol: item.points.length < 80, symbolSize: 5, connectNulls: false, lineStyle: {width: 2, color}, itemStyle: {color},
          data: item.buckets.map(b => [new Date(b.time.replace(' ', 'T')).getTime(), b.close]),
        }
      })

      const hasRightAxis = !isSingle && axisMode === 'separate' && selectedSeries.length >= 2

      chart.setOption({
        animation: false, textStyle: {color: text, fontFamily: 'Microsoft YaHei, sans-serif'},
        grid: {left: 65, right: hasRightAxis ? 65 : 30, top: !isSingle ? 80 : 65, bottom: 85},
        legend: !isSingle ? {show: true, top: 16, left: 'center', textStyle: {color: text}, data: selectedSeries.map(s => s.label)} : undefined,
        tooltip: {
          trigger: 'axis', confine: true, renderMode: 'richText', axisPointer: {type: 'cross'},
          valueFormatter: (val: any) => typeof val === 'number' ? val.toLocaleString(undefined, {maximumFractionDigits: 2}) : String(val),
          ...(minimal ? {backgroundColor: surface, borderColor: border, textStyle: {color: text}, extraCssText: '', shadowBlur: 0} : {}),
        },
        toolbox: {
          right: 20,
          feature: {
            dataZoom: {yAxisIndex: 'none', title: {zoom: ui('stats.toolboxZoom'), back: ui('stats.toolboxBack')}},
            restore: {title: ui('stats.toolboxRestore')},
            saveAsImage: {title: ui('stats.toolboxSave'), name: selectedSeries.map(s => s.label).join('-'), pixelRatio: 2},
          },
        },
        xAxis: isCandlestick ? {type: 'category', data: categoryTimes, axisLabel: {hideOverlap: true}} : {type: 'time', axisLabel: {hideOverlap: true}},
        yAxis: yAxes,
        dataZoom: [
          {type: 'inside', zoomOnMouseWheel: 'ctrl'},
          {
            type: 'slider', bottom: 16, height: 26,
            ...(minimal ? {
              backgroundColor: surface, fillerColor: colors.getPropertyValue('--accent-soft').trim(), borderColor: border,
              dataBackground: {lineStyle: {color: secondary, opacity: 1}, areaStyle: {color: surface, opacity: 1}},
              selectedDataBackground: {lineStyle: {color: primary, opacity: 1}, areaStyle: {color: colors.getPropertyValue('--accent-soft').trim(), opacity: 1}},
              handleStyle: {color: primary, borderColor: primary}, moveHandleStyle: {color: secondary},
            } : {}),
          },
        ],
        series: echartsSeries,
      }, true)
    }

    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        event.stopPropagation()
      }
    }
    container.addEventListener('wheel', onWheel, {capture: true, passive: true})

    render()
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    const themeObserver = new MutationObserver(render)
    themeObserver.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-palette', 'data-color-mode', 'style']})
    return () => {
      container.removeEventListener('wheel', onWheel, {capture: true})
      observer.disconnect()
      themeObserver.disconnect()
    }
  }, [seriesData, hasPoints, isCandlestick, axisMode, isSingle, selectedSeries, categoryTimes, language, ui, theme])

  const mergedRows = useMemo(() => {
    return isSingle ? single.points.map(p => [p.time, p.value, p.source || '—']) : mergeMultiSeriesRows(selectedSeries, from, to)
  }, [isSingle, single, selectedSeries, from, to])

  /* 图表设置（类型、坐标轴、采样粒度、时间范围）排在图表下方：先看数据，再决定怎么画。 */
  const controls = <div className="statistics-controls">
    <label>
      {ui('stats.chart')}
      <Select
        aria-label={ui('stats.chartType')}
        value={mode}
        onChange={event => {
          const nextMode: ChartMode = event.target.value === 'candlestick' ? 'candlestick' : 'line'
          setMode(nextMode)
          if (nextMode === 'candlestick' && bucket === 0) {
            setBucket(60)
          }
        }}
      >
        <option value="line">{ui('stats.line')}</option>
        <option value="candlestick">{isSingle ? ui('stats.candlestick') : ui('stats.candlestickOverlay')}</option>
      </Select>
    </label>

    {!isSingle && (
      <label>
        {ui('stats.axisMode')}
        <Select aria-label={ui('stats.axisMode')} value={axisMode} onChange={event => setAxisMode(event.target.value as 'separate' | 'unified')}>
          <option value="separate">{ui('stats.axisSeparate')}</option>
          <option value="unified">{ui('stats.axisUnified')}</option>
        </Select>
      </label>
    )}

    <label>
      {ui('stats.bucket')}
      <Select aria-label={ui('stats.bucket')} value={effectiveBucket} onChange={event => setBucket(Number(event.target.value))}>
        {!isCandlestick && <option value={0}>{ui('stats.eachRecord')}</option>}
        <option value={5}>{ui('stats.fiveMinutes')}</option>
        <option value={60}>{ui('stats.hourly')}</option>
        <option value={1440}>{ui('stats.daily')}</option>
      </Select>
    </label>

    <label>
      {ui('stats.startTime')}
      <div className="date-input-wrap">
        <input type="datetime-local" aria-label={ui('stats.startTime')} value={from} className={from ? '' : 'date-empty'} onChange={event => setFrom(event.target.value)}/>
        {!from && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <label>
      {ui('stats.endTime')}
      <div className="date-input-wrap">
        <input type="datetime-local" aria-label={ui('stats.endTime')} value={to} className={to ? '' : 'date-empty'} onChange={event => setTo(event.target.value)}/>
        {!to && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <button className="text-button" onClick={() => {setFrom(''); setTo('')}}>{ui('stats.allTime')}</button>
  </div>

  const rangeError = from && to && from > to ? <p className="preview-error" role="alert">{ui('stats.invalidRange')}</p> : null

  return (
    <section className={`panel statistics-chart ${expanded ? 'chart-expanded' : ''}`}>
      {/* 紧凑主题把标题与「放大查看」上提到页面工具栏：分类切换已经说明了这是什么，
          面板里再写一遍「趋势与细节」是重复的。但放大视图会盖住整页工具栏（含分区切换），
          所以放大时必须把标题行放回来，否则只剩 Esc 能退出。 */}
      {(heading || expanded) && <div className="panel-heading">
        <h2>{expanded && title ? title : ui('stats.trendDetails')}</h2>
        <button className="text-button" onClick={onToggleExpanded}>{expanded ? ui('stats.collapseChart') : ui('stats.expandChart')}</button>
      </div>}

      <div className="statistics-metrics-container">
        <span className="statistics-metrics-label">{ui('stats.metric')}</span>
        <div className="statistics-metrics-chips" role="group" aria-label={ui('stats.metric')}>
          {series.map((item, idx) => {
            const active = selectedKeys.includes(item.key)
            const empty = item.points.length === 0
            const color = getSeriesColor(item.key, idx)
            const selectedIdx = selectedKeys.indexOf(item.key)
            const isCandlePrimary = active && isCandlestick && !isSingle && selectedIdx === 0
            const isOverlayLine = active && isCandlestick && !isSingle && selectedIdx > 0

            return (
              <button
                key={item.key} type="button"
                className={`stat-chip ${active ? 'active' : ''} ${empty ? 'empty' : ''}`}
                onClick={() => toggleKey(item.key)} onDoubleClick={() => selectOnly(item.key)}
                title={empty ? ui('stats.noSeriesRecord') : `${item.label} (${active ? '已启用' : '未启用'}，双击仅看此项)`}
                disabled={empty}
              >
                <span className="stat-chip-dot" style={{backgroundColor: active ? color : undefined}}/>
                <span>{item.label}</span>
                {isCandlePrimary && <span className="stat-chip-badge primary">{ui('stats.primaryCandle')}</span>}
                {isOverlayLine && (
                  <span className="stat-chip-badge secondary" title={ui('stats.setAsPrimary')} onClick={e => { e.stopPropagation(); setAsPrimary(item.key) }}>
                    {ui('stats.overlayLine')}
                  </span>
                )}
                {empty && <small>{ui('stats.noSeriesRecord')}</small>}
              </button>
            )
          })}
          {selectedKeys.length > 1 && (
            <button type="button" className="text-button" onClick={() => selectOnly(selectedKeys[0])}>{ui('stats.resetSelection')}</button>
          )}
        </div>
      </div>

      {hasPoints ? (
        <>
          {isSingle ? (
            <div className="stat-metrics">
              {[[ui('stats.latest'), single.latest], [ui('stats.change'), single.change], [ui('stats.maximum'), single.maximum], [ui('stats.minimum'), single.minimum], [ui('stats.rawCount'), single.points.length]].map(([label, value]) => (
                <div key={String(label)}><span>{label}</span><strong>{Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
              ))}
            </div>
          ) : (
            <div className="stat-multi-metrics">
              {seriesData.map((item, idx) => {
                const diffClass = item.change > 0 ? 'positive' : item.change < 0 ? 'negative' : 'neutral'
                const formattedChange = item.change > 0 ? `+${item.change.toLocaleString(undefined, {maximumFractionDigits: 2})}` : item.change.toLocaleString(undefined, {maximumFractionDigits: 2})
                const isCandle = isCandlestick && idx === 0
                return (
                  <div key={item.series.key} className="stat-metric-card">
                    <div className="stat-metric-header">
                      <span className="stat-chip-dot" style={{backgroundColor: item.color}}/>
                      <strong>{item.series.label}{isCandle && <span className="stat-chip-badge primary">{ui('stats.primaryCandle')}</span>}</strong>
                    </div>
                    <div className="stat-metric-body">
                      <div><span>{ui('stats.latest')}</span><strong>{item.latest == null ? '—' : item.latest.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                      <div><span>{ui('stats.change')}</span><strong className={diffClass}>{formattedChange}</strong></div>
                      <div><span>{ui('stats.maximum')}</span><strong>{item.maximum.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                      <div><span>{ui('stats.minimum')}</span><strong>{item.minimum.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div ref={element} className="chart-canvas" role="img" aria-label={ui('stats.chartAria', {label: selectedSeries.map(s => s.label).join(' / ')})}/>
          {controls}
          {rangeError}
          <p className="panel-note">{ui('stats.chartHint')}</p>

          <StatisticsTable
            data={{
              title: isSingle ? ui('stats.rawTitle', {label: single.series.label}) : ui('stats.multiMetrics'),
              columns: isSingle ? [ui('stats.time'), ui('stats.value'), ui('stats.source')] : [ui('stats.time'), ...selectedSeries.map(s => s.label), ui('stats.source')],
              rows: mergedRows,
              defaultSort: {index: 0, descending: true},
            }}
          />
          {tables.map(table => <StatisticsTable key={table.title} data={table}/>)}
        </>
      ) : (
        <>
          {controls}
          {rangeError}
          <Empty title={ui('stats.noValidTitle')}>{ui('stats.noValidHint')}</Empty>
        </>
      )}
    </section>
  )
}



