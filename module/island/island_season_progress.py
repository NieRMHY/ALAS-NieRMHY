"""赛季任务进度：直接取仓库读数（Add by MHY）。

为什么不再 OCR 赛季页：开发计划页的进度文字会被误读（拿铁 82 读成 282），而邮件、
方案刷新、常驻餐品轮换都依赖这个数。店铺每次生产/上架前都要进仓库核对库存，那个读数
是准确的，所以每次收取生产、核对销售时顺带记录一份，当作该物品的当前数量。

用户可以在 WebUI「赛季任务」里直接看到并手动改这份进度（提交任务后仓库掉下去，
可以把对应物品改回实际值）。配置文本格式，每行一项，# 开头为注释：

    latte=82/100
    iced_coffee=250/250

左边是当前数量（程序每次读仓库后覆盖），右边是任务需要数量（默认取赛季数据，可改）。
"""
from module.island.island_season_plan_data import SEASON_PLAN_TASKS
from module.logger import logger

PROGRESS_KEY = 'IslandSeasonPlan.IslandSeasonPlan.Progress'


def parse_progress_text(text):
    """
    解析进度文本。

    Args:
        text: 每行「物品=当前/需求」，# 开头或行内 # 之后为注释

    Returns:
        dict: {物品: [当前数量, 需求数量]}；格式错误的行跳过
    """
    result = {}
    for raw in str(text or '').splitlines():
        line = raw.split('#', 1)[0].strip()
        item, sep, value = line.partition('=')
        have, slash, need = value.replace(' ', '').partition('/')
        item = item.strip()
        if not item or not sep or not slash:
            continue
        try:
            result[item] = [max(int(have), 0), max(int(need), 0)]
        except ValueError:
            continue
    return result


def format_progress_text(progress):
    """进度字典写回文本，按物品名排序保证显示稳定。"""
    return '\n'.join(f'{item}={have}/{need}' for item, (have, need) in sorted(progress.items()))


def default_progress(season, shop_items):
    """
    赛季里店铺餐品类任务的初始进度（当前 0，需求取赛季数据）。

    Args:
        season: 赛季
        shop_items: 店铺餐品物品集合（有对应店铺的才需要规划，材料类交给农田牧场）

    Returns:
        dict: {物品: [0, 需求数量]}
    """
    return {item: [0, need] for _, item, need in SEASON_PLAN_TASKS.get(season, [])
            if item in shop_items}


def merge_readings(progress, readings, season, shop_items):
    """
    把本次仓库读数合并进进度，只更新赛季任务里的物品。

    读数是仓库当前真实库存，直接覆盖「当前数量」，不做累加：仓库里有多少就是多少，
    提交任务后掉下去就如实反映，不会和手动修改打架。需求数量保留用户改过的值。

    Args:
        progress: parse_progress_text() 的结果（就地修改）
        readings: {物品: 仓库读数}
        season: 赛季
        shop_items: 店铺餐品物品集合

    Returns:
        dict: {物品: (旧当前数量, 新当前数量)} 本次变化的项
    """
    for item, row in default_progress(season, shop_items).items():
        progress.setdefault(item, row)
    changed = {}
    for item, count in readings.items():
        if item not in progress or count is None or count < 0:
            continue
        old = progress[item][0]
        if old != count:
            progress[item][0] = int(count)
            changed[item] = (old, int(count))
    return changed


def ready_items(progress):
    """已达标（当前 >= 需求）的物品列表：[(物品, 当前, 需求)]。"""
    return [(item, have, need) for item, (have, need) in sorted(progress.items())
            if need and have >= need]


def gaps(progress):
    """未达标项：{物品: (当前, 需求)}，供排产与方案刷新使用。"""
    return {item: (have, need) for item, (have, need) in progress.items()
            if need and have < need}


def load_progress(config, season, shop_items):
    """读取配置里的进度，缺项按赛季数据补齐。"""
    progress = parse_progress_text(config.cross_get(PROGRESS_KEY, default=''))
    for item, row in default_progress(season, shop_items).items():
        progress.setdefault(item, row)
    return progress


def record_readings(config, readings, season=None):
    """
    用本次仓库读数更新配置里的进度，返回变化项。

    Args:
        config: AzurLaneConfig 实例
        readings: {物品: 仓库读数}
        season: 赛季；缺省取全局配置

    Returns:
        dict: {物品: (旧, 新)}
    """
    from module.island.island_economy import ECONOMY_PRODUCTS
    from module.island.island_season import SeasonConfig

    season = season or SeasonConfig(config).season
    if not season or not readings:
        return {}
    shop_items = set(ECONOMY_PRODUCTS)
    progress = load_progress(config, season, shop_items)
    changed = merge_readings(progress, readings, season, shop_items)
    if changed:
        config.cross_set(PROGRESS_KEY, format_progress_text(progress))
        try:
            config.update()
        except Exception:
            logger.exception('[岛屿-赛季进度] 进度保存失败')
        logger.info('[岛屿-赛季进度] ' + '、'.join(
            f'{item} {old}->{new}' for item, (old, new) in changed.items()))
    return changed
