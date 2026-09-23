import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Download, FileJson, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useApp, useConnection } from '../app/context'
import { CreateInstance } from '../app/App'
import { Empty, ErrorBox, PageTitle, StatusBadge } from '../components/ui'

/** 把配置写成 json 文件下载。内容即配置本体（含 Alas 段），与导入接口期望的格式一致。 */
function downloadJson(filename: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/**
 * 配置管理：列出全部配置实例，提供概览 / 导出 / 删除，以及新建与导入的入口。
 *
 * 删除要带 revision（磁盘 JSON 的 SHA-256），所以先取一次配置再删。
 */
export function ConfigManager() {
  const {instances, t, ui, notify, refresh} = useApp()
  const connection = useConnection()
  const [creating, setCreating] = useState<null | 'new' | 'import'>(null)
  const [busy, setBusy] = useState('')
  const [confirming, setConfirming] = useState('')
  const [error, setError] = useState('')

  async function exportConfig(name: string) {
    setBusy(name); setError('')
    try {
      const config = await api.request('config.get', {instance: name})
      downloadJson(`${name}.json`, config.values)
      notify(ui('config.exported', {name}))
    } catch (error) { setError((error as Error).message) } finally { setBusy('') }
  }

  async function remove(name: string) {
    setBusy(name); setError('')
    try {
      const config = await api.request('config.get', {instance: name})
      await api.request('instances.delete', {instance: name, revision: config.revision})
      await refresh()
      notify(ui('instance.backupNotice'))
    } catch (error) { setError((error as Error).message) } finally { setBusy(''); setConfirming('') }
  }

  return <>
    <PageTitle title={ui('nav.configs')} actions={<>
      <button className="button secondary" disabled={connection !== 'ready'} onClick={() => setCreating('import')}><FileJson size={15}/>{ui('config.import')}</button>
      <button className="button primary" disabled={connection !== 'ready'} onClick={() => setCreating('new')}><Plus size={16}/>{ui('config.create')}</button>
    </>}/>
    {error && <ErrorBox message={error}/>}
    <div className="config-list">
      {instances.map(item => <section className="panel config-row" key={item.name}>
        <div className="config-row-main">
          <h3>{item.name}</h3>
          <div className="config-row-meta">
            {item.server !== 'disabled' && <span>{t(`Emulator.ServerName.${item.server}`)}</span>}
            <span>{item.serial}</span>
          </div>
        </div>
        <StatusBadge status={item.status} simulate/>
        <div className="config-row-actions">
          <Link className="button secondary" to={`/i/${item.name}/overview`}><ArrowRight size={15}/>{ui('config.overview')}</Link>
          <button className="button secondary" disabled={busy === item.name} onClick={() => void exportConfig(item.name)}><Download size={15}/>{ui('config.export')}</button>
          {confirming === item.name
            ? <button className="button danger" disabled={busy === item.name} onClick={() => void remove(item.name)}><Trash2 size={15}/>{ui('instance.deleteConfirm')}</button>
            : <button className="button danger subtle" onClick={() => setConfirming(item.name)}><Trash2 size={15}/>{ui('instance.delete')}</button>}
        </div>
      </section>)}
      {!instances.length && <Empty icon={<FileJson size={30}/>} title={ui('config.empty')}>{ui('config.emptyHint')}</Empty>}
    </div>
    {creating && <CreateInstance onClose={() => setCreating(null)} startWithImport={creating === 'import'}/>}
  </>
}
