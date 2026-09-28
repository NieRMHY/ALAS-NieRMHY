/**
 * @fileoverview 统计页面单分类内容区组件。
 */

import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import { useConnection } from '../app/context'
import type { StatisticsCategory } from '../app/statisticsPrefs'

/** 单个页面的取数参数，与该页在布局文档里保存的一致。 */
export interface CategoryParams {
  instance: string
  category: StatisticsCategory
  days: number
  month: string
  period: 'day' | 'week' | 'month'
  researchSeries: string
  lootTask: string
}

/** 一段页面的内容区：自己取数、自己订阅统计事件，数据与渲染都交给调用方。 */
export function CategorySection({params, revision, onState, render}: {
  params: CategoryParams
  revision: number
  onState?: (state: {data?: StatisticsReport; error: string}) => void
  render: (data: StatisticsReport | undefined, error: string, page: StatisticsCategory) => ReactNode
}) {
  const {instance, category, days, month, period, researchSeries, lootTask} = params
  const researchScope = researchSeries === 'consumable' ? researchSeries : 'series'
  const connection = useConnection()
  const [data, setData] = useState<StatisticsReport>()
  const [error, setError] = useState('')

  const request = useCallback(() => api.request('statistics.report', {
    instance, category, days, month, period,
    series: researchScope === 'series' ? Number(researchSeries) : 0,
    scope: researchScope,
    task: lootTask || null,
  }), [instance, category, days, month, period, researchScope, researchSeries, lootTask])

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setData(undefined); setError('')
    void request().then(value => {if (active) setData(value)}).catch(reason => {if (active) setError(reason.message)})
    return () => {active = false}
  }, [connection, request, revision])

  /* 静默更新：后端数据更新推送到前端时平滑更新图表与指标，避免 Loading 闪烁。 */
  const silentRefresh = useCallback(() => {
    if (connection !== 'ready') return
    void request().then(value => setData(value)).catch(() => {
      /* 静默更新失败时不影响当前已展示视图。 */
    })
  }, [connection, request])

  useEffect(() => {
    if (connection !== 'ready') return
    let timer: ReturnType<typeof setTimeout> | undefined
    const triggerUpdate = () => {
      clearTimeout(timer)
      timer = setTimeout(silentRefresh, 300)
    }
    const off = api.onEvent(event => {
      const payload = event.data as {instance?: string} | undefined
      if (event.topic === 'statistics') {
        if (!payload?.instance || payload.instance === instance) triggerUpdate()
      } else if (event.topic === 'overview' && payload?.instance === instance) {
        triggerUpdate()
      }
    })
    return () => {
      clearTimeout(timer)
      off()
    }
  }, [connection, instance, silentRefresh])

  useEffect(() => onState?.({data, error}), [data, error, onState])

  return <>{render(data, error, category)}</>
}
