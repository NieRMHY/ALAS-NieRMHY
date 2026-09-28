/**
 * @fileoverview 统计页多页面组合链槽位编辑组件。
 */

import { Plus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useApp } from '../app/context'
import type { PageId } from '../app/statisticsLayout'
import { Select } from './Select'

/** 页面组合的槽位区：一行一条链，行尾是待填入的空槽位；行内不足两页时不参与组合。 */
export function PageChainSlots({rows, labels, options, onPlace, onRemove}: {
  rows: PageId[][]
  labels: Record<string, string>
  options: PageId[]
  onPlace: (rowIndex: number, page: PageId) => void
  onRemove: (page: PageId) => void
}) {
  const {ui} = useApp()
  const [picking, setPicking] = useState<string | null>(null)
  const slots = useRef<HTMLDivElement>(null)

  /* 选择列表是顶层弹出层，它自己收起时不会通知这里：指针按在区外、焦点离开或按 Esc 都收回空槽位。 */
  useEffect(() => {
    if (picking === null) return
    const away = (event: Event) => {
      if (event.target instanceof Node && slots.current?.contains(event.target)) return
      setPicking(null)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPicking(null)
    }
    document.addEventListener('pointerdown', away, true)
    document.addEventListener('focusin', away, true)
    document.addEventListener('keydown', escape, true)
    return () => {
      document.removeEventListener('pointerdown', away, true)
      document.removeEventListener('focusin', away, true)
      document.removeEventListener('keydown', escape, true)
    }
  }, [picking])

  const picker = (rowIndex: number) => <Select
    openOnFocus
    className="statistics-chain-picker"
    aria-label={ui('stats.chainPick')}
    value=""
    onChange={event => {
      const page = event.target.value as PageId
      setPicking(null)
      if (page) onPlace(rowIndex, page)
    }}
  >
    <option value="">{ui('stats.chainPick')}</option>
    {options.map(page => <option value={page} key={page}>{labels[page]}</option>)}
  </Select>

  const addSlot = (key: string, rowIndex: number) => <span className="statistics-chain-slot">
    {picking === key
      ? picker(rowIndex)
      : <button type="button" className="statistics-chain-add" aria-label={ui('stats.chainAdd')} title={ui('stats.chainAdd')} onClick={() => setPicking(key)}><Plus size={15}/></button>}
  </span>

  const lastFull = rows.length === 0 || rows[rows.length - 1].length >= 2

  return <div ref={slots} className="statistics-chain-slots" aria-label={ui('stats.chainTitle')}>
    {rows.map((row, rowIndex) => <div className="statistics-chain-row" key={row[0]}>
      {row.map(page => <span className="statistics-chain-card" key={page}>
        <span className="statistics-chain-label">{labels[page]}</span>
        <button type="button" className="text-button" aria-label={ui('stats.chainRemove')} title={ui('stats.chainRemove')} onClick={() => onRemove(page)}><X size={13}/></button>
      </span>).flatMap((card, index) => index === 0 ? [card] : [<span className="statistics-chain-link" aria-hidden="true" key={'link' + index}/>, card])}
      {row.length > 0 ? <span className="statistics-chain-link" aria-hidden="true"/> : null}
      {addSlot('row' + rowIndex, rowIndex)}
    </div>)}
    {lastFull ? <div className="statistics-chain-row">{addSlot('new', -1)}</div> : null}
  </div>
}
