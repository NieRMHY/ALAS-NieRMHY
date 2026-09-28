/**
 * @fileoverview 应用主题模式、明暗切换、紧凑布局与旧版外壳判定。
 */

import { palettes, paletteColors, paletteTokens, readCustomPalettes, colorModes, fixedColorModes, type Palette, type ColorMode, type ResolvedMode, type CustomPalette } from './palettes'
import { applyFamilyCustom } from './themeCustom'
export type Theme = 'light' | 'dark' | 'minimal' | 'extreme'
  | 'legacy-light' | 'legacy-dark'
export { palettes } from './palettes'
export type { Palette, ColorMode, CustomPalette } from './palettes'

/** 紧凑主题专属：调度与任务计划栏相对内容区的位置。 */
export type CompactRailSide = 'left' | 'right'
/** 紧凑主题专属的右栏宽度档位，244px 与 compact.css 的默认值一致。 */
export const COMPACT_RAIL_WIDTHS = [200, 244, 300, 360] as const
export type CompactRailWidth = (typeof COMPACT_RAIL_WIDTHS)[number]
export const COMPACT_RAIL_DEFAULT_SIDE: CompactRailSide = 'right'
export const COMPACT_RAIL_DEFAULT_WIDTH: CompactRailWidth = 244

type Preference = {
  theme: Theme; palette: Palette; colorMode: ColorMode; customPalettes: CustomPalette[]
  compactRailSide: CompactRailSide; compactRailWidth: CompactRailWidth
  material: Material
}
const defaults: Preference = {
  theme: 'light', palette: 'ocean', colorMode: 'auto', customPalettes: [],
  compactRailSide: COMPACT_RAIL_DEFAULT_SIDE, compactRailWidth: COMPACT_RAIL_DEFAULT_WIDTH,
  material: 'glass',
}

/** 走 Apple 玻璃/壁纸/装饰动画一档的主题；旧版浅色与深色是朴素风格，不在此列。 */
const MATERIAL_THEMES: readonly Theme[] = ['light', 'dark']
export const usesMaterial = (theme: Theme) => MATERIAL_THEMES.includes(theme)

/** 有材质轴（玻璃 / 普通）的家族：新版与旧版。简洁与紧凑的风格即「非透明」，没有材质轴。 */
const MATERIAL_AXIS_THEMES: readonly Theme[] = ['light', 'dark', 'legacy-light', 'legacy-dark']
export const hasMaterialAxis = (theme: Theme) => MATERIAL_AXIS_THEMES.includes(theme)

/** 是否支持自定义背景：两个有材质轴的家族都支持，普通材质同样可开。 */
export const supportsBackground = (theme: Theme) => hasMaterialAxis(theme)

/** 是否铺背景：有关闭档的材质由记录决定铺不铺，简洁与紧凑任何时候都不铺。 */
export const showsWallpaper = (theme: Theme, source: 'off' | 'default' | 'url' | 'upload') =>
  supportsBackground(theme) && source !== 'off'

export type Material = 'glass' | 'plain'
export const MATERIALS: readonly Material[] = ['glass', 'plain']

/** 各家族的默认材质：新版是玻璃（现状），旧版是普通（现状）——默认态因此与加材质轴之前一致。 */
export const defaultMaterial = (theme: Theme): Material => (theme === 'light' || theme === 'dark') ? 'glass' : 'plain'

/** 玻璃层：半透明磨砂与壁纸由材质决定，与家族无关。 */
export const usesGlassLayer = (theme: Theme, material: Material) => hasMaterialAxis(theme) && material === 'glass'

/** 一级主题大类。家族内切换材质或明暗不改变已存的其他自定义项。 */
export type Family = 'new' | 'legacy' | 'minimal' | 'extreme'
export const familyOf = (theme: Theme): Family =>
  theme === 'light' || theme === 'dark' ? 'new'
    : theme === 'legacy-light' || theme === 'legacy-dark' ? 'legacy'
      : theme === 'extreme' ? 'extreme' : 'minimal'

/** 走配色方案机制的主题（界面上显示「主题模式」与「配色方案」两块）。 */
const PALETTE_THEMES: readonly Theme[] = ['minimal', 'extreme']
export const usesPaletteOptions = (theme: Theme) => PALETTE_THEMES.includes(theme)

/** 走旧版版式的主题：实例视图的顶栏跨全宽、总览页两列、右栏让位。 */
const LEGACY_LAYOUT_THEMES: readonly Theme[] = ['legacy-light', 'legacy-dark']
export const usesLegacyLayout = (theme: Theme) => LEGACY_LAYOUT_THEMES.includes(theme)

