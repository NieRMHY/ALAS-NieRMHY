import type {Page} from '@playwright/test'
import type {Parameters} from '../src/api/generated'
import type {ApiResponse, Results} from '../src/api/types'

export function fleetAnalysisHash(instance: string, tab: 'data' | 'technology' | 'mind' | 'scan', shipId?: number) {
  return `#/i/${encodeURIComponent(instance)}/task/FleetAnalysis?tab=${tab}${shipId === undefined ? '' : `&ship=${shipId}`}`
}

/** Seed and inspect real backend state independently of the app's socket. */
export async function rpc<M extends keyof Parameters & keyof Results>(page: Page, method: M, params: Parameters[M]): Promise<Results[M]> {
  const result = await page.evaluate(({method, params}) => new Promise<unknown>((resolve, reject) => {
    const url = new URL('api/v1/ws', document.baseURI)
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(url)
    const fail = (message: string) => {
      clearTimeout(timer); socket.onclose = null; socket.close(); reject(new Error(message))
    }
    const timer = setTimeout(() => fail(`RPC timeout: ${method}`), 30000)
    socket.onopen = () => socket.send(JSON.stringify({v: 1, type: 'request', id: 'fleet-test', method, params}))
    socket.onmessage = event => {
      let response: ApiResponse
      try {response = JSON.parse(String(event.data))}
      catch {fail(`Invalid RPC response: ${method}`); return}
      if (response.type !== 'response' || response.id !== 'fleet-test') return
      clearTimeout(timer); socket.onclose = null; socket.close()
      response.ok ? resolve(response.result) : reject(new Error(response.error?.message ?? `RPC failed: ${method}`))
    }
    socket.onerror = () => fail(`RPC connection failed: ${method}`)
    socket.onclose = () => fail(`RPC closed before response: ${method}`)
  }), {method, params})
  return result as Results[M]
}
