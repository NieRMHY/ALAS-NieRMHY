import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ExternalLink, History, Plus, Server } from 'lucide-react'
import { useApp, useConnection } from '../app/context'
import type { Theme } from '../app/theme'
import type { UiTranslator } from '../i18n'
import { CreateInstance } from '../app/App'
import { StatusBadge } from '../components/ui'

/** 「切换旧版界面」快捷按钮用：恢复目标限定在现代主题里，避免来回落到别的档位。 */
const MODERN_THEMES: readonly string[] = ['light', 'dark', 'minimal']

function getGreeting(ui: UiTranslator): string {
  const hour = new Date().getHours()
  if (hour >= 5 && hour < 12) return ui('home.greetingMorning')
  if (hour >= 12 && hour < 18) return ui('home.greetingAfternoon')
  return ui('home.greetingEvening')
}

export function Home() {
  const {instances, t, ui, theme, setTheme, resolvedMode} = useApp()
  const connection = useConnection()
  const [creating, setCreating] = useState(false)
  useEffect(() => {
    document.documentElement.classList.add('home-active')
    return () => document.documentElement.classList.remove('home-active')
  }, [])
  const running = instances.filter(item => item.status === 'running').length
  const errored = instances.filter(item => item.status === 'error').length
  const legacyUi = theme === 'legacy-light' || theme === 'legacy-dark'
  function toggleLegacyUi() {
    if (!legacyUi) {
      try { localStorage.setItem('azurpilot.theme-before-legacy', theme) } catch { /* 存储不可用时仍可切换。 */ }
      setTheme(resolvedMode === 'dark' ? 'legacy-dark' : 'legacy-light')
      return
    }
    let previous: string | null = null
    try { previous = localStorage.getItem('azurpilot.theme-before-legacy') } catch { /* 同上。 */ }
    setTheme(previous !== null && MODERN_THEMES.includes(previous) ? previous as Theme : resolvedMode === 'dark' ? 'dark' : 'light')
  }
  return <>
    <div className="home-editorial">
      <aside className="home-deck">
        <div className="home-deck-copy">
          <p className="home-deck-eyebrow">{ui('home.commandCenter')}</p>
          <h1 className="home-deck-greeting">{getGreeting(ui)}</h1>
          <p className="home-deck-subtitle">{ui('home.subtitle')}</p>
        </div>
        <div className="home-deck-foot">
          <dl className="home-stats" aria-label={ui('home.summary')}>
            <div className="home-stat"><dt>{ui('home.allInstances')}</dt><dd>{instances.length}</dd></div>
            <div className="home-stat"><dt>{ui('status.running')}</dt><dd>{running}</dd></div>
            <div className="home-stat"><dt>{ui('status.error')}</dt><dd>{errored}</dd></div>
          </dl>
          <div className="home-deck-links">
            <a className="home-deck-link" href="https://github.com/wess09/AzurPilot" target="_blank" rel="noreferrer"><ExternalLink size={14}/>{ui('home.openSource')}</a>
            <button type="button" className="home-deck-link home-legacy-toggle" onClick={toggleLegacyUi}><History size={14}/>{ui(legacyUi ? 'home.modernUi' : 'home.legacyUi')}</button>
          </div>
        </div>
      </aside>
      <section className="home-main">
        <header className="home-main-heading">
          <h2>{ui('home.instances')}</h2>
          <button className="button primary" disabled={connection !== 'ready'} onClick={() => setCreating(true)}><Plus size={16}/>{ui('home.newInstance')}</button>
        </header>
        <div className="home-instance-grid">
          {instances.map(item => {
            const task = item.status === 'running' ? item.currentTask ? t(`Task.${item.currentTask}.name`) : ui('home.waitingSchedule') : item.status === 'error' ? ui('status.error') : item.status === 'updating' ? ui('status.updating') : ui('home.notRunning')
            return <Link className="instance-card panel" key={item.name} to={`/i/${item.name}/overview`}>
              <div className="instance-card-heading"><span className="home-instance-icon"><Server size={20}/></span><StatusBadge status={item.status} simulate/></div>
              <h3>{item.name}</h3>
              <div className="instance-device">{item.server !== 'disabled' && <span>{t(`Emulator.ServerName.${item.server}`)}</span>}<span>{item.serial}</span></div>
              <div className="instance-card-footer"><span>{task}</span><ArrowRight size={17}/></div>
            </Link>
          })}
          {!instances.length && <button className="home-instance-empty" disabled={connection !== 'ready'} onClick={() => setCreating(true)}><Plus size={28}/><span>{ui('instance.createFirst')}</span></button>}
        </div>
      </section>
    </div>
    {creating && <CreateInstance onClose={() => setCreating(false)}/>}
  </>
}
