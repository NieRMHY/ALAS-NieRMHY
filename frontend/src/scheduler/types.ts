/** 卡片公共模型；程序请求结构来自后端生成的契约。 */
import type {Parameters, SchedulerModels} from '../api/generated'

export type ProgramMode = 'native' | 'enhance' | 'takeover'
export type PortType = 'any' | 'number' | 'boolean' | 'string' | 'time' | 'duration' | 'resource' | 'task' | 'tasks' | 'result' | 'list' | 'object'
export interface Port {name: string; type: PortType; required: boolean}
export interface ProgramNode {id: string; type: string; label: string; comment?: string; params: Record<string, unknown>; position: {x: number; y: number}}
export interface ProgramEdge {id: string; source: string; sourcePort: string; target: string; targetPort: string; kind: 'control' | 'data'}
export interface Graph {entry: string; nodes: ProgramNode[]; edges: ProgramEdge[]}
export interface Subgraph extends Graph {id: string; name: string; pure: boolean; inputs: Port[]; outputs: Port[]}
export interface ProgramDocument extends Graph {
  schemaVersion: 1; name: string; subgraphs: Subgraph[]
  variables: Array<{name: string; type: PortType; initial: unknown; persistent: boolean}>
  viewport: {x: number; y: number; zoom: number}
}
export type ProgramRequest = Parameters['scheduler.program.save']['document']
export interface CardDefinition {type: string; label: string; category: string; pure: boolean; entry?: boolean; inputs: Port[]; outputs: Port[]; exits: string[]; params: Record<string, unknown>}
export interface Catalog {
  cards: CardDefinition[]; builtins: Subgraph[]; templates: Record<'takeover' | 'enhance' | 'all', ProgramDocument>
  tasks: Array<{name: string; command: string; enabled: boolean; nextRun: string}>
  resources: Array<{name: string; label: string; refreshable: boolean}>
  overrides: Record<string, string | string[]>
}
export interface ProgramSaved {mode: ProgramMode; draft: ProgramDocument; active: ProgramDocument | null; revision: string; generation: number}
export interface ProgramDiagnostic {message: string; node?: string | null; graph: string}
export interface ProgramValidation {valid: boolean; diagnostics: ProgramDiagnostic[]}
export type ResourceObservation = SchedulerModels['ResourceObservation']
export type TaskInvocation = SchedulerModels['TaskInvocation']
export type TaskOutcome = SchedulerModels['TaskOutcome']
export type ProgramState = Required<Pick<SchedulerModels['ProgramState'], 'status' | 'trace'>> & SchedulerModels['ProgramState']
export interface ProgramSimulation extends ProgramValidation {state: ProgramState; effects: Array<Record<string, unknown>>; persistent?: Record<string, unknown>}
export interface RuntimeProgramState {mode: ProgramMode; generation: number; state: ProgramState}