/** 实例视图是否换用旧版外壳；主页视图（没有实例）一律沿用新版外壳。 */
export const usesLegacyShell = (theme: Theme, instance?: string) => Boolean(instance) && usesLegacyLayout(theme)

/** 是否渲染右栏。旧版主题把调度器与任务计划放进实例页左列，右栏整体让位，否则同一块内容会出现两处。 */
export const showsRightRail = (theme: Theme, instance?: string) => Boolean(instance) && !usesLegacyLayout(theme)

const VALID_THEMES: readonly string[] = ['light', 'dark', 'minimal', 'extreme',
  'legacy-light', 'legacy-dark']

export function readThemePreference(): Preference {
  try {
    const theme = localStorage.getItem('azurpilot.theme')
    const palette = localStorage.getItem('azurpilot.palette')
    const colorMode = localStorage.getItem('azurpilot.color-mode')
    const customPalettes = readCustomPalettes(localStorage.getItem('azurpilot.custom-palettes'))
    const railSide = localStorage.getItem('azurpilot.compact-rail-side')
    const railWidth = Number(localStorage.getItem('azurpilot.compact-rail-width'))
    const storedMaterial = localStorage.getItem('azurpilot.material')
    const resolvedTheme = VALID_THEMES.includes(theme ?? '') ? theme as Theme : 'light'
    return {
      theme: resolvedTheme,
      material: MATERIALS.includes(storedMaterial as Material) ? storedMaterial as Material : defaultMaterial(resolvedTheme),
      palette: palettes.some(item => item === palette) || customPalettes.some(item => item.id === palette) ? palette as Palette : 'ocean',
      colorMode: colorModes.includes(colorMode as ColorMode) ? colorMode as ColorMode : 'auto',
      customPalettes,
      compactRailSide: railSide === 'left' || railSide === 'right' ? railSide : COMPACT_RAIL_DEFAULT_SIDE,
      compactRailWidth: COMPACT_RAIL_WIDTHS.includes(railWidth as CompactRailWidth) ? railWidth as CompactRailWidth : COMPACT_RAIL_DEFAULT_WIDTH,
    }
  } catch { return {...defaults} }
}

const listeners = new Set<() => void>()
let preference = {...readThemePreference(), resolvedMode: 'light' as ResolvedMode}
let revision = 0
let activeSkin: string | undefined
let systemQuery: MediaQueryList | undefined
let managedTokens: string[] = []
/* 用户层写入的 token 记账：换大类或重置时据此清理，避免跟着新主题生效。 */
let customTokens: string[] = []

/** 有材质轴的家族由主题 id 定明暗（浅色/深色各是一个主题值），配色方案的自动与固定档位不适用于它们。 */
const modeOfTheme = (theme: Theme): ResolvedMode => theme === 'dark' || theme === 'legacy-dark' ? 'dark' : 'light'

/** 用户改动自定义旋钮或品牌配色后立即下发：先清上一套再写当前大类的一套（主题与皮肤都不动）。 */
export function applyCustomLayer() {
  const root = document.documentElement
  for (const token of customTokens) root.style.removeProperty(token)
  customTokens = applyFamilyCustom(root, familyOf(preference.theme), modeOfTheme(preference.theme))
}
export const getThemePreference = () => preference
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 只有简约与紧凑的自动模式订阅系统变化；切换为固定模式或经典主题即移除监听。
    主题模式里的程序员 / 复古灰 / 复古蓝 / 复古红自带整套色值，此时忽略配色方案。 */
function applyColorMode(next: Preference) {
  const root = document.documentElement
  const themed = usesPaletteOptions(next.theme)
  const fixed = fixedColorModes[next.colorMode]
  const followSystem = themed && next.colorMode === 'auto'
  if (!followSystem) {
    systemQuery?.removeEventListener('change', systemModeChanged)
    systemQuery = undefined
  } else if (!systemQuery) {
    systemQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemQuery.addEventListener('change', systemModeChanged)
  }
  const resolvedMode: ResolvedMode = fixed ? fixed.mode
    : themed ? (next.colorMode === 'auto' ? (systemQuery?.matches ? 'dark' : 'light') : next.colorMode as ResolvedMode)
      : next.theme === 'dark' ? 'dark' : 'light'
  if (themed) {
    const tokens = fixed ? fixed.tokens
      : paletteTokens(paletteColors(next.palette, next.customPalettes, resolvedMode), resolvedMode)
    // 同一轮更新内联变量，让图表的属性监听合并处理本次变化。
    for (const key of managedTokens) if (!(key in tokens)) root.style.removeProperty(key)
    for (const [key, value] of Object.entries(tokens)) {
      if (root.style.getPropertyValue(key) !== value) root.style.setProperty(key, value)
    }
    managedTokens = Object.keys(tokens)
    if (root.dataset.colorMode !== resolvedMode) root.dataset.colorMode = resolvedMode
  } else {
    for (const key of managedTokens) root.style.removeProperty(key)
    managedTokens = []
    delete root.dataset.colorMode
  }
  return resolvedMode
}

