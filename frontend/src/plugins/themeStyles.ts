/**
 * Add by MHY, 插件主题样式的预载记录：index.html 在应用挂载前按它预载皮肤样式，
 * 应用接管后由 PluginStyles 撤掉预载链接并同步最新记录。
 */
import type { InstalledPlugin } from './types'

/** 预载样式链接上的标记；index.html 的内联脚本里是同一份字面量。 */
export const PRELOAD_ATTRIBUTE = 'data-apu-preload'
/** 预载记录在 localStorage 里的键。 */
export const STYLE_CACHE_KEY = 'azurpilot.apu-styles'

/** 能按标记选中并移除节点的文档视图；测试可以传最小桩。 */
interface PreloadHost {querySelectorAll(selector: string): ArrayLike<{remove(): void}>}

/** 预载记录的可写存储视图；同样只为让测试注入最小桩。 */
interface StyleStorage {setItem(key: string, value: string): void}

/** 接管样式时的宿主，缺省用当前文档与 localStorage。 */
interface ThemeStyleHost {document?: PreloadHost; storage?: StyleStorage}

/**
 * 撤掉 index.html 预载的样式链接。
 *
 * 插件列表加载完成后 React 已按当前主题注入样式，预载链接若留着，
 * 切换主题或停用主题后上一套皮肤仍然生效。
 */
export function releasePreloadedStyles(host: PreloadHost = document) {
  for (const link of Array.from(host.querySelectorAll('link[' + PRELOAD_ATTRIBUTE + ']'))) link.remove()
}

/**
 * 写入当前启用的主题样式记录，供下次刷新时预载；没有主题时写 null，
 * 这样下次加载不会再挂上已停用插件的旧样式。
 */
export function rememberThemeStyles(theme: InstalledPlugin | undefined, storage: StyleStorage = localStorage) {
  storage.setItem(STYLE_CACHE_KEY, JSON.stringify(theme ? {
    id: theme.manifest.id, revision: theme.revision, styles: theme.manifest.theme?.styles ?? {},
  } : null))
}

/**
 * 插件列表首次成功加载后由 React 接管主题样式：撤掉预载链接并同步记录。
 *
 * 列表就绪前不能动：登录前与加载中的 theme 必然是空的，这时写记录会把 index.html
 * 唯一能用的预载链接抹掉，下次刷新又要先闪一遍默认外观。因此以 ready 为界，
 * 只有真正知道当前主题是什么之后才修正记录。
 *
 * @returns 是否已经接管（未就绪或存储不可用时为 false）。
 */
export function syncThemeStyles(ready: boolean, theme: InstalledPlugin | undefined, host: ThemeStyleHost = {}) {
  if (!ready) return false
  try {
    releasePreloadedStyles(host.document ?? document)
    rememberThemeStyles(theme, host.storage ?? localStorage)
    return true
  } catch {
    // 拿不到 localStorage 或文档时退回应用内的常规样式注入，预载记录下次再纠正。
    return false
  }
}
