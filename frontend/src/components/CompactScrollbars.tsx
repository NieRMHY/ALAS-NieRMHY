import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useApp } from '../app/context'

/** 轨道宽度。原生条只有 5px，拖动命中区太小，这里给足。 */
const RAIL_WIDTH = 12
/** 缩略条的最短长度，内容很长时也要抓得住。 */
const MIN_THUMB = 36
/** 任务设置列表、侧栏与调度器栏不出浮层轨道，这几处不显示滚动条。 */
const NO_RAIL = '.task-config-settings, .task-config-rail, .task-nav, .group-nav, .sidebar, .rail-task-list, .task-rail-scheduler'

const scrollable = (element: HTMLElement) => element.scrollHeight > element.clientHeight + 1

/** 容器自己是不是「纵向可滚」。computed 值只有 auto/scroll 才算，visible 的溢出不算滚动区。 */
function isScrollHost(element: HTMLElement) {
  const overflowY = getComputedStyle(element).overflowY
  return (overflowY === 'auto' || overflowY === 'scroll') && scrollable(element)
}

/** 把页面上已经能滚的容器都标出来：CSS 靠这个属性压掉它们的原生滚动条。
    用运行时扫描而不是写死选择器列表 —— 任务配置页的设置区、统计页的图表区这类容器
    随页面不同，列不全就会出现「有的地方还是常驻条」。 */
function markScrollHosts(root: ParentNode) {
  for (const element of root.querySelectorAll<HTMLElement>('*')) {
    if (element.dataset.overlayScroll === 'on') continue
    if (!element.getClientRects().length) continue
    if (isScrollHost(element)) element.dataset.overlayScroll = 'on'
  }
}

/** 从指针位置向上找最近的滚动容器；找到即标记，下次它就不会再画出原生条。 */
function nearestScrollHost(node: EventTarget | null) {
  let element = node instanceof Element ? node : null
  while (element && element !== document.body) {
    if (element instanceof HTMLElement) {
      if (element.dataset.overlayScroll === 'on') return element
      if (isScrollHost(element)) {
        element.dataset.overlayScroll = 'on'
        return element
      }
    }
    element = element.parentElement
  }
  return undefined
}

/** 光标是否落在内容区里。页面级滚动条靠它触发：整页滚动的页面（任务配置最典型）没有
    容器级滚动区，只能按「鼠标进了内容区」来显形 —— 要求先贴到窗口右边缘才算，等于要用户
    先找到边缘，正是这次要修掉的体验。 */
function inContentArea(event: PointerEvent) {
  const shell = document.querySelector('.main-shell')
  if (!shell) return false
  const box = shell.getBoundingClientRect()
  return event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom
}

/** 紧凑主题专属：把常驻的原生滚动条换成 hover 才出现的浮层轨道。
    原生滚动条在 Chromium 里只有「占位」与「彻底消失」两种状态（宽度 0 就等于没有），
    做不到「可见但不挤压内容」，所以这里压掉原生条，另挂一条 fixed 轨道跟随鼠标所在的
    容器：不占内容宽度、移过去才显形、直角且比原来的 5px 宽得多。

    轨道全局只有一条，位置在滚动与尺寸变化时同步 —— 不在每个容器里插 DOM，避免和 React
    的树打架。
    @returns cleanup 卸掉轨道与监听，scan 供路由切换后重新标记新页面的容器。 */
