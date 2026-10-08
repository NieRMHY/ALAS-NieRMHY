/** 资源管理隔离场景：所有收支都留在内存，复用真实接口的筛选与分页形状。 */
const labels = {Oil: '石油', Coin: '物资', Gem: '钻石', Cube: '心智魔方', Pt: '活动 PT', Core: '核心数据', Medal: '荣誉勋章', Merit: '功勋', GuildCoin: '舰队币', ActionPoint: '行动力', YellowCoin: '作战补给凭证', PurpleCoin: '特别兑换凭证', Chip: '心智单元', Food: '后宅粮食'}
const startTime = Date.now() - 12 * 3600_000
const changes = [
  ['Commission', 'Oil', 1800, '奖励领取', 'recognition'], ['Commission', 'Coin', 2500, '奖励领取', 'recognition'],
  ['Commission', 'Cube', 3, '奖励领取', 'recognition'], ['Commission', 'Gem', 30, '奖励领取', 'recognition'],
  ['Event', 'Oil', -600, '任务内库存变化', 'observed'], ['Event', 'Pt', 360, '任务内库存变化', 'observed'],
  ['OilControl', 'Oil', -1050, '后宅购粮', 'confirmed'], ['OilControl', 'Food', 21, '后宅购粮', 'confirmed'],
  ['Research', 'Coin', -3000, '启动科研 D-001', 'confirmed'], ['Research', 'Cube', -2, '启动科研 H-002', 'confirmed'],
  ['Research', 'Chip', 100, '奖励领取', 'recognition'], ['EventShop', 'Pt', -2000, '购买心智单元', 'confirmed'],
  ['OpsiDaily', 'YellowCoin', 6000, '奖励领取', 'recognition'], ['OpsiDaily', 'PurpleCoin', 150, '奖励领取', 'recognition'],
  ['OpsiDaily', 'ActionPoint', -100, '任务内库存变化', 'observed'], ['OpsiShop', 'YellowCoin', -2000, '购买材料', 'confirmed'],
  ['OpsiShop', 'PrototypeGearPartsT4', 3, '购买材料', 'confirmed'], ['OpsiShop', 'PurpleCoin', -50, '购买研发图纸', 'confirmed'],
  ['OpsiShop', 'GearDesignPlanGunT5', 1, '购买研发图纸', 'confirmed'], ['Hard', 'Core', 300, '奖励领取', 'recognition'],
  ['Reward', 'Medal', 5, '奖励领取', 'recognition'], ['Exercise', 'Merit', 800, '任务内库存变化', 'observed'],
  ['Guild', 'GuildCoin', 1000, '奖励领取', 'recognition'], ['Unattributed', 'Oil', 220, '跨任务或离线变化', 'adjustment'],
  ...Array.from({length: 125}, () => ['Main', 'Coin', 100, '奖励领取', 'recognition']),
]
const entries = changes.map(([task, resource, amount, operation, evidence], index) => ({id: index + 1, ts: new Date(startTime + index * 30_000).toISOString().slice(0, 23).replace('T', ' '), task, resource, amount, operation, evidence, run_id: `mock-${task}`}))
export function resourceFlows(params, config, storageCatalog, empty = false) {
  const end = params.end ?? new Date().toISOString().slice(0, 23).replace('T', ' ')
  const start = params.start ?? new Date(Date.parse(end.replace(' ', 'T')) - (params.days ?? 7) * 86400_000).toISOString().slice(0, 23).replace('T', ' ')
  const duration = Date.parse(end.replace(' ', 'T')) - Date.parse(start.replace(' ', 'T'))
  if (!Number.isFinite(duration) || duration <= 0 || duration > 366 * 86400_000) throw Object.assign(new Error('请选择不超过一年的有效本地时间区间'), {code: 'INVALID_PARAMS'})
  const throughId = params.through_id ?? entries.length
  const window = (empty ? [] : entries).filter(entry => entry.ts >= start.replace('T', ' ') && entry.ts < end.replace('T', ' ') && entry.id <= throughId)
  const tasks = [...new Set(window.map(entry => entry.task))].sort()
  const filteredTask = window.filter(entry => !params.task || entry.task === params.task)
  const items = [...Object.entries(labels).map(([key, label]) => ({key, label, group: '货币'})), ...storageCatalog.items.map(item => ({key: item.id, label: item.name, group: item.group}))]
  const resources = items.map(item => {
    const rows = filteredTask.filter(row => row.resource === item.key)
    return {...item, current: empty ? null : config.values.Dashboard[item.key]?.Value ?? (rows.length ? 10 : null), observedAt: empty ? null : end, income: rows.filter(row => row.amount > 0 && row.evidence !== 'adjustment').reduce((sum, row) => sum + row.amount, 0), expense: rows.filter(row => row.amount < 0 && row.evidence !== 'adjustment').reduce((sum, row) => sum - row.amount, 0), adjustment: rows.filter(row => row.evidence === 'adjustment').reduce((sum, row) => sum + row.amount, 0), count: rows.length}
  })
  const filtered = filteredTask.filter(entry => !params.resource || entry.resource === params.resource)
  const grouped = new Map()
  filtered.forEach(row => {const key = `${row.resource}:${row.task}:${row.operation}:${row.evidence}`, value = grouped.get(key) ?? {resource: row.resource, task: row.task, operation: row.operation, evidence: row.evidence, income: 0, expense: 0, count: 0}; value.count++; value[row.amount > 0 ? 'income' : 'expense'] += Math.abs(row.amount); grouped.set(key, value)})
  const offset = params.offset ?? 0, limit = params.limit ?? 100
  return {instance: params.instance, start, end, resources, tasks, flows: [...grouped.values()], entries: filtered.toReversed().slice(offset, offset + limit), offset, limit, total: filtered.length, throughId, oilControl: {enable: config.values.General.OilControl.Enable, target: config.values.General.OilControl.Target}}
}
