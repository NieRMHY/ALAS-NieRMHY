import {describe, expect, it} from 'vitest'
import {compatible, duplicate, horizontalLayout, withComments} from './graph'
import type {Graph, ProgramDocument} from './types'

const graph: Graph = {
  entry:'entry', nodes:[
    {id:'entry', type:'entry', label:'', params:{}, position:{x:90,y:70}},
    {id:'loop', type:'loop', label:'日常循环', comment:'循环执行日常任务', params:{count:3}, position:{x:0,y:0}},
    {id:'resource', type:'resource', label:'', params:{name:'Oil'}, position:{x:0,y:0}},
    {id:'branch', type:'branch', label:'', params:{}, position:{x:0,y:0}},
    {id:'repeat', type:'loop_end', label:'', params:{loop:'loop'}, position:{x:0,y:0}},
  ], edges:[
    {id:'1', source:'entry', sourcePort:'next', target:'loop', targetPort:'in', kind:'control'},
    {id:'2', source:'loop', sourcePort:'body', target:'branch', targetPort:'in', kind:'control'},
    {id:'3', source:'resource', sourcePort:'value', target:'branch', targetPort:'condition', kind:'data'},
    {id:'4', source:'branch', sourcePort:'yes', target:'repeat', targetPort:'in', kind:'control'},
  ],
}

describe('调度图编辑', () => {
  it('按执行和数据依赖横向排列，保留程序语义与原文档', () => {
    const before = structuredClone(graph), result = horizontalLayout(graph)
    const positions = new Map(result.nodes.map(n => [n.id,n.position]))
    for (const edge of graph.edges) expect(positions.get(edge.target)!.x).toBeGreaterThan(positions.get(edge.source)!.x)
    expect(positions.get('entry')!.y).not.toBe(positions.get('resource')!.y)
    expect(result.edges).toBe(graph.edges)
    expect(graph).toEqual(before)
    expect(horizontalLayout(result)).toEqual(result)
  })
  it('复制循环时重绑定结束卡片，并保留自定义别名与注释', () => {
    const result = duplicate(graph, new Set(['loop','branch','repeat']))
    const loop = result.nodes.find(n => n.type === 'loop')!
    expect(loop.label).toBe('日常循环')
    expect(loop.comment).toBe('循环执行日常任务')
    expect(result.nodes.find(n => n.type === 'loop_end')!.params.loop).toBe(loop.id)
    expect(result.edges).toHaveLength(2)
    expect(result.edges.every(e => result.nodes.some(n => n.id === e.source) && result.nodes.some(n => n.id === e.target))).toBe(true)
    expect(graph.nodes.find(n => n.id === 'repeat')!.params.loop).toBe('loop')
  })
  it('兼容补全旧文档缺少的注释字段并保留已有别名与注释', () => {
    const legacyDoc = {
      schemaVersion: 1 as const,
      entry: 'entry',
      name: '旧方案',
      subgraphs: [],
      variables: [],
      viewport: {x: 0, y: 0, zoom: 1},
      nodes: [
        {id: 'a', type: 'filter', label: '启用过滤', params: {}, position: {x: 0, y: 0}},
        {id: 'b', type: 'execute', label: '', comment: '已存在的注释', params: {}, position: {x: 0, y: 0}},
      ],
      edges: [],
    } as unknown as ProgramDocument
    const normalized = withComments(legacyDoc)
    expect(normalized.nodes[0]!.comment).toBe('')
    expect(normalized.nodes[0]!.label).toBe('启用过滤')
    expect(normalized.nodes[1]!.comment).toBe('已存在的注释')
  })
  it('只允许兼容的端口类型连接', () => {
    expect(compatible('task','tasks')).toBe(false)
    expect(compatible('number','boolean')).toBe(false)
    expect(compatible('resource','number')).toBe(false)
    expect(compatible('duration','number')).toBe(true)
    expect(compatible('tasks','list')).toBe(true)
    expect(compatible('object','resource')).toBe(true)
  })
})
