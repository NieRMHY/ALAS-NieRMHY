import { useEffect, useState } from 'react'
import { Palette } from 'lucide-react'

import { useApp } from '../app/context'
import { applyCustomLayer, familyOf } from '../app/theme'
import { clearFamilyKnob, clearFamilyRegion, readFamilyCustom, resetFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { familyRegions } from '../app/themeKnobs'
import { MaterialDetailPanel } from './ThemeCustomPreference'
import { Modal } from './ui'

/** 材质细节二级菜单：设置页与运行总览共用同一个弹窗，谁需要就在谁那里挂一个入口。
    onChange 用于让调用方同步自己那份状态（设置页要更新入口上的已调项数）。 */
export function MaterialDetailModal({onClose, onChange}: {onClose: () => void; onChange?: () => void}) {
  const {ui, theme} = useApp()
  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)); onChange?.() }
  return <Modal title={ui('settings.materialDetail')} onClose={onClose} className="material-detail-modal">
    <MaterialDetailPanel
      regions={familyRegions[family]}
      custom={custom}
      ui={ui}
      onKnob={(id, value) => { writeFamilyCustom(family, {params: {[id]: value}}); refresh() }}
      onResetKnob={id => { clearFamilyKnob(family, id); refresh() }}
      onResetRegion={region => { clearFamilyRegion(family, region); refresh() }}
      onResetAll={() => { resetFamilyCustom(family); refresh() }}
    />
  </Modal>
}

/** 侧栏里的低调入口：挂在「运行总览 / 资源统计」下面，图标与它们对齐（同一个调色盘图标）。
    常态隐藏，鼠标移到这一行或键盘聚焦时才出现；只在有区域材质的家族 + 玻璃材质下渲染。 */
export function MaterialQuickButton() {
  const {ui, theme, material} = useApp()
  const [open, setOpen] = useState(false)
  if (material !== 'glass' || !familyRegions[familyOf(theme)].length) return null
  return <>
    <div className="material-quick-slot">
      <button
        type="button"
        className="material-quick-button"
        title={ui('settings.materialDetail')}
        aria-label={ui('settings.materialDetail')}
        onClick={() => setOpen(true)}
      >
        <Palette size={17} aria-hidden="true"/>
      </button>
    </div>
    {open && <MaterialDetailModal onClose={() => setOpen(false)}/>}
  </>
}
