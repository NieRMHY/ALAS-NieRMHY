/**
 * @fileoverview 任务通知的系统级推送：把 WS 的 notifications 事件弹成 Windows 原生通知。
 */

import {useEffect} from 'react'
import {api} from '../api/client'

type TaskNotification = {instance?: string; title?: string; content?: string}

let permissionArmed = false

function armPermissionRequest(data: TaskNotification) {
  // 授权框必须由用户手势触发：等下一次点击页面时申请，授权后补弹错过的一条。
  if (permissionArmed) return
  permissionArmed = true
  const request = () => {
    permissionArmed = false
    void Notification.requestPermission().then(permission => {
      if (permission === 'granted') show(data)
    })
  }
  document.addEventListener('pointerdown', request, {once: true})
}

function show(data: TaskNotification) {
  if (typeof Notification === 'undefined' || Notification.permission === 'denied') return
  if (Notification.permission === 'default') {
    armPermissionRequest(data)
    return
  }
  // Modify by MHY, 系统通知沿用本地品牌与 essex 图标。
  const notification = new Notification(data.title ?? 'ESSEX Secretary', {
    body: data.content ?? '',
    icon: `${import.meta.env.BASE_URL}alas-icon.png`,
  })
  notification.onclick = () => { window.focus(); notification.close() }
}

export function useSystemNotifications() {
  useEffect(() => api.onEvent(event => {
    if (event.topic !== 'notifications') return
    show(event.data as TaskNotification)
  }), [])
}
