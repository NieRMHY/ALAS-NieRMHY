/**
 * @fileoverview 插件上下文：加载已安装插件列表，维护启用状态、主题皮肤选择与插件 API 请求通道。
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { useConnection } from '../app/context'
import { syncThemeStyles } from './themeStyles'
import { pluginAsset, type InstalledPlugin } from './types'

/** 插件上下文对外暴露的状态与操作；组件一律通过 usePlugins() 读取。 */
interface PluginState {
  /** 已安装插件列表；未就绪或未登录时为空数组。 */
  plugins: InstalledPlugin[]
  /** 插件列表是否完成过一次成功加载。 */
  ready: boolean
  /** 最近一次加载失败的错误文案；正常为空字符串。 */
  error: string
  /** 重新向后端拉取插件列表。 */
  refresh: () => Promise<void>
  /** 以插件身份请求宿主后端接口，自动附带插件访问令牌。 */
  request: (path: string, options: RequestInit) => Promise<void>
  /** 当前启用且声明了主题皮肤、被选为皮肤源的插件。 */
  theme?: InstalledPlugin
  /** 持久化的皮肤插件 ID；空字符串表示使用内置外观。 */
  themeId: string
  /** 选择皮肤插件并写入 localStorage。 */
  setTheme: (id: string) => void
}

const initial: PluginState = {
  plugins: [], ready: false, error: '', themeId: '',
  refresh: async () => {}, request: async () => {}, setTheme: () => {},
}
const PluginContext = createContext(initial)
/** 读取插件上下文；未在 PluginProvider 之内调用时得到初始空状态。 */
export const usePlugins = () => useContext(PluginContext)

/**
 * 插件状态 Provider：连接就绪后拉取插件列表并监听后端变更事件。
 * 皮肤选择持久化在 localStorage，连接进入 auth 时清空已加载状态。
 */
export function PluginProvider({children}: {children: ReactNode}) {
  const connection = useConnection()
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [themeId, setSelectedTheme] = useState(() => {
    try { return localStorage.getItem('azurpilot.apu-theme') ?? '' } catch { return '' }
  })
  const requestId = useRef(0)
  const accept = useCallback((next: InstalledPlugin[]) => {
    setPlugins(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
    setReady(true)
    setError('')
  }, [])
  const refresh = useCallback(async () => {
    const id = ++requestId.current
    try {
      const result = await api.request('plugins.list', {})
      if (requestId.current === id) accept(result)
    } catch (failure) {
      if (requestId.current === id) setError((failure as Error).message)
    }
  }, [accept])
  useEffect(() => {
    if (connection === 'ready') void refresh()
    if (connection === 'auth') {setPlugins([]); setReady(false); setError('')}
    return () => { requestId.current++ }
  }, [connection, refresh])
  useEffect(() => api.onEvent(event => {
    if (event.topic === 'plugins') {
      requestId.current++
      accept(event.data as InstalledPlugin[])
    }
  }), [accept])
  const request = useCallback(async (path: string, options: RequestInit) => {
    const {token} = await api.request('plugins.access', {})
    const headers = new Headers(options.headers)
    headers.set('x-azurpilot-plugin-token', token)
    const response = await fetch('./api/v1/plugins' + path, {
      ...options, headers,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(payload.error || response.statusText)
    }
    await refresh()
  }, [refresh])
  const setTheme = useCallback((id: string) => {
    setSelectedTheme(id)
    try { localStorage.setItem('azurpilot.apu-theme', id) } catch { /* 保留会话选择。 */ }
  }, [])
  const theme = plugins.find(plugin => plugin.enabled && plugin.manifest.id === themeId && plugin.manifest.theme)
  const state = useMemo(() => ({plugins, ready, error, refresh, request, theme, themeId, setTheme}),
    [plugins, ready, error, refresh, request, theme, themeId, setTheme])
  return <PluginContext.Provider value={state}>{children}</PluginContext.Provider>
}

/** 将启用主题的样式表按槽位注入页面，并在插件列表就绪后接管 index.html 的预载记录。 */
export function PluginStyles() {
  const {theme, ready} = usePlugins()
  useEffect(() => {
    // Modify by MHY, 就绪前不动预载记录：登录前与加载中的 theme 为空，这时清缓存会抹掉
    // index.html 唯一能用的皮肤链接，下次刷新先闪一遍默认外观。
    syncThemeStyles(ready, theme)
  }, [ready, theme])
  if (!theme) return null
  return <>{Object.entries(theme.manifest.theme?.styles ?? {}).map(([component, path]) =>
    <link key={component} rel="stylesheet" href={pluginAsset(theme, path) + '?component=' + component}/>)}</>
}
