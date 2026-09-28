/**
 * @fileoverview 全局毛玻璃材质背景层挂载组件。
 */

import { lazy, Suspense, useSyncExternalStore } from 'react'
import { getBackground, subscribeBackground } from '../app/background'
import { useApp } from '../app/context'
import { showsWallpaper, usesMaterial } from '../app/theme'

const ClassicGlass = lazy(() => import('./ClassicGlass').then(module => ({default: module.ClassicGlass})))
const Wallpaper = lazy(() => import('./Wallpaper').then(module => ({default: module.Wallpaper})))

/** 朴素主题不挂载 Apple 装饰层；壁纸对两个有材质轴的家族都开放，按需延迟加载。 */
export function GlassMaterial() {
  const {theme} = useApp()
  return usesMaterial(theme) ? <Suspense fallback={null}><ClassicGlass/></Suspense> : null
}

export function ThemeWallpaper() {
  const {theme} = useApp()
  const background = useSyncExternalStore(subscribeBackground, getBackground)
  return showsWallpaper(theme, background.source) ? <Suspense fallback={null}><Wallpaper/></Suspense> : null
}
