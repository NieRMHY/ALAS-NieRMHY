import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UpdateStatus } from '../api/types'
import { useConnection } from './context'

export function useUpdater() {
  const connection = useConnection()
  const [data, setData] = useState<UpdateStatus>()
  const [error, setError] = useState('')
  const [generation, setGeneration] = useState(0)
  const refresh = useCallback(() => setGeneration(value => value + 1), [])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const value = await api.request('updater.status', {})
        if (active) {setData(value); setError('')}
      } catch (error) {if (active) setError((error as Error).message)}
      if (active) timer = setTimeout(poll, 3000)
    }
    void poll()
    return () => {active = false; clearTimeout(timer)}
  }, [connection, generation])
  return {data, error, refresh}
}

export type UpdaterState = ReturnType<typeof useUpdater>
