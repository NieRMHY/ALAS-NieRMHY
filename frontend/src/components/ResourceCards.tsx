import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Box, GripVertical, Plus, X } from 'lucide-react'
import type { Resource } from '../api/types'
import { useApp } from '../app/context'
import { readDashboardPrefs, subscribeDashboardPrefs } from '../app/dashboardPrefs'
import type { UiKey } from '../i18n'

export const resourceLabels: Record<string, UiKey> = {Oil: 'resource.Oil', Coin: 'resource.Coin', Gem: 'resource.Gem', Cube: 'resource.Cube', Pt: 'resource.Pt', ActionPoint: 'resource.ActionPoint', YellowCoin: 'resource.YellowCoin', PurpleCoin: 'resource.PurpleCoin', Core: 'resource.Core', Medal: 'resource.Medal', Merit: 'resource.Merit', GuildCoin: 'resource.GuildCoin', Chip: 'resource.Chip'}
const iconBase = import.meta.env.BASE_URL
const iconImages: Record<string, string> = {
  Oil: `${iconBase}oil.webp`,
  Coin: `${iconBase}gold.webp`,
  Gem: `${iconBase}diamond.webp`,
  Cube: `${iconBase}cube.webp`,
  Pt: `${iconBase}pt.webp`,
  ActionPoint: `${iconBase}guild_coin.webp`,
  YellowCoin: `${iconBase}supply_token.webp`,
  PurpleCoin: `${iconBase}special_token.webp`,
  Core: `${iconBase}core_data.webp`,
  Medal: `${iconBase}honor_medal.webp`,
  Merit: `${iconBase}merit.webp`,
  GuildCoin: `${iconBase}stamina.webp`,
}

function ResourceIcon({resourceKey, size = 32}: {resourceKey: string; size?: number}) {
  const src = iconImages[resourceKey]
  return src ? <img className="resource-icon-image" src={src} alt="" width={size} height={size} draggable={false}/> : <Box size={Math.round(size * .62)}/>
}
export const defaultResourceKeys = ['Oil', 'Coin', 'Gem', 'Cube']

export function moveResourceKey(keys: string[], fromKey: string, toKey: string): string[] {
  if (fromKey === toKey) return keys
  const from = keys.indexOf(fromKey)
  const to = keys.indexOf(toKey)
  if (from < 0 || to < 0) return keys
  const next = [...keys]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

function ResourceValue({value, suffix}: {value: string; suffix?: string}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    const container = containerRef.current
    const content = contentRef.current
    if (!container || !content) return
    const fit = () => {
      const available = container.clientWidth
      if (!available) return
      // 先恢复主题字号测量，宽度增加或数字变短后也能恢复正常大小。
      content.style.fontSize = '1em'
      const natural = content.getBoundingClientRect().width
      if (natural > available) content.style.fontSize = `${Math.max(0, available - 1) / natural}em`
    }
    fit()
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(fit)
    })
    observer.observe(container)
    // 字体加载和主题切换也可能改变文字宽度。
    observer.observe(content)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(frame)
    }
  }, [value, suffix])

  return <div className="resource-value" ref={containerRef}>
    <span className="resource-value-content" ref={contentRef}><span>{value}</span>{suffix && <small>/ {suffix}</small>}</span>
  </div>
}

/* 记录时间：当日给时分秒，跨日给月日与小时；超过一年标记为过久。 */
const RECORD_STALE_MS = 365 * 24 * 60 * 60 * 1000

function recordText(value: string | undefined): {text: string; stale: boolean} {
  const at = value ? new Date(value) : null
  if (!at || Number.isNaN(at.getTime())) return {text: '', stale: false}
  if (Date.now() - at.getTime() > RECORD_STALE_MS) return {text: '', stale: true}
  const pad = (count: number) => String(count).padStart(2, '0')
  const now = new Date()
  const sameDay = at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate()
  const text = sameDay ? `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}` : `${pad(at.getMonth() + 1)}-${pad(at.getDate())}-${pad(at.getHours())}`
  return {text, stale: false}
}

