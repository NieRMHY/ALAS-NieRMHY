/**
 * @fileoverview 界面外观偏好设置页面（主题、配色、背景与多语言）。
 */

import { Select } from '../components/FormControls'
import { languages, useApp, useConnection } from '../app/context'
import { familyOf, hasMaterialAxis, supportsBackground, usesPaletteOptions, type Theme } from '../app/theme'
import { PageTitle } from '../components/ui'
import { SegmentedControl } from '../components/SegmentedControl'
import { ThemeCustomPreference } from '../components/ThemeCustomPreference'
import { ThemePreferences } from '../components/ThemePreferences'
import { CompactLayoutPreference } from '../components/CompactLayoutPreference'
import { BackgroundPreferences } from '../components/BackgroundPreferences'

/** 一级主题大类各自的明暗成员；新版与旧版各有两个，简洁与紧凑各一个。 */
const familyThemes: Record<ReturnType<typeof familyOf>, Theme[]> = {
  new: ['light', 'dark'], legacy: ['legacy-light', 'legacy-dark'], minimal: ['minimal'], extreme: ['extreme'],
}

/** 界面设置：主题、材质、明暗、配色、背景与语言，只影响当前浏览器，不写进实例配置。 */
export function InterfaceSettings() {
  const {theme, setTheme, material, setMaterial, language, setLanguage, ui} = useApp()
  const connection = useConnection()
  const family = familyOf(theme)
  const dark = theme === 'dark' || theme === 'legacy-dark'
  const switchFamily = (next: ReturnType<typeof familyOf>) => {
    const themes = familyThemes[next]
    setTheme(themes.length === 1 ? themes[0] : themes[dark ? 1 : 0])
  }

  return (
    <>
      <PageTitle title={ui('nav.interface')} />
      <section className="panel config-group">
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-theme">{ui('settings.theme')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-theme" value={family} onChange={event => switchFamily(event.target.value as ReturnType<typeof familyOf>)}>
              <option value="new">{ui('settings.familyNew')}</option>
              <option value="legacy">{ui('settings.familyLegacy')}</option>
              <option value="minimal">{ui('settings.themeMinimal')}</option>
              <option value="extreme">{ui('settings.themeExtreme')}</option>
            </Select>
          </div>
        </div>
        {/* 材质与明暗只对有材质轴的家族（新版、旧版）显示；切走时取值仍留在偏好里。 */}
        {hasMaterialAxis(theme) && <div className="field-row">
          <div className="field-label">
            <label>{ui('settings.material')}</label>
          </div>
          <div className="field-control">
            <SegmentedControl className="settings-segmented" label={ui('settings.material')} value={material} onChange={setMaterial} options={[
              {value: 'glass', label: ui('settings.materialGlass')},
              {value: 'plain', label: ui('settings.materialPlain')},
            ]}/>
          </div>
        </div>}
        {hasMaterialAxis(theme) && <div className="field-row">
          <div className="field-label">
            <label>{ui('settings.mode')}</label>
          </div>
          <div className="field-control">
            <SegmentedControl className="settings-segmented" label={ui('settings.mode')} value={dark ? 'dark' : 'light'} onChange={mode => {
              const themes = familyThemes[familyOf(theme)]
              setTheme(themes[mode === 'dark' ? 1 : 0])
            }} options={[
              {value: 'light', label: ui('settings.themeLight')},
              {value: 'dark', label: ui('settings.themeDark')},
            ]}/>
          </div>
        </div>}
        {/* 有材质轴的家族各自一套自定义外观；没有旋钮的家族不渲染。 */}
        <ThemeCustomPreference/>
        {/* 紧凑主题的列布局选项紧跟主题选择，切到其它主题即隐藏，偏好仍保存在当前浏览器。 */}
        {theme === 'extreme' && <CompactLayoutPreference/>}
        {usesPaletteOptions(theme) && <ThemePreferences/>}
        {supportsBackground(theme) && <BackgroundPreferences/>}
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-language">{ui('settings.language')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-language" value={language} disabled={connection !== 'ready'} onChange={event => setLanguage(event.target.value as typeof language)}>
              {Object.entries(languages).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </Select>
          </div>
        </div>
      </section>
    </>
  )
}
