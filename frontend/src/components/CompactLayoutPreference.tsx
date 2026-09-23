import { COMPACT_RAIL_WIDTHS, type CompactRailSide, type CompactRailWidth } from '../app/theme'
import { useApp } from '../app/context'
import { Select } from './FormControls'

/** 三格示意图：左边是侧栏窄条，另外两格分别是内容区与计划栏，计划栏用主色标出落在哪一侧。
    两边的 rect 只换 x，宽度不变 —— 换位只交换顺序，不改变两栏的宽度关系。 */
function LayoutPreview({railSide}: {railSide: CompactRailSide}) {
  const railLeft = railSide === 'left'
  return <svg className="layout-preview" viewBox="0 0 58 36" aria-hidden="true" focusable="false">
    <rect className="layout-bar" x="1" y="1" width="10" height="34" rx="2"/>
    <rect className="layout-content" x={railLeft ? 25 : 13} y="1" width="32" height="34" rx="2"/>
    <rect className="layout-rail" x={railLeft ? 13 : 47} y="1" width="10" height="34" rx="2"/>
  </svg>
}

/** 紧凑主题专属的布局偏好：调度与任务计划栏相对内容区的位置，以及这一栏的宽度。
    切到其它主题时这一组不渲染 —— 列序与宽度只对紧凑皮肤有定义。 */
export function CompactLayoutPreference() {
  const {ui, compactRailSide, setCompactRailSide, compactRailWidth, setCompactRailWidth} = useApp()
  const widthKeys = {
    200: 'settings.compactWidthNarrow',
    244: 'settings.compactWidthStandard',
    300: 'settings.compactWidthWide',
    360: 'settings.compactWidthWider',
  } as const
  return <>
    <div className="field-row">
      <div className="field-label">
        <label>{ui('settings.compactLayout')}</label>
        <p>{ui('settings.compactLayoutHelp')}</p>
      </div>
      <div className="field-control">
        <fieldset className="layout-options">
          <legend>{ui('settings.compactLayout')}</legend>
          {(['right', 'left'] as CompactRailSide[]).map(side => <label className="layout-option" key={side}>
            <input
              type="radio"
              name="compact-rail-side"
              value={side}
              checked={compactRailSide === side}
              onChange={() => setCompactRailSide(side)}
            />
            <LayoutPreview railSide={side}/>
            <span>{side === 'left' ? ui('settings.compactRailLeft') : ui('settings.compactRailRight')}</span>
          </label>)}
        </fieldset>
      </div>
    </div>
    <div className="field-row">
      <div className="field-label">
        <label htmlFor="ui-compact-rail-width">{ui('settings.compactRailWidth')}</label>
        <p>{ui('settings.compactRailWidthHelp')}</p>
      </div>
      <div className="field-control">
        <Select id="ui-compact-rail-width" value={compactRailWidth} onChange={event => setCompactRailWidth(Number(event.target.value) as CompactRailWidth)}>
          {COMPACT_RAIL_WIDTHS.map(width => <option key={width} value={width}>{ui(widthKeys[width], {width})}</option>)}
        </Select>
      </div>
    </div>
  </>
}
