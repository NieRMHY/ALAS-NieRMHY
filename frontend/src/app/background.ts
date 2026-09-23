export type BackgroundSource = 'default' | 'url' | 'upload'
export type BackgroundKind = 'image' | 'video'

export interface BackgroundPreference {
  source: BackgroundSource
  kind: BackgroundKind
  url: string
  name: string
}

export interface BackgroundSnapshot extends BackgroundPreference {
  assetUrl: string
  loading: boolean
  revision: number
}

export const DEFAULT_BACKGROUND_URL = 'https://api.yppp.net/api.php'
export const MAX_BACKGROUND_FILE_SIZE = 200 * 1024 * 1024
const STORAGE_KEY = 'azurpilot.background'
const DATABASE_NAME = 'azurpilot-preferences'
const DATABASE_VERSION = 1
const STORE_NAME = 'media'
const UPLOAD_KEY = 'background'
const listeners = new Set<() => void>()

function readPreference(): BackgroundPreference {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Partial<BackgroundPreference> | null
    if (value?.source === 'url' && (value.kind === 'image' || value.kind === 'video') && typeof value.url === 'string') {
      return {source: 'url', kind: value.kind, url: normalizeBackgroundUrl(value.url), name: ''}
    }
    if (value?.source === 'upload' && (value.kind === 'image' || value.kind === 'video')) {
      return {source: 'upload', kind: value.kind, url: '', name: typeof value.name === 'string' ? value.name : ''}
    }
  } catch { /* 存储不可用或旧数据损坏时使用默认背景。 */ }
  return {source: 'default', kind: 'image', url: '', name: ''}
}

const initial = readPreference()
let snapshot: BackgroundSnapshot = {
  ...initial,
  assetUrl: initial.source === 'default' ? DEFAULT_BACKGROUND_URL : initial.source === 'url' ? initial.url : '',
  loading: initial.source === 'upload',
  revision: 0,
}
let objectUrl = ''
let uploadLoad: Promise<void> | undefined

export const getBackground = () => snapshot
export const subscribeBackground = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(next: Omit<BackgroundSnapshot, 'revision'>) {
  snapshot = {...next, revision: snapshot.revision + 1}
  listeners.forEach(listener => listener())
}

function savePreference(value: BackgroundPreference) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)) } catch { /* 本次会话内仍立即生效。 */ }
}

function replaceObjectUrl(next = '') {
  if (objectUrl) URL.revokeObjectURL(objectUrl)
  objectUrl = next
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) return reject(new Error('当前浏览器不支持持久化文件存储。'))
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION)
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('无法打开背景文件存储。'))
  })
}

async function storedFile(mode: IDBTransactionMode, value?: Blob): Promise<Blob | undefined> {
  const database = await openDatabase()
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode)
      let result: Blob | undefined
      const request = value === undefined
        ? transaction.objectStore(STORE_NAME).get(UPLOAD_KEY)
        : transaction.objectStore(STORE_NAME).put(value, UPLOAD_KEY)
      request.onsuccess = () => { result = value === undefined ? request.result as Blob | undefined : value }
      request.onerror = () => reject(request.error ?? new Error('无法保存背景文件。'))
      transaction.onabort = () => reject(transaction.error ?? new Error('背景文件存储事务已中止。'))
      transaction.oncomplete = () => resolve(result)
    })
  } finally {
    database.close()
  }
}

async function deleteStoredFile() {
  let database: IDBDatabase | undefined
  try {
    const opened = await openDatabase()
    database = opened
    await new Promise<void>((resolve, reject) => {
      const transaction = opened.transaction(STORE_NAME, 'readwrite')
      const request = transaction.objectStore(STORE_NAME).delete(UPLOAD_KEY)
      request.onerror = () => reject(request.error)
      transaction.oncomplete = () => resolve()
    })
  } catch { /* 清理失败不应阻止切换到其他背景。 */ }
  finally { database?.close() }
}

export function normalizeBackgroundUrl(value: string): string {
  const input = value.trim()
  if (!input || input.length > 2048) throw new Error('请输入不超过 2048 个字符的背景地址。')
  let parsed: URL
  try { parsed = new URL(input) } catch { throw new Error('请输入有效的背景地址。') }
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('背景地址仅支持 HTTP 或 HTTPS。')
  return parsed.href
}

export async function loadUploadedBackground() {
  if (snapshot.source !== 'upload' || snapshot.assetUrl || uploadLoad) return uploadLoad
  uploadLoad = (async () => {
    try {
      const file = await storedFile('readonly')
      if (!file || snapshot.source !== 'upload') {
        const {revision: _, ...current} = snapshot
        return publish({...current, loading: false})
      }
      const url = URL.createObjectURL(file)
      replaceObjectUrl(url)
      if (snapshot.source === 'upload') {
        const {revision: _, ...current} = snapshot
        publish({...current, assetUrl: url, loading: false})
      }
    } catch {
      if (snapshot.source === 'upload') {
        const {revision: _, ...current} = snapshot
        publish({...current, loading: false})
      }
    } finally {
      uploadLoad = undefined
    }
  })()
  return uploadLoad
}

export function setBackgroundUrl(value: string, kind: BackgroundKind) {
  const url = normalizeBackgroundUrl(value)
  const preference: BackgroundPreference = {source: 'url', kind, url, name: ''}
  replaceObjectUrl()
  savePreference(preference)
  publish({...preference, assetUrl: url, loading: false})
  void deleteStoredFile()
}

export async function setBackgroundUpload(file: File) {
  const kind: BackgroundKind | undefined = file.type.startsWith('image/') ? 'image' : file.type.startsWith('video/') ? 'video' : undefined
  if (!kind) throw new Error('请选择图片或视频文件。')
  if (!file.size) throw new Error('所选文件为空。')
  if (file.size > MAX_BACKGROUND_FILE_SIZE) throw new Error('背景文件不能超过 200 MB。')
  await storedFile('readwrite', file)
  const url = URL.createObjectURL(file)
  const preference: BackgroundPreference = {source: 'upload', kind, url: '', name: file.name}
  replaceObjectUrl(url)
  savePreference(preference)
  publish({...preference, assetUrl: url, loading: false})
}

export function resetBackground() {
  const preference: BackgroundPreference = {source: 'default', kind: 'image', url: '', name: ''}
  replaceObjectUrl()
  savePreference(preference)
  publish({...preference, assetUrl: DEFAULT_BACKGROUND_URL, loading: false})
  void deleteStoredFile()
}
