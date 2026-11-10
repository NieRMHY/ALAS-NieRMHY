"""岛屿「常驻餐品」自动轮换（Add by MHY）。

背景：ALAS 的店铺生产只做「货架补货」，补完之后剩下的空闲岗位交给
「常驻餐品」（Island<店>NextTask.AwayCook）填充；没配置就地空转。
真机日志：一天出现 20 次「有空闲岗位」，其中 14 次是「未设置特殊餐品
或常驻餐品，保持空闲」——纯浪费产能。

本模块按**赛季开发计划的缺口**挑常驻餐品：谁差得多就先产谁，攒够自动
换下一个。产能口径按 WorkerJuu（wiki 基础工时），与方案生成器一致。

纯逻辑部分可离线单测；写配置由调用方（经营端库存校验）在读到仓库库存后触发。

冬季另有两处口径（Add by MHY）：轮换在冬季保持用户设置（不覆盖 AwayCook）；达标提醒的
门槛提高到「任务需求 + 营业储备 + MealBuffer」，营业储备与缓冲来自 island_winter_meals，
见 notify_ready_from_progress。

Add by MHY, 2026-11-10：过季任务不再产生缺口；库存校验会按备份里的来源标记回收历史
自动写入的 AwayCook，用户手改过或没有备份的残留只告警、不擅自清空。
"""
from module.island.island_economy import ECONOMY_PRODUCTS
from module.island.island_season_plan_data import (
    SEASON_PLAN_TASKS,
    is_retired_season_item,
    season_is_retired,
)
from module.island.island_state import state_file
from module.logger import logger

# 店铺类型 -> 常驻餐品配置键
# 路径格式 <Task>.<Group>.<Arg>，与 config/template.json 一致
AWAY_COOK_KEYS = {
    'restaurant': 'IslandRestaurant.IslandRestaurantNextTask.AwayCook',
    'teahouse': 'IslandTeahouse.IslandTeahouseNextTask.AwayCook',
    'juu_eatery': 'IslandJuuEatery.IslandJuuEateryNextTask.AwayCook',
    'grill': 'IslandGrill.IslandGrillNextTask.AwayCook',
    'juu_coffee': 'IslandJuuCoffee.IslandJuuCoffeeNextTask.AwayCook',
}


def season_items_for_shop(shop, season, slots=None):
    """
    该店在赛季任务里要交的物品。

    Modify by MHY, 需求数量与已完成来自配置（IslandSeasonPlan.Need_<物品>/Done_<物品>）：
    已标记完成或需求为 0 的餐品不在其中，所以不会再被轮换成常驻餐品。没传 slots 时退回
    进行中的赛季表（离线测试用）。过季任务表只用于页面识别，不能当轮换兜底，否则配置
    缺键时会重新选中已经退场的秋季物品。

    Args:
        shop: 店铺类型标识
        season: 赛季
        slots: island_season_progress.read_slots() 的结果；None 用赛季表默认需求

    Returns:
        list[(物品, 需要数量, 单件工时)]
    """
    if season_is_retired(season):
        # Add by MHY, 2026-11-10：过季赛季即使调用方传了旧 slots 也不再选品，
        # 避免历史自动值被继续写成常驻餐品。
        return []
    if slots is not None:
        pairs = [(s['item'], s['need']) for s in slots if not s['done'] and s['need'] > 0]
    else:
        pairs = [(item, need) for _, item, need in SEASON_PLAN_TASKS.get(season, [])]
    result = []
    for item, need in pairs:
        info = ECONOMY_PRODUCTS.get(item)
        if info and info['shop'] == shop:
            result.append((item, need, info['time_min']))
    return result


