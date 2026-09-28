import { useEffect, useState, type CSSProperties } from 'react'
import { useApp } from '../app/context'
import { applyCustomLayer, familyOf } from '../app/theme'
import { MaterialDetailModal } from './MaterialDetailModal'
import { clearFamilyPalette, readFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { familyRegions, regionKnobs, regionLabels, type RegionId, type RegionKnob } from '../app/themeKnobs'
import { RotateCcw } from 'lucide-react'

import { SegmentedControl } from './SegmentedControl'
import { PaletteSwatches } from './PaletteSwatches'
import type { UiKey } from '../i18n'

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
export function MaterialDetailPanel({regions, custom, ui, onKnob, onResetKnob, onResetRegion, onResetAll, initialRegion}: PanelProps & {initialRegion?: RegionId}) {
  const [region, setRegion] = useState<RegionId>(initialRegion ?? regions[0])
  const dirtyIn = (target: RegionId) => Object.keys(custom.params).some(id => id.startsWith(`${target}.`))
  const knobs = regionKnobs.filter(knob => knob.region === region)
  return <>
    <div className="material-detail-body">
      <div className="field-row">
        <div className="field-label"><label>{ui('settings.materialDetailScope')}</label></div>
        <div className="field-control">
          <SegmentedControl
            className="settings-segmented material-detail-scope"
            label={ui('settings.materialDetailScope')}
            value={region}
            onChange={setRegion}
            options={regions.map(item => ({value: item, label: ui(regionLabels[item])}))}
          />
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
              /* 只认真实用户操作：表单值恢复或脚本派发的合成事件不应改写用户偏好。 */
              onChange={event => { if (event.nativeEvent.isTrusted) onKnob(knob.id, Number(event.target.value)) }}
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

/** 有材质轴的家族专属的自定义外观：一级界面只放主题色与二级菜单入口，全部材质滑块都在二级菜单里。
    区域只是默认值多数取自一级面（不想调的人不用管），每一区都能独立调、也能单独还原。 */
export function ThemeCustomPreference() {
  const {ui, theme, material} = useApp()
  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  const [detail, setDetail] = useState(false)
  /* 切换大类后要换成那一套已存的值。 */
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const regions = familyRegions[family]
  if (!regions.length) return null
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)) }
  const brand = custom.palette
  const touched = Object.keys(custom.params).length
  return <>
    <div className="field-row palette-field">
      <div className="field-label">
        <label>{ui('settings.brandColor')}</label>
        <p>{ui('settings.brandColorHelp')}</p>
      </div>
      <div className="field-control palette-control">
        {/* 第一项是「原版色」：选它等于清掉覆盖，回到该大类自带的强调色。 */}
        <PaletteSwatches stock value={brand} onChange={palette => { if (palette) writeFamilyCustom(family, {palette}); else clearFamilyPalette(family); refresh() }} legend={ui('settings.brandColor')}/>
      </div>
    </div>
    {/* 材质旋钮只对玻璃材质有意义：普通材质没有材质层，调了也看不见。 */}
    {material === 'glass' && <div className="field-row">
      <div className="field-label">
        <label>{ui('settings.materialDetail')}</label>
        <p>{ui('settings.materialDetailHelp')}</p>
      </div>
      <div className="field-control">
        <button type="button" className="button" onClick={() => setDetail(true)}>{ui('settings.materialDetailOpen')}{touched > 0 ? ` (${touched})` : ''}</button>
      </div>
    </div>}
    {detail && <MaterialDetailModal onClose={() => setDetail(false)} onChange={refresh}/>}
  </>
}
