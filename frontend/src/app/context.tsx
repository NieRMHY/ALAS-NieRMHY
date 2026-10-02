/**
 * @fileoverview 全局 React 上下文提供者，统合实例、配置架构、语言和主题状态。
 */

import { createContext, useCallback, useMemo, useContext, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Instance, Schema } from '../api/types'
import type { Parameters } from '../api/generated'
import { resumeEditors } from '../config/editors'
import { detectLanguage, isLanguage, languages, localeForLanguage, translateUi, type Language, type UiTranslator } from '../i18n'
import { readDevMode, writeDevMode } from './devMode'
import { applyTheme, getThemePreference, subscribeTheme, type Theme, type Palette, type ColorMode, type CustomPalette, type CompactRailSide, type CompactRailWidth, type Material } from './theme'
import type { ResolvedMode } from './palettes'

export { languages }

type SchemaLanguage = NonNullable<Parameters['schema.get']['language']>
const _languageCompatibility: Record<Language, SchemaLanguage> = {
  'zh-CN': 'zh-CN', 'zh-TW': 'zh-TW', 'en-US': 'en-US', 'ja-JP': 'ja-JP', 'zh-MIAO': 'zh-MIAO',
}
void _languageCompatibility

export interface AppContextValue {
  instancesLoaded: boolean; instances: Instance[]; schema?: Schema; refresh: () => Promise<void>; t: (key: string) => string; ui: UiTranslator
  notify: (message: string, error?: boolean) => void
  previewEnabled: boolean; setPreviewEnabled: (enabled: boolean) => void
  devMode: boolean; setDevMode: (enabled: boolean) => void
  theme: Theme; setTheme: (theme: Theme, colorMode?: ColorMode) => void
  material: Material; setMaterial: (material: Material) => void
  palette: Palette; setPalette: (palette: Palette) => void
  colorMode: ColorMode; resolvedMode: ResolvedMode; setColorMode: (mode: ColorMode) => void
  customPalettes: CustomPalette[]; saveCustomPalette: (palette: CustomPalette) => void; deleteCustomPalette: (id: CustomPalette['id']) => void
  compactRailSide: CompactRailSide; setCompactRailSide: (side: CompactRailSide) => void
  compactRailWidth: CompactRailWidth; setCompactRailWidth: (width: CompactRailWidth) => void
  language: Language; setLanguage: (language: Language) => void
}
export const AppContext = createContext<AppContextValue | null>(null)
const Context = AppContext
export const useConnection = () => useSyncExternalStore(api.subscribe, api.getSnapshot)
export const useApp = () => useContext(AppContext)!

function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem('azurpilot.language')
    if (isLanguage(saved)) return saved
  } catch { /* 浏览器禁用存储时使用浏览器语言。 */ }
  return detectLanguage()
}

