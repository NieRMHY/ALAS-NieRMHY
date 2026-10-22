import {useEffect, useMemo, useRef, useState, type ReactNode} from 'react'
import {useParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {editor} from '../config/editors'
import {ErrorBox, Loading, PageTitle} from '../components/ui'
import {Select} from '../components/FormControls'
import {translateFleetTech} from '../fleet-tech/i18n'
import {matches, preview, scanRows, shipType, type Catalog, type Change, type Report, type Row} from '../fleet-tech/types'
import '../fleet-tech/style.css'

const types = [1, 2, 3, 18, 4, 5, 7, 6, 13, 12, 10, 8, 17, 19, 22]
const attrs = [1, 2, 3, 4, 5, 6, 9, 8, 12]
const number = (value: number) => value.toLocaleString()
const has = (value: object, key: string) => Object.hasOwn(value, key)

export function FleetTechnology() {
  const {instance = ''} = useParams(), {language, ui, instances, notify} = useApp(), connection = useConnection()
  const tr = (key: string) => translateFleetTech(language, key)
  const [catalog, setCatalog] = useState<Catalog>(), [report, setReport] = useState<Report>()
  const catalogLoaded = useRef<Catalog | undefined>(undefined)
  const saved = useRef<Report | undefined>(undefined), writing = useRef(false), epoch = useRef(0)
  const scope = useRef({instance, token: 0})
  if (scope.current.instance !== instance) scope.current = {instance, token: scope.current.token + 1}
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [low, setLow] = useState('95'), [high, setHigh] = useState('125')
  const [edit, setEdit] = useState(false), [bonuses, setBonuses] = useState(false), [extra, setExtra] = useState(false)
  const [view, setView] = useState<'latest' | 'history'>('latest')
  const [query, setQuery] = useState(''), [mode, setMode] = useState('all'), [stage, setStage] = useState('all')
  const [filters, setFilters] = useState<Record<string, string[]>>({}), [page, setPage] = useState(0)
  const [sort, setSort] = useState({key: 'code', direction: 1})
  const pending = useRef<Record<string, Change>>({}), nationPending = useRef<Record<string, number | null>>({})
  const [drafts, setDrafts] = useState<Record<string, Change>>({}), [nationDrafts, setNationDrafts] = useState<Record<string, number | null>>({})
  const draftKey = `azurpilot.fleet-tech.${instance}`
  const current = instances.find(item => item.name === instance), scanning = current?.status === 'running' && current.currentTask === 'FleetTechScan'
  const scanReason = connection !== 'ready' ? ui('mind.scanDisconnected') : !current || !report ? ui('mind.scanLoading')
    : current.status === 'running' ? ui(scanning ? 'mind.scanInProgress' : 'mind.scanRunning')
    : current.status === 'updating' ? ui('mind.scanUpdating') : current.region && current.region !== 'cn' ? ui('mind.scanUnsupported') : ''
  function remember() {
    setDrafts({...pending.current}); setNationDrafts({...nationPending.current})
    try {
      if (Object.keys(pending.current).length || Object.keys(nationPending.current).length) sessionStorage.setItem(draftKey, JSON.stringify({changes: pending.current, nations: nationPending.current}))
      else sessionStorage.removeItem(draftKey)
    } catch { /* 存储被禁用时，当前页面仍保留待提交编辑。 */ }
  }
  async function reload(clearError = false) {
    const token = scope.current.token, version = ++epoch.current
    try {
      const [data, value] = await Promise.all([catalogLoaded.current ? Promise.resolve(catalogLoaded.current) : api.request('fleetTech.catalog', {instance}), api.request('fleetTech.report', {instance})])
      if (scope.current.token === token && epoch.current === version && !writing.current
          && (clearError || !saved.current || !Object.keys(pending.current).length && !Object.keys(nationPending.current).length)) {
        if (!saved.current) {setLow(String(value.min_level)); setHigh(String(value.max_level))}
        catalogLoaded.current = data; setCatalog(data); saved.current = value; setReport(value)
        // 自动轮询保留操作失败提示，只有用户主动重载才清除。
        if (clearError) setError('')
      }
    } catch (e) {if (scope.current.token === token) setError((e as Error).message)}
  }
  useEffect(() => {
    const token = scope.current.token
    let active = true
    saved.current = undefined; writing.current = false; epoch.current++
    setReport(undefined); setCatalog(undefined); catalogLoaded.current = undefined; setBusy(false); setError(''); setPage(0); setView('latest'); setEdit(false)
    pending.current = {}; nationPending.current = {}
    try {
      const draft = JSON.parse(sessionStorage.getItem(draftKey) ?? 'null')
      if (draft && typeof draft.changes === 'object' && draft.changes && typeof draft.nations === 'object' && draft.nations) {
        pending.current = draft.changes; nationPending.current = draft.nations
      }
    } catch { /* 不恢复损坏的浏览器草稿。 */ }
    setDrafts({...pending.current}); setNationDrafts({...nationPending.current})
    if (connection !== 'ready') return
    void Promise.all([api.request('fleetTech.catalog', {instance}), api.request('fleetTech.report', {instance})]).then(([data, value]) => {
      if (active && scope.current.token === token) {
        catalogLoaded.current = data; setCatalog(data); saved.current = value; setReport(value)
        setLow(String(value.min_level)); setHigh(String(value.max_level))
      }
    }).catch(e => {if (active) setError(e.message)})
    const timer = setInterval(() => {if (active && !writing.current) void reload()}, 5000)
    return () => {active = false; scope.current.token++; epoch.current++; clearInterval(timer)}
  }, [instance, connection])

  async function save() {
    if (writing.current || !saved.current) return
    const token = scope.current.token, changes = {...pending.current}, nations = {...nationPending.current}
    writing.current = true; epoch.current++; setBusy(true); setError('')
    try {
      const value = await api.request('fleetTech.patch', {instance, revision: saved.current.revision, changes: Object.values(changes), nations})
      // 请求成功时即使已切换实例，也只清除这次提交对应的旧草稿。
      try {
        if (sessionStorage.getItem(draftKey) === JSON.stringify({changes, nations})) sessionStorage.removeItem(draftKey)
      } catch { /* 存储不可用时，服务端记录仍已保存。 */ }
      if (scope.current.token !== token) return
      saved.current = value; setReport(value)
      for (const [key, change] of Object.entries(changes)) if (JSON.stringify(pending.current[key]) === JSON.stringify(change)) delete pending.current[key]
      for (const [key, level] of Object.entries(nations)) if (nationPending.current[key] === level) delete nationPending.current[key]
      remember(); notify(tr('saved'))
    } catch (e) {if (scope.current.token === token) setError((e as Error).message)}
    finally {if (scope.current.token === token) {writing.current = false; setBusy(false)}}
  }
  function commit(change: Change) {
    const key = String(change.group_type)
    pending.current[key] = change
    remember(); void save()
  }
  async function action(run: () => Promise<unknown>) {
    if (writing.current) return
    const token = scope.current.token
    writing.current = true; epoch.current++; setBusy(true); setError('')
    try {await run()} catch (e) {if (scope.current.token === token) setError((e as Error).message)}
    finally {if (scope.current.token === token) {writing.current = false; setBusy(false); void reload()}}
  }
  const historyRows = useMemo(() => {
    const progress = new Map(report?.ships.map(row => [row.group_type, row]))
    return (catalog?.ships ?? []).flatMap(ship => progress.has(ship.group_type) ? [preview({...ship, ...progress.get(ship.group_type)!}, drafts[ship.group_type])] : [])
  }, [catalog, report, drafts])
  const hasScan = Array.isArray(report?.last_scan?.ships)
  const latest = view === 'latest' && hasScan && !edit
  const rows = useMemo(() => latest && catalog && report?.last_scan ? scanRows(catalog, report.last_scan) : historyRows,
    [latest, catalog, report, historyRows])
  function nation(value: number) {const label = tr(`nation.${value}`); return label.startsWith('nation.') ? `${tr('collaboration')} · ${value}` : label}
  function rarity(value: string) {return value === 'PR' || value === 'DR' ? tr(`rarity.${value}`) : ui(`mind.rarity.${value}` as 'mind.rarity.N')}
  function effect(row: Row, stage: 'get' | 'level') {
    const t = row.technology
    return t ? `${[...new Set(t[`add_${stage}_shiptype`].map(shipType))].map(value => tr(`type.${value}`)).join('/')} ${tr(`attr.${t[`add_${stage}_attr`]}`)}+${t[`add_${stage}_value`]}` : '—'
  }
  function sortValue(row: Row): number | string {
    const t = row.technology
    if (['pt_get', 'pt_upgrage', 'pt_level'].includes(sort.key)) return t?.[sort.key as 'pt_get'] ?? -1
    if (sort.key === 'total') return t ? t.pt_get + t.pt_upgrage + t.pt_level : -1
    if (sort.key === 'get' || sort.key === 'level') return effect(row, sort.key)
    if (sort.key === 'scanLevel') return row.level ?? -1
    return sort.key === 'name' ? row.name : sort.key === 'nation' ? row.nationality : sort.key === 'type' ? row.type : row.code
  }
  const filtered = rows.filter(row => matches(row, filters, query, mode, extra ? stage : 'all')).sort((a, b) => {
    const x = sortValue(a), y = sortValue(b)
    return sort.direction * (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y)))
  })
  const pages = Math.max(1, Math.ceil(filtered.length / 50)), currentPage = Math.min(page, pages - 1)
  function toggle(key: string, value: string) {
    setFilters(previous => ({...previous, [key]: !value ? [] : previous[key]?.includes(value) ? previous[key]!.filter(item => item !== value) : [...previous[key] ?? [], value]})); setPage(0)
  }
  function group(key: string, options: [string, string][]) {
    return <div className="ft-filter-row" key={key}><strong>{tr(key === 'type' ? 'category' : key)}</strong><div className="ft-chips">{[['', tr('all')], ...options].map(([value, label]) => <button key={value} aria-pressed={value ? filters[key]?.includes(value) ?? false : !filters[key]?.length} onClick={() => toggle(key, value!)}>{label}</button>)}</div></div>
  }
  function head(key: string, label: string, span = 1) {
    return <th rowSpan={span} aria-sort={sort.key === key ? sort.direction === 1 ? 'ascending' : 'descending' : 'none'}><button onClick={() => setSort({key, direction: sort.key === key ? -sort.direction : 1})}>{label} <small>↕</small></button></th>
  }
  function marker(row: Row, field: 'owned' | 'complete' | 'star', content: ReactNode, label: string) {
    const active = field === 'owned' ? row.owned : field === 'complete' ? row.lv120 : !!row.full_star
    const inner = <>{active && field === 'star' && edit && <span className="ft-check" aria-hidden="true">✓</span>}{content}</>
    return edit ? <button className="ft-state-button" aria-label={`${label} ${row.name} (${row.code})`} aria-pressed={active}
      disabled={busy || connection !== 'ready' || !!drafts[row.group_type]}
      onClick={() => commit({group_type: row.group_type, toggle: field, target: !active})}>{inner}</button>
      : <span className="ft-state-value">{inner}</span>
  }
  if (!catalog || !report) return error ? <ErrorBox message={error} retry={() => void reload(true)}/> : <Loading/>
  const nations = [...new Set(historyRows.map(row => row.nationality))].sort((a, b) => a - b)
  const dirty = Object.keys(drafts).length + Object.keys(nationDrafts).length
  return <div className="fleet-technology">
    <PageTitle title={tr('title')} actions={<button className="button secondary" disabled={busy || connection !== 'ready'} onClick={() => void reload(true)}>{ui('mind.reload')}</button>}/>
    {error && <ErrorBox message={error} retry={() => void reload(true)}/>}
    <section className="ft-summary"><div><small>{tr('historySummary')}</small><p>{tr('max')}： <b>{number(catalog.max_points)}</b></p><p>{tr('four')}： {[1, 2, 3, 4].map(id => <span key={id}>{nation(id)} {number(catalog.nation_points[id] ?? 0)}　</span>)}</p><p>{tr('count')}： <b>{report.completed} / {historyRows.filter(row => row.technology).length}</b>　{tr('confirmed')}：{number(report.confirmed_points)}　<small>{tr('pendingStar')}{report.pending_star}</small></p></div><small>{tr('version')}：Lua · {catalog.updated_at}<br/>{tr('all')} {historyRows.length} · {tr('tech')} {historyRows.filter(row => row.technology).length} · {tr('none')} {historyRows.filter(row => !row.technology).length}</small></section>
    <section className="ft-toolbar">
      <label>{tr('low')}<input aria-label={tr('low')} type="number" min={1} max={125} value={low} disabled={busy || !!scanReason} onChange={e => setLow(e.target.value)}/></label>
      <label>{tr('high')}<input aria-label={tr('high')} type="number" min={1} max={125} value={high} disabled={busy || !!scanReason} onChange={e => setHigh(e.target.value)}/></label>
      <button className="button primary" title={scanReason} disabled={busy || !!scanReason || !!dirty} onClick={() => void action(async () => {
        const min = Number(low), max = Number(high)
        if (!low.trim() || !high.trim() || !Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max > 125 || min > max) throw new Error(ui('mind.invalidRange'))
        await editor(`config:${instance}`).settled()
        const config = await api.request('config.get', {instance})
        await api.request('config.patch', {instance, revision: config.revision, changes: [{path: 'FleetTechScan.FleetTech.MinLevel', value: min}, {path: 'FleetTechScan.FleetTech.MaxLevel', value: max}]})
        await api.request('tasks.run', {instance, task: 'FleetTechScan'})
        setView('latest'); setEdit(false); setPage(0)
      })}>{tr('scan')}</button>
      {scanning && <button className="button secondary" disabled={busy} onClick={() => void action(() => api.request('scheduler.stop', {instance}))}>{ui('mind.stop')}</button>}
      <button className="button secondary" disabled={busy || connection !== 'ready' || !!dirty} onClick={() => void action(() => api.request('fleetTech.syncMind', {instance}))}>{tr('sync')}</button>
      {dirty > 0 && <button className="button secondary" disabled={busy || connection !== 'ready'} onClick={() => void save()}>{tr('retry')} ({dirty})</button>}
      <small role="status">{busy ? ui('mind.processing') : dirty ? ui('mind.unsaved') : scanReason || tr('hint')}</small>
    </section>
    <section className="ft-view" aria-label={tr('resultView')}><div className="ft-chips">
      <button aria-pressed={latest} disabled={!hasScan || busy} onClick={() => {setView('latest'); setEdit(false); setPage(0)}}>{tr('latestScan')}</button>
      <button aria-pressed={!latest} disabled={busy} onClick={() => {setView('history'); setPage(0)}}>{tr('history')}</button>
    </div><small>{tr(latest ? 'latestHint' : 'historyHint')}</small></section>
    {report.last_scan && <p className="ft-scan-summary">{tr(report.last_scan.complete ? 'fullScan' : 'partialScan')} · Lv.{report.last_scan.min_level}–{report.last_scan.max_level} · {tr('matched')} {report.last_scan.matched_count} · {tr('review')} {report.review_ships.length} · {tr('scanTime')} {report.last_scan.updated_at.replace('T', ' ')}</p>}
    {!!report.review_ships.length && <details className="ft-reviews"><summary>{tr('review')} ({report.review_ships.length})</summary><p>{tr('reviewHint')}</p>
      {report.review_ships.map((ship, index) => <div key={index}><span>{ship.name} · {ship.level ? `Lv.${ship.level}` : tr('unknown')}</span>
        {(ship.candidates?.length ? ship.candidates : ship.group_type ? [ship.group_type] : []).map(gid => {const row = historyRows.find(item => item.group_type === gid); return row && <button key={gid} className="button secondary" onClick={() => {setFilters({}); setMode('all'); setQuery(String(row.code)); setView('history'); setEdit(true); setPage(0)}}>{row.name} · {nation(row.nationality)} · {tr(`type.${shipType(row.type)}`)} · {row.code}</button>})}
        <small>{ship.source}</small></div>)}
    </details>}
    <section className="ft-filters">
      {group('type', [['front', tr('front')], ['back', tr('back')], ...types.map(value => [String(value), tr(`type.${value}`)] as [string, string])])}
      {group('rarity', ['N', 'R', 'SR', 'SSR', 'UR', 'PR', 'DR'].map(value => [value, rarity(value)]))}
      {group('nation', [...nations.map(value => [String(value), nation(value)] as [string, string]), ['mu', tr('mu')], ['child', tr('child')]])}
      {group('bonusType', types.map(value => [String(value), tr(`type.${value}`)]))}
      {group('attr', attrs.map(value => [String(value), tr(`attr.${value}`)]))}
      {group('status', ['incomplete', 'unfinished', 'unowned', 'owned', 'complete'].map(value => [value, tr(value)]))}
      <div className="ft-filter-row"><strong>{tr('functions')}</strong><div className="ft-chips"><button aria-pressed={edit} onClick={() => {setView('history'); setEdit(!edit)}}>{tr('edit')}</button><button aria-pressed={bonuses} onClick={() => setBonuses(!bonuses)}>{tr('bonuses')}</button><button aria-pressed={extra} onClick={() => setExtra(!extra)}>{tr('extra')}</button></div></div>
    </section>
    {extra && <label className="ft-stage">{tr('stage')}<Select value={stage} onChange={e => {setStage(e.target.value); setPage(0)}}><option value="all">{tr('all')}</option><option value="get">{tr('unlock')}</option><option value="level">Lv.120</option></Select></label>}
    {bonuses && <section className="ft-bonuses"><h2>{tr('bonuses')}</h2><div className="ft-nation-levels">{Object.entries(catalog.nations).map(([id, levels]) => <label key={id}>{nation(Number(id))} {tr('factionLevel')}<Select aria-label={`${nation(Number(id))} ${tr('factionLevel')}`} disabled={busy || connection !== 'ready'} value={(has(nationDrafts, id) ? nationDrafts[id] : report.nation_levels[id]) ?? ''} onChange={e => {nationPending.current[id] = e.target.value === '' ? null : Number(e.target.value); remember(); void save()}}><option value="">{tr('unknown')}</option>{Array.from({length: levels.length + 1}, (_, value) => <option key={value} value={value}>{value}</option>)}</Select></label>)}</div><p>{tr('factionHint')}</p><div className="ft-bonus-grid">{Object.entries(report.bonuses).map(([type, values]) => <div key={type}><b>{tr(`type.${type}`)}</b> {Object.entries(values).map(([attr, value]) => `${tr(`attr.${attr}`)}+${value}`).join(' · ')}</div>)}</div></section>}
    <div className="ft-search"><input aria-label={tr('search')} placeholder={tr('search')} value={query} onChange={e => {setQuery(e.target.value); setPage(0)}}/><label>{tr('scope')}<Select aria-label={tr('scope')} value={mode} onChange={e => {setMode(e.target.value); setPage(0)}}>{['all', 'tech', 'none'].map(value => <option value={value} key={value}>{tr(value)}</option>)}</Select></label><span>{ui('mind.rowCount', {count: filtered.length})}</span></div>
    <div className="ft-table-wrap"><table><thead><tr>{head('code', tr('code'), 2)}{head('name', tr('name'), 2)}{latest && head('scanLevel', tr('observedLevel'), 2)}{head('nation', tr('nation'), 2)}{head('type', tr('shipClass'), 2)}<th colSpan={4}>{tr('points')}</th><th colSpan={2}>{tr('bonuses')}</th>{edit && <th rowSpan={2}>{tr('edit')}</th>}</tr><tr>{head('pt_get', tr('get'))}{head('pt_upgrage', tr('star'))}{head('pt_level', 'Lv.120')}{head('total', tr('total'))}{head('get', tr('unlock'))}{head('level', 'Lv.120')}</tr></thead><tbody>{filtered.slice(currentPage * 50, currentPage * 50 + 50).map(row => {
      const t = row.technology, level = row.level
      const name = row.names[language === 'en-US' ? 'en' : language === 'ja-JP' ? 'jp' : language === 'zh-TW' ? 'tw' : 'cn'] || row.name
      return <tr key={row.group_type} className={`ft-${row.status}`} data-group={row.group_type} title={[row.level ? `Lv.${row.level}` : '', row.manual ? tr('manual') : ''].filter(Boolean).join(' · ') || undefined}>
        <td>{String(row.code).padStart(3, '0')}</td><td className={`ft-name ft-rarity-${row.rarity}`}>{name}</td>{latest && <td>Lv.{row.level}</td>}
        <td>{nation(row.nationality)}{row.variant && <small> · {tr(row.variant)}</small>}</td><td>{tr(`type.${shipType(row.type)}`)}</td>
        <td>{t?.pt_get ?? '—'}</td><td className="ft-state-cell">{t ? marker(row, 'star', t.pt_upgrage, tr('star')) : '—'}</td>
        <td>{t?.pt_level ?? '—'}</td><td>{t ? t.pt_get + t.pt_upgrage + t.pt_level : '—'}</td>
        <td className={`ft-state-cell ft-unlock ${row.owned ? 'ft-marked' : ''}`}>{marker(row, 'owned', effect(row, 'get'), tr('unlock'))}</td>
        <td className={`ft-state-cell ft-completion ${row.lv120 ? 'ft-marked' : ''}`}>{marker(row, 'complete', effect(row, 'level'), tr('completion'))}</td>
        {edit && <td className="ft-edit"><label>{tr('level')}<input key={`${row.group_type}:${level}`} aria-label={`${tr('level')} ${row.name} (${row.code})`}
          disabled={busy || connection !== 'ready' || !!drafts[row.group_type]} type="number" min={1} max={125} defaultValue={level ?? ''}
          onKeyDown={e => {if (e.key === 'Enter') e.currentTarget.blur()}}
          onBlur={e => {const value = e.target.value === '' ? null : Number(e.target.value); if (value !== level) {if (value !== null && (!Number.isInteger(value) || value < 1 || value > 125)) {setError(ui('mind.invalidRange')); return} commit({group_type: row.group_type, level: value})}}}/></label>
          <button disabled={busy || connection !== 'ready'} onClick={() => commit({group_type: row.group_type, restore: true})}>{tr('restore')}</button></td>}
      </tr>
    })}</tbody></table>{!filtered.length && <p className="ft-empty">{ui('mind.empty')}</p>}</div>
    <footer><a href="https://wiki.biligame.com/blhx/舰队科技" target="_blank" rel="noreferrer">{tr('attribution')}</a><div><button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>{ui('mind.previous')}</button><span>{currentPage + 1} / {pages}</span><button disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>{ui('mind.next')}</button></div></footer>
  </div>
}