export function ResourceCards({resources, selected}: {resources: Resource[]; selected: string[]}) {
  const {ui} = useApp()
  const prefs = useSyncExternalStore(subscribeDashboardPrefs, readDashboardPrefs, readDashboardPrefs)
  const gridRef = useRef<HTMLDivElement>(null)
  const mergedRef = useRef<HTMLElement>(null)

  /* 卡片适应：按容器宽度算一行放得下几张，列数即「卡片数与一排容量」的较小者 ——
     溢出到第二排以后时末排沿用第一排尺寸，总数不足一排时列数就等于卡片数因而仍均分。 */
  useLayoutEffect(() => {
    const grid = gridRef.current
    /* 通用卡片把卡片包成一张大卡，列数要算在真正装卡片的那一层上。 */
    const target = prefs.merged ? mergedRef.current : grid
    if (!grid || !target || !(prefs.fitCards || prefs.merged)) return
    const fit = () => {
      const style = getComputedStyle(target)
      const gap = parseFloat(style.columnGap) || 0
      const min = parseFloat(style.getPropertyValue('--resource-card-min')) || 0
      if (!target.clientWidth || !min) return
      const perRow = Math.max(1, Math.floor((target.clientWidth + gap) / (min + gap)))
      target.style.gridTemplateColumns = `repeat(${Math.min(selected.length, perRow)}, minmax(0, 1fr))`
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(target)
    return () => { observer.disconnect(); target.style.gridTemplateColumns = '' }
  }, [prefs.fitCards, prefs.merged, selected.length])

  const entries = selected.map((key, index) => {
    const resource = resources.find(item => item.name === key)
    const recorded = resource?.record && !resource.record.startsWith('2020-01-01')
    const labelKey = resourceLabels[key]
    const label = labelKey ? ui(labelKey) : resource?.label ?? key
    const limit = resource?.limit
    const total = resource?.total
    const showLimit = typeof limit === 'number' && limit > 0
    const showTotal = !!recorded && !showLimit && resource?.name === 'ActionPoint' && typeof resource.value === 'number' && typeof total === 'number' && Number.isFinite(total) && total >= resource.value
    const value = resource?.value
    const currentText = recorded && value != null ? value.toLocaleString() : '—'
    const totalText = showTotal ? (total as number).toLocaleString() : undefined
    /* 总行动力优先时总量与当前值互换；行动力以外的字段不受影响。 */
    const displayValue = prefs.totalFirst && totalText ? totalText : currentText
    const suffix = prefs.totalFirst && totalText ? currentText : recorded && showLimit ? limit.toLocaleString() : totalText
    const record = recordText(resource?.record)
    const foot = recorded ? (record.stale ? ui('resource.recordedTooOld') : record.text) : ui('resource.waitingSync')
    return {key, index, label, displayValue, suffix, foot}
  })

  const className = ['resource-grid',
    (prefs.fitCards || prefs.merged) && 'resource-fit',
    prefs.fitText && 'resource-fit-text',
    prefs.dense && 'resource-dense'].filter(Boolean).join(' ')

  /* 通用卡片只换外层容器：两种排法共用这段卡片内部渲染。 */
  const cardBody = (entry: typeof entries[number]) => <>
    <div className="resource-heading"><span>{entry.label}</span><div className="resource-image-wrap"><ResourceIcon resourceKey={entry.key} size={32}/></div></div>
    <ResourceValue value={entry.displayValue} suffix={entry.suffix}/>
    <div className="resource-foot">{entry.foot}</div>
  </>

  return <div className={className} ref={gridRef}>{prefs.merged
    ? <section className="resource-card resource-merged" ref={mergedRef}>{entries.map(entry => <section key={entry.key} className={`resource-card resource-merged-item resource-${entry.index % 4}`}>{cardBody(entry)}</section>)}</section>
    : entries.map(entry => <section key={entry.key} className={`resource-card resource-${entry.index % 4}`}>{cardBody(entry)}</section>)}</div>
}
export function ResourceSettings({resources, selected, onChange}: {resources: Resource[]; selected: string[]; onChange: (keys: string[]) => void}) {
  const {ui} = useApp()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [draggingKey, setDraggingKey] = useState<string | null>(null)
  const [dragOrder, setDragOrder] = useState<string[] | null>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const dragOrderRef = useRef<string[] | null>(null)
  const dragPointerRef = useRef<number | null>(null)
  const dragKeyRef = useRef<string | null>(null)
  const dragAnchorRef = useRef<{key: string; card: HTMLElement; pointerX: number; pointerY: number; movedX: number; movedY: number; left: number; top: number} | null>(null)
  const releasedKeyRef = useRef<string | null>(null)
  const pickerDragRef = useRef<string | null>(null)
  const slotsRef = useRef<{key: string; left: number; top: number; right: number; bottom: number}[]>([])
  const rectsRef = useRef<Map<string, {left: number; top: number}>>(new Map())
  const framesRef = useRef<number[]>([])
  const available = resources.filter(resource => !selected.includes(resource.name))
  const displayed = dragOrder ?? selected

  function captureRects() {
    const rects = new Map<string, DOMRect>()
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => rects.set(card.dataset.resourceKey ?? '', card.getBoundingClientRect()))
    return rects
  }

  /* 换位动画的基准取布局位置：卡片身上的位移属于绘制结果，不是布局。 */
  function captureLayout() {
    const positions = new Map<string, {left: number; top: number}>()
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => positions.set(card.dataset.resourceKey ?? '', {left: card.offsetLeft, top: card.offsetTop}))
    return positions
  }

  /* 跟手：落点取自按下的位置加指针位移，再减去卡片当前的布局位置，与它所在格子无关。 */
  function followPointer() {
    const anchor = dragAnchorRef.current
    if (!anchor) return
    anchor.card.style.transition = 'none'
    anchor.card.style.translate = `${anchor.left + anchor.movedX - anchor.pointerX - anchor.card.offsetLeft}px ${anchor.top + anchor.movedY - anchor.pointerY - anchor.card.offsetTop}px`
  }

  /* 换位用 FLIP：重排后先把卡片移回原位，下一帧再放开，位移走独立的 translate 属性，
     与拖起态的缩放互不覆盖；过渡结束后清掉内联值，落定不留痕迹。 */
  useLayoutEffect(() => {
    const before = rectsRef.current
    const moved: HTMLElement[] = []
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => {
      /* 被拖动的卡片不参与换位动画，改为按新布局重算跟手位移并重新捕获指针；
         刚松手的那张只跳过动画。 */
      if (card.dataset.resourceKey === dragKeyRef.current) {
        followPointer()
        const pointerId = dragPointerRef.current
        if (pointerId !== null && !card.hasPointerCapture(pointerId)) card.setPointerCapture(pointerId)
        return
      }
      if (card.dataset.resourceKey === releasedKeyRef.current) return
      const previous = before.get(card.dataset.resourceKey ?? '')
      if (!previous) return
      const dx = previous.left - card.offsetLeft
      const dy = previous.top - card.offsetTop
      if (!dx && !dy) return
      /* 起点值瞬时到位，随后的放开才由过渡接管。 */
      card.style.transition = 'none'
      card.style.translate = `${dx}px ${dy}px`
      moved.push(card)
    })
    rectsRef.current = captureLayout()
    releasedKeyRef.current = null
    if (!moved.length) return
    /* 放开落在下一帧：中间隔着一次样式更新，过渡才会成立。 */
    framesRef.current.push(requestAnimationFrame(() => {
      framesRef.current.push(requestAnimationFrame(() => {
        moved.forEach(card => {
          card.style.transition = ''
          card.style.translate = 'none'
          card.addEventListener('transitionend', event => {
            if (event.propertyName === 'translate' && card.style.translate === 'none') card.style.translate = ''
          }, {once: true})
        })
      }))
    }))
  }, [dragOrder])

  useEffect(() => () => {
    framesRef.current.forEach(cancelAnimationFrame)
    framesRef.current = []
  }, [])

  /* 上层把顺序写回同序后交还显示权：此时两边一致，DOM 不再变化。 */
  useEffect(() => {
    if (dragOrder && dragOrder.length === selected.length && dragOrder.every((key, index) => key === selected[index])) setDragOrder(null)
  }, [dragOrder, selected])

  function add(key: string) {
    if (!selected.includes(key)) onChange([...selected, key])
  }
  function remove(key: string) {
    onChange(selected.filter(item => item !== key))
  }
  function finishDrag(pointerId: number, apply: boolean) {
    if (dragPointerRef.current !== pointerId) return
    const next = dragOrderRef.current
    /* 松手结算：跟手的位移交回过渡，卡片滑入所在格子。 */
    const anchor = dragAnchorRef.current
    if (anchor) {
      releasedKeyRef.current = anchor.key
      anchor.card.style.transition = ''
      anchor.card.style.translate = 'none'
      anchor.card.addEventListener('transitionend', event => {
        if (event.propertyName === 'translate' && anchor.card.style.translate === 'none') anchor.card.style.translate = ''
      }, {once: true})
    }
    dragAnchorRef.current = null
    dragPointerRef.current = null
    dragOrderRef.current = null
    dragKeyRef.current = null
    slotsRef.current = []
    setDraggingKey(null)
    if (apply) {
      /* 松手落在未展示区，这张卡就此移出仪表盘；其余情况按拖动后的顺序提交。 */
      const dropped = anchor && document.elementFromPoint(anchor.movedX, anchor.movedY)?.closest('.resource-picker')
      if (dropped) { remove(anchor.key); setDragOrder(null) }
      else if (next && next.some((key, index) => key !== selected[index])) onChange(next)
    } else setDragOrder(null)
  }

  return <div className="resource-settings">
    <div className="resource-settings-heading"><div><strong>{ui('resource.cards')}</strong><span>{ui('resource.cardsHint')}</span></div><button type="button" className="button" onClick={() => onChange(defaultResourceKeys)}>{ui('resource.restoreDefault')}</button></div>
    <div className="resource-card-editor" ref={editorRef}>
      {displayed.map(key => {
        const resource = resources.find(item => item.name === key)
          const labelKey = resourceLabels[key]
          const label = labelKey ? ui(labelKey) : resource?.label ?? key
        return <div key={key} data-resource-key={key} className={`resource-editor-card${draggingKey === key ? ' dragging' : ''}`}
          onPointerDown={event => {
            if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return
            event.preventDefault()
            event.currentTarget.setPointerCapture(event.pointerId)
            dragPointerRef.current = event.pointerId
            dragKeyRef.current = key
            dragOrderRef.current = [...selected]
            /* 格子位置与各卡矩形都在按下时量一次：拖动期间卡片会重排，实时量会取到滞后一帧的 DOM。 */
            const rects = captureRects()
            dragAnchorRef.current = {key, card: event.currentTarget, pointerX: event.clientX, pointerY: event.clientY, movedX: event.clientX, movedY: event.clientY, left: event.currentTarget.offsetLeft, top: event.currentTarget.offsetTop}
            rectsRef.current = captureLayout()
            slotsRef.current = [...rects].map(([slotKey, rect]) => ({key: slotKey, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom}))
            setDragOrder([...selected])
            setDraggingKey(key)
          }}
          onPointerMove={event => {
            const sourceKey = dragKeyRef.current
            const order = dragOrderRef.current
            const anchor = dragAnchorRef.current
            if (dragPointerRef.current !== event.pointerId || !sourceKey || !order || !anchor) return
            anchor.movedX = event.clientX
            anchor.movedY = event.clientY
            followPointer()
            const index = slotsRef.current.findIndex(slot => event.clientX >= slot.left && event.clientX <= slot.right && event.clientY >= slot.top && event.clientY <= slot.bottom)
            const target = index < 0 ? undefined : order[index]
            if (!target) return
            const next = moveResourceKey(order, sourceKey, target)
            if (next === order) return
            dragOrderRef.current = next
            setDragOrder(next)
          }}
          onPointerUp={event => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
            finishDrag(event.pointerId, true)
          }}
          onPointerCancel={event => finishDrag(event.pointerId, false)}>
          <span className="resource-editor-grip" aria-hidden="true"><GripVertical size={16}/></span>
          <span className="resource-editor-icon resource-editor-icon-image"><ResourceIcon resourceKey={key} size={30}/></span>
          <span className="resource-editor-label">{label}</span>
          <button type="button" className="resource-editor-remove" aria-label={ui('resource.remove', {label})} title={ui('resource.remove', {label})} onClick={() => remove(key)}><X size={15}/></button>
        </div>
      })}
      <button type="button" className={`resource-editor-card resource-editor-add${pickerOpen ? ' open' : ''}`} onClick={() => setPickerOpen(open => !open)}><span className="resource-editor-add-icon"><Plus size={18}/></span><span>{ui('resource.addCard')}</span></button>
    </div>
    {pickerOpen && <div className="resource-picker">{available.length ? <div className="resource-picker-grid">{available.map(resource => {
      const labelKey = resourceLabels[resource.name]
      const label = labelKey ? ui(labelKey) : resource.label ?? resource.name
      return <button type="button" key={resource.name} className="resource-editor-card resource-picker-card" onPointerDown={event => { if (event.button !== 0) return
            event.currentTarget.setPointerCapture(event.pointerId)
            pickerDragRef.current = resource.name }}
          /* 从「未展示」拖进已展示区，等于把这张卡加回来。 */
          onPointerUp={event => { const key = pickerDragRef.current; pickerDragRef.current = null
            if (key && document.elementFromPoint(event.clientX, event.clientY)?.closest(".resource-card-editor")) add(key) }}
          onClick={() => add(resource.name)}><span className="resource-editor-icon resource-editor-icon-image"><ResourceIcon resourceKey={resource.name} size={28}/></span><span>{label}</span><Plus size={15}/></button>
    })}</div> : <div className="resource-picker-empty">{ui('resource.allAdded')}</div>}</div>}
  </div>
}
