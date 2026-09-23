import { ArrowDown, ArrowUp } from 'lucide-react'
import { useState } from 'react'
import type { StatTable, TableSort } from '../api/types'
import { downloadCsv } from './statisticsData'
import { useApp } from '../app/context'
import { localeForLanguage } from '../i18n'

export function StatisticsTable({data}: {data: StatTable}) {
  const {ui, language} = useApp()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<TableSort>()
  const activeSort = sort ?? data.defaultSort
  const rows = data.rows.filter(row => row.some(value => String(value ?? '').toLowerCase().includes(search.toLowerCase())))
  if (activeSort) rows.sort((a, b) => {
    const av = a[activeSort.index], bv = b[activeSort.index]
    const order = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av ?? '').localeCompare(String(bv ?? ''), localeForLanguage(language), {numeric: true})
    return order * (activeSort.descending ? -1 : 1)
  })
  const pages = Math.max(1, Math.ceil(rows.length / 25))
  const current = Math.min(page, pages - 1)
  return <section className="statistics-table"><div className="panel-heading"><h3>{data.title}</h3><button className="text-button" disabled={!rows.length} onClick={() => downloadCsv(data.title, [data.columns, ...rows])}>{ui('stats.exportDetails')}</button></div>{data.note && <p className="panel-note">{data.note}</p>}<div className="table-toolbar"><input aria-label={ui('stats.searchTable', {title: data.title})} value={search} onChange={event => {setSearch(event.target.value); setPage(0)}} placeholder={ui('stats.searchPlaceholder')}/><span>{ui('stats.records', {count: rows.length})}</span></div><div className="table-scroll"><table><thead><tr>{data.columns.map((column, index) => <th key={column} aria-sort={activeSort?.index === index ? activeSort.descending ? 'descending' : 'ascending' : 'none'}><button onClick={() => {setPage(0); setSort(currentSort => {const current = currentSort ?? data.defaultSort; return {index, descending: current?.index === index ? !current.descending : false}})}}>{column}{activeSort?.index === index ? activeSort.descending ? <ArrowDown size={14} aria-hidden="true"/> : <ArrowUp size={14} aria-hidden="true"/> : null}</button></th>)}</tr></thead><tbody>{rows.slice(current * 25, (current + 1) * 25).map((row, index) => <tr key={index}>{row.map((value, cell) => <td key={cell}>{value == null ? '—' : typeof value === 'number' ? value.toLocaleString(localeForLanguage(language), {maximumFractionDigits: 4}) : String(value)}</td>)}</tr>)}</tbody></table>{!rows.length && <p className="panel-note">{ui('stats.noRecords')}</p>}</div><div className="table-toolbar"><button className="text-button" disabled={!current} onClick={() => setPage(current - 1)}>{ui('common.previous')}</button><span>{current + 1} / {pages}</span><button className="text-button" disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>{ui('common.next')}</button></div></section>
}
