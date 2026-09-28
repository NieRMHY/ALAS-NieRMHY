import { accentTokens, paletteColors, palettes, readCustomPalettes, type Palette, type ResolvedMode } from './palettes'
import { knobFor, type RegionId } from './themeKnobs'
import type { Family } from './theme'

/** 一个大类的自定义项：区域参数（键为 `<区域>.<参数>`）+ 可选的品牌配色（未选则跟随主题自带配色）。 */
export type FamilyCustom = {params: Record<string, number>; palette?: Palette}

const knobsKey = (family: Family) => `azurpilot.custom.${family}`
/** 自定义配色的定义是全局资产，只有「选哪套」按大类各存。 */
const customPalettesKey = 'azurpilot.custom-palettes'

const isPalette = (value: unknown): value is Palette =>
  typeof value === 'string' && ((palettes as readonly string[]).includes(value) || /^custom:[\w-]+$/.test(value))

/* 早期版本按「玻璃参数 + 圆角 + 阴影」五个全局旋钮存，键名没有区域；读到就折算到一级面。
   阴影不再是旋钮（人类定的四组参数是不透明度/模糊/饱和度/圆角），旧值丢弃。 */
const legacyKeys: Record<string, string> = {blur: 'surface.blur', saturation: 'surface.saturation', opacity: 'surface.alpha', radius: 'surface.radius'}

function readParams(input: Record<string, unknown>) {
  const source = (input.params && typeof input.params === 'object' ? input.params : {}) as Record<string, unknown>
  const params: Record<string, number> = {}
  const accept = (id: string, value: unknown) => {
    const knob = knobFor(id)
    if (!knob || typeof value !== 'number' || !Number.isFinite(value)) return
    params[id] = Math.min(knob.max, Math.max(knob.min, value))
  }
  for (const [key, value] of Object.entries(source)) accept(key, value)
  for (const [oldKey, id] of Object.entries(legacyKeys)) accept(id, input[oldKey])
  return params
}

export function readFamilyCustom(family: Family): FamilyCustom {
  try {
    const raw = JSON.parse(localStorage.getItem(knobsKey(family)) ?? '{}') as Record<string, unknown>
    if (!raw || typeof raw !== 'object') return {params: {}}
    return {params: readParams(raw), ...(isPalette(raw.palette) ? {palette: raw.palette} : {})}
  } catch { return {params: {}} }
}

function save(family: Family, custom: FamilyCustom) {
  try {
    /* 没有内容就不留键：无记录与默认态完全等价。 */
    if (Object.keys(custom.params).length || custom.palette) localStorage.setItem(knobsKey(family), JSON.stringify(custom))
    else localStorage.removeItem(knobsKey(family))
  } catch { /* 存储不可用时本次会话内仍生效。 */ }
}

/** 写入该大类动过的参数 token，返回写入的 token 名供调用方记账清理。 */
export function applyFamilyCustom(root: HTMLElement, family: Family, mode: ResolvedMode): string[] {
  const custom = readFamilyCustom(family)
  const written: string[] = []
  for (const [id, value] of Object.entries(custom.params)) {
    const knob = knobFor(id)
    if (!knob) continue
    const css = knob.format(value)
    if (root.style.getPropertyValue(knob.token) !== css) root.style.setProperty(knob.token, css)
    written.push(knob.token)
  }
  if (custom.palette) {
    const palettes2 = readCustomPalettes(localStorage.getItem(customPalettesKey))
    /* 材质与旧版的表面/文字/边框归主题自己管，品牌配色只换强调色一族。 */
    const tokens = accentTokens(paletteColors(custom.palette, palettes2, mode), mode)
    for (const [token, value] of Object.entries(tokens)) {
      if (root.style.getPropertyValue(token) !== value) root.style.setProperty(token, value)
      written.push(token)
    }
  }
  return written
}

export function writeFamilyCustom(family: Family, patch: {params?: Record<string, number | undefined>; palette?: Palette}) {
  const current = readFamilyCustom(family)
  const merged: Record<string, number> = {...current.params}
  for (const [id, value] of Object.entries(patch.params ?? {})) {
    /* undefined 表示这一项回默认：连同键一起丢掉。 */
    if (value === undefined) delete merged[id]
    else merged[id] = value
  }
  save(family, {params: merged, palette: patch.palette ?? current.palette})
}

/** 只保留 keep 认可的旋钮，其余回默认。 */
export function clearFamilyKnobs(family: Family, keep: (id: string) => boolean) {
  const current = readFamilyCustom(family)
  save(family, {params: Object.fromEntries(Object.entries(current.params).filter(([id]) => keep(id))), palette: current.palette})
}

export const clearFamilyKnob = (family: Family, id: string) => clearFamilyKnobs(family, kept => kept !== id)
export const clearFamilyRegion = (family: Family, region: RegionId) => clearFamilyKnobs(family, id => !id.startsWith(`${region}.`))

/** 品牌配色回到「跟随主题」：清掉选择，由主题自带配色接管。 */
export function clearFamilyPalette(family: Family) {
  const current = readFamilyCustom(family)
  save(family, {params: current.params})
}

export function resetFamilyCustom(family: Family) {
  try { localStorage.removeItem(knobsKey(family)) } catch { /* 忽略：内联 token 由 applyTheme 清理。 */ }
}
