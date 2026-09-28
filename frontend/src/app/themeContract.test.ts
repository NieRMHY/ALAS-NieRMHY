import { describe, expect, it } from 'vitest'
import materialPalette from '../styles/theme-system.css?raw'
import legacyPalette from '../styles/legacy-palette.css?raw'
import minimalPalette from '../styles/minimal-palette.css?raw'
import materialAxis from '../styles/theme-material.css?raw'
import classicSkin from '../styles/classic.css?raw'
import legacySkin from '../styles/legacy.css?raw'

/* 主题契约：三份调色板各自声明整份 --theme-* 键。
   组件只消费契约变量，缺一个键就会静默落到别的样式表写死的值。 */
const palettes: Record<string, string> = {
  material: materialPalette,
  legacy: legacyPalette,
  minimal: minimalPalette,
}

const keysOf = (css: string) => new Set([...css.matchAll(/(--theme-[a-z0-9-]+)\s*:/g)].map(match => match[1]))

describe('主题契约键集合', () => {
  it('三份调色板声明同一组键', () => {
    const sets = Object.fromEntries(Object.entries(palettes).map(([name, css]) => [name, keysOf(css)]))
    const all = new Set(Object.values(sets).flatMap(set => [...set]))
    const missing = Object.fromEntries(Object.entries(sets).map(([name, set]) => [name, [...all].filter(key => !set.has(key)).sort()]))
    expect(missing).toEqual({material: [], legacy: [], minimal: []})
  })

  it('每份调色板都声明了非空的契约', () => {
    for (const css of Object.values(palettes)) expect(keysOf(css).size).toBeGreaterThan(0)
  })
})

/* 有材质轴的家族必须真的声明玻璃取值：漏了就只有普通一种观感，
   「玻璃 / 普通」两个选项会长得一模一样，而不会报任何错。 */
describe('材质轴取值', () => {
  /* 磨砂参数只在一级面声明一次，旧的 --theme-glass-* 键改为委托，避免两套同值 token 以后漂移。 */
  it('新版与旧版家族都声明了磨砂参数，且旧键委托给一级面', () => {
    for (const [name, css] of [['新版', materialPalette], ['旧版', legacyPalette]] as const) {
      expect(css, name).toMatch(/--theme-surface-blur:\s*(?!0px)\d/)
      expect(css, name).toMatch(/--theme-surface-saturation:\s*\d/)
      expect(css, name).toMatch(/--theme-glass-blur:\s*var\(--theme-surface-blur\)/)
      expect(css, name).toMatch(/--theme-material-filter:\s*var\(--theme-surface-filter\)/)
      expect(css, name).toMatch(/--theme-glass:\s*var\(--theme-surface-bg\)/)
    }
  })

  it('普通材质分支把玻璃压回不透明与无滤镜', () => {
    expect(materialAxis).toMatch(/:root\[data-material='plain'\]/)
    expect(materialAxis).toMatch(/--theme-material-filter:\s*none/)
    expect(materialAxis).toMatch(/--theme-glass:\s*var\(--surface\)/)
  })

  it('两个有材质轴的家族皮肤都引入了材质轴样式表', () => {
    for (const css of [classicSkin, legacySkin]) expect(css).toContain("theme-material.css")
  })
})

/* 区域化材质：7 区 × 8 键。参数键（alpha/blur/saturation/radius）由旋钮写入，
   合成键（bg/filter/edge/shadow）由皮肤消费；五区默认取一级面的参数（默认值关系，不是界面锁定）。 */
const REGIONS = ['surface', 'plate', 'sidebar', 'topbar', 'modal', 'menu', 'control'] as const
const REGION_PROPS = ['alpha', 'blur', 'saturation', 'radius', 'bg', 'filter', 'edge', 'shadow'] as const
const INHERITING = ['sidebar', 'topbar', 'modal', 'menu'] as const

const declaration = (css: string, key: string) => {
  const needle = `${key}:`
  const start = css.indexOf(needle)
  if (start < 0) return ''
  const valueStart = start + needle.length
  const semicolon = css.indexOf(';', valueStart)
  if (semicolon < 0) return ''
  return css.slice(valueStart, semicolon).trim()
}

describe('区域化材质契约', () => {
  it('七个区域各八键齐备', () => {
    for (const css of Object.values(palettes)) {
      for (const region of REGIONS) {
        for (const prop of REGION_PROPS) {
          expect(declaration(css, `--theme-${region}-${prop}`), `${region}-${prop}`).not.toBe('')
        }
      }
    }
  })

  it('四区的参数默认取自一级面', () => {
    for (const css of Object.values(palettes)) {
      for (const region of INHERITING) {
        for (const prop of ['alpha', 'blur', 'saturation', 'radius'] as const) {
          expect(declaration(css, `--theme-${region}-${prop}`), `${region}-${prop}`).toContain('--theme-surface-')
        }
      }
    }
  })

  /* 二级贴片的不透明度跟随一级面，
     但它自己的模糊与圆角仍是独立默认值；控件区整体独立。 */
  it('控件区独立，二级贴片保留自己的模糊与圆角', () => {
    for (const css of Object.values(palettes)) {
      for (const prop of ['alpha', 'blur', 'saturation'] as const) {
        expect(declaration(css, `--theme-control-${prop}`), `control-${prop}`).not.toContain('var(--theme-surface-')
      }
      expect(declaration(css, '--theme-plate-blur'), 'plate-blur').not.toContain('var(--theme-surface-')
      expect(declaration(css, '--theme-plate-radius'), 'plate-radius').not.toContain('var(--theme-surface-')
    }
  })

  it('合成键由参数键与 surface 合成', () => {
    for (const css of Object.values(palettes)) {
      for (const region of REGIONS) {
        expect(declaration(css, `--theme-${region}-bg`), `${region}-bg`).toContain(`var(--theme-${region}-alpha)`)
        expect(declaration(css, `--theme-${region}-filter`), `${region}-filter`).toContain(`var(--theme-${region}-blur)`)
      }
    }
  })
})
