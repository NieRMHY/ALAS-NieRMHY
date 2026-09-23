import { useRef, useState } from 'react'
import { Check, Copy, Globe } from 'lucide-react'
import { useApp } from '../app/context'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { DeployGroups } from '../components/DeployGroups'
import { useDeploySettings } from '../app/useDeploySettings'
import { remoteStatus } from '../app/remoteStatus'
import { REMOTE_ACCESS_GROUPS } from '../app/settingsGroups'

/** 远程访问页：顶部是当前可直接打开的地址，下面是远程访问与 WebUI 设置。 */
export function RemoteAccess() {
  const {ui} = useApp()
  const {data, error, edits, queue} = useDeploySettings()
  const [copied, setCopied] = useState(false)
  const addressRef = useRef<HTMLElement>(null)

  const status = remoteStatus(data?.remote?.state, data?.remote?.enabled ?? false)
  const address = data?.remote?.address ?? ''
  const stateLabel = {
    disabled: ui('remote.stateDisabled'),
    starting: ui('remote.stateStarting'),
    ready: ui('remote.stateReady'),
    failed: ui('remote.stateFailed'),
  }[status]

  async function copy() {
    try {
      await navigator.clipboard.writeText(address)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // 局域网 http 等非安全上下文没有剪贴板权限，退化成选中地址让用户手动复制。
      const node = addressRef.current
      if (!node) return
      const range = document.createRange()
      range.selectNodeContents(node)
      const selection = window.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)
    }
  }

  return (
    <>
      <PageTitle title={ui('nav.remote')} />
      {error && <ErrorBox message={error} />}
      {edits.storageError && <ErrorBox message={edits.storageError} />}
      <section className="panel config-group">
        <div className="panel-heading">
          <div>
            <Globe size={18} />
            <h2 data-text={ui('remote.title')}>{ui('remote.title')}</h2>
          </div>
          <span className={`remote-badge remote-badge-${status}`}>{stateLabel}</span>
        </div>
        {address ? (
          <div className="remote-address">
            <code ref={addressRef}>{address}</code>
            <button type="button" className="button secondary" aria-label={ui('remote.copy')} onClick={copy}>
              {copied ? <Check size={16}/> : <Copy size={16}/>}
              {copied ? ui('remote.copied') : ui('remote.copy')}
            </button>
          </div>
        ) : status === 'disabled' ? (
          <p className="remote-hint muted">{ui('remote.disabledHint')}</p>
        ) : null}
        {data?.remote?.error && <p className="remote-hint muted">{data.remote.error}</p>}
        <p className="remote-hint muted">{ui('remote.passwordHint')}</p>
      </section>
      {!data ? <Loading/> : (
        <DeployGroups data={data} only={REMOTE_ACCESS_GROUPS} edits={edits} queue={queue} />
      )}
    </>
  )
}
