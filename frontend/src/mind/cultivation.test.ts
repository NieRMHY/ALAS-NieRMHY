import {describe, expect, it} from 'vitest'
import {automaticCandidates, highestCopies, readPlan} from './cultivation'
import type {DockCard} from '../api/types'
import type {Catalog, Progress} from '../fleet-tech/types'
const card = (id: number, level: number, extra: Partial<DockCard> = {}): DockCard => ({id, name: '企业', group_type: 10706, level, rarity: 'SSR', base_rarity: 'SSR', extra_exp: null, review: false, source: '', ...extra})
const catalog = {ships: [{group_type: 10706, technology: {}}, {group_type: 10102, technology: null}]} as Catalog
const progress = (lv120: boolean) => [{group_type: 10706, lv120}] as Progress[]
describe('automatic cultivation', () => {
  it('selects highest physical copy once, keeping unknown identities separate', () => {
    expect(highestCopies([card(1, 100), card(2, 110), card(3, 0, {review: true}), card(4, 0, {review: true})])).toEqual([2, 3, 4])
    expect(automaticCandidates([card(1, 100), card(2, 110)], catalog, progress(false)).map(row => row.id)).toEqual([2])
  })
  it('retains cumulative completion after the level120 copy retires', () => {
    expect(automaticCandidates([card(1, 100)], catalog, progress(true))).toEqual([])
    expect(automaticCandidates([card(1, 100), card(2, 120)], catalog, progress(false))).toEqual([])
  })
  it('uses incomplete milestones without changing them and omits unsupported identities', () => {
    const facts = progress(false), before = JSON.stringify(facts)
    expect(automaticCandidates([card(1, 100), card(2, 119, {review: true}), card(3, 100, {group_type: 10102}), card(4, 0, {group_type: null})], catalog, facts).map(row => row.id)).toEqual([1])
    expect(JSON.stringify(facts)).toBe(before)
  })
  it('replaces the chosen copy automatically when a new higher copy appears', () => {
    const first = [card(1, 100)], updated = [...first, card(2, 110)]
    expect(automaticCandidates(first, catalog, progress(false)).map(row => row.id)).toEqual([1])
    expect(automaticCandidates(updated, catalog, progress(false)).map(row => row.id)).toEqual([2])
    expect(automaticCandidates([...updated, card(3, 120)], catalog, progress(true))).toEqual([])
  })
  it('stores exclusions by group so they survive replacement of the highest copy', () => {
    const plan = readPlan(JSON.stringify({excluded_groups: [10706, 10706, 99]}), [card(2, 110)])
    expect(plan.excluded_groups).toEqual([10706])
  })
  it('starts with no exclusions when preferences are missing or damaged', () => {
    expect(readPlan(null, [card(1, 100)])).toEqual({excluded_groups: []})
    expect(readPlan('{', [card(1, 100)])).toEqual({excluded_groups: []})
  })
})
