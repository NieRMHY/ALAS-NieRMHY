import type { UiKey } from '../i18n'
import type { Family } from './theme'

/** 材质区域：每个区域都能独立调，默认值多数取自一级面（见契约层 `--theme-<区>-*`）。 */
export const REGIONS = ['surface', 'plate', 'sidebar', 'topbar', 'modal', 'menu', 'control'] as const
export type RegionId = typeof REGIONS[number]

/** 每个区域的五组旋钮：界面里就是 7×5 的矩阵。 */
export const PROPS = ['alpha', 'blur', 'saturation', 'radius', 'shadow'] as const
export type KnobProp = typeof PROPS[number]

export type RegionKnob = {
  /** 旋钮标识：`<区域>.<参数>`，也是偏好里的键。 */
  id: `${RegionId}.${KnobProp}`
  region: RegionId
  prop: KnobProp
  labelKey: UiKey
  unit: 'px' | '%'
  min: number
  max: number
  step: number
  /** 主题取值读不出数值时滑块的标称位置。 */
  fallback: number
  /** 该旋钮写入的契约参数键。 */
  token: string
  /** 数值 → CSS 值。 */
  format: (value: number) => string
}

const px = (value: number) => `${value}px`
const percent = (value: number) => `${value}%`

/** 四组参数的取值范围与写法只在这里定义一次；区域只决定写入哪个 token。 */
const propSpec: Record<KnobProp, {labelKey: UiKey; unit: 'px' | '%'; min: number; max: number; step: number; fallback: number; format: (value: number) => string}> = {
  alpha: {labelKey: 'settings.propAlpha', unit: '%', min: 0, max: 100, step: 5, fallback: 80, format: percent},
  blur: {labelKey: 'settings.glassBlur', unit: 'px', min: 0, max: 48, step: 1, fallback: 16, format: px},
  saturation: {labelKey: 'settings.glassSaturation', unit: '%', min: 70, max: 180, step: 5, fallback: 120, format: percent},
  radius: {labelKey: 'settings.customRadius', unit: 'px', min: 0, max: 48, step: 1, fallback: 12, format: px},
  /* 阴影不是单个数字：这一格直接写合成键，0 即无阴影（沿用早期阴影旋钮的写法）。 */
  shadow: {labelKey: 'settings.customShadow', unit: 'px', min: 0, max: 48, step: 1, fallback: 24, format: value => value === 0 ? 'none' : `0 ${Math.round(value / 3)}px ${value * 2}px rgb(0 0 0 / .18)`},
}

/** 区域名（界面里作为折叠分组的标题）。 */
export const regionLabels: Record<RegionId, UiKey> = {
  surface: 'settings.regionSurface',
  plate: 'settings.regionPlate',
  sidebar: 'settings.regionSidebar',
  topbar: 'settings.regionTopbar',
  modal: 'settings.regionModal',
  menu: 'settings.regionMenu',
  control: 'settings.regionControl',
}

export const regionKnobs: readonly RegionKnob[] = REGIONS.flatMap(region =>
  PROPS.map(prop => {
    const spec = propSpec[prop]
    return {id: `${region}.${prop}`, region, prop, token: `--theme-${region}-${prop}`, ...spec}
  }))

/** 哪些家族暴露这套区域旋钮；简洁与紧凑保持现状。 */
export const familyRegions: Record<Family, readonly RegionId[]> = {
  new: REGIONS,
  legacy: REGIONS,
  minimal: [],
  extreme: [],
}

export const knobFor = (id: string) => regionKnobs.find(knob => knob.id === id)
