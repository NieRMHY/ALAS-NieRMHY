/**
 * @fileoverview 分段选择器控件组件。
 */

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'

type Option<T extends string> = {value: T; label: ReactNode}

/** 共用监控页的分段样式，按实际按钮尺寸定位滑块。 */
export function SegmentedControl<T extends string>({label, value, options, onChange, onItemContextMenu, onItemPointerDown, onItemMove, itemClassName, className = '', trailing}: {
  label: string
  value: T
  options: Option<T>[]
  onChange: (value: T) => void
  className?: string
  /** 逐项的右键回调。 */
  onItemContextMenu?: (value: T) => void
  /** 逐项的指针按下回调，用于在条目上起拖。 */
  onItemPointerDown?: (value: T, event: React.PointerEvent<HTMLButtonElement>) => void
  /** 逐项的方向键移动回调，方向键配合 Alt 时触发。 */
  onItemMove?: (value: T, delta: number) => void
  /** 逐项的附加类名，用于标记禁用这类状态。 */
  itemClassName?: (value: T) => string
  /** 固定排在条目之后的附加控件，不参与逐项回调与键盘导航。 */
  trailing?: ReactNode
}) {
  const {theme} = useApp()
  const simple = !usesMaterial(theme)
  const ref = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({x: 0, y: 0, width: 0, height: 0})
  useLayoutEffect(() => {
    const control = ref.current
    if (!control || simple) return
    const update = () => {
      const active = control.querySelector<HTMLButtonElement>('[aria-selected="true"]')
      if (active) setIndicator({x: active.offsetLeft, y: active.offsetTop, width: active.offsetWidth, height: active.offsetHeight})
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(control)
    control.querySelectorAll('button').forEach(button => observer.observe(button))
    return () => observer.disconnect()
  }, [value, options, simple])
  return <div ref={ref} className={`monitor-segmented ${className}`.trim()} role="tablist" aria-label={label}>
    {/* 测量后才挂载滑块，避免从零尺寸向选中项播放入场过渡。 */}
    {!simple && indicator.width > 0 && <span className="segmented-indicator" aria-hidden="true" style={{transform: `translate3d(${indicator.x}px, ${indicator.y}px, 0)`, width: indicator.width, height: indicator.height}}/>}
    {options.map((option, index) => <button type="button" key={option.value} role="tab" className={itemClassName?.(option.value)} onPointerDown={event => onItemPointerDown?.(option.value, event)} onContextMenu={onItemContextMenu ? event => {event.preventDefault(); onItemContextMenu(option.value)} : undefined} aria-selected={value === option.value} tabIndex={value === option.value ? 0 : -1} onClick={() => onChange(option.value)} onKeyDown={event => {
      if (event.altKey && onItemMove && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
        event.preventDefault()
        onItemMove(option.value, event.key === 'ArrowRight' ? 1 : -1)
        return
      }
      const next = event.key === 'ArrowRight' ? (index + 1) % options.length : event.key === 'ArrowLeft' ? (index - 1 + options.length) % options.length : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : -1
      if (next < 0) return
      event.preventDefault()
      onChange(options[next].value)
      const button = ref.current?.querySelectorAll<HTMLButtonElement>('button')[next]
      button?.focus({preventScroll: true})
      button?.scrollIntoView({block: 'nearest', inline: 'nearest'})
    }}>{option.label}</button>)}
  {trailing}
  </div>
}
