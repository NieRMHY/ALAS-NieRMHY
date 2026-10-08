/**
 * @fileoverview 材质检视器状态：整站悬浮/停靠的开关、停靠与最小化三态，跨组件共享。
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
    /* 存储不可用时用默认值：停靠与否只影响观感，不必阻断渲染。 */
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
  const previous = state
  state = { ...state, ...patch }
  if (state.docked !== previous.docked) {
    try {
      localStorage.setItem(STORAGE_DOCKED_KEY, state.docked ? '1' : '0')
    } catch {
      /* 存储不可用时仅当前会话有效 */
    }
  }
  listeners.forEach(l => l())
}

export const openMaterialInspector = () => publish({ open: true, minimized: false })
export const closeMaterialInspector = () => publish({ open: false })
export const toggleMaterialInspectorDocked = () => publish({ docked: !state.docked })
export const toggleMaterialInspectorMinimized = () => publish({ minimized: !state.minimized })
export const setMaterialInspectorMinimized = (minimized: boolean) => publish({ minimized })
