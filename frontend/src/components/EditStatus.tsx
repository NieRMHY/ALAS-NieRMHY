import type { Edit, EditQueue } from '../config/EditQueue'
import { Check, CircleAlert, CloudOff, LoaderCircle } from 'lucide-react'
import { useApp } from '../app/context'

export function EditStatus({edit, id, retry, queue}: {edit?: Edit; id: string; retry: () => void; queue?: EditQueue}) {
  const {ui} = useApp()
  // 静默期内不显示保存结果。
  if (!edit || (queue !== undefined && !queue.savedVisible(edit))) return null
  const Icon = edit.status === 'error' ? CircleAlert : edit.status === 'saved' ? Check : edit.status === 'saving' ? LoaderCircle : CloudOff
  // 状态贴在参数行里显示，文案会被省略号截断，所以全文同时交给 title 与 aria-label。
  const full = edit.status === 'error' ? ui('edit.inputPreserved', {error: edit.error ?? ''}) : edit.status === 'saved' ? ui('edit.saved') : edit.status === 'saving' ? ui('edit.saving') : ui('edit.waitingConnection')
  return <div id={`${id}-status`} className={`edit-status ${edit.status === 'error' ? 'edit-error' : ''}`} role={edit.status === 'error' ? 'alert' : 'status'} title={full} aria-label={full}>
    <Icon size={14} aria-hidden="true" className={edit.status === 'saving' ? 'spin' : undefined}/>
    <span className="edit-status-text" key={edit.readyAt ?? full}>{full}</span>
    {edit.retryable && edit.status === 'error' && <button className="button subtle" onClick={retry}>{ui('edit.retry')}</button>}
  </div>
}
