/**
 * @fileoverview 全局壁纸背景与视频渲染组件。
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { getBackground, initBackgroundGallery, subscribeBackground } from '../app/background'

interface DisplayItem {
  id: string
  url: string
  kind: 'image' | 'video'
}

/** 背景支持远程图片、远程视频和保存在当前浏览器中的上传文件。 */
export function Wallpaper() {
  const background = useSyncExternalStore(subscribeBackground, getBackground, getBackground)
  const [active, setActive] = useState<DisplayItem | null>(null)
  const [videoReady, setVideoReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const activeRef = useRef<DisplayItem | null>(null)
  activeRef.current = active

  useEffect(() => {
    setFailed(false)
    /* 图库模式没有现成地址时，启动流程会随机铺一张。 */
    void initBackgroundGallery()
  }, [background.source, background.assetUrl, background.revision])

  useEffect(() => {
    const targetUrl = background.assetUrl
    const targetKind = background.kind

    if (!targetUrl) {
      setActive(null)
      return
    }

    if (activeRef.current?.url === targetUrl && activeRef.current?.kind === targetKind) {
      return
    }

    if (targetKind === 'video') {
      setVideoReady(false)
      const nextItem: DisplayItem = { id: `${targetUrl}-${Date.now()}`, url: targetUrl, kind: 'video' }
      setActive(nextItem)
      return
    }

    // 图片预载与解码：解码完成再上屏，避免大图流式加载时的逐行扫出。
    let cancelled = false
    const img = new Image()
    img.src = targetUrl
    img.referrerPolicy = 'no-referrer'

    const handleReady = () => {
      if (cancelled) return
      const nextItem: DisplayItem = { id: `${targetUrl}-${Date.now()}`, url: targetUrl, kind: 'image' }
      setActive(nextItem)
    }

    const handleError = () => {
      if (cancelled) return
      if (!activeRef.current) {
        setFailed(true)
      }
    }

    const tryDecodeAndReady = () => {
      if (typeof img.decode === 'function') {
        img.decode().then(handleReady).catch(handleReady)
      } else {
        handleReady()
      }
    }

    if (img.complete && img.naturalWidth > 0) {
      tryDecodeAndReady()
    } else {
      img.onload = tryDecodeAndReady
      img.onerror = handleError
    }

    return () => {
      cancelled = true
    }
    /* 也依赖 revision：随机图 API 的地址不变、图要变，同一条再应用一次必须重新取图。 */
  }, [background.assetUrl, background.kind, background.revision])

  const renderItem = (item: DisplayItem) => {
    if (item.kind === 'video') {
      return (
        <video
          key={item.id}
          src={item.url}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          className={`wallpaper-media ${videoReady ? 'wallpaper-fade-in' : 'wallpaper-hidden'}`}
          onLoadedData={() => setVideoReady(true)}
          onError={() => setFailed(true)}
        />
      )
    }
    return (
      <img
        key={item.id}
        src={item.url}
        alt=""
        referrerPolicy="no-referrer"
        decoding="async"
        className="wallpaper-media wallpaper-fade-in"
        onError={() => setFailed(true)}
      />
    )
  }

  return (
    <div className="wallpaper" aria-hidden="true">
      {!failed && (
        active && renderItem(active)
      )}
    </div>
  )
}