def rotation_count(value):
    """
    轮换选品用的库存读数：读不到（缺失/None/负数）按 0 算。

    轮换只决定「先产哪个」，按 0 只会多产一点，不会把未知误判成已经攒够；
    进度与达标提醒用 island_season_progress 的未知口径（不当 0、不算达标），
    两处不能混用。

    Args:
        value: 仓库读数

    Returns:
        int: 非负整数
    """
    if value is None or isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def pick_away_cook(shop, season, counts, producible=None, exclude=None, skip=None, slots=None):
    """
    挑该店的常驻餐品：赛季缺口最大的物品优先。

    缺口按「还差多少件」算，同缺口时取单件工时短的（更快补上一个任务）。
    已确认提交完成的任务物品会被跳过，不再重复生产。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        producible: 可生产集合；None 不限制
        exclude: 排除集合（未解锁商品等）
        skip: 已完成的物品集合（本季不再生产）
        slots: 配置槽位；已完成的槽位不参与

    Returns:
        str: 物品英文名；没有缺口或没有可生产的返回 'None'
    """
    exclude = set(exclude or ()) | set(skip or ())
    best, best_key = None, None
    for item, need, time_min in season_items_for_shop(shop, season, slots):
        if producible is not None and item not in producible:
            continue
        if item in exclude:
            continue
        gap = need - rotation_count(counts.get(item))
        if gap <= 0:
            continue
        key = (-gap, time_min)
        if best_key is None or key < best_key:
            best, best_key = item, key
    return best or 'None'


def rotation_key(shop):
    """该店常驻餐品对应的配置键。"""
    return AWAY_COOK_KEYS.get(shop)


DEFAULT_FILE = state_file('island_away_cook_default.json')
# Add by MHY, 2026-11-10：没有备份可还原的过季残留每个 (店铺, 现值) 只提示一次。
_STALE_LOGGED = set()


def load_defaults(path=DEFAULT_FILE):
    """读取用户原本的常驻餐品设置（轮换前的值）。

    Modify by MHY, 2026-11-10：新记录是 {'value': 用户原值, 'auto': 上次自动写入值}；
    旧状态文件里的纯字符串原样返回，由 resolve_away_cook 按无 auto 标记兼容处理。
    """
    import json
    import os
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_defaults(defaults, path=DEFAULT_FILE):
    """记录用户原本的常驻餐品设置，赛季物品攒够后好还原。"""
    import json
    import os
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(defaults, f, ensure_ascii=False, indent=2, sort_keys=True)


NOTIFIED_FILE = state_file('island_season_notified.json')


def load_notified(path=NOTIFIED_FILE):
    """读取「已通知过攒够」的赛季物品记录：{赛季: {物品: True}}。"""
    import json
    import os
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_notified(notified, path=NOTIFIED_FILE):
    """保存通知记录，避免同一件物品反复发邮件。"""
    import json
    import os
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(notified, f, ensure_ascii=False, indent=2, sort_keys=True)


def _state_entry(state, item):
    """
    取物品的提醒状态，兼容早期版本写的 {物品: True} 格式。

    Args:
        state: {物品: 状态} 字典（就地更新）
        item: 物品英文名

    Returns:
        dict: {'notified': bool}
    """
    value = state.get(item)
    if value is True:
        entry = {'notified': True}
    elif isinstance(value, dict):
        entry = {'notified': bool(value.get('notified'))}
    else:
        entry = {'notified': False}
    state[item] = entry
    return entry


def is_shop_product(item):
    """
    是否是店铺生产的餐品（相对农田/牧场的材料而言）。

    材料类任务（小麦/牧草/大豆/大米/玉米/胡萝卜/牛奶/洋葱）在农田牧场长期溢出，
    用户明确说这部分不需要规划；对它们提醒「可以提交」只会刷屏（真机踩过：
    一次运行发了 8 封，其中 7 封是材料）。

    Args:
        item: 物品键

    Returns:
        bool: 有对应店铺的餐品返回 True
    """
    from module.island.island_economy import ECONOMY_PRODUCTS
    return bool(item) and item in ECONOMY_PRODUCTS


def winter_meal_reserve(config):
    """
    冬季餐品的营业储备：({物品: 保留数量}, 无法确认的店铺集合, 餐品缓冲)。

    营业储备取库存下限与「一轮货架直售 + 各套餐原料耗用」的较大值，
    包含跨店配方；货架容量不是日销量，见 island_winter_meals.business_requirements。
    商品配方未确认时，该店进入 unknown 集合，提醒等待完整储备计算。

    Args:
        config: AzurLaneConfig 实例

    Returns:
        tuple: (reserve, unknown_shops, meal_buffer)；读取失败向上抛异常
    """
    from module.island.island_winter_meals import business_requirements, meal_buffer

    totals, unknown = business_requirements(config)
    return dict(totals), set(unknown), meal_buffer(config)


