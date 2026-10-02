import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sliders, Tv } from 'lucide-react'

import { useApp } from '../app/context'
import { openMaterialInspector } from '../app/materialInspectorState'
import { applyCustomLayer, familyOf } from '../app/theme'
import { clearFamilyKnob, clearFamilyRegion, readFamilyCustom, resetFamilyCustom, writeFamilyCustom, type FamilyCustom } from '../app/themeCustom'
import { familyRegions } from '../app/themeKnobs'
import { MaterialDetailPanel } from './ThemeCustomPreference'
import { MockInstancePreview } from './MockInstancePreview'
import { Modal } from './ui'

/** 材质细节二级菜单：设置页与运行总览共用同一个弹窗，谁需要就在谁那里挂一个入口。
    支持在弹窗内一键切换到真实例悬浮调节，亦支持全真假实例预览模式。 */
export function MaterialDetailModal({onClose, onChange, defaultPreview = false}: {onClose: () => void; onChange?: () => void; defaultPreview?: boolean}) {
  const {ui, theme, instances} = useApp()
  const navigate = useNavigate()
  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  const [preview, setPreview] = useState(defaultPreview)

  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const refresh = () => { applyCustomLayer(); setCustom(readFamilyCustom(family)); onChange?.() }

  if (preview) {
    return <MockInstancePreview onClose={() => { setPreview(false); refresh() }} />
  }

  return <Modal title={ui('settings.materialDetail')} onClose={onClose} className="material-detail-modal">
    <div style={{display: 'flex', justifyContent: 'flex-end', gap: '8px', marginBottom: '12px', flexWrap: 'wrap'}}>
      <button
        type="button"
        className="button secondary"
        style={{display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', height: '34px', padding: '0 14px'}}
        onClick={() => {
          onClose()
          openMaterialInspector()
          const target = instances[0]?.name ? `/i/${instances[0].name}/overview` : '/'
          navigate(target)
        }}
        title={ui('settings.materialLiveOnInstanceHelp')}
      >
        <Sliders size={15} style={{color: 'var(--accent)'}} />
        <span>{ui('settings.materialLiveOnInstance')}</span>
      </button>
      <button
        type="button"
        className="button secondary"
        style={{display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', height: '34px', padding: '0 14px', opacity: 0.85}}
        onClick={() => setPreview(true)}
        title={ui('settings.materialLivePreviewHelp')}
      >
        <Tv size={15} />
        <span>{ui('settings.materialLivePreview')}</span>
      </button>
    </div>
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
