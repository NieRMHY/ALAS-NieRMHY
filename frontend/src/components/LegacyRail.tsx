import type { ReactNode } from 'react'
import { Clock3 } from 'lucide-react'
import type { Overview } from '../api/types'
import { useApp } from '../app/context'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/**
 * 旧版实例页的左列：调度器 + 任务计划。
 *
 * 旧 WebUI 把这两块放在页面左列，只有总览页用得上 —— 任务详细设置与资源统计
 * 各自按旧版排版（前者参数卡 + 右列锚点导航，后者整页一条内容带）。
 * 右栏在旧版主题下不渲染（见 app/theme.ts 的 showsRightRail）。
 * `children` 插在调度器与任务计划之间，供总览页放「统计界面」入口。
 */
export function LegacyRail({instance, data, onData, children}: {instance: string; data?: Overview; onData: (data: Overview) => void; children?: ReactNode}) {
  const {ui} = useApp()
  return <div className="instance-page-rail">
    <SchedulerWidget instance={instance} data={data} onData={onData}/>
    {children}
    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <div className="rail-section-heading">
        <div><Clock3 size={15}/><span>{ui('scheduler.plan')}</span></div>
        <span>{data?.tasks.length ?? 0}</span>
      </div>
      <TaskQueue instance={instance} data={data}/>
    </section>
  </div>
}
