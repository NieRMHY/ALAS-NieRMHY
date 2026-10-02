/**
 * @fileoverview 全局真实例材质细节检视器：叠加在当前真实页面/真实例上方，实时调整 7 大区域 × 5 项材质属性。
 */

import { useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Dock,
  Image as ImageIcon,
  Minimize2,
  PanelRightClose,
  Sliders,
  Sparkles,
  X,
} from 'lucide-react'

import { useApp } from '../app/context'
import { DEFAULT_BACKGROUND_URLS, getBackground, setBackgroundUrls, subscribeBackground } from '../app/background'
import {
  closeMaterialInspector,
  getMaterialInspector,
  setMaterialInspectorMinimized,
  subscribeMaterialInspector,
  toggleMaterialInspectorDocked,
  toggleMaterialInspectorMinimized,
} from '../app/materialInspectorState'
import { applyCustomLayer, familyOf, showsWallpaper } from '../app/theme'
import {
  clearFamilyKnob,
  clearFamilyRegion,
  readFamilyCustom,
  resetFamilyCustom,
  writeFamilyCustom,
  type FamilyCustom,
} from '../app/themeCustom'
import { familyRegions, type RegionId } from '../app/themeKnobs'
import { MaterialDetailPanel } from './ThemeCustomPreference'