function systemModeChanged() {
  preference = {...preference, resolvedMode: applyColorMode(preference)}
  listeners.forEach(listener => listener())
}

/** 紧凑主题的列序与右栏宽度以根元素属性加内联变量下发。切到其它主题时必须一并清掉，
    否则同一份内联变量会跟着简约主题生效 —— 两者右栏宽度不同（紧凑 244，简约 292/320）。 */
function applyCompactLayout(root: HTMLElement, next: Preference) {
  if (next.theme !== 'extreme') {
    delete root.dataset.compactRail
    root.style.removeProperty('--right-rail-width')
    return
  }
  if (root.dataset.compactRail !== next.compactRailSide) root.dataset.compactRail = next.compactRailSide
  const width = `${next.compactRailWidth}px`
  if (root.style.getPropertyValue('--right-rail-width') !== width) root.style.setProperty('--right-rail-width', width)
}

/** Vite 要求 import 路径静态可分析，所以用显式映射表而不是变量拼接。 */
const skinLoaders = {
  minimal: () => import('../styles/minimal.css?inline'),
  legacy: () => import('../styles/legacy.css?inline'),
  classic: () => import('../styles/classic.css?inline'),
} as const
type Skin = keyof typeof skinLoaders

/** 浅色与深色各自是独立主题值，但共用同一份 CSS：明暗靠 data-theme 选择器切换。 */
function skinFor(theme: Theme): Skin {
  if (theme === 'minimal' || theme === 'extreme') return 'minimal'
  if (theme === 'legacy-light' || theme === 'legacy-dark') return 'legacy'
  return 'classic'
}

/** 样式作为惰性文本模块加载，切换时替换唯一节点，避免旧主题规则驻留。 */
export async function applyTheme(next: Preference) {
  const request = ++revision
  const skin = skinFor(next.theme)
  let css: string | undefined
  if (activeSkin !== skin) {
    const module = await skinLoaders[skin]()
    css = module.default
  }
  // 快速切换时只提交最后一次选择，较早返回的请求不能覆盖新主题。
  if (request !== revision) return
  if (css !== undefined) {
    let style = document.querySelector<HTMLStyleElement>('style[data-azurpilot-skin]')
    if (!style) {
      style = document.createElement('style')
      document.head.appendChild(style)
    }
    style.dataset.azurpilotSkin = skin
    style.textContent = css
    activeSkin = skin
  }
  // 外部 theme.css 是材质主题的用户定制入口；朴素主题（简约、旧版浅色/深色）不加载。
  const custom = document.querySelector('link[data-azurpilot-theme]')
  if (usesMaterial(next.theme)) {
    if (!custom) {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = `${import.meta.env.BASE_URL}theme.css`
      link.dataset.azurpilotTheme = 'user'
      document.head.appendChild(link)
    }
  } else custom?.remove()
  const root = document.documentElement
  if (root.dataset.theme !== next.theme) root.dataset.theme = next.theme
  if (root.dataset.palette !== next.palette) root.dataset.palette = next.palette
  /* 材质属性只在有材质轴的家族下发；切到简洁或紧凑时必须清掉，否则同一份普通取值会跟着生效。 */
  if (hasMaterialAxis(next.theme)) {
    if (root.dataset.material !== next.material) root.dataset.material = next.material
  } else delete root.dataset.material
  const resolvedMode = applyColorMode(next)
  applyCompactLayout(root, next)
  applyCustomLayer()
  try {
    localStorage.setItem('azurpilot.theme', next.theme)
    localStorage.setItem('azurpilot.palette', next.palette)
    localStorage.setItem('azurpilot.color-mode', next.colorMode)
    localStorage.setItem('azurpilot.custom-palettes', JSON.stringify(next.customPalettes))
    localStorage.setItem('azurpilot.compact-rail-side', next.compactRailSide)
    localStorage.setItem('azurpilot.compact-rail-width', String(next.compactRailWidth))
    localStorage.setItem('azurpilot.material', next.material)
  } catch { /* 存储不可用时仍允许切换，本次会话内生效。 */ }
  preference = {...next, resolvedMode}
  listeners.forEach(listener => listener())
}
