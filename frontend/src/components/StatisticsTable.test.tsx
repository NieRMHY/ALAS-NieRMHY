import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { StatisticsTable } from './StatisticsTable'

const context = {ui: (key: Parameters<AppContextValue['ui']>[0], params?: Parameters<AppContextValue['ui']>[1]) => translateUi('zh-CN', key, params)} as AppContextValue

describe('统计表格', () => {
  it('明确声明后默认按时间降序展示记录', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <StatisticsTable data={{title: '原始记录', columns: ['时间', '数值'], rows: [['2026-09-01 09:16:17', 20], ['2026-09-15 09:31:52', 66], ['2026-09-03 19:42:03', 17]], defaultSort: {index: 0, descending: true}}}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('aria-sort="descending"')
    expect(html.indexOf('2026-09-15 09:31:52')).toBeLessThan(html.indexOf('2026-09-03 19:42:03'))
    expect(html.indexOf('2026-09-03 19:42:03')).toBeLessThan(html.indexOf('2026-09-01 09:16:17'))
  })
})
