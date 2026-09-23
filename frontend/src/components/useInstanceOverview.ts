import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'

/**
 * 订阅实例总览数据：连上后拉取一次，之后由 overview 事件增量刷新。
 *
 * 右栏（调度器 + 任务计划）用它取数；总览页自己取一份并传给页内左列，
 * 免得同一个页面上请求两次。`enabled` 为假时完全不请求。
 */
export function useInstanceOverview(instance: string, enabled = true) {
  const connection = useConnection()
  const {notify} = useApp()
  const [data, setData] = useState<Overview>()

  useEffect(() => {
    if (!enabled || connection !== 'ready') return
    let active = true
    void api.request('overview.get', {instance})
      .then(value => { if (active) setData(value) })
      .catch(error => notify((error as Error).message, true))
    return () => { active = false }
  }, [connection, instance, notify, enabled])

  useEffect(() => {
    if (!enabled) return
    return api.onEvent(event => {
      if (event.topic !== 'overview') return
      const next = event.data as Overview
      if (next.instance === instance) setData(next)
    })
  }, [instance, enabled])

  return [data, setData] as const
}
