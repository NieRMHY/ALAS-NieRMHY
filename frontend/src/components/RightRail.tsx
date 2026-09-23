import { Clock3, X } from 'lucide-react'
import { useApp } from '../app/context'
import { useInstanceOverview } from './useInstanceOverview'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/** 右侧栏：调度器与任务计划。旧版主题改用页内左列承载，本组件只在其余主题渲染。 */
export function RightRail({instance, onMobileClose}: {instance: string; onMobileClose: () => void}) {
  const {ui} = useApp()
  const [data, setData] = useInstanceOverview(instance)

  return <aside className="right-rail" id="right-rail-menu" aria-label={ui('scheduler.rail')}>
    <div className="right-rail-header">
      <div>
        <span className="right-rail-eyebrow">{ui('scheduler.workspace')}</span>
        <strong>{instance}</strong>
      </div>
      <button className="mobile-rail-close icon-button" aria-label={ui('nav.closeRail')} onClick={onMobileClose}><X size={18}/></button>
    </div>

    <SchedulerWidget instance={instance} data={data} onData={setData}/>

    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <div className="rail-section-heading">
        <div><Clock3 size={15}/><span>{ui('scheduler.plan')}</span></div>
        <span>{data?.tasks.length ?? 0}</span>
      </div>
      <TaskQueue instance={instance} data={data} onNavigate={onMobileClose}/>
    </section>
  </aside>
}
