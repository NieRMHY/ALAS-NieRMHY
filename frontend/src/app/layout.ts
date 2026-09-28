/** 收起/看图模式的界面状态：侧栏收起（全页面有效）与主页卡片收起（页面级）。
 *
 * 侧栏状态要跨页面共享（人在总览页收起，切到别的页面仍该是收起的），
 * 两个收起状态都持久化；侧栏状态跨页面共享，故放在模块级。
 */
const SIDEBAR_KEY = 'azurpilot.layout.sidebar'
const HOME_KEY = 'azurpilot.layout.home'

export interface LayoutState {
  /** 侧栏是否收起：全页面有效。 */
  sidebarCollapsed: boolean
  /** 主页「实例 + 公告」两张卡片是否收起：只影响主页，与侧栏互不干扰。 */
  homeHidden: boolean
}

const read = (key: string) => {
  try { return localStorage.getItem(key) === '1' } catch { return false }
}

let state: LayoutState = {sidebarCollapsed: read(SIDEBAR_KEY), homeHidden: read(HOME_KEY)}
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
    localStorage.setItem(HOME_KEY, state.homeHidden ? '1' : '0')
  } catch { /* 存储不可用时只在本次会话生效，不影响使用。 */ }
  listeners.forEach(listener => listener())
}

export const setSidebarCollapsed = (value: boolean) => publish({sidebarCollapsed: value})
export const toggleSidebar = () => publish({sidebarCollapsed: !state.sidebarCollapsed})
export const setHomeHidden = (value: boolean) => publish({homeHidden: value})
export const toggleHomeHidden = () => publish({homeHidden: !state.homeHidden})
