import { useEffect, useSyncExternalStore } from 'react'
import { useApp } from './context'
import { usesMaterial } from './theme'
import { motionReducedActive, subscribeMotionPrefs } from './motionPrefs'

const reducedQuery = '(prefers-reduced-motion: reduce)'

function subscribeReduced(listener: () => void) {
  const unsubscribePrefs = subscribeMotionPrefs(listener)
  const media = window.matchMedia(reducedQuery)
  media.addEventListener('change', listener)
  return () => {
    unsubscribePrefs()
    media.removeEventListener('change', listener)
  }
}

export function pointerFraction(client: number, start: number, size: number): number {
  if (size <= 0) return 0.5
  return Math.max(0, Math.min(1, (client - start) / size))
}

/** 顶栏「光随鼠标」掠光：一帧最多写一次 CSS 变量（绝不做 setState），
 *  由 motion.css 的 .topbar::after 消费 --mx/--my。
 *  仅在材质主题（light/dark）启用；减弱动效或非精细指针环境不挂监听。 */
export function useGlassPointerLight() {
  const { theme } = useApp()
  const enabled = usesMaterial(theme)
  const reduced = useSyncExternalStore(subscribeReduced, motionReducedActive, () => true)
  useEffect(() => {
    if (!enabled || reduced) return
    if (!window.matchMedia('(pointer: fine)').matches) return
    const target = document.querySelector<HTMLElement>('.topbar')
    if (!target) return
    let raf = 0
    let clientX: number | null = null
    let clientY: number | null = null
    const style = document.documentElement.style
    const flush = () => {
      raf = 0
      const rect = target.getBoundingClientRect()
      const x = clientX === null ? 0.5 : pointerFraction(clientX, rect.left, rect.width)
      const y = clientY === null ? 0.35 : pointerFraction(clientY, rect.top, rect.height)
      style.setProperty('--mx', `${(x * 100).toFixed(2)}%`)
      style.setProperty('--my', `${(y * 100).toFixed(2)}%`)
    }
    const onMove = (event: PointerEvent) => {
      clientX = event.clientX
      clientY = event.clientY
      if (!raf) raf = requestAnimationFrame(flush)
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    flush()
    return () => {
      window.removeEventListener('pointermove', onMove)
      if (raf) cancelAnimationFrame(raf)
      style.removeProperty('--mx')
      style.removeProperty('--my')
    }
  }, [enabled, reduced])
}
