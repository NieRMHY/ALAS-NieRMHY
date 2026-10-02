/** 画布快捷键；文本控件由浏览器处理自己的复制、粘贴和删除。 */
export type EditorCommand = 'copy' | 'cut' | 'paste' | 'undo' | 'redo' | 'delete' | 'all' | 'clear'
export function editorCommand(event: {key:string; ctrlKey:boolean; metaKey:boolean; shiftKey:boolean; altKey:boolean}): EditorCommand | undefined {
  if (event.altKey) return
  const key = event.key.toLowerCase(), modifier = event.ctrlKey || event.metaKey
  if (modifier) return ({c:'copy', x:'cut', v:'paste', a:'all', y:'redo', z:event.shiftKey ? 'redo' : 'undo'} as Record<string,EditorCommand>)[key]
  if (key === 'backspace' || key === 'delete') return 'delete'
  if (key === 'escape') return 'clear'
}
export function editingText(target: EventTarget | null) {
  return target instanceof Element && !!target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="textbox"]')
}
