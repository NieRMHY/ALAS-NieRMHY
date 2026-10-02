import { useEffect, useState, type CSSProperties } from 'react'
import { useApp } from '../app/context'
import { openMaterialInspector } from '../app/materialInspectorState'
import { applyCustomLayer, familyOf } from '../app/theme'
import { MaterialDetailModal } from './MaterialDetailModal'
import { clearFamilyPalette, readFamilyCustom, subscribeFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { familyRegions, regionKnobs, regionLabels, type RegionId, type RegionKnob } from '../app/themeKnobs'
import {
  AppWindow,
  Layers,
  LayoutGrid,
  Menu as MenuIcon,
  Palette,
  PanelLeft,
  PanelTop,
  RotateCcw,
  Sliders,
  SlidersHorizontal,
  Tv,
} from 'lucide-react'
import { MockInstancePreview } from './MockInstancePreview'

import { PaletteSwatches } from './PaletteSwatches'
import type { UiKey } from '../i18n'

export const REGION_ICONS: Record<RegionId, React.ComponentType<{size?: number; className?: string}>> = {
  surface: Layers,
  plate: LayoutGrid,
  sidebar: PanelLeft,
  topbar: PanelTop,
  modal: AppWindow,
  menu: MenuIcon,
  control: SlidersHorizontal,
}

type Ui = (key: UiKey, params?: Record<string, string | number>) => string

/** 滑块当前位置：用户动过就按存的值；否则尽量读主题自身的取值，读不出数值时用目录给的标称位置。 */
function knobPosition(knob: RegionKnob, stored: number | undefined) {
  if (stored !== undefined) return stored
  /* 主题取值要从计算样式里读；没有 DOM 时（静态渲染）退回标称位置。 */
  const raw = typeof document === 'undefined' ? '' : getComputedStyle(document.documentElement).getPropertyValue(knob.token).trim()
  if (!new RegExp(`^\\d+(\\.\\d+)?${knob.unit}$`).test(raw)) return knob.fallback
  return Math.min(knob.max, Math.max(knob.min, Number.parseFloat(raw)))
}

type PanelProps = {
  regions: readonly RegionId[]
  custom: FamilyCustom
  ui: Ui
  onKnob: (id: string, value: number) => void
  onResetKnob: (id: string) => void
  onResetRegion: (region: RegionId) => void
  onResetAll: () => void
}

/** 二级菜单的内容：先选「作用的类别」（七选一），下面只列这一类别的五组滑块，避免把 35 条挤在一屏。
    控件复用主题自己的 `SegmentedControl` 与 `.field-row`，材质族与朴素族各按各自的风格渲染。 */
export function MaterialDetailPanel({regions, custom, ui, onKnob, onResetKnob, onResetRegion, onResetAll, initialRegion, onRegionChange}: PanelProps & {initialRegion?: RegionId; onRegionChange?: (region: RegionId) => void}) {
  const [region, setRegion] = useState<RegionId>(initialRegion ?? regions[0])
  useEffect(() => {
    if (initialRegion) setRegion(initialRegion)
  }, [initialRegion])
  const dirtyIn = (target: RegionId) => Object.keys(custom.params).some(id => id.startsWith(`${target}.`))
  const knobs = regionKnobs.filter(knob => knob.region === region)
  return <>
    <div className="material-detail-body">
      <div className="field-row material-scope-row">
        <div className="field-label"><label>{ui('settings.materialDetailScope')}</label></div>
        <div className="field-control">
          <div className="material-scope-chips" role="tablist" aria-label={ui('settings.materialDetailScope')}>
            {regions.map((item, index) => {
              const isSelected = region === item
              const isDirty = dirtyIn(item)
              const Icon = REGION_ICONS[item]
              return (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                  className={`scope-chip ${isSelected ? 'active' : ''} ${isDirty ? 'has-changes' : ''}`}
                  onClick={() => { setRegion(item); onRegionChange?.(item) }}
                  onKeyDown={event => {
                    const next = event.key === 'ArrowRight'
                      ? (index + 1) % regions.length
                      : event.key === 'ArrowLeft'
                      ? (index - 1 + regions.length) % regions.length
                      : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                      ? regions.length - 1
                      : -1
                    if (next >= 0) {
                      event.preventDefault()
                      const nextRegion = regions[next]
                      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next]?.focus()
                      setRegion(nextRegion)
                      onRegionChange?.(nextRegion)
                    }
                  }}
                >
                  {Icon && <Icon size={13} className="scope-chip-icon" aria-hidden="true" />}
                  <span>{ui(regionLabels[item])}</span>
                  {isDirty && <span className="scope-chip-dot" title="已自定义修改" aria-label="已自定义修改" />}
                </button>
              )
            })}
          </div>
        </div>
      </div>
      {knobs.map(knob => {
        const stored = custom.params[knob.id]
        const value = knobPosition(knob, stored)
        const label = `${ui(regionLabels[region])} ${ui(knob.labelKey)}`
        return <div className="field-row knob-row" key={knob.id}>
          <div className="field-label"><label htmlFor={`ui-knob-${knob.id}`}>{ui(knob.labelKey)}</label></div>
          <div className="field-control knob-control">
            <input
              id={`ui-knob-${knob.id}`}
              type="range"
              aria-label={label}
              min={knob.min}
              max={knob.max}
              step={knob.step}
              value={value}
              /* 已填充比例：滑块轨道的进度渐变按它绘制。 */
              style={{['--knob-fill']: `${Math.round(((value - knob.min) / (knob.max - knob.min)) * 100)}%`} as CSSProperties}
              onChange={event => onKnob(knob.id, Number(event.target.value))}
            />
            <span className="knob-value">{value}{knob.unit}</span>
            <button type="button" className="knob-reset" title={ui('settings.resetItem')} aria-label={`${ui('settings.resetItem')} · ${label}`} disabled={stored === undefined} onClick={() => onResetKnob(knob.id)}><RotateCcw size={14} aria-hidden="true"/></button>
          </div>
        </div>
      })}
    </div>
    <div className="material-detail-actions">
      <button type="button" className="text-button" disabled={!dirtyIn(region)} onClick={() => onResetRegion(region)}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customReset')}</button>
      <button type="button" className="text-button" onClick={onResetAll}><RotateCcw size={14} aria-hidden="true"/>{ui('settings.customResetAll')}</button>
    </div>
  </>
}

