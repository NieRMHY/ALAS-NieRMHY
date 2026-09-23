/**
 * 顶栏怎么呈现实例。
 *
 * `dropdown` —— 默认。实例藏在「主页 / 实例 ▾」的下拉里，顶栏只有一个名字。
 * `tabs`     —— 所有实例平铺在顶栏上，像浏览器分页，一处看全运行状态。
 *
 * 与「上次停留的实例」存在一起：两者都是「关掉再打开要接着上次」的界面偏好。
 */
export type TopbarMode = 'dropdown' | 'tabs'

/** 标签页的档位。顶栏高度是各主题自己定的，所以缩放的落点放在标签页自己身上。
    五档由小到大：最小 → 小 → 中 → 大 → 最大。 */
export type TabSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

const MODE_KEY = 'azurpilot.topbar-mode'
const TAB_SIZE_KEY = 'azurpilot.topbar-tab-size'
const LAST_INSTANCE_KEY = 'azurpilot.last-instance'
const LAST_PATH_KEY = 'azurpilot.last-path'

/** 点一下循环一档：最小 → 小 → 中 → 大 → 最大 → 回到最小。 */
const TAB_SIZE_ORDER: readonly TabSize[] = ['xs', 'sm', 'md', 'lg', 'xl']

/** 档位要落在 :root 上：顶栏高度与标签页尺寸都由这一处驱动。 */
function applyTabSize(size: TabSize) {
    document.documentElement.dataset.tabSize = size
}

/* 模块加载即落一次，让存下来的档位在首帧就生效，不必等用户点按钮。 */
applyTabSize(readTabSize())

const listeners = new Set<() => void>()

export function readTopbarMode(): TopbarMode {
    try { return localStorage.getItem(MODE_KEY) === 'tabs' ? 'tabs' : 'dropdown' } catch { return 'dropdown' }
}

export function readTabSize(): TabSize {
    try {
        const stored = localStorage.getItem(TAB_SIZE_KEY)
        return TAB_SIZE_ORDER.find(size => size === stored) ?? 'md'
    } catch { return 'md' }
}

export const subscribeTopbarMode = (listener: () => void) => {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
}

export function setTopbarMode(mode: TopbarMode) {
    try { localStorage.setItem(MODE_KEY, mode) } catch { /* 存储不可用时本次会话内仍生效。 */ }
    listeners.forEach(listener => listener())
}

export function cycleTabSize(size: TabSize): TabSize {
    const next = TAB_SIZE_ORDER[(TAB_SIZE_ORDER.indexOf(size) + 1) % TAB_SIZE_ORDER.length]
    applyTabSize(next)
    try { localStorage.setItem(TAB_SIZE_KEY, next) } catch { /* 存储不可用时本次会话内仍生效。 */ }
    listeners.forEach(listener => listener())
    return next
}

/** 上次停留的实例名。关掉再打开时用它回到原处；实例已被删除则由调用方忽略。 */
export function readLastInstance(): string {
    try { return localStorage.getItem(LAST_INSTANCE_KEY) ?? '' } catch { return '' }
}

export function writeLastInstance(name: string) {
    try {
        if (name) localStorage.setItem(LAST_INSTANCE_KEY, name)
        else localStorage.removeItem(LAST_INSTANCE_KEY)
    } catch { /* 存储不可用只影响下次启动的落点。 */ }
}

/** 上次停留的页面路径（如 `/` 或 `/i/ap/overview`）。
    记路径而不是实例：用户说的是「上次停在哪个界面，下次打开就回哪个界面」。 */
export function readLastPath(): string {
    try { return localStorage.getItem(LAST_PATH_KEY) ?? '' } catch { return '' }
}

export function writeLastPath(path: string) {
    try { localStorage.setItem(LAST_PATH_KEY, path) } catch { /* 存储不可用只影响下次启动的落点。 */ }
}
