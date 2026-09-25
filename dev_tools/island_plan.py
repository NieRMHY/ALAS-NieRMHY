"""生成岛屿生产/上架方案，并可选写回 ALAS 配置。

用法：
    uv run python dev_tools/island_plan.py                        # 只看方案
    uv run python dev_tools/island_plan.py --season autumn        # 指定季节
    uv run python dev_tools/island_plan.py --warehouse wh.json    # 按仓库库存过滤上架
    uv run python dev_tools/island_plan.py --apply                # 写回 config/ALAS.json

方案是纯计算产物：只改配置里的 Meal1-8 / MealNumber1-8 / Product1-5，
实际生产与售卖仍由 ALAS 原有框架执行。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module.island.island_planner import (  # noqa: E402
    SHELF_SLOTS,
    apply_patch,
    config_patch,
    format_report,
    load_unproducible,
    mine_verified,
    plan_all,
    save_unproducible,
    save_verified,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='岛屿生产/销售方案生成器')
    parser.add_argument('--level', default='diamond',
                        choices=['bronze', 'silver', 'gold', 'diamond'],
                        help='店铺等级（决定单格容量与售出系数），默认 diamond')
    parser.add_argument('--season', default=None,
                        choices=['spring', 'summer', 'autumn', 'winter'],
                        help='当前季节；不传则只安排常驻商品')
    parser.add_argument('--shelf-slots', type=int, default=SHELF_SLOTS,
                        help=f'上架格数，默认 {SHELF_SLOTS}')
    parser.add_argument('--warehouse', default=None,
                        help='仓库库存 JSON 文件；传入后无库存商品不上架')
    parser.add_argument('--config', default=os.path.join('config', 'ALAS.json'),
                        help='配置文件路径，默认 config/ALAS.json')
    parser.add_argument('--apply', action='store_true',
                        help='写回配置（自动备份为 .bak）；不加只打印方案')
    parser.add_argument('--json', action='store_true', help='输出配置补丁 JSON')
    parser.add_argument('--exclude', default=None,
                        help='本次额外排除，格式 shop:name,shop:name（不落盘）')
    parser.add_argument('--mark-exclude', default=None,
                        help='把商品记入未解锁名单（落盘），格式 shop:name')
    parser.add_argument('--unmark-exclude', default=None,
                        help='从名单移除（落盘），格式 shop:name')
    parser.add_argument('--mine-logs', nargs='*', default=None,
                        metavar='LOG',
                        help='从 ALAS 日志挖掘「已验证可生产」商品并落盘（可给多个日志文件）')
    parser.add_argument('--allow-unverified', action='store_true',
                        help='允许把未验证商品排进生产清单（默认只排验证过的，防止未解锁商品触发重启循环）')
    return parser.parse_args(argv)


def split_pairs(text):
    """解析 'shop:name,shop:name' 形式的参数。"""
    out = []
    for chunk in (text or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        shop, _, name = chunk.partition(':')
        if not shop or not name:
            raise ValueError(f'格式应为 shop:name，收到 {chunk!r}')
        out.append((shop.strip(), name.strip()))
    return out


def load_warehouse(path):
    if not path:
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('仓库库存文件应为 {商品: 数量} 结构')
    return {k: int(v) for k, v in data.items()}


def main(argv=None):
    args = parse_args(argv)
    warehouse = load_warehouse(args.warehouse)

    # 未解锁名单：落盘增删（取代运行时自动学习，方案侧维护）
    for shop, name in split_pairs(args.mark_exclude):
        names = load_unproducible(shop) | {name}
        save_unproducible(shop, names)
        print(f'已记入未解锁名单: {shop}:{name}')
    for shop, name in split_pairs(args.unmark_exclude):
        names = load_unproducible(shop) - {name}
        save_unproducible(shop, names)
        print(f'已从未解锁名单移除: {shop}:{name}')

    extra = {}
    for shop, name in split_pairs(args.exclude):
        extra.setdefault(shop, set()).add(name)

    if args.mine_logs:
        data = mine_verified(args.mine_logs)
        save_verified(data)
        for shop, names in sorted(data.items()):
            print(f'已验证可生产 {shop}: {len(names)} 个')
        if not args.mine_logs:
            return 0

    plans = plan_all(shop_level=args.level, season=args.season,
                     warehouse=warehouse, shelf_slots=args.shelf_slots,
                     extra_exclude=extra,
                     verified_only=not args.allow_unverified)
    patch = config_patch(plans)

    if args.json:
        print(json.dumps(patch, ensure_ascii=False, indent=2))
    else:
        print(format_report(plans))

    if args.apply:
        if not os.path.exists(args.config):
            print(f'[错误] 配置不存在: {args.config}', file=sys.stderr)
            return 1
        backup = apply_patch(args.config, patch)
        print(f'已写入 {args.config}（备份 {backup}）')
    elif not args.json:
        print('（未写回配置；加 --apply 生效）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
