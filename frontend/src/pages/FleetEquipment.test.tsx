import {describe, expect, it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {AppContext, type AppContextValue} from '../app/context'
import {translateUi} from '../i18n'
import {FLEET_EQUIPMENT, taskLabel, taskNavItems} from '../components/taskNavItems'
import {EquipmentCodeFields, equipmentCodes, equipmentTypes} from './FleetEquipment'

describe('换船装备配置页面', () => {
  it('空配置提供15种舰种的空码，兼容配置恢复并拒绝错误映射', () => {
    expect(equipmentCodes(undefined)).toEqual(Object.fromEntries(equipmentTypes.map(type => [type, ['', '', '']])))
    expect(equipmentCodes('{"DD":" code ","CV":""}').DD).toEqual(['code', '', ''])
    expect(equipmentCodes({DD: ['one', '', 'three']}).DD).toEqual(['one', '', 'three'])
    for (const value of ['{', '[]', '{"unknown":""}', '{"DD":3}', '{"DD":null}', '{"DD":["a","b","c","d"]}', '{"DD":[null]}']) expect(() => equipmentCodes(value)).toThrow()
  })
  it('装备配置收进智能换船，使用换船装备名称', () => {
    expect(taskNavItems('FleetManagement', ['FleetInfo'])).toContain('FleetSwitch')
    expect(taskNavItems('FleetManagement', ['FleetInfo'])).not.toContain(FLEET_EQUIPMENT)
    expect(taskNavItems('Tool', ['FleetScan'])).not.toContain(FLEET_EQUIPMENT)
    expect(taskLabel(FLEET_EQUIPMENT, key => translateUi('zh-CN', key), () => '非独立任务')).toBe('换船装备')
  })
  it('全部输入框有舰种名称、跳过说明和已保存值', () => {
    const html = renderToStaticMarkup(<AppContext.Provider value={{
      ui: (key, params) => translateUi('zh-CN', key, params),
    } as AppContextValue}><EquipmentCodeFields codes={equipmentCodes({DD: 'MC8wLzAvMC8wXDA='})} disabled={false} change={() => {}}/></AppContext.Provider>)
    expect(html.match(/<input/g)).toHaveLength(45)
    for (const type of equipmentTypes) for (const index of [1, 2, 3]) expect(html).toContain(`id="equipment-${type}-${index}"`)
    expect(html).toContain('未填写：跳过此顺序位')
    expect(html).toContain('MC8wLzAvMC8wXDA=')
    expect(html).toContain('航空战列舰')
    expect(html.indexOf('装备码')).toBeLessThan(html.indexOf('fleet-column'))
  })
  it('四种界面语言包含15舰种及明确的空码行为', () => {
    for (const language of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP'] as const) {
      for (const type of equipmentTypes) expect(translateUi(language, `fleetEquipment.${type}`)).not.toBe(`fleetEquipment.${type}`)
      expect(translateUi(language, 'fleetEquipment.skip')).not.toBe('fleetEquipment.skip')
    }
  })
})
