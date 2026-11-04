import type { Parameters } from '../api/generated'

export type MindShip = Parameters['dock.stageImport']['ships'][number]
export type Rarity = 'N' | 'R' | 'SR' | 'SSR' | 'UR'
export interface CatalogShip {nationality?: number; nation?: string; name: string; raw_name?: string; group_type?: number; code?: number | null; rarity: Rarity; base_rarity: Rarity; base_name: string; group: string; type: string}
export interface MindCatalog {updated_at: string; ships: CatalogShip[]}
