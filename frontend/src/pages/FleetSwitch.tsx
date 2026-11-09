import {useParams, useSearchParams} from 'react-router-dom'
import {useApp} from '../app/context'
import {PageTitle} from '../components/ui'
import {FleetInfoPage} from './FleetInfoPage'
import {FleetRotation} from './FleetRotation'
import {FleetTraining} from './FleetTraining'
import {FleetEquipment} from './FleetEquipment'
import './fleet-switch.css'

/** 只整合页面入口；各页签继续使用原有的配置和游戏操作。 */
export function FleetSwitch() {
  const {instance = ''} = useParams(), {ui, t} = useApp(), [params, setParams] = useSearchParams()
  const value = params.get('tab')
  const tab = value === 'rotation' || value === 'training' || value === 'equipment' ? value : 'info'
  const tabs = [
    {id: 'info', label: t('Task.FleetInfo.name'), content: <FleetInfoPage/>},
    {id: 'rotation', label: ui('rotation.title'), content: <FleetRotation/>},
    {id: 'training', label: ui('training.title'), content: <FleetTraining/>},
    {id: 'equipment', label: ui('fleetEquipment.title'), content: <FleetEquipment/>},
  ]
  return <div className="fleet-switch">
    <PageTitle title={ui('rotation.pageTitle')}/>
    <div className="fleet-switch-tabs" role="tablist" aria-label={ui('rotation.pageTitle')}>
      {tabs.map(({id, label}) => <button key={id} type="button" role="tab" id={`fleet-switch-tab-${id}`}
        aria-selected={tab === id} aria-controls={`fleet-switch-${id}`}
        onClick={() => setParams({tab: id}, {replace: true})}>{label}</button>)}
    </div>
    <section key={`${instance}:${tab}`} role="tabpanel" id={`fleet-switch-${tab}`} aria-labelledby={`fleet-switch-tab-${tab}`}>
      {tabs.find(item => item.id === tab)!.content}
    </section>
  </div>
}