export function AppProvider({children}: {children: ReactNode}) {
  const connection = useConnection()
  const [instances, setInstances] = useState<Instance[]>([])
  const [instancesLoaded, setInstancesLoaded] = useState(false)
  const [schema, setSchema] = useState<Schema>()
  const [previewEnabled, setPreviewEnabled] = useState(false)
  const [devMode, setDevMode] = useState(readDevMode)
  const {theme, palette, colorMode, resolvedMode, customPalettes, compactRailSide, compactRailWidth, material} = useSyncExternalStore(subscribeTheme, getThemePreference)
  const [language, setLanguage] = useState<Language>(initialLanguage)
  const [toast, setToast] = useState<{message: string; error: boolean}>()
  /* 这八个 setter 只在调用时读 getThemePreference()，不依赖渲染期的值。 */
  const setTheme = useCallback((theme: Theme, colorMode?: ColorMode) => { void applyTheme({...getThemePreference(), theme, ...(colorMode && {colorMode})}).catch(() => setToast({message: '主题加载失败，请重试。', error: true})) }, [])
  const setPalette = useCallback((palette: Palette) => { void applyTheme({...getThemePreference(), palette}).catch(() => setToast({message: '配色加载失败，请重试。', error: true})) }, [])
  const setColorMode = useCallback((colorMode: ColorMode) => { void applyTheme({...getThemePreference(), colorMode}).catch(() => setToast({message: '模式切换失败，请重试。', error: true})) }, [])
  const setMaterial = useCallback((material: Material) => { void applyTheme({...getThemePreference(), material}).catch(() => setToast({message: '主题加载失败，请重试。', error: true})) }, [])
  const setCompactRailSide = useCallback((compactRailSide: CompactRailSide) => { void applyTheme({...getThemePreference(), compactRailSide}).catch(() => setToast({message: '布局切换失败，请重试。', error: true})) }, [])
  const setCompactRailWidth = useCallback((compactRailWidth: CompactRailWidth) => { void applyTheme({...getThemePreference(), compactRailWidth}).catch(() => setToast({message: '布局切换失败，请重试。', error: true})) }, [])
  const saveCustomPalette = useCallback((item: CustomPalette) => {
    const current = getThemePreference()
    const customPalettes = current.customPalettes.some(palette => palette.id === item.id)
      ? current.customPalettes.map(palette => palette.id === item.id ? item : palette) : [...current.customPalettes, item]
    void applyTheme({...current, customPalettes, palette: item.id}).catch(() => setToast({message: '配色保存失败，请重试。', error: true}))
  }, [])
  const deleteCustomPalette = useCallback((id: CustomPalette['id']) => {
    const current = getThemePreference()
    void applyTheme({...current, customPalettes: current.customPalettes.filter(item => item.id !== id), palette: current.palette === id ? 'ocean' : current.palette})
      .catch(() => setToast({message: '配色删除失败，请重试。', error: true}))
  }, [])
  useEffect(() => { writeDevMode(devMode) }, [devMode])
  useEffect(() => {
    document.documentElement.lang = localeForLanguage(language)
    try { localStorage.setItem('azurpilot.language', language) } catch { /* 存储不可用时仅当前会话生效。 */ }
  }, [language])
  useEffect(() => { api.connect(); return () => api.disconnect() }, [])
  useEffect(() => { if (connection === 'ready') resumeEditors() }, [connection])
  const notify = useCallback((message: string, error = false) => setToast({message, error}), [])
  const refresh = useCallback(async () => setInstances(await api.request('instances.list', {})), [])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    void api.request('instances.list', {}).then(instances => {
      if (active) {setInstances(instances); setInstancesLoaded(true)}
    }).catch(error => notify(error.message, true))
    return () => { active = false }
  }, [connection, notify])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    void api.request('schema.get', {language}).then(schema => {
      if (active) {
        setSchema(schema)
      }
    }).catch(error => {if (active) notify(error.message, true)})
    return () => {active = false}
  }, [connection, language, notify])
  useEffect(() => api.onEvent(event => {
    if (event.topic !== 'instances') return
    const next = event.data as Instance[]
    /* 后端每 2s 推一次快照；内容没变就留住旧引用，避免整棵消费树跟着重渲染。 */
    setInstances(previous => JSON.stringify(previous) === JSON.stringify(next) ? previous : next)
  }), [])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(undefined), 6000)
    return () => clearTimeout(timer)
  }, [toast])
  const t = useCallback((key: string) => {
    let value: unknown = schema?.translations
    for (const part of key.split('.')) value = value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined
    return typeof value === 'string' && value !== key ? value : key.split('.').filter(item => item !== 'name' && item !== '_info').at(-1) ?? key
  }, [schema])
  const ui = useCallback<UiTranslator>((key, params) => translateUi(language, key, params), [language])
  /* value 固定身份：provider 因 toast、连接状态等无关状态重渲染时，消费点不跟着重渲染。 */
  const value = useMemo(() => ({instancesLoaded, instances, schema, refresh, t, ui, notify, previewEnabled, setPreviewEnabled, devMode, setDevMode, theme, setTheme, material, setMaterial, palette, setPalette, colorMode, resolvedMode, setColorMode, customPalettes, saveCustomPalette, deleteCustomPalette, compactRailSide, setCompactRailSide, compactRailWidth, setCompactRailWidth, language, setLanguage}),
    [instancesLoaded, instances, schema, refresh, t, ui, notify, previewEnabled, setPreviewEnabled, devMode, setDevMode, theme, setTheme, material, setMaterial, palette, setPalette, colorMode, resolvedMode, setColorMode, customPalettes, saveCustomPalette, deleteCustomPalette, compactRailSide, setCompactRailSide, compactRailWidth, setCompactRailWidth, language, setLanguage])
  return <Context.Provider value={value}>
    {children}
    {toast && <div role={toast.error ? 'alert' : 'status'} className={`toast ${toast.error ? 'error' : ''}`} onClick={() => setToast(undefined)}>{toast.message}</div>}
  </Context.Provider>
}
