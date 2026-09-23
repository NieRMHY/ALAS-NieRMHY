import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import { editor } from '../config/editors'
import { useConnection } from './context'

/**
 * 部署设置的取数与编辑队列。
 *
 * 三个设置页共用同一份逻辑与同一条 `deploy` 队列：队列按作用域取单例，
 * 页面切换不会丢掉未确认的输入。
 */
export function useDeploySettings() {
  const [data, setData] = useState<SettingsData>()
  const [error, setError] = useState('')
  const connection = useConnection()
  const queue = editor('deploy')
  const edits = useSyncExternalStore(queue.subscribe, queue.getSnapshot)

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const confirmed = queue.confirmed()
    void api.request('settings.get', {})
      .then(data => {
        if (active) {
          setData(data)
          setError('')
          queue.reconcile(confirmed)
        }
      })
      .catch(error => {
        if (active) setError(error.message)
      })
    return () => { active = false }
  }, [connection, queue])

  return {data, error, edits, queue}
}