def notify_ready_from_progress(config, season, progress):
    """
    赛季进度达标时推送提醒（每项只提醒一次，进度回落后复位）。

    Modify by MHY, 进度来自仓库读数（见 island_season_progress），不再依赖赛季页 OCR。
    提醒的是「仓库里已经攒够了」，具体是否已提交以你为准：提交任务后仓库数量
    掉下去，物品自然回到缺口，复位 notified，下次攒够会再提醒。

    Modify by MHY, 冬季餐品的达标线提高到「任务需求 + 营业储备 + MealBuffer」：
    营业储备是货架直售与套餐（含整条配方）要占用的库存，销售会持续消耗它，所以：
      - 库存未知（缺失/None/负数）一律不提醒；
      - 冬季开关关闭时不提醒，与其他赛季的普通需求口径互不影响；
      - 消息写明依据是最近一次库存记录、提交前要自己在游戏内核对、提交后勾 Done，
        自动提交还没接入；不能宣称对销售完全没有影响。

    Args:
        config: AzurLaneConfig 实例
        season: 赛季
        progress: {物品: [当前数量, 需求数量]}（可带 known 标志）

    Returns:
        list[str]: 本次提醒的物品
    """
    from module.island.island_season_plan_data import cn_name, task_of_item, winter_task_enabled
    from module.island.island_season_progress import last_reading_time, progress_values
    from module.logger import logger
    from module.notify.notify import handle_notify, notify_title

    if not season or not progress:
        return []
    # 总开关：关闭后完全不发邮件（提交过的任务仓库数量仍可能高于需求，会反复打扰）
    if not config.cross_get('IslandSeasonPlan.IslandSeasonPlan.NotifyEnable', default=True):
        return []
    winter = season == 'winter'
    reserve, buffer = {}, 0
    if winter:
        if not winter_task_enabled(config):
            return []
        try:
            reserve, unknown, buffer = winter_meal_reserve(config)
        except Exception:
            # 储备算不出来就没法保证「不影响销售」，宁可不提醒
            logger.warning('[岛屿-赛季任务] 冬季营业储备无法确认，本次不发送达标提醒')
            return []
        if unknown:
            logger.warning('[岛屿-赛季任务] 以下店铺配方未确认，暂缓冬季达标提醒: '
                           + '、'.join(sorted(unknown)))
            return []
    notified = load_notified()
    state = notified.setdefault(season, {})
    dirty = False
    ready = []
    thresholds = {}
    for item, entry in sorted(progress.items()):
        have, need = progress_values(entry)
        target = need + reserve.get(item, 0) + buffer if winter else need
        thresholds[item] = target
        current = _state_entry(state, item)
        if have is None:
            # 库存未知：既不是 0，也不能算攒够了，连复位都不做
            continue
        if not target or have < target:
            # 进度回落（提交后掉下去、销售消耗、或需求被调高）：复位，下次攒够再提醒
            if current['notified']:
                current['notified'] = False
                dirty = True
            continue
        if current['notified'] or not is_shop_product(item):
            continue
        current['notified'] = True
        dirty = True
        ready.append((item, have, target))
    if winter and thresholds:
        logger.info('[岛屿-赛季任务] 冬季提醒阈值（需求+营业储备+缓冲）: '
                    + '、'.join(f'{cn_name(item)} {target}'
                               for item, target in sorted(thresholds.items())))
    if dirty:
        save_notified(notified)
    if not ready:
        return []
    lines = []
    for item, have, target in ready:
        task, _ = task_of_item(item, season)
        lines.append(f"{task or cn_name(item)}（{cn_name(item)} {have}/{target}）")
    logger.info(f"[岛屿-赛季任务] {len(ready)} 项已达标，推送提醒: {'、'.join(lines)}")
    content = (f"<{config.config_name}> 赛季任务已达标："
               + '\n' + '\n'.join(lines)
               + '\n可以去岛屿「开发季」提交了')
    if winter:
        content += (f"\n冬季达标线 = 任务需求 + 营业储备 + 餐品缓冲 {buffer}；"
                    "营业储备按当前货架直售与套餐配置估算，不能保证销售完全不占用任务库存")
    when = last_reading_time()
    content += (f"\n提醒基于最近一次仓库读数{'（' + when + '）' if when else ''}，"
                "不是实时库存：提交前请在游戏内核对，提交后销售仍可能继续消耗库存")
    content += ("\n提交后在 IslandSeasonPlan 勾选对应 Done_<物品>；"
                "自动提交尚未接入，本提醒不会代你提交")
    handle_notify(
        config.Error_OnePushConfig,
        title=notify_title(config.config_name, '岛屿', f'{len(ready)} 项赛季任务可以提交'),
        content=content,
    )
    return [item for item, _, _ in ready]


