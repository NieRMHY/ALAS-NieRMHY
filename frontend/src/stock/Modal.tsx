import {useEffect,useRef,type ReactNode} from 'react'
import {createPortal} from 'react-dom'
import {X} from 'lucide-react'
import {useStockTheme} from './theme'
import './modal.css'

export function Modal({children,label,className,header,footer,onClose,closeLabel='关闭',busy=false}:{children:ReactNode;label:string;className:string;header?:ReactNode;footer?:ReactNode;onClose?:()=>void;closeLabel?:string;busy?:boolean}){
  const {theme}=useStockTheme(),root=useRef<HTMLDivElement>(null),dialog=useRef<HTMLElement>(null),close=useRef(onClose),processing=useRef(busy)
  close.current=onClose;processing.current=busy
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null
    // 手机键盘和页面放大可能只改变可见视口，弹窗始终跟随实际可见区域。
    const viewport=window.visualViewport
    const resize=()=>{
      const style=root.current?.style;if(!style)return
      style.setProperty('--stock-modal-height',`${viewport?.height??window.innerHeight}px`)
      style.setProperty('--stock-modal-width',`${viewport?.width??window.innerWidth}px`)
      style.setProperty('--stock-modal-top',`${viewport?.offsetTop??0}px`)
      style.setProperty('--stock-modal-left',`${viewport?.offsetLeft??0}px`)
    }
    resize();viewport?.addEventListener('resize',resize);viewport?.addEventListener('scroll',resize);window.addEventListener('resize',resize)
    const backgrounds=Array.from(document.body.children).filter(element=>element instanceof HTMLElement&&element!==root.current&&!element.querySelector('iframe[src*="recaptcha"]')) as HTMLElement[]
    const inert=backgrounds.map(element=>element.inert)
    backgrounds.forEach(element=>{element.inert=true})
    const overflow=document.body.style.overflow;document.body.style.overflow='hidden'
    const controls=()=>Array.from(dialog.current?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),iframe,[tabindex="0"]')??[]).filter(element=>element.getClientRects().length>0)
    controls()[0]?.focus()
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&close.current){event.preventDefault();event.stopPropagation();if(!processing.current)close.current()}
      if(event.key==='Tab'){
        const elements=controls(),first=elements[0],last=elements.at(-1)
        if(event.shiftKey&&(document.activeElement===first||!dialog.current?.contains(document.activeElement))){event.preventDefault();last?.focus()}
        else if(!event.shiftKey&&(document.activeElement===last||!dialog.current?.contains(document.activeElement))){event.preventDefault();first?.focus()}
      }
    }
    document.addEventListener('keydown',key,true)
    return ()=>{document.removeEventListener('keydown',key,true);viewport?.removeEventListener('resize',resize);viewport?.removeEventListener('scroll',resize);window.removeEventListener('resize',resize);backgrounds.forEach((element,index)=>{element.inert=inert[index]});document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus()}
  },[])
  return createPortal(<div ref={root} className="stock-terminal stock-overlay-root" data-stock-theme={theme}><div className="modal-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!busy)onClose?.()}}><section ref={dialog} className={`${className} modal-dialog`} role="dialog" aria-modal="true" aria-label={label}>
    {(header||onClose)&&<header className="modal-heading"><div>{header}</div>{onClose&&<button type="button" className="modal-close" aria-label={closeLabel} disabled={busy} onClick={onClose}><X size={20}/></button>}</header>}
    <div className="modal-body">{children}</div>{footer&&<footer className="modal-actions">{footer}</footer>}
  </section></div></div>,document.body)
}
