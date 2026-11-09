import {useEffect, useState, type Dispatch, type SetStateAction} from 'react'

type Preference = string | boolean | Record<string, string[]> | {column: string; direction: 'ascending' | 'descending'}

function read<T extends Preference>(key: string, fallback: T): T {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    if (typeof fallback !== 'object') return typeof value === typeof fallback ? value as T : fallback
    if (!value || typeof value !== 'object' || Array.isArray(value)) return fallback
    if ('column' in fallback) {
      return 'column' in value && typeof value.column === 'string' && 'direction' in value
        && (value.direction === 'ascending' || value.direction === 'descending') ? value as T : fallback
    }
    return Object.values(value).every(items => Array.isArray(items) && items.every(item => typeof item === 'string')) ? value as T : fallback
  } catch {return fallback}
}

export function useFleetPreference<T extends Preference>(instance: string, name: string, fallback: T): [T, Dispatch<SetStateAction<T>>] {
  const key = `azurpilot.fleet-view.v1.${instance}.${name}`
  const [stored, setStored] = useState(() => ({key, value: read(key, fallback)}))
  const value = stored.key === key ? stored.value : read(key, fallback)
  // 切换实例时先恢复该实例的选择，避免把上一实例的筛选写到新实例。
  if (stored.key !== key) setStored({key, value})
  useEffect(() => {
    if (stored.key === key) try {localStorage.setItem(key, JSON.stringify(stored.value))} catch { /* 浏览器存储不可用时仍可操作当前页面。 */ }
  }, [key, stored])
  return [value, update => setStored(previous => ({key, value: typeof update === 'function'
    ? update(previous.key === key ? previous.value : read(key, fallback)) : update}))]
}
