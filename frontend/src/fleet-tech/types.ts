export interface Technology {pt_get: number; pt_upgrage: number; pt_level: number; max_star: number; add_get_shiptype: number[]; add_get_attr: number; add_get_value: number; add_level_shiptype: number[]; add_level_attr: number; add_level_value: number}
export interface Ship {group_type: number; code: number; handbook_type: number; blueprint: boolean; full_star_rule: 'ordinary_level_cap' | 'explicit_breakthrough'; name: string; names: Record<string, string | null>; nationality: number; rarity: string; type: number; variant?: 'child' | 'mu' | ''; technology: Technology | null}
export interface Catalog {ships: Ship[]; nations: Record<string, [number[], number, number][][]>; updated_at: string; source_commit: string; max_points: number; nation_points: Record<string, number>; mind_costs_100_to_120?: Record<string, number>}
export type Milestone = 'owned' | 'full_star' | 'lv120'
export type RecordField = Milestone | 'awakening_pending'
export type State = boolean
export interface Change {group_type: number; owned?: State; full_star?: State; lv120?: State; awakening_pending?: State}
export interface Progress {source?: string; updated_at?: string; group_type: number; owned: State; full_star: State; lv120: State; awakening_pending: State; current_count: number; current_level: number | null; evidence: Record<Milestone, number[]>; points: number; status: 'complete' | 'unowned' | 'unfinished'}
export type Bonuses = Record<string, Record<string, number>>
export interface Report {instance: string; revision: string; data_version?: string; ships: Progress[]; nation_levels: Record<string, number | null>; bonuses: Bonuses; ship_bonuses: Bonuses; nation_bonuses: Bonuses; confirmed_points: number; completed: number; milestone_counts: Record<Milestone, number>}
export type Row = Ship & Progress
export const milestones: Milestone[] = ['owned', 'full_star', 'lv120']
export const recordFields: RecordField[] = [...milestones, 'awakening_pending']
export const shipType = (value: number) => [20, 21].includes(value) ? 1 : [22, 23, 24].includes(value) ? 22 : value
/** Unrecorded milestones start incomplete, independently of current holdings. */
export function catalogRows(catalog: Catalog, progress: Progress[]): Row[] {
  const facts = new Map(progress.map(row => [row.group_type, row]))
  return catalog.ships.map(ship => ({...ship, ...(facts.get(ship.group_type) ?? {
    group_type: ship.group_type, owned: false, full_star: false, lv120: false, awakening_pending: false, current_count: 0,
    current_level: null, evidence: {owned: [], full_star: [], lv120: []}, points: 0, status: 'unowned' as const,
  })}))
}
export function complete(row: Row) {return milestones.every(key => row[key] === true)}
export function matches(row: Row, filters: Record<string, string[]>, query: string) {
  if (query && ![row.name, ...Object.values(row.names), String(row.code).padStart(3, '0')].some(value => value?.toLocaleLowerCase().includes(query.toLocaleLowerCase()))) return false
  const statuses = [
    ...(!row.current_count ? ['notHeld'] : ['held']),
    ...(row.owned === false ? ['unowned'] : []),
    ...(row.owned === true ? ['owned'] : []),
    ...(row.lv120 === true ? ['lv120'] : row.owned === true && row.lv120 === false ? ['unfinished'] : []),
    ...(row.full_star === false ? ['missingStar'] : []),
    ...(row.awakening_pending ? ['awakening_pending'] : []),
    ...(row.lv120 === false && !row.awakening_pending ? ['notTrained120'] : []),
    ...(row.lv120 === false ? ['missing120'] : []),
    ...(row.technology && !complete(row) ? ['incomplete'] : []),
    ...(row.technology && complete(row) ? ['complete'] : []),
  ]
  for (const [key, values] of Object.entries(filters)) {
    if (!values.length || ['bonusType', 'attr', 'getBonusType', 'getAttr', 'levelBonusType', 'levelAttr'].includes(key)) continue
    // Sailing S (22) is submarine-positioned, V (23) is front, and M (24) is back.
    const current = key === 'type' ? [String(shipType(row.type)), ...([1, 2, 3, 18, 19, 20, 21, 23].includes(row.type) ? ['front'] : []), ...([4, 5, 6, 7, 10, 12, 13, 24].includes(row.type) ? ['back'] : [])] : key === 'status' ? statuses : key === 'nation' ? [String(row.nationality)] : [row.rarity]
    if (!values.some(value => current.includes(value))) return false
  }
  if (filters.bonusType?.length || filters.attr?.length) {
    const t = row.technology
    if (!t) return false
    const effects = [[t.add_get_shiptype, t.add_get_attr], [t.add_level_shiptype, t.add_level_attr]] as const
    if (!effects.some(([types, attr]) => (!filters.bonusType?.length || types.some(value => filters.bonusType!.includes(String(shipType(value))))) && (!filters.attr?.length || filters.attr.includes(String(attr))))) return false
  }
  for (const stage of ['get', 'level'] as const) {
    const classes = filters[`${stage}BonusType`], attrs = filters[`${stage}Attr`], t = row.technology
    if ((classes?.length || attrs?.length) && (!t
      || classes?.length && !t[`add_${stage}_shiptype`].some(value => classes.includes(String(shipType(value))))
      || attrs?.length && !attrs.includes(String(t[`add_${stage}_attr`])))) return false
  }
  return true
}
/** Completing fills prerequisites; clearing ownership also clears both dependent milestones. */
export function changeMilestone(change: Change, key: Milestone, value: State, fullStarRule?: Ship['full_star_rule']): Change {
  const next = {...change, [key]: value}
  if (key === 'owned' && !value) return {...next, full_star: false, lv120: false}
  if (key === 'full_star' && !value && fullStarRule === 'ordinary_level_cap') return {...next, lv120: false}
  if (value && key !== 'owned') next.owned = true
  if (value && key === 'lv120' && fullStarRule === 'ordinary_level_cap') next.full_star = true
  return next
}
