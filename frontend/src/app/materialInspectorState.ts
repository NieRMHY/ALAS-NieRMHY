/**
 * @fileoverview 材质细节检视器状态管理：支持在真实例及各页面上悬浮/停靠展示。
 */

export interface MaterialInspectorState {
  open: boolean
  docked: boolean
  minimized: boolean
}

const STORAGE_DOCKED_KEY = 'azurpilot.materialInspector.docked'

const readDocked = (): boolean => {
  try {
    const val = localStorage.getItem(STORAGE_DOCKED_KEY)
    return val !== null ? val === '1' : true
  } catch {
    return true
  }
}

let state: MaterialInspectorState = {
  open: false,
  docked: readDocked(),
  minimized: false,
}

const listeners = new Set<() => void>()

export const getMaterialInspector = () => state

export function subscribeMaterialInspector(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function publish(patch: Partial<MaterialInspectorState>) {
  state = { ...state, ...patch }
  try {
    localStorage.setItem(STORAGE_DOCKED_KEY, state.docked ? '1' : '0')
  } catch {
    /* 存储不可用时仅当前会话有效 */
  }
  listeners.forEach(l => l())
}

export const openMaterialInspector = () => publish({ open: true, minimized: false })
export const closeMaterialInspector = () => publish({ open: false })
export const toggleMaterialInspectorDocked = () => publish({ docked: !state.docked })
export const toggleMaterialInspectorMinimized = () => publish({ minimized: !state.minimized })
export const setMaterialInspectorMinimized = (minimized: boolean) => publish({ minimized })
