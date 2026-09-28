"""导出岛屿经济库全表（Markdown），便于查阅生产时间/成本/售价/利润。

用法:
    uv run python dev_tools/island_economy_table.py [输出路径]
默认输出 docs/island_economy_table.md（docs/ 不入库）。
"""
import sys

sys.path.insert(0, '.')
from module.island.island_economy import ECONOMY_PRODUCTS, SHOP_CN_NAMES, SHOP_LEVELS

SHOP_ORDER = ['restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee']

lines = ['# 岛屿商品经济表（生产时间 / 成本 / 售价 / 利润）', '',
         '数据来源：碧蓝航线 wiki「岛屿计划」与仓库代码资源核对。',
         '利润 = 售价 - 成本（不含店铺等级系数）；效率 = 利润 除以 生产时间。',
         '自产材料 = 该原料本身也是岛屿商品（会占用同类产能）；基础材料（面粉/牛奶等）未展开。', '']

for shop in SHOP_ORDER:
    items = [(k, v) for k, v in ECONOMY_PRODUCTS.items() if v['shop'] == shop]
    items.sort(key=lambda kv: -(kv[1]['profit'] / kv[1]['time_min'] if kv[1]['time_min'] else 0))
    lines.append('## ' + SHOP_CN_NAMES.get(shop, shop) + '（' + shop + '，' + str(len(items)) + ' 项）')
    lines.append('')
    lines.append('| 商品 | 英文名 | 生产时间 | 成本 | 售价 | 利润 | 效率/分 | 自产材料 | 季节 |')
    lines.append('| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |')
    for name, info in items:
        ppm = info['profit'] / info['time_min'] if info['time_min'] else 0
        subs = [ECONOMY_PRODUCTS[m]['cn_name'] for m in info['materials'] if m in ECONOMY_PRODUCTS]
        base = [m for m in info['materials'] if m not in ECONOMY_PRODUCTS]
        parts = '、'.join(subs + [m + '(基础)' for m in base]) or '—'
        lines.append('| ' + info['cn_name'] + ' | `' + name + '` | ' + str(info['time_min']) + ' 分 | '
                     + str(int(info['cost'])) + ' | ' + str(int(info['price'])) + ' | '
                     + str(int(info['profit'])) + ' | ' + ('%.1f' % ppm) + ' | ' + parts + ' | '
                     + (info['seasonal'] or '常驻') + ' |')
    lines.append('')

lines.append('## 店铺等级参数')
lines.append('')
lines.append('| 等级 | 货架格数 | 每格堆叠 | 售价系数 | 满级容量 |')
lines.append('| --- | ---: | ---: | ---: | ---: |')
for level, cfg in SHOP_LEVELS.items():
    lines.append('| ' + level + ' | ' + str(cfg['slots']) + ' | ' + str(cfg['per_slot']) + ' | '
                 + str(cfg['sell_rate']) + ' | ' + str(cfg['slots'] * cfg['per_slot']) + ' |')
lines.append('')
lines.append('售价系数说明：wiki 口径的实际售出为 售价 x 系数 / 1.6；系数越高，同件商品实收越高。')

out = 'docs/island_economy_table.md'
open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('已写入', out, '商品总数:', len(ECONOMY_PRODUCTS))