def _default_entry(value):
    """
    常驻餐品备份项归一化：{'value': 用户原值, 'auto': 上次自动写入值}。

    Add by MHY, 2026-11-10：auto 让回收历史自动值时能区分「当前仍是自己写的」与
    「用户后来手改过」。旧状态文件里的纯字符串按无标记处理，只有当前值仍是过季
    任务物品时才认作历史自动残留。
    """
    if isinstance(value, dict):
        return {'value': value.get('value', 'None'), 'auto': value.get('auto')}
    return {'value': value, 'auto': None}


def _warn_stale_once(shop, current):
    """
    没有备份可还原的过季残留只提示一次。

    Add by MHY, 2026-11-10：历史 Meal/AwayCook 没有来源标记，不能凭猜测替用户清掉
    手填值；这里保留现值并在日志里点名，交给人工或上层定点修正。
    """
    key = (shop, current)
    if key in _STALE_LOGGED:
        return
    _STALE_LOGGED.add(key)
    logger.warning(f'[岛屿-常驻餐品] {shop} 当前值 {current} 属于已过季任务，'
                   f'但没有可还原的用户原值记录；保留现值，请人工确认')


def resolve_away_cook(shop, season, counts, current, defaults=None, producible=None,
                      exclude=None, skip=None, slots=None):
    """
    决定该店常驻餐品该写什么，并维护「用户原值」备份。

    规则：
      - 有赛季缺口 -> 写缺口最大的赛季物品，同时把用户原值记进 defaults，
        并记录本次自动写入值
      - 没有缺口   -> 仅当当前值仍是上次自动写入的值（旧备份没有 auto 标记时，
        要求当前值仍是过季任务物品）才还原用户原值；用户手改过就保留现值并丢弃
        过期备份，避免把自动化残留当成用户设置。

    Modify by MHY, 2026-11-10：过季任务不再产生缺口，下一次库存校验会走「没有缺口」
    分支，按上面的条件安全回收历史自动值；没有备份的残留只告警、不改配置。

    Args:
        shop: 店铺类型标识
        season: 赛季
        counts: {物品: 仓库库存}
        current: 当前配置值
        defaults: {店铺: 用户原值/自动值记录}
        producible: 可生产集合
        exclude: 排除集合

    Returns:
        tuple: (要写入的值, 更新后的 defaults)
    """
    defaults = {shop_name: _default_entry(value)
                for shop_name, value in (defaults or {}).items()}
    target = pick_away_cook(shop, season, counts,
                            producible=producible, exclude=exclude, skip=skip, slots=slots)
    if target != 'None':
        if shop not in defaults:
            # Modify by MHY, 来源不明的过季残留不能成为下一轮自动恢复的原值。
            if is_retired_season_item(current):
                _warn_stale_once(shop, current)
                return current, defaults
            defaults[shop] = {'value': current, 'auto': target}
        else:
            entry = defaults[shop]
            if entry['auto'] is not None and current != entry['auto']:
                # 用户在自动接管期间手改过：以手填值作为新的原值
                entry['value'] = current
            entry['auto'] = target
        return target, defaults
    if shop in defaults:
        entry = defaults.pop(shop)
        original, auto = entry['value'], entry['auto']
        if auto is None:
            if is_retired_season_item(current):
                logger.info(f'[岛屿-常驻餐品] {shop}: 还原过季任务前的用户原值 '
                            f'{current} -> {original}')
                return original, defaults
            logger.info(f'[岛屿-常驻餐品] {shop}: 当前值 {current} 不是过季任务物品，'
                        f'保留手填值并丢弃过期备份')
            return current, defaults
        if current == auto:
            logger.info(f'[岛屿-常驻餐品] {shop}: 回收自动写入的 {current}，'
                        f'还原用户原值 {original}')
            return original, defaults
        logger.info(f'[岛屿-常驻餐品] {shop}: 当前值 {current} 已不是自动写入的 {auto}，'
                    f'保留手填值并丢弃过期备份')
        return current, defaults
    if is_retired_season_item(current):
        _warn_stale_once(shop, current)
    return current, defaults
