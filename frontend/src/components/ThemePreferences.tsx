/**
 * @fileoverview 主题模式与配色方案配置面板组件。
 */

import { useApp } from '../app/context'
import { fixedColorModes } from '../app/palettes'
import { PaletteSwatches } from './PaletteSwatches'
import { Select } from './FormControls'

/** 简约与紧凑的主题模式、预设与自定义方案共用一份配色数据，保证预览跟随系统明暗变化。 */
export function ThemePreferences() {
  const {ui, colorMode, setColorMode, palette, setPalette} = useApp()
  return <>
    <div className="field-row">
      <div className="field-label"><label htmlFor="ui-color-mode">{ui('settings.colorMode')}</label><p>{ui('settings.colorModeHelp')}</p></div>
      <div className="field-control"><Select id="ui-color-mode" value={colorMode} onChange={event => setColorMode(event.target.value as typeof colorMode)}>
        <option value="auto">{ui('settings.modeAuto')}</option>
        <option value="light">{ui('settings.themeLight')}</option>
        <option value="dark">{ui('settings.themeDark')}</option>
        <option value="terminal">{ui('settings.modeTerminal')}</option>
        <option value="retro-gray">{ui('settings.modeRetroGray')}</option>
        <option value="retro-blue">{ui('settings.modeRetroBlue')}</option>
        <option value="retro-red">{ui('settings.modeRetroRed')}</option>
      </Select></div>
    </div>
    {/* 自带整套色值的模式（程序员 / 复古灰 / 复古蓝 / 复古红）会忽略配色方案，先收起来免得选了却看不出变化。 */}
    {!fixedColorModes[colorMode] && <div className="field-row palette-field">
      <div className="field-label"><label>{ui('settings.palette')}</label><p>{ui('settings.paletteHelp')}</p></div>
      <div className="field-control palette-control">
        <PaletteSwatches value={palette} onChange={next => { if (next) setPalette(next) }} legend={ui('settings.palette')}/>
      </div>
    </div>}
  </>
}
