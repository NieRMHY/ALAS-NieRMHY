/**
 * @fileoverview 顶栏实例切换下拉菜单组件。
 */

import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Check, ChevronDown, Plus, Ship } from 'lucide-react'
import { useApp, useConnection } from '../app/context'
import { createPortal } from 'react-dom'

export function InstanceSwitcher({onCreate}: {onCreate: () => void}) {
  const {instances, ui} = useApp()
  const {instance} = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const connection = useConnection()
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const [menuPos, setMenuPos] = useState({top: 0, left: 0})
  /* 菜单挂在 body 上：外壳容器的 clip-path 会裁掉后代。 */
  useEffect(() => {
    if (!open) return
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect()
      if (rect) setMenuPos({top: rect.bottom + 6, left: rect.left})
    }
    place()
    const outside = (event: PointerEvent) => {
      const node = event.target as Node
      if (!container.current?.contains(node) && !menu.current?.contains(node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('scroll', place, {capture: true, passive: true})
    window.addEventListener('resize', place)
    menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"], [role="menuitemradio"], [role="menuitem"]')?.focus()
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])
  useEffect(() => {setOpen(false)}, [location.pathname])
  /* 键盘导航挂在触发器与菜单两处：菜单不在容器内，菜单里的按键不会冒泡到容器。 */
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === 'Escape') {setOpen(false); trigger.current?.focus(); return}
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    if (!open) {setOpen(true); return}
    const items = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]:not(:disabled)') ?? [])
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }
  return <div className="instance-picker" ref={container} onBlur={event => {
    const next = event.relatedTarget as Node | null
    if (!event.currentTarget.contains(next) && !menu.current?.contains(next)) setOpen(false)
  }} onKeyDown={onKeyDown}>
    <div className="instance-switcher">
      <Link className="instance-caption" to={`/i/${instance}/overview`} title={ui('instance.backOverview')}>
        <strong>{instance}</strong>
      </Link>
      <button ref={trigger} type="button" className="instance-toggle" aria-label={ui('instance.switch')} title={ui('instance.switch')} aria-haspopup="menu" aria-expanded={open} aria-controls="instance-menu" onClick={() => setOpen(!open)}>
        <ChevronDown size={12}/>
      </button>
    </div>
    {open && createPortal(<div className="instance-menu" id="instance-menu" role="menu" aria-label={ui('instance.configInstances')} ref={menu} onKeyDown={onKeyDown} style={{position: 'fixed', top: menuPos.top, left: menuPos.left}}>
      <div className="instance-options">{instances.map(item => <button key={item.name} role="menuitemradio" aria-checked={item.name === instance} onClick={() => {
        setOpen(false); trigger.current?.focus()
        if (item.name !== instance) navigate(`/i/${item.name}/${location.pathname.split('/').slice(3).join('/') || 'overview'}`)
      }}><Ship size={16}/><span>{item.name}</span>{item.name === instance && <Check size={16}/>}</button>)}</div>
      <button
        className="instance-create"
        role="menuitem"
        aria-label={ui('instance.create')}
        title={ui('instance.create')}
        disabled={connection !== 'ready'}
        onClick={() => {setOpen(false); onCreate()}}
      >
        <Plus size={16}/>
        <span>{ui('home.newInstance')}</span>
      </button>
    </div>, document.body)}
  </div>
}