export function MaterialInspector() {
  const inspector = useSyncExternalStore(subscribeMaterialInspector, getMaterialInspector)
  const background = useSyncExternalStore(subscribeBackground, getBackground)
  const { ui, theme } = useApp()
  const location = useLocation()
  const navigate = useNavigate()

  const family = familyOf(theme)
  const [custom, setCustom] = useState<FamilyCustom>(() => readFamilyCustom(family))
  useEffect(() => setCustom(readFamilyCustom(family)), [family])
  const [activeRegion, setActiveRegion] = useState<RegionId>('surface')
  const [showModal, setShowModal] = useState(false)
  const [showMenu, setShowMenu] = useState(false)

  if (!inspector.open) return null

  const refresh = () => {
    applyCustomLayer()
    setCustom(readFamilyCustom(family))
  }

  const wallpaperActive = showsWallpaper(theme, background.source)

  const handleRegionSelect = (r: RegionId) => {
    setActiveRegion(r)
    if (r === 'modal') {
      setShowModal(true)
      setShowMenu(false)
    } else if (r === 'menu') {
      setShowMenu(true)
      setShowModal(false)
    } else {
      setShowModal(false)
      setShowMenu(false)
    }
  }

  const isDocked = inspector.docked
  const isMinimized = inspector.minimized

  const overlay = (
    <>
      <div
        className={`mock-preview-inspector material-inspector ${
          isDocked ? 'is-docked' : 'is-floating'
        } ${isMinimized ? 'is-minimized' : ''}`}
        role="dialog"
        aria-label={ui('settings.materialDetail')}
      >
        {isMinimized ? (
          <button
            type="button"
            className="inspector-expand-button"
            onClick={toggleMaterialInspectorMinimized}
            title={ui('settings.materialDetail')}
          >
            <Sliders size={16} />
            <span>{ui('settings.materialDetail')}</span>
          </button>
        ) : (
          <div className="inspector-panel-inner">
            <header className="inspector-header">
              <div className="inspector-header-left">
                <Sliders size={16} className="inspector-icon" />
                <span className="inspector-title">{ui('settings.materialDetail')}</span>
                <span className="inspector-badge">
                  {family === 'new' ? 'Apple HIG' : 'Google M3'}
                </span>
              </div>
              <div className="inspector-header-right">
                {location.pathname !== '/interface' && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => navigate('/interface')}
                    title="返回界面设置"
                    aria-label="返回界面设置"
                  >
                    <ArrowLeft size={15} />
                  </button>
                )}
                <button
                  type="button"
                  className="icon-button"
                  onClick={toggleMaterialInspectorDocked}
                  title={isDocked ? '切换为悬浮模式' : '停靠在右侧'}
                  aria-label={isDocked ? '切换为悬浮模式' : '停靠在右侧'}
                >
                  {isDocked ? <PanelRightClose size={15} /> : <Dock size={15} />}
                </button>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => setMaterialInspectorMinimized(true)}
                  title="最小化"
                  aria-label="最小化"
                >
                  <Minimize2 size={15} />
                </button>
                <button
                  type="button"
                  className="icon-button"
                  onClick={closeMaterialInspector}
                  title="关闭"
                  aria-label="关闭"
                >
                  <X size={16} />
                </button>
              </div>
            </header>

            {!wallpaperActive && (
              <div
                style={{
                  margin: '8px 14px 0',
                  padding: '8px 12px',
                  borderRadius: '10px',
                  background: 'color-mix(in srgb, var(--theme-warning, #f59e0b) 12%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--theme-warning, #f59e0b) 28%, transparent)',
                  fontSize: '12px',
                  color: 'var(--theme-text)',
                  lineHeight: '1.45',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <ImageIcon size={14} style={{ color: 'var(--theme-warning, #f59e0b)', flexShrink: 0 }} />
                  <strong>当前未启用壁纸背景</strong>
                </div>
                <div>纯单色底色下无法观察到毛玻璃滤镜（模糊与饱和度）的折射效果。</div>
                <button
                  type="button"
                  className="button secondary"
                  style={{ height: '26px', fontSize: '11.5px', alignSelf: 'flex-start', marginTop: '2px' }}
                  onClick={() => {
                    setBackgroundUrls(DEFAULT_BACKGROUND_URLS, 'image')
                    refresh()
                  }}
                >
                  <Sparkles size={12} />
                  一键开启默认二次元壁纸
                </button>
              </div>
            )}

            <div className="inspector-body">
              <div
                style={{
                  display: 'flex',
                  gap: '8px',
                  marginBottom: '10px',
                  padding: '0 4px',
                }}
              >
                <button
                  type="button"
                  className={`button ${showModal ? 'primary' : 'secondary'}`}
                  style={{ flex: 1, height: '30px', fontSize: '12px' }}
                  onClick={() => {
                    setShowModal(m => !m)
                    setShowMenu(false)
                  }}
                >
                  {showModal ? '关闭测试弹窗' : '测试弹窗 (Modal)'}
                </button>
                <button
                  type="button"
                  className={`button ${showMenu ? 'primary' : 'secondary'}`}
                  style={{ flex: 1, height: '30px', fontSize: '12px' }}
                  onClick={() => {
                    setShowMenu(m => !m)
                    setShowModal(false)
                  }}
                >
                  {showMenu ? '收起测试选单' : '测试选单 (Menu)'}
                </button>
              </div>

              <MaterialDetailPanel
                regions={familyRegions[family]}
                custom={custom}
                ui={ui}
                initialRegion={activeRegion}
                onRegionChange={handleRegionSelect}
                onKnob={(id, value) => {
                  writeFamilyCustom(family, { params: { [id]: value } })
                  refresh()
                }}
                onResetKnob={id => {
                  clearFamilyKnob(family, id)
                  refresh()
                }}
                onResetRegion={r => {
                  clearFamilyRegion(family, r)
                  refresh()
                }}
                onResetAll={() => {
                  resetFamilyCustom(family)
                  refresh()
                }}
              />
            </div>

            <footer className="inspector-footer">
              <button
                type="button"
                className="button primary"
                style={{ width: '100%' }}
                onClick={closeMaterialInspector}
              >
                完成调节
              </button>
            </footer>
          </div>
        )}
      </div>

      {/* 测试用弹出菜单 (menu 区域) */}
      {showMenu && (
        <div
          className="mock-popover-menu"
          style={{
            position: 'fixed',
            top: '70px',
            right: isDocked && !isMinimized ? '435px' : '30px',
            zIndex: 140,
            minWidth: '220px',
            borderRadius: 'var(--theme-menu-radius, 14px)',
            background: 'var(--theme-menu-bg, var(--surface))',
            WebkitBackdropFilter: 'var(--theme-menu-filter, blur(28px))',
            backdropFilter: 'var(--theme-menu-filter, blur(28px))',
            boxShadow: 'var(--theme-menu-shadow, 0 16px 40px rgba(0,0,0,0.28))',
            border: '1px solid var(--theme-glass-edge, var(--border))',
            padding: '8px',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
          }}
        >
          <div style={{ padding: '6px 10px', fontSize: '12px', fontWeight: 600, opacity: 0.7 }}>
            测试选单 (Menu 材质区)
          </div>
          <button
            type="button"
            className="menu-item"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 10px',
              borderRadius: '8px',
              border: 'none',
              background: 'transparent',
              color: 'var(--theme-text)',
              cursor: 'pointer',
              fontSize: '13px',
              textAlign: 'left',
            }}
          >
            <span>选项一：常规项目</span>
            <Check size={14} style={{ color: 'var(--accent)' }} />
          </button>
          <button
            type="button"
            className="menu-item"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 10px',
              borderRadius: '8px',
              border: 'none',
              background: 'transparent',
              color: 'var(--theme-text)',
              cursor: 'pointer',
              fontSize: '13px',
              textAlign: 'left',
            }}
          >
            <span>选项二：级联菜单</span>
            <ChevronRight size={14} style={{ opacity: 0.5 }} />
          </button>
          <div style={{ height: '1px', background: 'var(--theme-glass-edge, var(--border))', margin: '4px 0' }} />
          <button
            type="button"
            className="menu-item danger"
            style={{
              display: 'flex',
              alignItems: 'center',
              padding: '8px 10px',
              borderRadius: '8px',
              border: 'none',
              background: 'transparent',
              color: 'var(--theme-danger, #ef4444)',
              cursor: 'pointer',
              fontSize: '13px',
              textAlign: 'left',
            }}
            onClick={() => setShowMenu(false)}
          >
            <span>关闭选单</span>
          </button>
        </div>
      )}

      {/* 测试用弹窗 (modal 区域) */}
      {showModal && (
        <div
          className="mock-modal-scrim"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 135,
            background: 'rgba(0, 0, 0, 0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={e => {
            if (e.target === e.currentTarget) setShowModal(false)
          }}
        >
          <div
            className="modal"
            style={{
              width: '460px',
              maxWidth: '90vw',
              margin: 'auto',
              background: 'var(--theme-modal-bg, var(--surface))',
              color: 'var(--theme-text)',
              borderRadius: 'var(--theme-modal-radius, 24px)',
              boxShadow: 'var(--theme-modal-shadow, 0 24px 64px rgba(0,0,0,0.36))',
              WebkitBackdropFilter: 'var(--theme-modal-filter, blur(28px))',
              backdropFilter: 'var(--theme-modal-filter, blur(28px))',
              border: '1px solid var(--theme-glass-edge, var(--border))',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h3 style={{ margin: 0, fontSize: '17px', fontWeight: 650 }}>
                测试弹窗 (Modal 材质区)
              </h3>
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowModal(false)}
                title="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <p style={{ margin: 0, fontSize: '13.5px', lineHeight: 1.6, opacity: 0.85 }}>
              这是一个覆盖在真实例上方的测试弹窗。您可以调节右侧「弹窗 (modal)」区域的不透明度、模糊度、饱和度、圆角和投影大小，观察本弹窗的实时渲染效果。
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button
                type="button"
                className="button secondary"
                onClick={() => setShowModal(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="button primary"
                onClick={() => setShowModal(false)}
              >
                确定并关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )

  if (typeof document !== 'undefined' && document.body) {
    return createPortal(overlay, document.body)
  }
  return overlay
}
