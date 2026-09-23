import { useEffect, useState, useSyncExternalStore, type FormEvent } from 'react'
import { Upload } from 'lucide-react'
import { getBackground, loadUploadedBackground, resetBackground, setBackgroundUpload, setBackgroundUrl, subscribeBackground, type BackgroundKind, type BackgroundSource } from '../app/background'
import { useApp } from '../app/context'
import { Select } from './FormControls'

/** 图片与视频背景属于当前浏览器偏好；上传文件保存在 IndexedDB，避免进入部署配置。 */
export function BackgroundPreferences() {
  const {ui, notify} = useApp()
  const background = useSyncExternalStore(subscribeBackground, getBackground)
  const [source, setSource] = useState<BackgroundSource>(background.source)
  const [kind, setKind] = useState<BackgroundKind>(background.kind)
  const [url, setUrl] = useState(background.url)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { if (background.source === 'upload') void loadUploadedBackground() }, [background.source])

  function changeSource(next: BackgroundSource) {
    setSource(next)
    setError('')
    if (next === 'default') resetBackground()
  }

  function applyUrl(event: FormEvent) {
    event.preventDefault()
    try {
      setBackgroundUrl(url, kind)
      setSource('url')
      setError('')
      notify(ui('settings.backgroundApplied'))
    } catch (error) { setError((error as Error).message) }
  }

  async function upload(file?: File) {
    if (!file) return
    setBusy(true); setError('')
    try {
      await setBackgroundUpload(file)
      setSource('upload')
      notify(ui('settings.backgroundApplied'))
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }

  return <div className="field-row background-field">
    <div className="field-label">
      <label htmlFor="ui-background-source">{ui('settings.background')}</label>
      <p>{ui('settings.backgroundHelp')}</p>
    </div>
    <div className="field-control background-control">
      <Select id="ui-background-source" value={source} onChange={event => changeSource(event.target.value as BackgroundSource)}>
        <option value="default">{ui('settings.backgroundDefault')}</option>
        <option value="url">{ui('settings.backgroundUrl')}</option>
        <option value="upload">{ui('settings.backgroundUpload')}</option>
      </Select>
      {source === 'url' && <form className="background-url-form" onSubmit={applyUrl}>
        <input aria-label={ui('settings.backgroundUrl')} type="url" required maxLength={2048} value={url} placeholder="https://example.com/background.jpg" onChange={event => setUrl(event.target.value)}/>
        <div className="background-url-actions">
          <Select aria-label={ui('settings.backgroundType')} value={kind} onChange={event => setKind(event.target.value as BackgroundKind)}>
            <option value="image">{ui('settings.backgroundImage')}</option>
            <option value="video">{ui('settings.backgroundVideo')}</option>
          </Select>
          <button className="button primary" type="submit">{ui('settings.backgroundApply')}</button>
        </div>
      </form>}
      {source === 'upload' && <label className="background-upload">
        <input className="background-upload-input" type="file" accept="image/*,video/*" disabled={busy} onChange={event => {
          const file = event.target.files?.[0]
          event.target.value = ''
          void upload(file)
        }}/>
        <span className="background-upload-icon" aria-hidden="true"><Upload size={19}/></span>
        <span className="background-upload-copy">
          <strong>{busy ? ui('settings.backgroundSaving') : background.source === 'upload' && background.name ? background.name : ui('settings.backgroundChoose')}</strong>
          <small>{ui('settings.backgroundLimit')}</small>
        </span>
      </label>}
      {error && <p className="background-error" role="alert">{error}</p>}
    </div>
  </div>
}
