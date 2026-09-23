import { describe, expect, it } from 'vitest'
import { contrastRatio, fixedColorModes, paletteColors, paletteTokens, palettes, presetColors, readCustomPalettes, type CustomPalette } from './palettes'

const custom: CustomPalette = {id: 'custom:test', primary: '#ffffff', secondary: '#ffff00'}

describe('简约配色生成与校验', () => {
  it('预设在明暗模式下具有不同配色且保留可读性', () => {
    for (const id of palettes) {
      expect(presetColors[id].light).not.toEqual(presetColors[id].dark)
      for (const mode of ['light', 'dark'] as const) {
        const tokens = paletteTokens(presetColors[id][mode], mode)
        for (const background of ['--surface', '--surface-muted', '--accent-soft']) {
          expect(contrastRatio(tokens['--accent'], tokens[background])).toBeGreaterThanOrEqual(4.5)
        }
        expect(contrastRatio(tokens['--theme-on-accent'], tokens['--accent'])).toBeGreaterThanOrEqual(4.5)
      }
    }
  })
  it('自带色值的模式：对比度达标，程序员那一档保持纯灰阶', () => {
    for (const [id, fixed] of Object.entries(fixedColorModes)) {
      const tokens = fixed!.tokens
      expect(Object.values(tokens).every(value => /^#[\da-f]{6}$/i.test(value)), id).toBe(true)
      for (const background of ['--surface', '--surface-muted', '--accent-soft']) {
        expect(contrastRatio(tokens['--accent'], tokens[background]), `${id} 的 accent 落在 ${background} 上`).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrastRatio(tokens['--theme-on-accent'], tokens['--accent']), `${id} 的按钮文字`).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(tokens['--text'], tokens['--surface']), `${id} 的正文`).toBeGreaterThanOrEqual(7)
    }
    const isGray = (value: string) => value.slice(1, 3) === value.slice(3, 5) && value.slice(3, 5) === value.slice(5, 7)
    for (const value of Object.values(fixedColorModes.terminal!.tokens)) expect(isGray(value), value).toBe(true)
  })
  it('极端自定义颜色也能生成清晰的实色界面，浅色深色通用', () => {
    for (const mode of ['light', 'dark'] as const) {
      expect(paletteColors(custom.id, [custom], mode)).toEqual({primary: '#ffffff', secondary: '#ffff00'})
      const tokens = paletteTokens(paletteColors(custom.id, [custom], mode), mode)
      expect(Object.values(tokens).every(value => /^#[\da-f]{6}$/i.test(value))).toBe(true)
      expect(contrastRatio(tokens['--accent'], tokens['--surface-muted'])).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(tokens['--secondary'], tokens['--surface-muted'])).toBeGreaterThanOrEqual(4.5)
    }
  })
  it('损坏、重复和非实色的存储条目不进入可选方案，并兼容旧版双色模式数据', () => {
    expect(readCustomPalettes('broken')).toEqual([])
    expect(readCustomPalettes('{}')).toEqual([])
    const legacy = {id: 'custom:legacy', name: '旧版配色', light: {primary: '#112233', secondary: '#445566'}, dark: {primary: '#778899', secondary: '#aabbcc'}}
    expect(readCustomPalettes(JSON.stringify([
      null, custom, custom,
      {...custom, id: 'custom:invalid', primary: 'red; background: url(test)', secondary: '#000000'},
      legacy,
    ]))).toEqual([
      custom,
      {id: 'custom:legacy', primary: '#112233', secondary: '#445566'},
    ])
    expect(paletteColors('custom:deleted', [], 'dark')).toEqual(presetColors.ocean.dark)
  })
})
