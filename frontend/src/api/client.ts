import type { Parameters } from './generated'
import type { ApiEvent, ApiResponse, Results } from './types'
import { translateCurrentUi } from '../i18n'

export class ApiError extends Error {
  constructor(public code: string, message: string, public details?: unknown) { super(message) }
}
export type Connection = 'connecting' | 'ready' | 'auth' | 'offline'
type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }

export class ApiClient {
  private socket?: WebSocket
  private pending = new Map<string, Pending>()
  private listeners = new Set<() => void>()
  private events = new Set<(event: ApiEvent) => void>()
  private retry?: ReturnType<typeof setTimeout>
  private heartbeat?: ReturnType<typeof setInterval>
  private password = ''
  private attempt = 0
  private stopped = true
  private state: Connection = 'connecting'
  private counter = 0
  private lastReceived = 0

  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  onEvent = (listener: (event: ApiEvent) => void) => { this.events.add(listener); return () => { this.events.delete(listener) } }
  private setState(state: Connection) { this.state = state; this.listeners.forEach(listener => listener()) }

  connect = () => {
    if (this.socket && this.socket.readyState < 2) return
    if (!this.password) { try { this.password = window.localStorage.getItem('azurpilot.access-password') ?? '' } catch { /* 浏览器禁用存储时保留会话登录。 */ } }
    this.stopped = false
    this.setState('connecting')
    // 远程访问隧道把页面挂在 /<peer_id>/ 前缀下（index.html 用 <base> 固定该前缀），
    // 绝对路径 /api/v1/ws 会打到隧道服务端而不是本机，必须跟着 document.baseURI 走。
    const url = new URL('api/v1/ws', document.baseURI)
    url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = this.socket = new WebSocket(url)
    socket.onmessage = event => {
      if (socket !== this.socket) return
      this.lastReceived = Date.now()
      let message: ApiResponse | ApiEvent
      try { message = JSON.parse(event.data) } catch { socket.close(1002); return }
      if (message.v !== 1) { socket.close(1002); return }
      if (message.type === 'response') {
        const pending = this.pending.get(message.id)
        if (!pending) return
        clearTimeout(pending.timer)
        this.pending.delete(message.id)
        if (message.ok) pending.resolve(message.result)
        else pending.reject(new ApiError(message.error?.code ?? 'UNKNOWN', message.error?.message ?? translateCurrentUi('api.requestFailed'), message.error?.details))
      } else if (message.type === 'event') {
        if (message.topic === 'session') {
          const data = message.data as {authRequired: boolean}
          if (!data.authRequired) this.ready()
          else if (this.password) void this.login(this.password).catch(() => this.setState('auth'))
          else this.setState('auth')
        }
        this.events.forEach(listener => listener(message as ApiEvent))
      }
    }
    socket.onclose = () => {
      if (socket !== this.socket) return
      clearInterval(this.heartbeat)
      this.pending.forEach(pending => {
        clearTimeout(pending.timer)
        pending.reject(new ApiError('DISCONNECTED', translateCurrentUi('api.disconnected')))
      })
      this.pending.clear()
      this.setState('offline')
      if (!this.stopped) this.retry = setTimeout(this.connect, Math.min(15000, 800 * 2 ** this.attempt++) + Math.random() * 400)
    }
    socket.onerror = () => socket.close()
  }

  private ready() {
    this.attempt = 0
    this.setState('ready')
    clearInterval(this.heartbeat)
    this.heartbeat = setInterval(() => {
      if (Date.now() - this.lastReceived > 45000) { this.socket?.close(); return }
      void this.request('system.ping', {}).catch(() => this.socket?.close())
    }, 15000)
  }

  async login(password: string) {
    try { await this.request('auth.login', {password}) } catch (error) {
      if (error instanceof ApiError && error.code === 'UNAUTHORIZED') {
        this.password = ''
        try { window.localStorage.removeItem('azurpilot.access-password') } catch { /* 存储不可用。 */ }
      }
      throw error
    }
    try { window.localStorage.setItem('azurpilot.access-password', password) } catch { /* 存储不可用时仍允许登录。 */ }
    this.password = password
    this.ready()
  }

  request<M extends keyof Results & keyof Parameters>(method: M, params: Parameters[M]): Promise<Results[M]> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || (this.state !== 'ready' && method !== 'auth.login')) {
      return Promise.reject(new ApiError('DISCONNECTED', translateCurrentUi('api.notConnected')))
    }
    const id = `${Date.now()}-${++this.counter}`
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new ApiError('TIMEOUT', translateCurrentUi('api.timeout')))
      }, 45000)
      this.pending.set(id, {resolve: value => resolve(value as Results[M]), reject, timer})
      this.socket!.send(JSON.stringify({v: 1, type: 'request', id, method, params}))
    })
  }

  disconnect() {
    this.stopped = true
    this.password = ''
    clearTimeout(this.retry)
    clearInterval(this.heartbeat)
    this.socket?.close()
  }
}

export const api = new ApiClient()