function installOverlayScrollbars(): {cleanup: () => void; scan: () => void} {
  const rail = document.createElement('div')
  rail.className = 'overlay-scrollbar'
  rail.setAttribute('aria-hidden', 'true')
  const thumb = document.createElement('div')
  thumb.className = 'overlay-scrollbar-thumb'
  rail.appendChild(thumb)
  document.body.appendChild(rail)

  let current: HTMLElement | undefined
  let dragging = false
  let dragStartY = 0
  let dragStartScroll = 0
  let dragRatio = 0
  let frame = 0

  function sync() {
    if (!current) return
    const viewport = current === document.documentElement
    const box = current.getBoundingClientRect()
    const trackHeight = viewport ? window.innerHeight : box.height
    const trackRight = viewport ? window.innerWidth : box.right
    const thumbHeight = Math.min(trackHeight, Math.max(MIN_THUMB, (current.clientHeight / current.scrollHeight) * trackHeight))
    const travel = trackHeight - thumbHeight
    const maxScroll = current.scrollHeight - current.clientHeight
    const offset = maxScroll > 0 ? (current.scrollTop / maxScroll) * travel : 0
    rail.style.top = `${viewport ? 0 : box.top}px`
    rail.style.height = `${trackHeight}px`
    rail.style.left = `${trackRight - RAIL_WIDTH}px`
    thumb.style.height = `${thumbHeight}px`
    thumb.style.transform = `translateY(${offset}px)`
  }

  function schedule() {
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      sync()
    })
  }

  function show(target?: HTMLElement) {
    if (target === current) return
    current = target
    rail.dataset.visible = target ? 'on' : 'off'
    if (target) sync()
  }

  function pick(event: PointerEvent) {
    if (dragging) return
    /* 指针落在轨道自己身上时保持当前目标：轨道挂在 body 下，向上找不到滚动容器，
       否则鼠标一移上去轨道就把自己关掉，缩略条再也抓不住。 */
    if (rail.contains(event.target as Node)) return
    const host = nearestScrollHost(event.target)
    if (host) {
      show(host.closest(NO_RAIL) ? undefined : host)
      return
    }
    show(scrollable(document.documentElement) && inContentArea(event) ? document.documentElement : undefined)
  }

  /* 两件事都由这一处 DOM 变化驱动：日志与任务列表追加内容后 thumb 长度要跟着变；
     内容长到开始溢出时，容器还得在鼠标移入之前就被标记，否则它会先画出常驻原生条。 */
  const pending = new Set<Element>()
  let scanTimer = 0
  const mutation = new MutationObserver(records => {
    for (const record of records) {
      if (record.target instanceof Element) pending.add(record.target)
      for (const node of record.addedNodes) if (node instanceof Element) pending.add(node)
    }
    if (!scanTimer) {
      scanTimer = window.setTimeout(() => {
        scanTimer = 0
        /* 只沿变化点向上查祖先链：内容变多而开始溢出的是这些容器，不必扫全页。 */
        for (const element of pending) {
          let node: Element | null = element
          while (node && node !== document.body) {
            if (node instanceof HTMLElement && node.dataset.overlayScroll !== 'on' && isScrollHost(node)) node.dataset.overlayScroll = 'on'
            node = node.parentElement
          }
        }
        pending.clear()
      }, 250)
    }
    schedule()
  })
  mutation.observe(document.body, {childList: true, subtree: true})

  thumb.addEventListener('pointerdown', event => {
    if (!current) return
    event.preventDefault()
    dragging = true
    thumb.setPointerCapture(event.pointerId)
    dragStartY = event.clientY
    dragStartScroll = current.scrollTop
    const travel = (current === document.documentElement ? window.innerHeight : current.getBoundingClientRect().height) - thumb.offsetHeight
    dragRatio = travel > 0 ? (current.scrollHeight - current.clientHeight) / travel : 0
  })
  thumb.addEventListener('pointermove', event => {
    if (!dragging || !current) return
    current.scrollTop = dragStartScroll + (event.clientY - dragStartY) * dragRatio
  })
  const endDrag = (event: PointerEvent) => {
    if (!dragging) return
    dragging = false
    if (thumb.hasPointerCapture(event.pointerId)) thumb.releasePointerCapture(event.pointerId)
  }
  thumb.addEventListener('pointerup', endDrag)
  thumb.addEventListener('pointercancel', endDrag)

  document.addEventListener('pointermove', pick, {passive: true})
  /* 容器的 scroll 不冒泡，靠捕获阶段统一收。 */
  document.addEventListener('scroll', schedule, {capture: true, passive: true})
  window.addEventListener('resize', schedule)

  const scan = () => markScrollHosts(document.body)
  scan()

  return {
    scan,
    cleanup: () => {
      if (frame) cancelAnimationFrame(frame)
      if (scanTimer) clearTimeout(scanTimer)
      mutation.disconnect()
      document.removeEventListener('pointermove', pick)
      document.removeEventListener('scroll', schedule, {capture: true})
      window.removeEventListener('resize', schedule)
      rail.remove()
    },
  }
}

/** 紧凑主题挂载时接管滚动条，切到其它主题即还原原生滚动条。 */
export function CompactScrollbars() {
  const {theme} = useApp()
  const location = useLocation()
  const handle = useRef<{cleanup: () => void; scan: () => void} | undefined>(undefined)
  useEffect(() => {
    if (theme !== 'extreme') return
    const installed = installOverlayScrollbars()
    handle.current = installed
    return () => {
      handle.current = undefined
      installed.cleanup()
    }
  }, [theme])
  /* 换页后新页面的滚动容器要重新标记，否则它们还留着常驻原生条。 */
  useEffect(() => {
    handle.current?.scan()
  }, [location.pathname])
  return null
}
