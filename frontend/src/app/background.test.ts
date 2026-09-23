import { describe, expect, it } from 'vitest'
import { normalizeBackgroundUrl } from './background'

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
