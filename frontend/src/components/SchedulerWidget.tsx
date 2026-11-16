/**
 * @fileoverview 调度器核心控制卡片与任务数量摘要组件。
 */

import { CalendarClock, CirclePlay, Play, Square, TriangleAlert } from 'lucide-react'
import { useApp } from '../app/context'
import { pluginAsset } from '../plugins/types'
import { usePlugins } from '../plugins/context'
import { useSchedulerControls, type SchedulerPanelProps } from './useSchedulerControls'

/**
 * 调度器卡片：状态、三类任务计数与启停按钮。
 *
 * 旧版主题的总览页左列、其余主题的右栏、实例设置页的调度器栏都渲染它，
 * 三处共用同一份启停逻辑，保证「不带旧配置启动调度器」的排队屏障不会在某一处漏掉。
 */
export function SchedulerWidget(props: SchedulerPanelProps) {
  const {action} = props
  const {disabled, busy, isRunning, running, pending, waiting, toggleScheduler} = useSchedulerControls(props)
  const {ui} = useApp()
  const theme = usePlugins().theme
  const appearance = theme?.manifest.theme
  const icons = appearance?.icons
  const custom = appearance?.replaceSchedulerStyles
  const actionIcon = icons?.[isRunning ? 'scheduler.stop' : 'scheduler.start']
  const titleIcon = theme && icons?.['scheduler.title']
    ? <img className="apu-scheduler-icon" src={pluginAsset(theme, icons['scheduler.title'])} alt=""/>
    : <CalendarClock size={17}/>

  return <section className={custom ? 'apu-scheduler' : 'scheduler-widget'} data-apu-component="scheduler" data-state={isRunning ? 'running' : 'stopped'} aria-label={ui('scheduler.title')}>
    <div className={custom ? undefined : 'scheduler-widget-heading'} data-apu-part="header">
      <div>{action ?? titleIcon}<span>{ui('scheduler.title')}</span></div>
      {!custom && <span className={`scheduler-status ${isRunning ? 'running' : ''}`}>
        {isRunning ? <CirclePlay size={13}/> : props.data?.status === 'error' ? <TriangleAlert size={13}/> : <Square size={12}/>}
        {isRunning ? ui('status.running') : props.data?.status === 'error' ? ui('scheduler.abnormal') : ui('scheduler.stopped')}
      </span>}
    </div>
    <div className={custom ? undefined : 'scheduler-stats'} data-apu-part="counts">
      <div data-apu-part="running"><span>{ui('scheduler.running')}</span><strong>{running}</strong></div>
      <div data-apu-part="pending"><span>{ui('scheduler.pending')}</span><strong>{pending}</strong></div>
      <div data-apu-part="waiting"><span>{ui('scheduler.waiting')}</span><strong>{waiting}</strong></div>
    </div>
    <button
      type="button"
      className={custom ? undefined : `button scheduler-toggle ${isRunning ? 'danger' : 'primary'}`}
      data-apu-part="toggle"
      onClick={toggleScheduler}
      disabled={disabled}
    >
      {theme && actionIcon ? <img className="apu-scheduler-icon" src={pluginAsset(theme, actionIcon)} alt=""/>
        : isRunning ? <Square size={14}/> : <Play size={14}/>} {busy ? ui('scheduler.processing') : isRunning ? ui('scheduler.stop') : ui('scheduler.start')}
    </button>
  </section>
}