/** 材质细节入口：紧跟在材质选择（玻璃/普通）之后，分区调整玻璃的不透明度、模糊、饱和度与圆角。
    普通材质下没有材质层，返回 null。 */
export function MaterialDetailPreference() {
  const {ui, theme, material, instances} = useApp()
  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  const [detail, setDetail] = useState(false)
  const [livePreview, setLivePreview] = useState(false)
  /* 切换大类后要换成那一套已存的值。 */
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const regions = familyRegions[family]
  if (!regions.length || material !== 'glass') return null
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)) }
  const touched = Object.keys(custom.params).length

  return <>
    <div className="field-row">
      <div className="field-label">
        <label>{ui('settings.materialDetail')}</label>
        <p>{ui('settings.materialDetailHelp')}</p>
      </div>
      <div className="field-control" style={{display: 'flex', gap: '10px', flexWrap: 'wrap'}}>
        <button type="button" className="button" onClick={() => setDetail(true)}>
          <Palette size={16} aria-hidden="true"/>
          {ui('settings.materialDetailOpen')}{touched > 0 ? ` (${touched})` : ''}
        </button>
        <button
          type="button"
          className="button secondary"
          title={ui('settings.materialLiveOnInstanceHelp')}
          onClick={() => {
            openMaterialInspector()
            const target = instances[0]?.name ? `/i/${instances[0].name}/overview` : '/'
            if (typeof window !== 'undefined') {
              window.location.hash = target
            }
          }}
        >
          <Sliders size={16} aria-hidden="true"/>
          {ui('settings.materialLiveOnInstance')}
        </button>
        <button
          type="button"
          className="button secondary"
          style={{opacity: 0.85}}
          title={ui('settings.materialLivePreviewHelp')}
          onClick={() => setLivePreview(true)}
        >
          <Tv size={16} aria-hidden="true"/>
          {ui('settings.materialLivePreview')}
        </button>
      </div>
    </div>
    {detail && <MaterialDetailModal onClose={() => setDetail(false)} onChange={refresh}/>}
    {livePreview && <MockInstancePreview onClose={() => { setLivePreview(false); refresh() }}/>}
  </>
}

/** 品牌配色入口：仅新版与旧版主题支持自定义品牌色。 */
export function BrandColorPreference() {
  const {ui, theme} = useApp()
  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  /* 切换大类后要换成那一套已存的值。 */
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  useEffect(() => subscribeFamilyCustom(changed => {
    if (changed === family) setCustom(readFamilyCustom(family))
  }), [family])
  const regions = familyRegions[family]
  if (!regions.length) return null
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)) }
  const brand = custom.palette

  return <div className="field-row palette-field">
    <div className="field-label">
      <label>{ui('settings.brandColor')}</label>
      <p>{ui('settings.brandColorHelp')}</p>
    </div>
    <div className="field-control palette-control">
      {/* 第一项是「原版色」：选它等于清掉覆盖，回到该大类自带的强调色。 */}
      <PaletteSwatches stock value={brand} onChange={palette => { if (palette) writeFamilyCustom(family, {palette}); else clearFamilyPalette(family); refresh() }} legend={ui('settings.brandColor')}/>
    </div>
  </div>
}

/** 有材质轴的家族专属的自定义外观：包含材质细节与品牌配色。 */
export function ThemeCustomPreference() {
  return <>
    <MaterialDetailPreference/>
    <BrandColorPreference/>
  </>
}
