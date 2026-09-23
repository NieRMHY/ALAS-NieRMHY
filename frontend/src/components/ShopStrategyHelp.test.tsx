import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ShopStrategyHelp } from './ShopStrategyHelp'

describe('高级策略说明', () => {
  it('展示完整受限接口、评分组合语义和当前任务域', () => {
    const html = renderToStaticMarkup(<ShopStrategyHelp task="ShopOnce"/>)
    expect(html).toContain('高级商店策略说明')
    expect(html).toContain('context.domain')
    expect(html).toContain('ShopFrequent')
    expect(html).toContain('general')
    expect(html).toContain('大舰队、勋章、功勋、核心商店共享此域')
    expect(html).toContain('id, key, name, group, sub_genre, tier')
    expect(html).toContain('currency, spent, purchased')
    expect(html).toContain(':where(function(item)')
    expect(html).toContain(':score(function(item)')
    expect(html).toContain('sum(评分 × 购买数量)')
    expect(html).toContain('省略方向时默认 asc')
    expect(html).toContain('跨同一商店会话和刷新保存')
    expect(html).toContain('context.purchased[item.id]')
    expect(html).toContain('--[[ 多行 ]]')
    expect(html).toContain('源码最长 20,000 个字符')
    expect(html).toContain('幂指数绝对值最多 64')
    expect(html).toContain('候选链总调用数最多 16')
  })

  it('按界面语言展示完整说明，而非始终显示简体中文', () => {
    const english = renderToStaticMarkup(<ShopStrategyHelp task="EventShop" language="en-US"/>)
    const japanese = renderToStaticMarkup(<ShopStrategyHelp task="EventShop" language="ja-JP"/>)
    const traditional = renderToStaticMarkup(<ShopStrategyHelp task="EventShop" language="zh-TW"/>)
    const miao = renderToStaticMarkup(<ShopStrategyHelp task="EventShop" language="zh-MIAO"/>)

    expect(english).toContain('Advanced Shop Strategy Reference')
    expect(english).toContain('sum(score × quantity)')
    expect(english).toContain('defaults to asc')
    expect(english).toContain('legacy UR ship, URpt exchange, and unobtained-item forced stages do not run')
    expect(japanese).toContain('高度ショップ戦略リファレンス')
    expect(japanese).toContain('sum(スコア × 購入数量)')
    expect(traditional).toContain('進階商店策略說明')
    expect(traditional).toContain('sum(分數 × 購買數量)')
    expect(miao).toContain('高级商店策略说明喵')
  })
})
