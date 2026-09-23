import { Trash2 } from 'lucide-react'
import type { Value } from '../api/types'
import { useApp } from '../app/context'

export function StorageField({value, disabled, onClear}: {value: Value; disabled: boolean; onClear: () => void}) {
  const {ui} = useApp()
  return <div className="storage-field"><pre aria-label={ui('storage.content')}>{JSON.stringify(value, null, 2)}</pre><button type="button" className="button danger subtle" disabled={disabled} onClick={onClear}><Trash2 size={15}/>{ui('storage.clear')}</button></div>
}
