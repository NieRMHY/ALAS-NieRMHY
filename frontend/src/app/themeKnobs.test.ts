import { describe, expect, it } from 'vitest'
import materialPalette from '../styles/theme-system.css?raw'
import legacyPalette from '../styles/legacy-palette.css?raw'
import minimalPalette from '../styles/minimal-palette.css?raw'
import { PROPS, REGIONS, familyRegions, knobFor, regionKnobs } from './themeKnobs'

const contractKeys = new Set([materialPalette, legacyPalette, minimalPalette]
  .flatMap(css => [...css.matchAll(/(--theme-[a-z0-9-]+)\s*:/g)].map(m => m[1])))

describe('区域旋钮目录', () => {
  it('七个区域各四组旋钮，不多不少', () => {
    expect(regionKnobs).toHaveLength(REGIONS.length * PROPS.length)
    for (const region of REGIONS) {
      expect(regionKnobs.filter(knob => knob.region === region).map(knob => knob.prop)).toEqual([...PROPS])
    }
  })

  it('每个旋钮写入的 token 都在契约键里（拼错会静默无效）', () => {
    for (const knob of regionKnobs) {
      expect(knob.token, knob.id).toBe(`--theme-${knob.region}-${knob.prop}`)
      expect(contractKeys.has(knob.token), knob.id).toBe(true)
    }
  })

  it('范围自洽：min < max、step 为正、量程端点的写法带得出单位', () => {
    for (const knob of regionKnobs) {
      expect(knob.min, knob.id).toBeLessThan(knob.max)
      expect(knob.step, knob.id).toBeGreaterThan(0)
      expect(knob.fallback, knob.id).toBeGreaterThanOrEqual(knob.min)
      expect(knob.fallback, knob.id).toBeLessThanOrEqual(knob.max)
      expect(knob.format(knob.max), knob.id).toContain(knob.unit)
    }
  })

  it('简洁与紧凑不暴露区域旋钮', () => {
    expect(familyRegions.minimal).toEqual([])
    expect(familyRegions.extreme).toEqual([])
    expect(familyRegions.new).toEqual([...REGIONS])
    expect(familyRegions.legacy).toEqual([...REGIONS])
  })

  it('knobFor 只认目录里的 id', () => {
    expect(knobFor('plate.alpha')?.token).toBe('--theme-plate-alpha')
    expect(knobFor('plate.opacity')).toBeUndefined()
    expect(knobFor('unknown.alpha')).toBeUndefined()
  })
})
