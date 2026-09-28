/**
 * @fileoverview 侧边栏任务分组与导航菜单入口组件。
 */

import { useSyncExternalStore } from 'react'
import { useApp } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { isDesktopDevice, TaskNavFlyout } from './TaskNavFlyout'
import { TaskNavTree } from './TaskNavTree'

function subscribeDesktop(callback: () => void) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener('resize', callback)
  const hoverMedia = typeof window.matchMedia === 'function' ? window.matchMedia('(hover: none)') : null
  hoverMedia?.addEventListener('change', callback)
  return () => {
    window.removeEventListener('resize', callback)
    hoverMedia?.removeEventListener('change', callback)
  }
}

/**
 * 响应式监听当前是否为桌面端（宽屏且支持鼠标悬停）。
 * SSR / 无 window 环境下默认视作桌面端以保证首屏和已有测试一致。
 */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeDesktop,
    isDesktopDevice,
    () => true
  )
}

export type TaskNavProps = {
  defaultOpenKey?: string
  isDesktop?: boolean
  onNavigate?: () => void
}

/**
 * 侧栏任务菜单分流：
 * 1. 经典主题（usesLegacyLayout）在任何设备下均使用树状折叠菜单（TaskNavTree）。
 * 2. 移动端/窄屏（!isDesktop，即宽度 <= 950px 或触屏设备）下，所有主题参考经典主题
 *    使用内嵌树状折叠菜单（TaskNavTree），避免弹出悬浮菜单遮挡主内容。
 * 3. 电脑宽屏端，现代主题继续使用向右浮出的二级菜单（TaskNavFlyout）。
 */
export function TaskNav({ defaultOpenKey, isDesktop: isDesktopProp, onNavigate }: TaskNavProps = {}) {
  const { theme } = useApp()
  const responsiveDesktop = useIsDesktop()
  const isDesktop = isDesktopProp ?? responsiveDesktop

  const useTreeNav = usesLegacyLayout(theme) || !isDesktop

  return useTreeNav
    ? <TaskNavTree defaultOpenKey={defaultOpenKey} onNavigate={onNavigate} />
    : <TaskNavFlyout defaultOpenKey={defaultOpenKey} onNavigate={onNavigate} />
}

