import { describe, expect, it } from 'vitest'
import type { InstalledPlugin } from './types'
import { PRELOAD_ATTRIBUTE, STYLE_CACHE_KEY, releasePreloadedStyles, rememberThemeStyles, syncThemeStyles } from './themeStyles'

const skin: InstalledPlugin = {
  enabled: true, revision: 'r7',
  manifest: {id: 'skin', name: 'Skin', version: '1.0.0', apiVersion: 1, theme: {styles: {overview: 'theme/overview.css'}}},
}

class FakeLink {
  removed = false
  remove() { this.removed = true }
}

/** 最小宿主桩：记录选择器与写入值，用来断言预载链接与缓存的处理边界。 */
function fakeHost() {
  const links = [new FakeLink(), new FakeLink()]
  const selectors: string[] = []
  const values = new Map<string, string>()
  return {
    links, selectors, values,
    document: {querySelectorAll: (selector: string) => { selectors.push(selector); return links }},
    storage: {setItem: (key: string, value: string) => { values.set(key, value) }},
  }
}

describe('插件主题样式预载记录', () => {
  it('只撤掉带预载标记的链接', () => {
    const host = fakeHost()
    releasePreloadedStyles(host.document)
    expect(host.selectors).toEqual(['link[' + PRELOAD_ATTRIBUTE + ']'])
    expect(host.links.every(link => link.removed)).toBe(true)
  })

  it('记录启用主题的 id、revision 与槽位样式，供下次挂载前预载', () => {
    const host = fakeHost()
    rememberThemeStyles(skin, host.storage)
    expect(host.values.get(STYLE_CACHE_KEY)).toBe(JSON.stringify({
      id: 'skin', revision: 'r7', styles: {overview: 'theme/overview.css'},
    }))
  })

  it('停用主题后记录置空，下次加载不再挂旧样式', () => {
    const host = fakeHost()
    rememberThemeStyles(undefined, host.storage)
    expect(host.values.get(STYLE_CACHE_KEY)).toBe('null')
  })

  it('插件列表就绪前保留预载链接与缓存，避免加载/登录前把皮肤记录清空', () => {
    const host = fakeHost()
    expect(syncThemeStyles(false, undefined, host)).toBe(false)
    expect(host.selectors).toEqual([])
    expect(host.links.some(link => link.removed)).toBe(false)
    expect(host.values.size).toBe(0)
  })

  it('列表就绪后接管：撤掉预载链接并写入当前主题记录', () => {
    const host = fakeHost()
    expect(syncThemeStyles(true, skin, host)).toBe(true)
    expect(host.links.every(link => link.removed)).toBe(true)
    expect(host.values.get(STYLE_CACHE_KEY)).toBe(JSON.stringify({
      id: 'skin', revision: 'r7', styles: {overview: 'theme/overview.css'},
    }))
  })

  it('切换主题后记录跟着换，不残留上一套皮肤', () => {
    const host = fakeHost()
    syncThemeStyles(true, skin, host)
    syncThemeStyles(true, {
      enabled: true, revision: 'r9',
      manifest: {id: 'other', name: 'Other', version: '2.0.0', apiVersion: 1, theme: {styles: {shell: 'theme/shell.css'}}},
    }, host)
    expect(host.values.get(STYLE_CACHE_KEY)).toBe(JSON.stringify({
      id: 'other', revision: 'r9', styles: {shell: 'theme/shell.css'},
    }))
  })

  it('列表就绪但没有启用主题时同样清掉预载链接与缓存', () => {
    const host = fakeHost()
    expect(syncThemeStyles(true, undefined, host)).toBe(true)
    expect(host.links.every(link => link.removed)).toBe(true)
    expect(host.values.get(STYLE_CACHE_KEY)).toBe('null')
  })
})
