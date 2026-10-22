import type {Parameters} from '../api/generated'

export type Change = NonNullable<Parameters['fleetTech.patch']['changes']>[number]
export interface Technology {pt_get: number; pt_upgrage: number; pt_level: number; max_star: number; add_get_shiptype: number[]; add_get_attr: number; add_get_value: number; add_level_shiptype: number[]; add_level_attr: number; add_level_value: number}
export interface Ship {group_type: number; code: number; handbook_type: number; blueprint: boolean; name: string; names: Record<string, string | null>; nationality: number; rarity: string; type: number; variant?: 'child' | 'mu' | ''; technology: Technology | null}
export interface Catalog {ships: Ship[]; nations: Record<string, [number[], number, number][][]>; updated_at: string; source_commit: string; max_points: number; nation_points: Record<string, number>}
export interface Progress {group_type: number; owned: boolean; full_star: boolean | null; lv120: boolean; level: number | null; observed_level: number | null; completion_target: number; acquire_level: number; acquire_lv120: boolean; status: 'complete' | 'unowned' | 'unfinished'; manual: boolean; points: number}
export interface ScanSummary {min_level: number; max_level: number; complete: boolean; reached_bottom: boolean; physical_count: number; expected_count: number | null; matched_count: number; review_count: number; updated_at: string; fingerprint: string; ships: [number, number][]}
export interface ReviewShip {name: string; level: number; source: string; candidates: number[]; group_type: number | null; review: boolean}
export interface Report {instance: string; revision: string; ships: Progress[]; nation_levels: Record<string, number | null>; bonuses: Record<string, Record<string, number>>; confirmed_points: number; completed: number; pending_star: number; min_level: number; max_level: number; last_scan: ScanSummary | null; review_ships: ReviewShip[]}
export type Row = Ship & Progress
export function scanRows(catalog: Catalog, scan: ScanSummary): Row[] {
  const levels = new Map(scan.ships)
  return catalog.ships.flatMap(ship => {
    const level = levels.get(ship.group_type)
    if (level === undefined) return []
    const lv120 = level >= 120
    const fullStar = level > 100 ? true : null
    return [{...ship, owned: true, full_star: fullStar, lv120, level, observed_level: level,
      status: lv120 ? 'complete' as const : 'unfinished' as const, manual: false,
      points: ship.technology ? ship.technology.pt_get + (fullStar ? ship.technology.pt_upgrage : 0)
        + (lv120 ? ship.technology.pt_level : 0) : 0,
      completion_target: lv120 ? 100 : 120, acquire_level: level, acquire_lv120: lv120}]
  })
}
export const shipType = (value: number) => [20, 21].includes(value) ? 1 : [22, 23, 24].includes(value) ? 22 : value
export function matches(row: Row, filters: Record<string, string[]>, query: string, scope: string, stage: string) {
  if (scope === 'tech' && !row.technology || scope === 'none' && row.technology) return false
  if (query && ![row.name, String(row.code).padStart(3, '0'), ...Object.values(row.names)].some(value => value?.toLocaleLowerCase().includes(query.toLocaleLowerCase()))) return false
  const type = shipType(row.type)
  const categories = [String(type), ...([1, 2, 3, 18].includes(type) ? ['front'] : [4, 5, 6, 7, 10, 12, 13].includes(type) ? ['back'] : [])]
  const statuses = [row.status, ...(row.owned ? ['owned'] : []), ...(row.status === 'unowned' || row.status === 'unfinished' ? ['incomplete'] : [])]
  for (const [key, values] of Object.entries(filters)) {
    if (!values.length || ['bonusType', 'attr'].includes(key)) continue
    const current = key === 'type' ? categories : key === 'status' ? statuses : key === 'nation' ? [String(row.nationality), row.variant ?? ''] : [row.rarity]
    if (!values.some(value => current.includes(value))) return false
  }
  if (filters.bonusType?.length || filters.attr?.length) {
    const t = row.technology
    if (!t) return false
    const effects = [...(stage !== 'level' ? [[t.add_get_shiptype, t.add_get_attr] as const] : []), ...(stage !== 'get' ? [[t.add_level_shiptype, t.add_level_attr] as const] : [])]
    if (!effects.some(([types, attr]) => (!filters.bonusType?.length || types.some(value => filters.bonusType!.includes(String(shipType(value))))) && (!filters.attr?.length || filters.attr.includes(String(attr))))) return false
  }
  return true
}

export function preview(row: Row, change?: Change): Row {
  if (!change || change.restore) return row
  const next = {...row, manual: true}
  if (change.toggle === 'owned') {
    next.owned = change.target === true
    if (!next.owned) {next.level = null; next.lv120 = false; next.full_star = false}
    else if (!row.owned) {next.level = row.acquire_level; next.lv120 = row.acquire_lv120}
  } else if (change.toggle === 'complete' && change.target !== row.lv120) {
    next.owned = true; next.level = row.completion_target; next.lv120 = change.target === true
  } else if (change.toggle === 'star') {
    next.full_star = change.target === true
    if (next.full_star) next.owned = true
  } else if (Object.hasOwn(change, 'level')) {
    next.level = change.level ?? null; next.lv120 = !!next.level && next.level >= 120
    if (next.level) next.owned = true
  }
  next.status = next.lv120 ? 'complete' : next.owned ? 'unfinished' : 'unowned'
  return next
}
