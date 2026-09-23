/**
 * 旧版实例页右列显示什么。
 *
 * `directory` —— 默认。任务设置页的锚点目录，点一下滚到对应的参数分组。
 * `scheduler` —— 调度器与任务计划，与新版右栏同一套内容。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 */
export type RailView = 'directory' | 'scheduler'

const VIEW_KEY = 'azurpilot.legacy-rail-view'

const listeners = new Set<() => void>()

export function readRailView(): RailView {
    try { return localStorage.getItem(VIEW_KEY) === 'scheduler' ? 'scheduler' : 'directory' } catch { return 'directory' }
}

export const subscribeRailView = (listener: () => void) => {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
}

export function setRailView(view: RailView) {
    try { localStorage.setItem(VIEW_KEY, view) } catch { /* 存储不可用时本次会话内仍生效。 */ }
    listeners.forEach(listener => listener())
}
