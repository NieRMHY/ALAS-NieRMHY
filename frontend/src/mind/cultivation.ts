import type {DockCard} from '../api/types'
import type {Catalog, Progress, Ship} from '../fleet-tech/types'
/** Compare all ships using the full four awakenings, independently of current progress. */
export function technologyEfficiency(ship: Pick<Ship, 'rarity' | 'technology'> | undefined, mindCosts: Record<string, number>) {
  const points = ship?.technology?.pt_level
  const rarity = ship?.rarity === 'PR' ? 'SSR' : ship?.rarity === 'DR' ? 'UR' : ship?.rarity
  const mind = rarity ? mindCosts[rarity] : undefined
  return {points, mind, value: points != null && mind != null && mind > 0 ? points / mind * 1000 : null}
}
export interface CultivationRow {
  id: number; name: string; current_level: number; level: number; target_level: number
  mind: number | null; mind2: number | null; gold: number | null
  status: 'exact' | 'unknown'; notes: string[]; stages: number[]
}
export interface CultivationReport {
  instance: string; revision: string; ships: CultivationRow[]; target_level: number
  included: number; unknown: number
  mind: number; mind2: number; gold: number; rules_sha256: string
  mind_costs_100_to_120: Record<string, number>
}
export interface CultivationPlan {excluded_groups: number[]}
export function highestCopies(cards: DockCard[]): number[] {
  const groups = new Map<string, DockCard>()
  for (const card of cards) {
    const key = card.review || !card.group_type ? `copy:${card.id}` : `group:${card.group_type}`
    const previous = groups.get(key)
    if (!previous || card.level > previous.level || card.level === previous.level && card.id < previous.id) groups.set(key, card)
  }
  return [...groups.values()].map(card => card.id)
}
/** Completed account achievements survive retirement; incomplete entries remain cultivation candidates. */
export function automaticCandidates(cards: DockCard[], catalog: Catalog, progress: Progress[]): DockCard[] {
  const supported = new Set(catalog.ships.filter(row => row.technology).map(row => row.group_type))
  const completed = new Set(progress.filter(row => row.lv120 === true).map(row => row.group_type))
  const confirmed = cards.filter(card => !card.review && card.group_type && supported.has(card.group_type))
  const highest = new Set(highestCopies(confirmed))
  return confirmed.filter(card => highest.has(card.id) && card.level < 120 && !completed.has(card.group_type!))
}
export function readPlan(raw: string | null, cards: DockCard[]): CultivationPlan {
  const groups = new Set(cards.map(card => card.group_type))
  try {
    const value = JSON.parse(raw ?? 'null') as CultivationPlan
    if (value && Array.isArray(value.excluded_groups)) {
      return {excluded_groups: [...new Set(value.excluded_groups.filter(id => Number.isInteger(id) && groups.has(id)))]}
    }
  } catch { /* Damaged preferences must never change confirmed data. */ }
  return {excluded_groups: []}
}
