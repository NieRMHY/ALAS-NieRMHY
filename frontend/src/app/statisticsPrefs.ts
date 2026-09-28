/**
 * @fileoverview 统计页外观偏好、时间跨度、图表类型与指标筛选持久化。
 */

/**
 * 统计页外观与交互偏好：统计分类、时间跨度、图表类型、采样粒度和选中的指标。
 *
 * 与其它界面偏好一致：关掉再打开接着上次的样子，直到用户自己调整。
 * 只存本浏览器，不区分实例。
 */
export type StatisticsCategory = 'resources' | 'action' | 'opsi' | 'commission' | 'ships' | 'loot' | 'research'
export type ChartMode = 'line' | 'candlestick'
export type ChartAxisMode = 'separate' | 'unified'
export type CommissionPeriod = 'day' | 'week' | 'month'

export interface StatisticsPrefs {
  category: StatisticsCategory
  days: number
  period: CommissionPeriod
  /** 科研页面的视图：'1'~'9' 是各期，'consumable' 是心智/物资 */
  researchSelect: string
  /** 大世界掉落页的任务筛选：'' 是全部大世界任务，其余是任务标识（opsi_xxx） */
  lootTask: string
  chartMode: ChartMode
  chartAxisMode: ChartAxisMode
  /** 纵轴起始值固定为 0，缩放后不跟着可见范围浮动 */
  chartZeroBase: boolean
  bucket: number
  /** 图表与原始记录卡共用的时间范围，空表示不限 */
  rangeFrom: string
  rangeTo: string
  selectedKeys: Record<string, string[]>
}

export const PREFS_KEY = 'azurpilot.statistics'

export const VALID_CATEGORIES: readonly StatisticsCategory[] = ['resources', 'action', 'opsi', 'commission', 'ships', 'loot', 'research']
export const VALID_DAYS: readonly number[] = [1, 7, 30, 90, 365]
export const VALID_PERIODS: readonly CommissionPeriod[] = ['day', 'week', 'month']
export const VALID_BUCKETS: readonly number[] = [0, 5, 60, 1440]
export const VALID_CHART_MODES: readonly ChartMode[] = ['line', 'candlestick']
export const VALID_AXIS_MODES: readonly ChartAxisMode[] = ['separate', 'unified']
export const VALID_RESEARCH_SELECTS: readonly string[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'consumable']
/* 任务标识由后端给（opsi_xxx），这里只校验形状；下架的任务在页面里自然没有记录 */
const LOOT_TASK_PATTERN = /^[a-z][a-z0-9_]{0,40}$/

export const DEFAULT_STATISTICS_PREFS: StatisticsPrefs = {
  category: 'resources',
  days: 7,
  period: 'month',
  researchSelect: '9',
  lootTask: '',
  chartMode: 'line',
  chartAxisMode: 'separate',
  chartZeroBase: false,
  bucket: 0,
  rangeFrom: '',
  rangeTo: '',
  selectedKeys: {},
}

export function readStatisticsPrefs(): StatisticsPrefs {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(PREFS_KEY) : null
    if (!raw) return { ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} }
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as Record<string, unknown>
      const category = VALID_CATEGORIES.includes(obj.category as StatisticsCategory)
        ? (obj.category as StatisticsCategory)
        : DEFAULT_STATISTICS_PREFS.category
      const days = typeof obj.days === 'number' && VALID_DAYS.includes(obj.days)
        ? obj.days
        : DEFAULT_STATISTICS_PREFS.days
      const period = VALID_PERIODS.includes(obj.period as CommissionPeriod)
        ? (obj.period as CommissionPeriod)
        : DEFAULT_STATISTICS_PREFS.period
      const researchSelect = VALID_RESEARCH_SELECTS.includes(obj.researchSelect as string)
        ? (obj.researchSelect as string)
        : DEFAULT_STATISTICS_PREFS.researchSelect
      const lootTask = typeof obj.lootTask === 'string' && (obj.lootTask === '' || LOOT_TASK_PATTERN.test(obj.lootTask))
        ? obj.lootTask
        : DEFAULT_STATISTICS_PREFS.lootTask
      const chartMode = VALID_CHART_MODES.includes(obj.chartMode as ChartMode)
        ? (obj.chartMode as ChartMode)
        : DEFAULT_STATISTICS_PREFS.chartMode
      const chartAxisMode = VALID_AXIS_MODES.includes(obj.chartAxisMode as ChartAxisMode)
        ? (obj.chartAxisMode as ChartAxisMode)
        : DEFAULT_STATISTICS_PREFS.chartAxisMode
      const chartZeroBase = typeof obj.chartZeroBase === 'boolean' ? obj.chartZeroBase : DEFAULT_STATISTICS_PREFS.chartZeroBase
      const bucket = typeof obj.bucket === 'number' && VALID_BUCKETS.includes(obj.bucket)
        ? obj.bucket
        : DEFAULT_STATISTICS_PREFS.bucket

      const rangeFrom = typeof obj.rangeFrom === 'string' ? obj.rangeFrom : ''
      const rangeTo = typeof obj.rangeTo === 'string' ? obj.rangeTo : ''

      const selectedKeys: Record<string, string[]> = {}
      if (obj.selectedKeys && typeof obj.selectedKeys === 'object') {
        for (const [key, value] of Object.entries(obj.selectedKeys as Record<string, unknown>)) {
          if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
            selectedKeys[key] = [...new Set(value)]
          }
        }
      }

      return {
        category,
        days,
        period,
        researchSelect,
        lootTask,
        chartMode,
        chartAxisMode,
        chartZeroBase,
        bucket,
              rangeFrom,
              rangeTo,
        selectedKeys,
      }
    }
  } catch {
    /* 损坏偏好沿用默认配置。 */
  }
  return { ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} }
}

let snapshot: StatisticsPrefs = readStatisticsPrefs()

/* 偏好是模块级快照：写入即通知订阅者，供同页的其它卡片跟着重算。 */
let version = 0
const listeners = new Set<() => void>()

export function subscribeStatisticsPrefs(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getStatisticsPrefsVersion(): number {
  return version
}

export function getStatisticsPrefs(): StatisticsPrefs {
  return snapshot
}

export function updateStatisticsPrefs(partial: Partial<StatisticsPrefs>) {
  snapshot = {
    ...snapshot,
    ...partial,
    selectedKeys: partial.selectedKeys ? { ...snapshot.selectedKeys, ...partial.selectedKeys } : snapshot.selectedKeys,
  }
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(PREFS_KEY, JSON.stringify(snapshot))
    }
  } catch {
    /* 存储不可用时本次会话内仍生效。 */
  }

  version += 1
  for (const listener of listeners) listener()
}

export function setSelectedKeysForCategory(category: string, keys: string[]) {
  const nextKeys = {
    ...snapshot.selectedKeys,
    [category]: [...new Set(keys)],
  }
  updateStatisticsPrefs({ selectedKeys: nextKeys })
}

export function getSelectedKeysForCategory(category: string, availableSeries: { key: string }[]): string[] {
  const saved = snapshot.selectedKeys[category]
  if (Array.isArray(saved) && saved.length > 0) {
    const valid = saved.filter(k => availableSeries.some(s => s.key === k))
    if (valid.length > 0) return valid
  }
  return []
}

/** 仅用于单元测试重置 snapshot 状态 */
export function resetStatisticsPrefsForTest() {
  snapshot = readStatisticsPrefs()
}
