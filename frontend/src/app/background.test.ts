import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ServerBackgroundPreference } from '../api/types'
import { DEFAULT_BACKGROUND_URLS, cacheServerBackgrounds, normalizeBackgroundUrl, readBackgroundPreference } from './background'
import { getThemePreference } from './theme'

describe('背景地址校验', () => {
  it('接受 HTTP 与 HTTPS 地址并清理首尾空白', () => {
    expect(normalizeBackgroundUrl(' https://example.com/a.jpg ')).toBe('https://example.com/a.jpg')
    expect(normalizeBackgroundUrl('http://example.com/video.mp4')).toBe('http://example.com/video.mp4')
  })

  it('拒绝空值、无效地址和非网络协议', () => {
    expect(() => normalizeBackgroundUrl('')).toThrow()
    expect(() => normalizeBackgroundUrl('not-a-url')).toThrow()
    expect(() => normalizeBackgroundUrl('javascript:alert(1)')).toThrow()
    expect(() => normalizeBackgroundUrl('file:///tmp/background.jpg')).toThrow()
  })
})

describe('背景记录按材质读回', () => {
  const store = (data: Record<string, string>) => {
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => data[key] ?? null,
      setItem: (key: string, value: string) => { data[key] = value },
      removeItem: (key: string) => { delete data[key] },
    })
    return data
  }
  afterEach(() => vi.unstubAllGlobals())

  /* 回归：普通材质的默认档是「关闭」，漏判 default 就会把用户选的随机图读成关闭（刷新即被重置）。 */
  it('普通材质下「默认随机图」读回来还是随机图（旧 default 记录折成 URL 模式的内置 API）', () => {
    store({'azurpilot.background.plain': JSON.stringify({source: 'default', kind: 'image', url: '', name: ''})})
    const preference = readBackgroundPreference('plain')
    expect(preference.source).toBe('url')
    expect(preference.urls).toEqual(DEFAULT_BACKGROUND_URLS)
  })

  it('没有记录时：玻璃默认用内置随机图 API，普通默认关闭', () => {
    store({})
    const glass = readBackgroundPreference('glass')
    expect(glass.source).toBe('url')
    expect(glass.urls).toEqual(DEFAULT_BACKGROUND_URLS)
    expect(readBackgroundPreference('plain').source).toBe('off')
  })

  it('旧单条 url 记录折成一行，新多行记录原样读回', () => {
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', url: 'https://example.com/old.jpg', name: ''})})
    expect(readBackgroundPreference('glass').urls).toEqual(['https://example.com/old.jpg'])
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', urls: ['https://a.test/1', 'https://b.test/2'], active: 1, name: ''})})
    const next = readBackgroundPreference('glass')
    expect(next.urls).toHaveLength(2)
    expect(next.active).toBe(1)
  })

  it('一行一条：空行与重复地址都被去掉', () => {
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', urls: ['https://a.test/1', '  ', 'https://a.test/1', 'https://b.test/2'], active: 0, name: ''})})
    expect(readBackgroundPreference('glass').urls).toEqual(['https://a.test/1', 'https://b.test/2'])
  })

  it('两个材质各读各的键，互不影响', () => {
    store({
      'azurpilot.background': JSON.stringify({source: 'off', kind: 'image', urls: [], active: 0, name: ''}),
      'azurpilot.background.plain': JSON.stringify({source: 'url', kind: 'image', urls: ['https://example.com/a.jpg'], active: 0, name: ''}),
    })
    expect(readBackgroundPreference('glass').source).toBe('off')
    const plain = readBackgroundPreference('plain')
    expect(plain.source).toBe('url')
    expect(plain.urls[plain.active]).toBe('https://example.com/a.jpg')
  })

  it('损坏或空白的记录回落到该材质的默认档', () => {
    store({'azurpilot.background.plain': '{不是 JSON'})
    expect(readBackgroundPreference('plain').source).toBe('off')
  })

  /* 服务端记录是「所有浏览器/访问地址共用」的那份：两个材质都写进本地缓存，只让当前材质生效。 */
  it('服务端记录写进本地缓存，并返回当前材质的那份', () => {
    const data = store({})
    const glass: ServerBackgroundPreference = {source: 'off', kind: 'image', urls: [], active: 0, name: ''}
    const plain: ServerBackgroundPreference = {source: 'url', kind: 'image', urls: ['https://a.test/1.jpg'], active: 0, name: ''}
    const applied = cacheServerBackgrounds({glass, plain})
    expect(JSON.parse(data['azurpilot.background']).source).toBe('off')
    expect(JSON.parse(data['azurpilot.background.plain']).source).toBe('url')
    expect(applied?.urls).toEqual(getThemePreference().material === 'plain' ? plain.urls : glass.urls)
  })

  it('服务端没有记录时返回 null，不覆盖本地记录', () => {
    store({'azurpilot.background': JSON.stringify({source: 'off', kind: 'image', urls: [], active: 0, name: ''})})
    expect(cacheServerBackgrounds({})).toBeNull()
    expect(cacheServerBackgrounds(null)).toBeNull()
    expect(readBackgroundPreference('glass').source).toBe('off')
  })
})
