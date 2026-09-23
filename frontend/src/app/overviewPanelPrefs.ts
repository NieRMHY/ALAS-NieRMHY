/**
 * 旧版总览页主区显示什么。
 *
 * `logs` —— 默认。实例的运行日志。
 * `stats` —— 资源统计，与统计页同一套内容。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 */
export type OverviewPanel = 'logs' | 'stats'

const PANEL_KEY = 'azurpilot.legacy-overview-panel'

const listeners = new Set<() => void>()

export function readOverviewPanel(): OverviewPanel {
    try { return localStorage.getItem(PANEL_KEY) === 'stats' ? 'stats' : 'logs' } catch { return 'logs' }
}

export const subscribeOverviewPanel = (listener: () => void) => {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
}

export function setOverviewPanel(panel: OverviewPanel) {
    try { localStorage.setItem(PANEL_KEY, panel) } catch { /* 存储不可用时本次会话内仍生效。 */ }
    listeners.forEach(listener => listener())
}
