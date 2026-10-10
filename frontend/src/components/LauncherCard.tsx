/**
 * @fileoverview 启动器卡片：展示启动器连接状态，并切换 Windows 开机自启动。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useApp } from '../app/context'

/** 启动器端点的响应：状态查询与开关请求共用。 */
type LauncherStatus = {
  success?: boolean
  launcher_connected?: boolean
  autostart_supported?: boolean
  autostart_enabled?: boolean | null
  error?: string
}

/** 状态行取值：面板状态机。 */
export type Phase = 'loading' | 'remote' | 'unsupported' | 'disconnected' | 'ready' | 'setting' | 'failed'

/** 空闲时的状态轮询间隔：启动器随时可能与页面连上或断开。 */
const POLL_INTERVAL_MS = 5000

/** 同源相对路径；远程访问隧道挂在子路径下时同样打到本机后端。 */
function launcherUrl(path: string) {
  return new URL(path, document.baseURI).toString()
}

/** 状态行文案：状态机 + 后端字段 → 界面用语。 */
export function launcherStatusText(phase: Phase, state: {enabled: boolean; pending: boolean; detail: string}, t: (key: string) => string) {
  if (phase === 'loading') return t('Gui.Launcher.Loading')
  if (phase === 'remote') return t('Gui.Launcher.RemoteUnavailable')
  if (phase === 'unsupported') return t('Gui.Launcher.Unsupported')
  if (phase === 'disconnected') return t('Gui.Launcher.Disconnected')
  if (phase === 'setting') return t('Gui.Launcher.Setting')
  if (phase === 'failed') return `${t('Gui.Launcher.Failed')}：${state.detail}`
  const flag = state.pending ? t('Gui.Launcher.Loading') : state.enabled ? t('Gui.Launcher.Enabled') : t('Gui.Launcher.Disabled')
  return `${t('Gui.Launcher.Connected')} · ${flag}`
}

export function LauncherCard() {
  const {t} = useApp()
  const [phase, setPhase] = useState<Phase>('loading')
  const [enabled, setEnabled] = useState(false)
  // 已连上启动器但还没拿到自启状态：状态行显示「已连接 · 正在读取」。
  const [pending, setPending] = useState(false)
  const [detail, setDetail] = useState('')
  const busy = useRef(false)

  /** 读取启动器状态；本机限定端点对非本机访问返回 403，据此提示只能在本机设置。 */
  const read = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    try {
      const response = await fetch(launcherUrl('api/launcher/status'), {cache: 'no-store'})
      if (response.status === 403 || response.status === 404) {
        setPhase('remote')
        return
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json() as LauncherStatus
      if (!data.autostart_supported) {
        setPhase('unsupported')
        return
      }
      if (!data.launcher_connected) {
        setPhase('disconnected')
        return
      }
      setEnabled(data.autostart_enabled === true)
      setPending(data.autostart_enabled === null || data.autostart_enabled === undefined)
      setPhase('ready')
    } catch (error) {
      setDetail(error instanceof Error ? error.message : String(error))
      setPhase('failed')
    } finally {
      busy.current = false
    }
  }, [])

  /** 请求启动器开关开机自启：先动开关，失败回滚并给出原因。 */
  const toggle = useCallback(async () => {
    if (busy.current) return
    const target = !enabled
    busy.current = true
    setEnabled(target)
    setPhase('setting')
    try {
      const response = await fetch(launcherUrl('api/launcher/startup'), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: target}),
      })
      const result = await response.json().catch(() => null) as LauncherStatus | null
      if (!response.ok || !result?.success) throw new Error(result?.error || `HTTP ${response.status}`)
    } catch (error) {
      setEnabled(!target)
      setDetail(error instanceof Error ? error.message : String(error))
      setPhase('failed')
      return
    } finally {
      busy.current = false
    }
    await read()
  }, [enabled, read])

  useEffect(() => {
    void read()
    const timer = window.setInterval(() => { void read() }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [read])

  const status = launcherStatusText(phase, {enabled, pending, detail}, t)

  return (
    <section className="panel config-group">
      <div className="panel-heading">
        <h2 data-text={t('Gui.Launcher.StartupTitle')}>{t('Gui.Launcher.StartupTitle')}</h2>
      </div>
      <div className="field-row">
        <div className="field-label">
          <label htmlFor="launcher-autostart">{t('Gui.Launcher.AutoStart')}</label>
          <p>{t('Gui.Launcher.AutoStartHelp')}</p>
          <p role={phase === 'failed' ? 'alert' : 'status'}>{status}</p>
        </div>
        <div className="field-control">
          <button id="launcher-autostart" type="button" role="switch" aria-checked={enabled}
            aria-label={t('Gui.Launcher.AutoStart')} className={`toggle ${enabled ? 'on' : ''}`}
            disabled={phase !== 'ready'} onClick={() => { void toggle() }}><span/></button>
        </div>
      </div>
    </section>
  )
}
