import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { getBackground, loadUploadedBackground, subscribeBackground } from '../app/background'

interface DisplayItem {
  id: string
  url: string
  kind: 'image' | 'video'
}

/** 背景支持远程图片、远程视频和保存在当前浏览器中的上传文件。 */
export function Wallpaper() {
  const background = useSyncExternalStore(subscribeBackground, getBackground)
  const [active, setActive] = useState<DisplayItem | null>(null)
  const [videoReady, setVideoReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const activeRef = useRef<DisplayItem | null>(null)
  activeRef.current = active

  useEffect(() => {
    setFailed(false)
    if (background.source === 'upload' && !background.assetUrl) void loadUploadedBackground()
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

    // 图片预载与显存解码：彻底杜绝大图网络流式传输时的逐行扫描线撕裂感
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
  }, [background.assetUrl, background.kind])

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
