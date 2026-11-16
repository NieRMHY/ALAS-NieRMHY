/**
 * @fileoverview 插件管理页：导入 .apu 插件包、启停、切换主题插件与卸载。
 */

import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { useApp, useConnection } from '../app/context'
import { ErrorBox, Loading, Modal, PageTitle } from '../components/ui'
import { usePlugins } from '../plugins/context'
import type { InstalledPlugin } from '../plugins/types'

/** 插件列表页：导入是主操作；已安装插件按名称、状态和操作排列，沿用设置面板的配色与间距。 */
export function Plugins() {
  const {ui} = useApp()
  const connection = useConnection()
  const {plugins, ready, error, refresh, request, theme, setTheme} = usePlugins()
  const fileInput = useRef<HTMLInputElement>(null)
  const busyRef = useRef(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [remove, setRemove] = useState<InstalledPlugin>()
  const disabled = busy || connection !== 'ready'

  async function run(path: string, options: RequestInit, afterSuccess?: () => void) {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setMessage('')
    try {
      await request(path, options)
      afterSuccess?.()
      setRemove(undefined)
    } catch (failure) {
      setMessage((failure as Error).message)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return <>
    <PageTitle title={ui('nav.plugins')}/>
    <section className="panel config-group">
      <div className="panel-heading">
        <div><h2>{ui('plugins.installed')}</h2></div>
        <input ref={fileInput} type="file" accept=".apu" hidden aria-label={ui('plugins.import')} onChange={event => {
          const file = event.currentTarget.files?.[0]
          event.currentTarget.value = ''
          if (!file) return
          if (!file.name.toLowerCase().endsWith('.apu')) {setMessage(ui('plugins.fileType')); return}
          void run('', {method: 'POST', body: file})
        }}/>
        <button type="button" className="button primary" disabled={disabled} onClick={() => fileInput.current?.click()}>
          <Upload size={15}/>{ui('plugins.import')}
        </button>
      </div>
      {message && <div className="apu-plugin-message"><ErrorBox message={message}/></div>}
      {error && <div className="apu-plugin-message"><ErrorBox message={error} retry={() => void refresh()}/></div>}
      {!ready && !error && <Loading/>}
      {ready && plugins.length === 0 && <p className="apu-plugin-empty">{ui('plugins.empty')}</p>}
      {plugins.map(plugin => {
        const {manifest, enabled} = plugin
        const path = '/' + encodeURIComponent(manifest.id)
        const selected = theme?.manifest.id === manifest.id
        return <article key={manifest.id} className="apu-plugin-row">
          <div className="apu-plugin-meta">
            <h3>{manifest.name}</h3>
            <p>{manifest.version} · {ui(enabled ? 'plugins.enabled' : 'plugins.disabled')}</p>
            {!!manifest.permissions?.length && <p className="apu-plugin-permissions">
              {manifest.permissions.map(permission => ui(`plugins.permission.${permission}`)).join(' · ')}
            </p>}
          </div>
          <div className="apu-plugin-actions">
            <button type="button" className="button secondary" disabled={disabled} onClick={() => void run(path, {
              method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: !enabled}),
            }, !enabled && manifest.theme ? () => setTheme(manifest.id) : undefined)}>{ui(enabled ? 'plugins.disable' : 'plugins.enable')}</button>
            {enabled && manifest.theme && <button type="button" className="button secondary" aria-pressed={selected}
              onClick={() => setTheme(selected ? '' : manifest.id)}>{ui(selected ? 'plugins.restoreTheme' : 'plugins.applyTheme')}</button>}
            <button type="button" className="button danger" disabled={disabled} onClick={() => setRemove(plugin)}>{ui('plugins.remove')}</button>
          </div>
        </article>
      })}
    </section>
    {remove && <Modal title={ui('plugins.remove')} onClose={() => {if (!busy) setRemove(undefined)}}>
      <p>{ui('plugins.removePrompt', {name: remove.manifest.name})}</p>
      <div className="apu-plugin-actions apu-plugin-confirm">
        <button type="button" className="button secondary" disabled={busy} onClick={() => setRemove(undefined)}>{ui('common.cancel')}</button>
        <button type="button" className="button danger" disabled={disabled}
          onClick={() => void run('/' + encodeURIComponent(remove.manifest.id), {method: 'DELETE'})}>{ui('plugins.remove')}</button>
      </div>
    </Modal>}
  </>
}
