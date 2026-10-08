import { once } from 'node:events'
import { createServer } from 'node:http'
import { WebSocket } from 'ws'
import { expect, it, vi } from 'vitest'
import { createMockServer } from './server.mjs'

it('WebSocket 认证、实例订阅替换与空订阅按协议工作', async () => {
  const mock = createMockServer({password: 'mock-password'})
  mock.server.listen(0, '127.0.0.1')
  await once(mock.server, 'listening')
  const port = mock.server.address().port
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/v1/ws`, {origin: `http://127.0.0.1:${port}`})
  const events = []
  const pending = new Map()
  let counter = 0
  socket.on('message', raw => {
    const message = JSON.parse(raw.toString())
    if (message.type === 'event') events.push(message)
    else {pending.get(message.id)?.(message); pending.delete(message.id)}
  })
  const request = (method, params = {}) => new Promise(resolve => {
    const id = String(++counter)
    pending.set(id, resolve)
    socket.send(JSON.stringify({v: 1, type: 'request', id, method, params}))
  })
  try {
    await once(socket, 'open')
    expect((await request('instances.list')).error.code).toBe('UNAUTHORIZED')
    expect(events[0].data.authRequired).toBe(true)
    expect((await request('auth.login', {password: 'wrong'})).ok).toBe(false)
    expect((await request('auth.login', {password: 'mock-password'})).ok).toBe(true)
    await request('events.subscribe', {instance: 'demo-main', topics: ['instances', 'overview']})
    await request('system.ping')
    expect(events.filter(event => event.topic === 'overview').at(-1).data.instance).toBe('demo-main')
    await request('events.subscribe', {instance: 'demo-alt', topics: ['overview']})
    await request('system.ping')
    expect(events.filter(event => event.topic === 'overview').at(-1).data.instance).toBe('demo-alt')
    await request('events.subscribe', {topics: []})
    const length = events.length
    await request('scheduler.start', {instance: 'demo-main'})
    await request('system.ping')
    expect(events).toHaveLength(length)
    expect(events.map(event => event.seq)).toEqual(events.map((_, index) => index + 1))
  } finally {socket.terminate(); await mock.close()}
})

it('交易所上游断连与无效响应按代理错误返回，恢复后可继续请求', async () => {
  let mode = 'invalid'
  const upstream = createServer((_request, response) => {
    if (mode === 'invalid') {response.end('<html>服务暂不可用</html>'); return}
    response.setHeader('Content-Type', 'application/json')
    response.setHeader('ETag', 'mock-market')
    if (mode === 'cached') {response.writeHead(304); response.end(); return}
    if (mode === 'rejected') {
      response.writeHead(401)
      response.end(JSON.stringify({error: {code: 'UNAUTHORIZED', message: '请先登录'}}))
      return
    }
    response.end(JSON.stringify({mock: true}))
  })
  upstream.listen(0, '127.0.0.1')
  await once(upstream, 'listening')
  const upstreamPort = upstream.address().port
  await new Promise(resolve => upstream.close(resolve))
  vi.stubEnv('STOCK_EXCHANGE_URL', `http://127.0.0.1:${upstreamPort}`)
  const mock = createMockServer()
  mock.server.listen(0, '127.0.0.1')
  await once(mock.server, 'listening')
  const port = mock.server.address().port
  const socket = new WebSocket(`ws://127.0.0.1:${port}/api/v1/ws`, {origin: `http://127.0.0.1:${port}`})
  const pending = new Map()
  let counter = 0
  socket.on('message', raw => {
    const message = JSON.parse(raw.toString())
    if (message.type === 'response') {pending.get(message.id)?.(message); pending.delete(message.id)}
  })
  const request = (params = {}) => new Promise(resolve => {
    const id = String(++counter)
    pending.set(id, resolve)
    socket.send(JSON.stringify({v: 1, type: 'request', id, method: 'stock.request', params: {instance: 'demo-main', path: '/meta', ...params}}))
  })
  try {
    await once(socket, 'open')
    const unavailable = await request()
    expect(unavailable.ok).toBe(false)
    expect(unavailable.error.code).toBe('STOCK_UNAVAILABLE')
    expect(unavailable.error.message).toContain('AzurPilot_StockExchange')
    expect(unavailable.error.message).toContain('npm run dev:mock --prefix frontend')
    upstream.listen(upstreamPort, '127.0.0.1')
    await once(upstream, 'listening')
    const invalid = await request()
    expect(invalid.ok).toBe(false)
    expect(invalid.error.code).toBe('STOCK_INVALID_RESPONSE')
    mode = 'valid'
    const recovered = await request()
    expect(recovered.ok).toBe(true)
    expect(recovered.result).toMatchObject({status: 200, data: {mock: true}, etag: 'mock-market'})
    expect(recovered.result.serverTime).toBeGreaterThan(0)
    mode = 'cached'
    expect((await request({path: '/market', etag: 'mock-market'})).result).toMatchObject({status: 304, data: null, etag: 'mock-market'})
    mode = 'rejected'
    const rejected = await request()
    expect(rejected.ok).toBe(true)
    expect(rejected.result).toMatchObject({status: 401, data: {error: {code: 'UNAUTHORIZED', message: '请先登录'}}})
    expect((await request({method: 'PUT'})).error.code).toBe('INVALID_PARAMS')
  } finally {
    socket.terminate()
    await mock.close()
    await new Promise(resolve => upstream.close(resolve))
    vi.unstubAllEnvs()
  }
})
