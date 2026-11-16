/**
 * @fileoverview 统一分发 WebUI RPC：操作连接的状态驱动登录界面，数据连接独立恢复。
 */

import {dataMethods, webSocketTransport, type Parameters} from './generated'
import {ApiError, RpcSocket} from './socket'
import type {ApiEvent, Results} from './types'

export {ApiError} from './socket'

const dataRequests = new Set<string>(dataMethods)
const dataTopics = new Set<string>(webSocketTransport.dataTopics)
// Add by MHY, 旧后端参数枚举没有插件主题，订阅前需裁剪。
const pluginTopics = new Set<string>(['plugins'])
type Subscription = Parameters['events.subscribe']

/**
 * WebUI 的统一 RPC 客户端：按方法把请求分发到操作、数据两条连接，并把事件广播给订阅者。
 *
 * 操作连接的状态（getSnapshot）驱动登录界面；数据连接断开后独立恢复，
 * 读取类请求在数据连接重连成功后自动重试一次。旧后端不返回 channel 时
 * 自动退回单连接模式，所有请求仍走操作连接。
 */
export class ApiClient {
  private password = ''
  private events = new Set<(event: ApiEvent) => void>()
  private dataSubscription?: Subscription
  private emit = (event: ApiEvent) => this.events.forEach(listener => listener(event))

  private data = new RpcSocket('data', session => {
    if (!session.authRequired) return
    if (!this.password) throw new Error('Missing data connection credentials')
    return this.data.request<void>('auth.login', {password: this.password})
  }, event => {
    if (event.topic !== 'session') this.emit(event)
  }, () => this.subscribeData())

  private control = new RpcSocket('control', (session, current) => {
    if (!session.authRequired) return
    if (!this.password) throw new Error('Missing access password')
    return this.authenticate(this.password, current)
  }, this.emit, () => {
    if (!this.control.splitTransport) {
      this.data.disconnect()
      return
    }
    if (this.data.getSnapshot() === 'auth') this.data.disconnect()
    this.data.connect()
  })

  getSnapshot = this.control.getSnapshot
  subscribe = this.control.subscribe
  /** 订阅事件广播；返回取消订阅函数。 */
  onEvent = (listener: (event: ApiEvent) => void) => {
    this.events.add(listener)
    return () => { this.events.delete(listener) }
  }

  /** 恢复本地保存的密码并接通连接；存储不可用时仍走会话内登录。 */
  connect = () => {
    if (!this.password) {
      try { this.password = window.localStorage.getItem('azurpilot.access-password') ?? '' }
      catch { /* 浏览器禁用存储时保留会话登录。 */ }
    }
    this.control.connect()
  }

  private async authenticate(password: string, current = () => true) {
    try { await this.control.request('auth.login', {password}) }
    catch (error) {
      if (current() && error instanceof ApiError && error.code === 'UNAUTHORIZED') {
        this.password = ''
        try { window.localStorage.removeItem('azurpilot.access-password') } catch { /* 存储不可用。 */ }
      }
      throw error
    }
    if (current()) {
      this.password = password
      try { window.localStorage.setItem('azurpilot.access-password', password) } catch { /* 保留会话登录。 */ }
    }
  }

  /** 用密码认证并把操作连接置为就绪；认证成功后密码写入 localStorage 供下次自动恢复。 */
  async login(password: string) {
    await this.authenticate(password)
    this.control.ready()
  }

  private subscribeData() {
    const subscription = this.dataSubscription
    if (!subscription || this.data.getSnapshot() !== 'ready') return
    void this.data.request('events.subscribe', subscription).catch(error => {
      if (this.dataSubscription !== subscription || this.data.getSnapshot() !== 'ready') return
      for (const topic of subscription.topics) {
        this.emit({v: 1, type: 'event', seq: 0, topic: 'subscription.error', data: {
          topic, instance: subscription.instance, code: error.code, message: error.message,
        }})
      }
    })
  }

  private async subscribeEvents(params: Subscription): Promise<Results['events.subscribe']> {
    const result = await this.control.request<Results['events.subscribe']>('events.subscribe', {
      instance: params.instance, topics: params.topics.filter(topic => !dataTopics.has(topic)),
    })
    this.dataSubscription = {instance: params.instance, topics: params.topics.filter(topic => dataTopics.has(topic))}
    this.subscribeData()
    return {...result, topics: params.topics}
  }

  /**
   * Modify by MHY, 按会话协商出的传输能力裁剪订阅主题。
   *
   * 旧后端 hello 不带 channel，客户端因此退回单连接；它的 SubscribeParams 也只认单通道
   * 那套主题，原样带过去一个 plugins 就让整条 events.subscribe 判 INVALID_PARAMS，
   * 通知、实例与总览事件会一起丢。hello 声明了 channel 的后端才认识插件主题。
   */
  private subscriptionParams(params: Subscription): Subscription {
    if (this.control.splitTransport) return params
    return {...params, topics: params.topics.filter(topic => !pluginTopics.has(topic))}
  }

  private async requestData<T>(method: string, params: unknown): Promise<T> {
    await this.data.waitReady()
    try { return await this.data.request<T>(method, params) }
    catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'DISCONNECTED') throw error
      // 数据通道只处理读取，重连后可以重试一次。写操作始终由调用方决定是否重试。
      await this.data.waitReady()
      return this.data.request<T>(method, params)
    }
  }

  request<M extends keyof Results & keyof Parameters>(method: M, params: Parameters[M]): Promise<Results[M]> {
    if (method === 'events.subscribe') {
      const subscription = this.subscriptionParams(params as Subscription)
      return this.control.splitTransport
        ? this.subscribeEvents(subscription) as Promise<Results[M]>
        : this.control.request<Results[M]>(method, subscription)
    }
    if (this.control.splitTransport && dataRequests.has(method)) {
      return this.requestData<Results[M]>(method, params)
    }
    return this.control.request<Results[M]>(method, params)
  }

  disconnect() {
    this.password = ''
    this.dataSubscription = undefined
    this.data.disconnect()
    this.control.disconnect()
  }
}

/** 全局唯一实例：整个前端直接 import 使用，不自行 new。 */
export const api = new ApiClient()
