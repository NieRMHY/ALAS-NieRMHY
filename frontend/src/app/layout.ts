/**
 * @fileoverview 侧栏收起（看图模式）的界面状态：全页面共享、持久化。
 */

const SIDEBAR_KEY = 'azurpilot.layout.sidebar'

const read = (key: string) => {
  try { return localStorage.getItem(key) === '1' } catch { return false }
}

export interface LayoutState {
  /** 侧栏是否收起：全页面有效。 */
  sidebarCollapsed: boolean
}

let state: LayoutState = {sidebarCollapsed: read(SIDEBAR_KEY)}
const listeners = new Set<() => void>()

export const getLayout = () => state

export function subscribeLayout(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(patch: Partial<LayoutState>) {
  state = {...state, ...patch}
  try {
    localStorage.setItem(SIDEBAR_KEY, state.sidebarCollapsed ? '1' : '0')
  } catch { /* 存储不可用时只在本次会话生效，不影响使用。 */ }
  listeners.forEach(listener => listener())
}

export const setSidebarCollapsed = (value: boolean) => publish({sidebarCollapsed: value})
