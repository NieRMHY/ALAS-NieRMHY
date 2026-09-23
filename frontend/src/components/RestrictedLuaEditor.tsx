import { useCallback, useEffect, useRef, useState } from 'react'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { bracketMatching } from '@codemirror/language'
import { Check, CircleAlert, LoaderCircle, Save } from 'lucide-react'
import type { ShopStrategyValidation } from '../api/types'
import { useApp } from '../app/context'
import { canApplyRestrictedLua, diagnosticLocation, diagnosticSeverity, validationFromError } from './restrictedLuaState'

const externalChange = Annotation.define<boolean>()
const draftPrefix = 'azurpilot.restricted-lua.'

function readDraft(key: string, fallback: string) {
  try { return window.sessionStorage.getItem(draftPrefix + key) ?? fallback } catch { return fallback }
}

function persistDraft(key: string, draft: string, committed: string) {
  try {
    if (draft === committed) window.sessionStorage.removeItem(draftPrefix + key)
    else window.sessionStorage.setItem(draftPrefix + key, draft)
    return true
  } catch { return false }
}

function clearDraft(key: string) {
  try { window.sessionStorage.removeItem(draftPrefix + key) } catch { /* 浏览器存储不可用时仅保留内存草稿。 */ }
}

export function RestrictedLuaEditor({
  id, value, draftKey, label, disabled = false, offline = false, onCheck, onApply,
}: {
  id: string
  value: string
  draftKey: string
  label: string
  disabled?: boolean
  offline?: boolean
  onCheck: (script: string) => Promise<ShopStrategyValidation>
  onApply: (script: string) => Promise<void>
}) {
  const {ui} = useApp()
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView>(undefined)
  const editable = useRef(new Compartment())
  const onDraftChange = useRef<(next: string) => void>(() => {})
  const draftRef = useRef(readDraft(draftKey, value))
  const committedRef = useRef(value)
  const [draft, setDraft] = useState(draftRef.current)
  const [checkedScript, setCheckedScript] = useState<string>()
  const [validation, setValidation] = useState<ShopStrategyValidation>()
  const [checking, setChecking] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [storageError, setStorageError] = useState(false)
  // 离线仍允许继续整理本地草稿；仅服务端检查和配置写入必须等待连接恢复。
  const editorDisabled = disabled || applying
  const actionDisabled = disabled || offline || applying
  const state = {draft, checkedScript, validation, checking, applying}
  const canApply = canApplyRestrictedLua(state, actionDisabled)
  const statusId = `${id}-script-status`

  const changeDraft = useCallback((next: string) => {
    draftRef.current = next
    setDraft(next)
    setCheckedScript(undefined)
    setValidation(undefined)
    setError('')
    setStorageError(!persistDraft(draftKey, next, committedRef.current))
  }, [draftKey])
  onDraftChange.current = changeDraft

  useEffect(() => {
    const next = readDraft(draftKey, value)
    committedRef.current = value
    draftRef.current = next
    setDraft(next)
    setCheckedScript(undefined)
    setValidation(undefined)
    setError('')
    setStorageError(false)
  }, [draftKey])

  useEffect(() => {
    const previous = committedRef.current
    committedRef.current = value
    if (draftRef.current !== previous) return
    draftRef.current = value
    setDraft(value)
    setCheckedScript(undefined)
    setValidation(undefined)
  }, [value])

  useEffect(() => {
    const editor = new EditorView({
      parent: host.current!,
      state: EditorState.create({doc: draftRef.current, extensions: [
        lineNumbers(), history(), bracketMatching(), highlightActiveLine(), EditorView.lineWrapping,
        keymap.of([...defaultKeymap, ...historyKeymap]),
        editable.current.of([]),
        EditorView.contentAttributes.of({id, 'aria-label': label, 'aria-multiline': 'true', role: 'textbox'}),
        EditorView.updateListener.of(update => {
          if (update.docChanged && update.transactions.some(transaction => !transaction.annotation(externalChange))) onDraftChange.current(update.state.doc.toString())
        }),
      ]}),
    })
    view.current = editor
    return () => {editor.destroy(); view.current = undefined}
  }, [id, label])

  useEffect(() => {
    const editor = view.current
    if (editor && editor.state.doc.toString() !== draft) {
      editor.dispatch({changes: {from: 0, to: editor.state.doc.length, insert: draft}, annotations: externalChange.of(true)})
    }
  }, [draft])

  useEffect(() => {
    view.current?.dispatch({effects: editable.current.reconfigure([
      EditorState.readOnly.of(editorDisabled), EditorView.editable.of(!editorDisabled),
      EditorView.contentAttributes.of({'aria-disabled': String(editorDisabled), 'aria-describedby': statusId}),
    ])})
  }, [editorDisabled, statusId])

  async function check() {
    const script = draftRef.current
    setChecking(true)
    setCheckedScript(undefined)
    setValidation(undefined)
    setError('')
    try {
      const result = await onCheck(script)
      if (draftRef.current !== script) return
      setCheckedScript(script)
      setValidation(result)
    } catch (cause) {
      if (draftRef.current !== script) return
      const failed = validationFromError(cause)
      if (failed) {
        setCheckedScript(script)
        setValidation(failed)
      } else setError((cause as Error).message)
    } finally {
      setChecking(false)
    }
  }

  async function apply() {
    if (!canApply) return
    const script = draftRef.current
    setApplying(true)
    setError('')
    try {
      await onApply(script)
      if (draftRef.current !== script) return
      committedRef.current = script
      clearDraft(draftKey)
      setCheckedScript(undefined)
      setValidation(undefined)
    } catch (cause) {
      const failed = validationFromError(cause)
      if (failed) {
        setCheckedScript(script)
        setValidation(failed)
      } else setError((cause as Error).message)
    } finally {
      setApplying(false)
    }
  }

  const diagnostics = validation?.diagnostics ?? []
  return <div className={`yaml-editor restricted-lua-editor ${editorDisabled ? 'is-disabled' : ''}`} aria-busy={checking || applying || undefined}>
    <div className="editor-heading">{ui('field.restrictedLua')}</div>
    <div ref={host}/>
    <div className="restricted-lua-actions">
      <button type="button" className="button secondary" onClick={check} disabled={actionDisabled || checking}>
        {checking ? <LoaderCircle size={15} className="spin"/> : <Check size={15}/>} {checking ? ui('script.checking') : ui('script.check')}
      </button>
      <button type="button" className="button primary" onClick={apply} disabled={!canApply}>
        {applying ? <LoaderCircle size={15} className="spin"/> : <Save size={15}/>} {applying ? ui('script.applying') : ui('script.apply')}
      </button>
    </div>
    <div id={statusId} className={`restricted-lua-status ${error || validation?.valid === false ? 'is-error' : ''}`} role={error || validation?.valid === false ? 'alert' : 'status'}>
      {offline ? ui('script.offline') : disabled ? ui('task.readonly') : checking ? ui('script.checking') : applying ? ui('script.applying') : error || validation?.summary || (validation?.valid ? ui('script.valid') : ui('script.draft'))}
      {storageError && <span>{ui('edit.draftPersistError')}</span>}
    </div>
    {!!diagnostics.length && <ul className="restricted-lua-diagnostics" aria-label={ui('script.diagnostics')}>
      {diagnostics.map((diagnostic, index) => {
        const location = diagnosticLocation(diagnostic)
        const severity = diagnosticSeverity(diagnostic, !!validation?.valid)
        return <li key={`${diagnostic.code ?? diagnostic.message}-${index}`} className={`is-${severity}`}>
          <CircleAlert size={14} aria-hidden="true"/>
          <span>{location ? ui('script.location', {location}) : ui('script.global')}</span>
          <strong>{diagnostic.message}</strong>
        </li>
      })}
    </ul>}
  </div>
}
