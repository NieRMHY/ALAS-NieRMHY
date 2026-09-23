import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiClient } from './client'

class FakeSocket {
  static OPEN = 1
  static latest: FakeSocket
  readyState = 1
  onmessage?: (event: {data: string}) => void
  onclose?: () => void
  sent: Record<string, unknown>[] = []
  url: string
  constructor(url: string | URL) {FakeSocket.latest = this; this.url = String(url)}
  send(message: string) {this.sent.push(JSON.parse(message))}
  close() {this.readyState = 3; this.onclose?.()}
  emit(message: unknown) {this.onmessage?.({data: JSON.stringify(message)})}
}

describe('WebSocket 客户端', () => {
  let client: ApiClient
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('window', {location: {href: 'http://localhost:5173/', protocol: 'http:'}})
    vi.stubGlobal('document', {baseURI: 'http://localhost:5173/'})
    vi.stubGlobal('WebSocket', FakeSocket)
    client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: false}})
  })
  afterEach(() => {client.disconnect(); vi.useRealTimers(); vi.unstubAllGlobals()})
  it('乱序响应按请求 ID 关联', async () => {
    const first = client.request('system.ping', {})
    const second = client.request('instances.list', {})
    const socket = FakeSocket.latest
    socket.emit({v: 1, type: 'response', id: socket.sent[1].id, ok: true, result: []})
    socket.emit({v: 1, type: 'response', id: socket.sent[0].id, ok: true, result: {pong: true}})
    expect(await first).toEqual({pong: true}); expect(await second).toEqual([])
  })
  it('断线拒绝未完成请求，不自动重复写操作', async () => {
    const request = client.request('instances.create', {name: 'pilot'})
    const rejection = expect(request).rejects.toMatchObject({code: 'DISCONNECTED'})
    FakeSocket.latest.close(); await rejection
    await vi.advanceTimersByTimeAsync(2000)
    expect(FakeSocket.latest.sent).toEqual([])
  })
  it('请求超时后清理等待项', async () => {
    const request = client.request('system.ping', {})
    const rejection = expect(request).rejects.toMatchObject({code: 'TIMEOUT'})
    await vi.advanceTimersByTimeAsync(45000); await rejection
  })
  it('认证完成前不发送业务请求', async () => {
    client.disconnect(); client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: true}})
    await expect(client.request('instances.list', {})).rejects.toMatchObject({code: 'DISCONNECTED'})
    expect(FakeSocket.latest.sent).toHaveLength(0)
  })
  it('WebSocket 地址跟随 document.baseURI，远程访问隧道前缀不丢', () => {
    // 地址与 peer_id 都是占位符，不要填真实隧道。
    vi.stubGlobal('window', {location: {href: 'https://tunnel.example.com/example-peer-id/', protocol: 'https:'}})
    vi.stubGlobal('document', {baseURI: 'https://tunnel.example.com/example-peer-id/'})
    client.disconnect(); client = new ApiClient(); client.connect()
    expect(FakeSocket.latest.url).toBe('wss://tunnel.example.com/example-peer-id/api/v1/ws')
  })
  it('保留校验失败的诊断详情供脚本编辑器定位行列', async () => {
    const request = client.request('system.ping', {})
    const rejection = expect(request).rejects.toMatchObject({
      code: 'INVALID_PARAMS', details: [{message: '不允许调用 os.execute', line: 4, column: 12}],
    })
    const sent = FakeSocket.latest.sent.at(-1)!
    FakeSocket.latest.emit({v: 1, type: 'response', id: sent.id, ok: false, error: {
      code: 'INVALID_PARAMS', message: '策略校验失败', details: [{message: '不允许调用 os.execute', line: 4, column: 12}],
    }})
    await rejection
  })
  it('刷新后用已保存的密码登录，密码失效时清除旧值', async () => {
    const values = new Map<string, string>()
    Object.assign(window, {localStorage: {getItem: (key: string) => values.get(key), setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key)}})
    const login = client.login('测试访问密码')
    FakeSocket.latest.emit({v: 1, type: 'response', id: FakeSocket.latest.sent.at(-1)!.id, ok: true, result: {authenticated: true}})
    await login
    client.disconnect(); client = new ApiClient(); client.connect()
    FakeSocket.latest.emit({v: 1, type: 'event', topic: 'session', seq: 1, data: {authRequired: true}})
    expect(FakeSocket.latest.sent.at(-1)).toMatchObject({method: 'auth.login', params: {password: '测试访问密码'}})
    FakeSocket.latest.emit({v: 1, type: 'response', id: FakeSocket.latest.sent.at(-1)!.id, ok: false, error: {code: 'UNAUTHORIZED', message: '密码已更换'}})
    await vi.advanceTimersByTimeAsync(0)
    expect(client.getSnapshot()).toBe('auth')
    expect(values.size).toBe(0)
  })
})
