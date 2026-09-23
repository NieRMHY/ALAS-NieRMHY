import { useState, type CSSProperties } from 'react'
import { Plus } from 'lucide-react'
import { useApp } from '../app/context'
import { isHexColor, paletteColors, palettes, fixedColorModes, type CustomPalette } from '../app/palettes'
import { Select } from './FormControls'
import { Modal } from './ui'

function CustomPaletteEditor({initial, onClose}: {initial: CustomPalette; onClose: () => void}) {
  const {ui, saveCustomPalette} = useApp()
  const [draft, setDraft] = useState(initial)
  const valid = isHexColor(draft.primary) && isHexColor(draft.secondary)
  return <Modal title={ui('settings.customPalette')} onClose={onClose} className="custom-palette-modal">
    <form className="form-stack" onSubmit={event => {
      event.preventDefault()
      if (!valid) return
      saveCustomPalette(draft)
      onClose()
    }}>
      <fieldset className="custom-palette-colors">
        <legend>{ui('settings.palette')}</legend>
        {(['primary', 'secondary'] as const).map(key => {
          const color = draft[key]
          const label = ui(key === 'primary' ? 'settings.primaryColor' : 'settings.secondaryColor')
          const update = (value: string) => setDraft({...draft, [key]: value})
          return <div className="custom-color-row" key={key}>
            <label htmlFor={`palette-${key}`}>{label}</label>
            <input type="color" value={isHexColor(color) ? color : '#000000'} aria-label={`${label} ${ui('settings.colorPicker')}`} onChange={event => update(event.target.value)}/>
            <input id={`palette-${key}`} aria-label={label} value={color} maxLength={7} pattern="#[0-9a-fA-F]{6}" required spellCheck={false} aria-invalid={!isHexColor(color)} aria-describedby={!isHexColor(color) ? 'palette-color-error' : undefined} onChange={event => update(event.target.value)}/>
          </div>
        })}
      </fieldset>
      {!valid && <p id="palette-color-error" role="status">{ui('settings.paletteInvalid')}</p>}
      <div className="custom-palette-actions">
        <button type="button" className="button secondary" onClick={onClose}>{ui('common.cancel')}</button>
        <button type="submit" className="button primary" disabled={!valid}>{ui('settings.savePalette')}</button>
      </div>
    </form>
  </Modal>
}

/** 简约主题的模式、预设与自定义方案共用一份配色数据，保证预览跟随系统明暗变化。 */
export function ThemePreferences() {
  const {ui, colorMode, setColorMode, resolvedMode, palette, setPalette, customPalettes, deleteCustomPalette} = useApp()
  const [editing, setEditing] = useState<CustomPalette>()
  const selected = customPalettes.find(item => item.id === palette)
  const paletteIds = [...palettes, ...customPalettes.map(item => item.id)]
  function createPalette() {
    const id = `custom:${crypto.getRandomValues(new Uint32Array(2)).join('-')}` as const
    const current = paletteColors(palette, customPalettes, resolvedMode)
    setEditing({id, primary: current.primary, secondary: current.secondary})
  }
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
        <fieldset className="palette-options">
          <legend>{ui('settings.palette')}</legend>
          {paletteIds.map(id => {
            const colors = paletteColors(id, customPalettes, resolvedMode)
            return <label className="palette-option" key={id}>
              <input type="radio" name="palette" value={id} checked={palette === id} onChange={() => setPalette(id)}/>
              <span className="palette-swatch" style={{'--accent': colors.primary, '--secondary': colors.secondary} as CSSProperties} aria-hidden="true"><i/><i/></span>
            </label>
          })}
          <button
            type="button"
            className="palette-add"
            disabled={customPalettes.length >= 32}
            onClick={createPalette}
            aria-label={ui('settings.addPalette')}
            title={ui('settings.addPalette')}
          >
            <Plus size={18} aria-hidden="true"/>
          </button>
        </fieldset>
        {selected && <div className="custom-palette-actions">
          <button type="button" className="text-button" onClick={() => setEditing(selected)}>{ui('settings.editPalette')}</button>
          <button type="button" className="text-button" onClick={() => deleteCustomPalette(selected.id)}>{ui('settings.deletePalette')}</button>
        </div>}
      </div>
    </div>}
    {editing && <CustomPaletteEditor initial={editing} onClose={() => setEditing(undefined)}/>}
  </>
}
