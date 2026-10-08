import {useEffect, useMemo, useRef} from 'react'
import {init, use} from 'echarts/core'
import {SankeyChart} from 'echarts/charts'
import {TooltipComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import type {ResourceFlowReport} from '../api/types'
import {useApp} from '../app/context'
import {flowGraph, type FlowLink, type FlowNode} from './graph'

use([SankeyChart, TooltipComponent, SVGRenderer])
export function Sankey({report, resourceLabel, taskLabel, onPick}: {report: ResourceFlowReport; resourceLabel: (key: string) => string; taskLabel: (key: string) => string; onPick: (resource: string, task?: string) => void}) {
  const {ui, resolvedMode, theme, language} = useApp(), container = useRef<HTMLDivElement>(null)
  const graph = useMemo(() => flowGraph(report, {resource: resourceLabel, task: taskLabel, stock: ui('flow.stock'), balance: ui('flow.balance')}), [report, resourceLabel, taskLabel, ui])
  useEffect(() => {
    const element = container.current!
    const chart = init(element, undefined, {renderer: 'svg'})
    const color = getComputedStyle(element).getPropertyValue('--text').trim() || (resolvedMode === 'dark' ? '#eee' : '#333')
    chart.setOption({animation: false, tooltip: {trigger: 'item', renderMode: 'richText', confine: true, formatter: (value: {dataType: string; data: FlowLink | FlowNode}) => {
      if (value.dataType === 'edge') {const link = value.data as FlowLink; return `${resourceLabel(link.resource)} · ${link.label}\n${link.amount.toLocaleString()}`}
      const node = value.data as FlowNode
      return `${resourceLabel(node.resource!)} · ${node.label}${node.amount === undefined ? '' : `\n${node.amount.toLocaleString()}`}`
    }}, series: [{type: 'sankey', left: 12, right: 140, top: 12, bottom: 12, nodeWidth: 14, nodeGap: 20, draggable: false, nodeAlign: 'justify', emphasis: {focus: 'adjacency'}, label: {color, fontSize: 12, lineHeight: 15, formatter: (value: {data: FlowNode}) => `${value.data.label}${value.data.amount === undefined ? '' : `\n${value.data.amount.toLocaleString()}`}`}, data: graph.nodes, links: graph.links, lineStyle: {color: 'source', opacity: .3, curveness: .5}}]})
    chart.on('click', (value: unknown) => {const data = (value as {data: FlowNode}).data; if (data?.resource) onPick(data.resource, data.task)})
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element)
    return () => {observer.disconnect(); chart.dispose()}
  }, [graph, resolvedMode, theme, language, onPick, resourceLabel])
  return <div className="resource-sankey" ref={container} role="img" aria-label={ui('flow.sankey')} style={{height: Math.max(300, ...[0, 1, 2].map(depth => graph.nodes.filter(node => node.depth === depth).length * 50))}}/>
}
