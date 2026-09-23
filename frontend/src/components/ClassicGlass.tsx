import { useSyncExternalStore } from 'react'
import LiquidGlass from 'liquid-glass-react'

const reducedEffects = '(prefers-reduced-motion: reduce), (prefers-reduced-transparency: reduce), (forced-colors: active)'
function subscribe(callback: () => void) {
  const query = window.matchMedia(reducedEffects)
  query.addEventListener('change', callback)
  return () => query.removeEventListener('change', callback)
}
const getSnapshot = () => window.matchMedia(reducedEffects).matches

/** 独立的装饰层，避免玻璃容器裁切菜单、焦点轮廓和可交互内容。 */
export function ClassicGlass() {
  const reduced = useSyncExternalStore(subscribe, getSnapshot, () => true)
  return <div className="glass-material" aria-hidden="true">
    {!reduced && <LiquidGlass className="glass-material-lens" padding="0" cornerRadius={22}
      displacementScale={24} blurAmount={0.16} saturation={125}
      aberrationIntensity={0.5} elasticity={0} mode="standard"
      style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}>
      <span />
    </LiquidGlass>}
  </div>
}
