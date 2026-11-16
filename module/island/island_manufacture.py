"""岛屿制造工坊模块。

继承 IslandShopBase，实现制造工坊的产品配置与岗位管理。
支持固定位置按钮（如荠菜）、滑动配置及制造时间前缀设置，管理工坊自动化生产流程。
"""
from module.island.island import *
from module.island_manufacture.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
import re
from datetime import timedelta

from module.config.time_source import now as current_time
from module.logger import logger
from module.base.button import Button
# Add by MHY, 2026-11-09: 冬季开发计划制造任务的有限配额（纯逻辑在 quota 模块）
from module.island.island_manufacture_quota import (
    CAPABILITY_DISPATCHABLE,
    DEFAULT_BATCH_LIMIT,
    DEPENDENCY_ITEMS,
    describe_decision,
    plan_winter_quota,
    read_winter_task_settings,
    season_quota_enabled,
)


# 固定位置按钮 — 在产品选择界面不滑动时，荠菜的固定位置
FIXED_SELECT_SHEPHERD_PURSE = Button(
    area=(), color=(), button=(224, 151, 274, 209),
    file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
)


# 季节限定手工产品配置（按 SEASONAL_ITEMS['handmade'] 的键引用）
# 注意：清单中的部分物品（如夏季茉莉精油、秋季花束）有意不在此配置内，
# 即季节定义保留但工厂不实际制作。
SEASONAL_HANDMADE_ITEMS = {
    'shepherd_purse': {
        'name': 'shepherd_purse', 'template': TEMPLATE_SHEPHERD_PURSE,
        'var_name': 'shepherd_purse', 'selection': FIXED_SELECT_SHEPHERD_PURSE,
        'selection_check': FIXED_SELECT_SHEPHERD_PURSE, 'post_action': POST_SHEPHERD_PURSE,
    },
    'summer_bouquet': {
        'name': 'summer_bouquet', 'template': TEMPLATE_SUMMER_BOUQUET,
        'var_name': 'summer_bouquet', 'selection': SELECT_SUMMER_BOUQUET,
        'selection_check': SELECT_SUMMER_BOUQUET_CHECK, 'post_action': POST_SUMMER_BOUQUET,
    },
    'plum_blossom_sachet': {
        'name': 'plum_blossom_sachet', 'template': TEMPLATE_PLUM_BLOSSOM_SACHET,
        'var_name': 'plum_blossom_sachet', 'selection': SELECT_PLUM_BLOSSOM_SACHET,
        'selection_check': SELECT_PLUM_BLOSSOM_SACHET_CHECK, 'post_action': POST_PLUM_BLOSSOM_SACHET,
    },
    'winter_bouquet': {
        'name': 'winter_bouquet', 'template': TEMPLATE_WINTER_BOUQUET,
        'var_name': 'winter_bouquet', 'selection': SELECT_WINTER_BOUQUET,
        'selection_check': SELECT_WINTER_BOUQUET_CHECK, 'post_action': POST_WINTER_BOUQUET,
    },
}


def _product(name, selection, selection_check):
    """可在产品列表中选择、但没有仓库模板和岗位「生产中」图的制造产品。

    识别图取自国际服实机截图（图标不含文字，国服同名图为同一截图）。没有仓库模板时
    不统计库存，没有岗位图时正在生产的岗位按未知产品处理，均不影响按配置顺序排产。
    """
    return {'name': name, 'template': None, 'var_name': name, 'selection': selection,
            'selection_check': selection_check, 'post_action': None}


# 各产线可选产品：产线配置项 -> 制造类别。产品顺序由 <产线>.Products 配置（岛屿生产规划器会写入）。
PRODUCT_LINES = {
    'WoodProcessing': 'wood_processing',
    'ElectronicProcessing': 'electronic_processing',
    'Industrial': 'industrial_production',
    'Handmade': 'handmade',
}


def parse_product_order(text):
    """解析产线产品顺序配置，如 ``paper > notebook``，也接受逗号和换行分隔。

    Returns:
        list[str]: 去重后的产品名，保持配置顺序。
    """
    names = [name.strip().lower() for name in re.split(r'[>,\n]', str(text or ''))]
    return list(dict.fromkeys(name for name in names if name))


class IslandManufacture(IslandShopBase):
    """岛屿制造工坊自动化管理器。

    继承 IslandShopBase，管理木料加工、电子加工、工业生产和手工制作四大区域的自动化排产。

    Attributes:
        shop_type (str): 店铺类型标识。
        time_prefix (str): 岗位完成时间前缀。
        post_manage_swipe_count (int): 岗位管理界面滑动次数。
        filter_asset (str): 仓库筛选分类。
        manufacture (dict): 制造业各分类的产品配置。
        post_buttons (dict): 岗位按钮映射。
        shop_items (list): 展平的所有产品配置列表。
        unavailable_products (set): 当前批次已确认材料不足的产品集合。
    """
    # 岗位 ID 按制造类别分组（排产与冬季配额共用，避免各处再抄一份列表）
    POST_IDS = {
        'wood_processing': ('ISLAND_WOOD_PROCESSING_POST1', 'ISLAND_WOOD_PROCESSING_POST2'),
        'electronic_processing': ('ISLAND_ELECTRONIC_PROCESSING_POST1',
                                  'ISLAND_ELECTRONIC_PROCESSING_POST2'),
        'industrial_production': ('ISLAND_INDUSTRIAL_POST1', 'ISLAND_INDUSTRIAL_POST2'),
        'handmade': ('ISLAND_HANDMADE_POST1', 'ISLAND_HANDMADE_POST2'),
    }

    def __init__(self, *args, **kwargs):
        # 先初始化基类
        IslandShopBase.__init__(self, *args, **kwargs)

        # 设置店铺类型
        self.shop_type = "manufacture"
        self.time_prefix = "time_manufacture"

        # 设置滑动配置（岗位管理界面需要两次滑动）
        self.post_manage_swipe_count = 2

        # === 初始化全局季节配置 ===
        self._init_season_config()

        # 设置筛选资产
        self.filter_asset = 'factory'

        # 制造业产品配置
        self.manufacture = {
            'wood_processing': {
                'items': [
                    {'name': 'file_cabinet', 'template': TEMPLATE_FILE_CABINET,
                     'var_name': 'file_cabinet', 'selection': SELECT_FILE_CABINET,
                     'selection_check': SELECT_FILE_CABINET_CHECK, 'post_action': POST_FILE_CABINET},
                    _product('paper', SELECT_PAPER, SELECT_PAPER_CHECK),
                    _product('notebook', SELECT_NOTEBOOK, SELECT_NOTEBOOK_CHECK),
                    _product('chair_desk', SELECT_CHAIR_DESK, SELECT_CHAIR_DESK_CHECK),
                ]
            },
            #TEMPLATE_FILTER_ELEMENT 未添加
            'electronic_processing': {
                'items': [
                    {'name': 'filter_element', 'template': TEMPLATE_FILE_CABINET,
                     'var_name': 'filter_element', 'selection': SELECT_FILTER_ELEMENT,
                     'selection_check': SELECT_FILTER_ELEMENT_CHECK, 'post_action': POST_FILTER_ELEMENT},
                    _product('ink_cartridge', SELECT_INK_CARTRIDGE, SELECT_INK_CARTRIDGE_CHECK),
                ]
            },
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail', 'template': TEMPLATE_IRON_NAIL,
                     'var_name': 'iron_nail', 'selection': SELECT_IRON_NAIL,
                     'selection_check': SELECT_IRON_NAIL_CHECK, 'post_action': POST_IRON_NAIL},
                    {'name': 'cutlery', 'template': TEMPLATE_CUTLERY,
                     'var_name': 'cutlery', 'selection': SELECT_CUTLERY,
                     'selection_check': SELECT_CUTLERY_CHECK, 'post_action': POST_CUTLERY},
                    _product('charcoal_brush', SELECT_CHARCOAL_BRUSH, SELECT_CHARCOAL_BRUSH_CHECK),
                    _product('cable', SELECT_CABLE, SELECT_CABLE_CHECK),
                ]
            },
            'handmade': {
                'items': [
                    {'name': 'leather', 'template': TEMPLATE_LEATHER,
                     'var_name': 'leather', 'selection': SELECT_LEATHER,
                     'selection_check': SELECT_LEATHER_CHECK, 'post_action': POST_LEATHER},
                    {'name': 'boot', 'template': TEMPLATE_BOOT,
                     'var_name': 'boot', 'selection': SELECT_BOOT,
                     'selection_check': SELECT_BOOT_CHECK, 'post_action': POST_BOOT},
                    {'name': 'peanut_oil', 'template': TEMPLATE_PEANUT_OIL,
                     'var_name': 'peanut_oil', 'selection': SELECT_PEANUT_OIL,
                     'selection_check': SELECT_PEANUT_OIL_CHECK, 'post_action': POST_PEANUT_OIL},
                    _product('cloth', SELECT_CLOTH, SELECT_CLOTH_CHECK),
                    _product('rope', SELECT_ROPE, SELECT_ROPE_CHECK),
                ]
            }
        }
        # 季节限定：手工类产品（荠菜干、秋季花束等，按当前季节配置）
        if hasattr(self, 'season_config') and self.season_config.is_seasonal_enabled:
            for item_name in (self.season_config.get_seasonal_items('handmade') or []):
                item_config = SEASONAL_HANDMADE_ITEMS.get(item_name)
                if not item_config:
                    continue
                if any(it['name'] == item_name for it in self.manufacture['handmade']['items']):
                    # 花生油等基础产品已常驻，无需重复添加
                    continue
                self.manufacture['handmade']['items'].append(item_config.copy())
                logger.info(f"[岛屿-制造业] 季节限定：{self._item_cn(item_name)} 已添加到手工产品列表")

        # 根据配置初始化岗位按钮
        self.post_buttons = self._init_post_buttons()

        # 将所有产品展平到一个列表中，供基类使用
        self.shop_items = []
        for category in self.manufacture.values():
            self.shop_items.extend(category['items'])

        # 初始化需求列表（制造业不需要外部配置的需求）
        self.post_products = []

        # 设置配置（使用4个参数，删除任务相关配置）
        self.setup_config(
            config_meal_prefix="IslandManufacture_Meal",
            config_number_prefix="IslandManufacture_MealNumber",
            config_away_cook="IslandManufactureNextTask_AwayCook",
            config_post_number="IslandManufacture_PostNumber"
        )

        # 初始化店铺
        self.initialize_shop()

        # 本批生产已确认材料不足的物品（同一批内后续岗位直接跳过）
        self.unavailable_products = set()

        # Add by MHY, 2026-11-09: 冬季任务有限配额状态（每个 run 重建）
        # post_items 记录每个岗位本轮识别到的产品/数量，配额据此判断在制是否已知
        self.winter_quota_plan = None
        self.winter_quota_ordered = {}
        self.post_items = {}
        self._post_check_product = None
        self._last_actual_number = 0
        self._warehouse_scanned = False

    def _init_post_buttons(self):
        """根据配置初始化启用的制造业岗位按钮。

        Returns:
            dict[str, Button]: 岗位标识到按钮资源的映射字典。
        """
        post_buttons = {}
        if self.config.WoodProcessing_Positions >= 1:
            post_buttons['ISLAND_WOOD_PROCESSING_POST1'] = ISLAND_WOOD_PROCESSING_POST1
        if self.config.WoodProcessing_Positions >= 2:
            post_buttons['ISLAND_WOOD_PROCESSING_POST2'] = ISLAND_WOOD_PROCESSING_POST2

        if self.config.ElectronicProcessing_Positions >= 1:
            post_buttons['ISLAND_ELECTRONIC_PROCESSING_POST1'] = ISLAND_ELECTRONIC_PROCESSING_POST1
        if self.config.ElectronicProcessing_Positions >= 2:
            post_buttons['ISLAND_ELECTRONIC_PROCESSING_POST2'] = ISLAND_ELECTRONIC_PROCESSING_POST2

        if self.config.Industrial_Positions >= 1:
            post_buttons['ISLAND_INDUSTRIAL_POST1'] = ISLAND_INDUSTRIAL_POST1
        if self.config.Industrial_Positions >= 2:
            post_buttons['ISLAND_INDUSTRIAL_POST2'] = ISLAND_INDUSTRIAL_POST2

        if self.config.Handmade_Positions >= 1:
            post_buttons['ISLAND_HANDMADE_POST1'] = ISLAND_HANDMADE_POST1
        if self.config.Handmade_Positions >= 2:
            post_buttons['ISLAND_HANDMADE_POST2'] = ISLAND_HANDMADE_POST2

        return post_buttons

    def get_idle_posts_by_category(self, category):
        """获取指定制造类别的空闲岗位 ID 列表。

        Args:
            category (str): 制造类别（'wood_processing'、'electronic_processing'、'industrial_production'、'handmade'）。

        Returns:
            list[str]: 属于该类别的空闲岗位 ID 列表。
        """
        # 只返回实际存在的空闲岗位
        return [post_id for post_id in self.POST_IDS.get(category, ())
                if post_id in self.posts and self.posts[post_id]['status'] == 'idle']

    def post_category(self, post_id):
        """岗位 ID 对应的制造类别；未知岗位返回 None。"""
        for category, post_ids in self.POST_IDS.items():
            if post_id in post_ids:
                return category
        return None

    # ==================== 冬季任务有限配额 ====================

    def get_warehouse_counts(self):
        """读取仓库库存，并记录本轮确实扫过仓库（配额据此判断库存是否已知）。"""
        counts = super().get_warehouse_counts()
        self._warehouse_scanned = True
        return counts

    def post_product_check(self):
        """识别岗位在产产品，同时留给 post_check 记录到岗位级状态。"""
        product = super().post_product_check()
        self._post_check_product = product
        return product

    def post_check(self, post_id, time_var_name):
        """巡检岗位状态，并记录岗位级产品/数量供冬季配额判断在制。

        基类只把数量累加到 post_check_meal，无法区分「某岗位数量没读到」和
        「该产品没在产」。这里用累加前后的差值还原单岗位数量，读不到记 None。
        """
        before = dict(self.post_check_meal)
        self._post_check_product = None
        super().post_check(post_id, time_var_name)
        status = self.posts.get(post_id, {}).get('status')
        product = self._post_check_product if status == 'working' else None
        number = None
        if product is not None:
            delta = self.post_check_meal.get(product, 0) - before.get(product, 0)
            if delta > 0:
                number = delta
        self.post_items[post_id] = {'status': status, 'product': product, 'number': number}

    def _warehouse_stock(self, item):
        """配额用的仓库库存读数，未识别时保留 None。

        Modify by MHY, 2026-11-09：优先用本轮 strict 扫描的 warehouse_observations，
        识别失败（None）也保留，避免「没读到」被 warehouse_counts 的 0 兜底盖掉。
        没有该属性的旧测试夹具退回 warehouse_counts，保持原行为。

        Args:
            item (str): 商品名称。

        Returns:
            int | None: 已知库存；未知返回 None。
        """
        observations = getattr(self, 'warehouse_observations', None)
        if observations is None:
            return self.warehouse_counts.get(item)
        return observations.get(item)

    def _winter_quota_state(self, tasks):
        """把岗位/仓库/本轮下单整理成配额层需要的观测状态。

        未知一律用 None 表示：没有仓库模板、没扫仓库、在产数量读不到都算未知，
        配额层会因此暂停任务派产，而不是按 0 补满缺口。仓库读数优先取 strict
        扫描结果（warehouse_observations），只有旧数据才回退 warehouse_counts。
        """
        stock = {}
        wip = {}
        dependency_stock = {}
        post_unknown = False
        wip_totals = {}
        wip_unknown = set()
        # 只有可派产任务所在产线的未知在产才影响配额；其它产线的无识别图
        # 产品（如布料/墨盒）在产时不该把餐具任务一起挂起。
        dispatchable_lines = {task.get('line') for task in tasks
                              if task['capability'] == CAPABILITY_DISPATCHABLE}

        for post_id, post_info in self.post_items.items():
            relevant = self.post_category(post_id) in dispatchable_lines
            status = post_info.get('status')
            if status == 'working':
                product = post_info.get('product')
                if product is None:
                    if relevant:
                        post_unknown = True
                    continue
                number = post_info.get('number')
                if number is None:
                    wip_unknown.add(product)
                else:
                    wip_totals[product] = wip_totals.get(product, 0) + number
            elif status not in ('idle', 'locked'):
                # Modify by MHY, 锁定岗位确定没有在制；其余未知状态仍暂停配额。
                if relevant:
                    post_unknown = True

        for task in tasks:
            item = task['item']
            if task['capability'] != CAPABILITY_DISPATCHABLE:
                stock[item] = None
                wip[item] = None
                continue
            product_config = self.name_to_config.get(item) or {}
            if self._warehouse_scanned and product_config.get('template') is not None:
                stock[item] = self._warehouse_stock(item)
            else:
                stock[item] = None
            if item in wip_unknown:
                wip[item] = None
            else:
                # Modify by MHY, 本轮有限订单已记入 ordered，重算时从在制中剔除。
                wip[item] = max(0, wip_totals.get(item, 0) - self.winter_quota_ordered.get(item, 0))

        for dependency in DEPENDENCY_ITEMS:
            dependency_config = self.name_to_config.get(dependency) or {}
            if self._warehouse_scanned and dependency_config.get('template') is not None:
                dependency_stock[dependency] = self._warehouse_stock(dependency)
            else:
                dependency_stock[dependency] = None

        return {
            'stock': stock,
            'wip': wip,
            'ordered': dict(self.winter_quota_ordered),
            'post_unknown': post_unknown,
            'dependency_stock': dependency_stock,
        }

    def prepare_winter_quota(self):
        """计算本轮冬季任务配额；非冬季或开关关闭时清空计划。"""
        self.winter_quota_plan = None
        enabled, tasks = read_winter_task_settings(self.config)
        season = getattr(self, 'current_season', None)
        if not season_quota_enabled(season, enabled):
            return None

        posts_by_line = {}
        for line in ('industrial_production', 'electronic_processing',
                     'handmade', 'wood_processing'):
            posts_by_line[line] = len(self.get_idle_posts_by_category(line))
        plan = plan_winter_quota(tasks, self._winter_quota_state(tasks), posts_by_line)
        self.winter_quota_plan = plan
        logger.info('[岛屿-制造业][冬季配额] 冬季开发计划制造任务启用，按有限缺口补产')
        for decision in plan['items']:
            logger.info(describe_decision(decision))
        return plan

    def winter_quota_active(self):
        """冬季任务配额是否生效（冬季 + WinterTaskEnabled），供排产回退判断。"""
        enabled, _ = read_winter_task_settings(self.config)
        return season_quota_enabled(getattr(self, 'current_season', None), enabled)

    def dispatch_winter_quota_batches(self, category):
        """把本产线的冬季配额批次派给空闲岗位。

        批次在 plan 里已经按缺口拆好，多岗位不会各自补满整个缺口；派完或
        遇到选择/材料失败就停，剩余缺口留到下一轮重新观测。

        每次派产后按岗位实际显示的数量扣减剩余缺口：实际比请求少时下一个岗位
        按剩余缺口补，实际比请求多时直接收工，都不会重复下单。实际数量读不到
        时既不当 0 也不按请求值记账，直接停止本项派产。
        """
        if not self.winter_quota_plan:
            return 0
        dispatched = 0
        for decision in self.winter_quota_plan['items']:
            if decision['status'] != 'dispatch' or not decision['batches']:
                continue
            if decision.get('line') != category:
                continue
            item_config = self.name_to_config.get(decision['item'])
            if item_config is None:
                logger.warning(
                    f"[岛屿-制造业][冬季配额] {decision['cn']} 不在本店产品配置中，跳过")
                continue
            batches = decision['batches']
            gap = decision.get('gap')
            remaining = int(gap) if gap is not None else sum(batches)
            batch_limit = int(decision.get('batch_limit') or DEFAULT_BATCH_LIMIT)
            for post_id in self.get_idle_posts_by_category(category):
                if remaining <= 0 or not batches:
                    break
                quantity = min(batch_limit, remaining)
                result = self.select_product_with_material_check(
                    post_id, [item_config], quantity=quantity)
                if result is None:
                    logger.info(
                        f"[岛屿-制造业][冬季配额] {decision['cn']} 本轮未能派发"
                        f"（选择/材料/角色原因），缺口保留到下一轮")
                    break
                actual = self._last_actual_number
                if actual is None or actual <= 0:
                    logger.warning(
                        f"[岛屿-制造业][冬季配额] {decision['cn']} 派遣后未读到实际数量，"
                        f"本轮停止该项派产，缺口留到下一轮重新观测（不按请求值记账）")
                    # 读不到实际数量就不猜测；岗位按「在产品已知、数量未知」记录，
                    # 清空批次避免同一轮再次下单
                    self.post_items[post_id] = {
                        'status': 'working', 'product': decision['item'], 'number': None}
                    batches.clear()
                    break
                batches.pop(0)
                remaining -= actual
                self.winter_quota_ordered[decision['item']] = (
                    self.winter_quota_ordered.get(decision['item'], 0) + actual)
                self.post_items[post_id] = {
                    'status': 'working', 'product': decision['item'], 'number': actual}
                dispatched += actual
                logger.info(
                    f"[岛屿-制造业][冬季配额] {decision['cn']} 派产 x{quantity}"
                    f"（实际 x{actual}，{post_id}），剩余缺口 {max(remaining, 0)}")
            decision['gap'] = max(remaining, 0)
            if remaining <= 0:
                # 实际产量已够本轮缺口：剩余批次作废，避免下一岗位重复下单
                batches.clear()
        return dispatched

    def select_product(self, product_selection, product_selection_check):
        """选择制造产品。

        荠菜使用固定坐标点击；其他产品调用父类模板匹配与滑动搜索逻辑。

        Args:
            product_selection (Button): 产品选择按钮或坐标。
            product_selection_check (Button): 产品选择确认检测按钮。

        Returns:
            bool: 是否成功选中目标产品。
        """
        # 荠菜 → 直接点击固定位置
        if product_selection == FIXED_SELECT_SHEPHERD_PURSE:
            self.device.click(FIXED_SELECT_SHEPHERD_PURSE)
            self.device.sleep(0.5)
            return True

        # 其他产品使用父类逻辑（模板匹配 + 向下滑动查找）
        return super().select_product(product_selection, product_selection_check)

    @staticmethod
    def _post_confirm_unavailable(image):
        """选品页确认按钮是否因材料/角色不足变灰，沿用基类的取色区域。"""
        color = get_color(image, (493, 597, 621, 643))
        return color_similar(color, (153, 156, 156), 80)

    def select_product_with_material_check(self, post_id, product_list, quantity=None):
        """选择产品并检查材料是否充足。

        按候选列表顺序尝试进入岗位选择；若材料不足则记忆并退出重置滑动，尝试下一个产品。

        冬季配额传入 quantity 时只派有限批次：选品页数量从 1 起（与餐馆/茶馆/
        矿场一致），点 quantity-1 次 +1；如果加到目标数量后确认按钮变灰（材料
        只够更少的数量），退回按 1 件重新派遣，避免硬点无效的确认导致等待超时。

        Args:
            post_id (str): 目标岗位标识。
            product_list (list[dict]): 待尝试的产品配置列表。
            quantity (int | None): 冬季任务配额的有限批次；None 时沿用 POST_MAX。

        Returns:
            dict | None: 成功安排生产的产品配置，全部失败则返回 None。
        """
        post_button = self.posts[post_id]['button']
        self._last_actual_number = 0
        requested_quantity = quantity

        for product_info in product_list:
            product_name = product_info['name']
            selection = product_info['selection']
            selection_check = product_info['selection_check']

            # 同一批内前面岗位已确认材料不足的物品，直接跳过
            if product_name in self.unavailable_products:
                logger.info(f"[岛屿-制造业] {self._item_cn(product_name)} 本批已确认材料不足，直接跳过")
                continue

            # 每个产品：进入岗位搜索并选择；找不到则退出岗位重进重试
            for attempt in range(self.PRODUCT_SELECT_RETRY_LIMIT):
                # 打开岗位（首次或重进）
                self.post_close()
                self.post_open(post_button)
                self.device.sleep(0.5)

                entered_product_page = False
                while True:
                    self.device.screenshot()
                    if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                        self.device.sleep(0.5)
                        continue
                    if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                        if self.select_character():
                            if not self.confirm_selected_character(f"{post_id}制造派遣"):
                                self.back_to_postmanage_from_dispatch()
                                return None
                        else:
                            logger.warning(f"[岛屿-制造业] {post_id}制造派遣无可用角色")
                            self.back_to_postmanage_from_dispatch()
                            return None
                        continue
                    if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                        entered_product_page = True
                        logger.info(f"[岛屿-制造业] 尝试选择产品: {self._item_cn(product_name)}")
                        selected = self.select_product(selection, selection_check)
                        self.device.sleep(0.5)
                        break

                if not entered_product_page:
                    return None

                if not selected:
                    # 搜索失败：退出岗位重新进入（重置列表滚动进度），重试同一产品
                    logger.warning(
                        f"[岛屿-制造业] 未能识别到产品选择项: {self._item_cn(product_name)}，"
                        f"退出岗位重进重试 ({attempt + 1}/{self.PRODUCT_SELECT_RETRY_LIMIT})"
                    )
                    self.device.click(SELECT_UI_BACK)
                    self.device.sleep(0.3)
                    self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                    self.device.sleep(0.5)
                    self.post_close()
                    for _ in range(self.post_manage_swipe_count):
                        self.post_manage_up_swipe(450)
                    if attempt + 1 >= self.PRODUCT_SELECT_RETRY_LIMIT:
                        # 产品列表里始终找不到，多为岛屿科技尚未解锁（如未解锁的刀叉餐具、鞋靴）。
                        # 记入本批不可用，后续岗位不再重复尝试，改试下一个候选产品
                        self.unavailable_products.add(product_name)
                        logger.warning(f"[岛屿-制造业] 多次未找到 {self._item_cn(product_name)}，可能尚未解锁，本批跳过")
                    continue  # 下一轮重进重试同一产品

                # 检查确认按钮状态：灰色（153, 156, 156）表示材料不足
                image = self.device.screenshot()
                if self._post_confirm_unavailable(image):
                    # 记忆本批材料不足的物品，后续岗位不再重复尝试
                    self.unavailable_products.add(product_name)
                    logger.info(f"[岛屿-制造业] 材料不足，跳过产品: {self._item_cn(product_name)}")
                    # 退出岗位，下一个产品重新进入时列表滚动进度已重置
                    self.device.click(SELECT_UI_BACK)
                    self.device.sleep(0.3)
                    self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                    self.device.sleep(0.5)
                    self.post_close()
                    for _ in range(self.post_manage_swipe_count):
                        self.post_manage_up_swipe(450)
                    break  # 跳出重试循环 -> 下一个产品

                # 材料充足，派遣生产
                if requested_quantity is None:
                    self.appear_then_click(POST_MAX)
                else:
                    # 冬季任务配额：复用 +1 数量调节，按缺口派有限批次，不用 POST_MAX。
                    # 点击间隔 0.1s，避免连续点击被模拟器丢帧；加完数量后复查确认
                    # 按钮颜色，材料只够 1 件以上不足时退回按 1 件重派。
                    self.device.sleep(0.5)
                    if int(requested_quantity) > 1:
                        self.post_add_one(int(requested_quantity) - 1, interval=0.1)
                        self.device.sleep(0.3)
                    if int(requested_quantity) > 1 and self._post_confirm_unavailable(
                            self.device.screenshot()):
                        logger.warning(
                            f"[岛屿-制造业] {self._item_cn(product_name)} 请求 "
                            f"{requested_quantity} 件时材料不足，退回按 1 件派遣")
                        requested_quantity = 1
                        self.device.click(SELECT_UI_BACK)
                        self.device.sleep(0.3)
                        self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                        self.device.sleep(0.5)
                        self.post_close()
                        for _ in range(self.post_manage_swipe_count):
                            self.post_manage_up_swipe(450)
                        continue
                self.device.click(POST_ADD_ORDER)
                logger.info(f"[岛屿-制造业] 选择产品成功: {self._item_cn(product_name)}")
                self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
                self.device.sleep(0.5)
                self.post_close()
                for _ in range(self.post_manage_swipe_count):
                    self.post_manage_up_swipe(450)

                # 获取生产时间和数量
                self.post_open(post_button)
                image = self.device.screenshot()
                ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                        alphabet='0123456789')
                actual_number = ocr_post_number.ocr(image)
                self._last_actual_number = actual_number
                if requested_quantity is not None:
                    if actual_number <= 0:
                        logger.warning(
                            f"[岛屿-制造业] {self._item_cn(product_name)} 派遣后未读到数量，"
                            f"按未知处理（不按请求值记账）")
                    elif actual_number != requested_quantity:
                        logger.warning(
                            f"[岛屿-制造业] {self._item_cn(product_name)} 请求 "
                            f"{requested_quantity} 件，岗位显示 {actual_number} 件")
                time_work = Duration(ISLAND_WORKING_TIME)
                time_value = time_work.ocr(self.device.image)
                finish_time = current_time() + time_value

                # 设置时间变量
                import re
                match = re.search(r'POST(\d+)', post_id)
                if match:
                    post_num = match.group(1)
                    time_var_name = f'{self.time_prefix}{post_num}'
                    setattr(self, time_var_name, finish_time)

                self.posts[post_id]['status'] = 'working'
                logger.info(f"[岛屿-制造业] 已安排生产：{self._item_cn(product_name)} x{actual_number}")
                self.post_close()
                return product_info

        # 所有产品都无法选择或材料不足
        logger.info("[岛屿-制造业] 所有产品都无法选择或材料不足")
        return None

    def configured_product_list(self, category):
        """按 <产线>.Products 配置的顺序返回该产线的产品列表。

        Args:
            category (str): 制造类别，见 PRODUCT_LINES。

        Returns:
            list[dict] | None: 配置了顺序时按顺序返回已知产品（未知名称记录警告后忽略）；
                未配置时返回 None，调用方沿用固定规则。
        """
        line = next(key for key, value in PRODUCT_LINES.items() if value == category)
        order = parse_product_order(getattr(self.config, f'{line}_Products', ''))
        if not order:
            return None
        items = {item['name']: item for item in self.manufacture[category]['items']}
        unknown = [name for name in order if name not in items]
        if unknown:
            logger.warning(f"[岛屿-制造业] {line}.Products 中的未知产品已忽略: {unknown}")
        return [items[name] for name in order if name in items]

    def schedule_manufacture(self):
        """安排制造业四大门类的生产排期。"""
        self.schedule_wood_processing()

        self.schedule_electronic_processing()

        self.schedule_industrial_production()

        self.schedule_handmade()

    def _schedule_line(self, category, product_list):
        """按产品列表为该类别的空闲岗位排产。"""
        for post_id in self.get_idle_posts_by_category(category):
            product = self.select_product_with_material_check(post_id, product_list)
            if product is not None:
                # Add by MHY, 后续任务缺口要扣除本轮普通排产；未知数量仍保留未知。
                actual = self._last_actual_number
                self.post_items[post_id] = {
                    'status': 'working', 'product': product['name'],
                    'number': actual if actual is not None and actual > 0 else None,
                }

    def schedule_wood_processing(self):
        """安排木料加工生产：按 WoodProcessing.Products 的顺序，未配置时只生产文件柜。"""
        product_list = self.configured_product_list('wood_processing')
        if product_list is None:
            product_list = [item for item in self.manufacture['wood_processing']['items']
                            if item['name'] == 'file_cabinet']
        self._schedule_line('wood_processing', product_list)

    def schedule_electronic_processing(self):
        """安排电子加工生产：按 ElectronicProcessing.Products 的顺序，未配置时只生产净水滤芯。"""
        product_list = self.configured_product_list('electronic_processing')
        if product_list is None:
            product_list = [item for item in self.manufacture['electronic_processing']['items']
                            if item['name'] == 'filter_element']
        self._schedule_line('electronic_processing', product_list)

    def schedule_industrial_production(self):
        """安排工业生产：显式日常排产优先，冬季缺口用剩余岗位补齐。

        无 Products 配置时先派有限任务，再回退铁钉；任务达标或 Done 后不再
        自动按 MAX 继续造餐具。非冬季仍沿用原回退规则。
        """
        product_list = self.configured_product_list('industrial_production')
        if product_list is not None:
            self._schedule_line('industrial_production', product_list)
            # Modify by MHY, 日常订单计入在制后重算，避免抢占日常岗位或重复补任务。
            self.prepare_winter_quota()
            self.dispatch_winter_quota_batches('industrial_production')
            return
        self.dispatch_winter_quota_batches('industrial_production')
        idle_posts = self.get_idle_posts_by_category('industrial_production')
        if not idle_posts:
            return
        items = {item['name']: item for item in self.manufacture['industrial_production']['items']}
        # 检查库存iron_nail
        iron_nail_stock = self.warehouse_counts.get('iron_nail', 0)
        # 铁钉足够时优先餐具是旧的高 PT 回退；冬季任务模式下餐具只由配额补，
        # 否则任务达标/ Done 之后仍会每轮按 MAX 继续造餐具。
        if iron_nail_stock >= 20 and not self.winter_quota_active():
            product_list = [items['cutlery'], items['iron_nail']]
        else:
            product_list = [items['iron_nail']]

        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def schedule_handmade(self):
        """安排手工制品生产：按 Handmade.Products 的顺序，未配置时优先季节限定品、皮靴与皮革。"""
        product_list = self.configured_product_list('handmade')
        if product_list is not None:
            self._schedule_line('handmade', product_list)
            return
        idle_posts = self.get_idle_posts_by_category('handmade')
        if not idle_posts:
            return
        # 检查库存leather
        leather_stock = self.warehouse_counts.get('leather', 0)
        # 构建产品选择列表（按优先级）
        product_list = []
        # 优先生产当前季节的限定手工品（荠菜干、夏季花束等）
        seasonal_names = []
        if hasattr(self, 'season_config') and self.season_config.is_seasonal_enabled:
            seasonal_names = self.season_config.get_seasonal_items('handmade') or []
        for item in self.manufacture['handmade']['items']:
            if item['name'] in seasonal_names:
                product_list.append(item)

        # 如果leather库存>=10，则生产boot
        if leather_stock >= 10:
            boot_item = [item for item in self.manufacture['handmade']['items']
                         if item['name'] == 'boot'][0]
            product_list.append(boot_item)

        # 最后生产leather
        leather_item = [item for item in self.manufacture['handmade']['items']
                        if item['name'] == 'leather'][0]
        product_list.append(leather_item)

        for post_id in idle_posts:
            self.select_product_with_material_check(post_id, product_list)

    def run(self):
        """运行制造业工坊自动化主流程。

        巡检各岗位状态、收取成品、读取原料库存并为各类别空闲岗位分配生产，
        最后计算并推迟调度时间。

        Raises:
            GameBugError: 遇到游戏内部错误需要重启时抛出。
        """
        self.island_error = False
        # 每批生产开始时清空“材料不足”记忆，避免跨批沿用旧库存状态
        self.unavailable_products = set()
        # 在制品与岗位级观测每轮重建：旧数据会把已完成的数量继续算进在制
        self.post_check_meal = {}
        self.post_items = {}
        self.winter_quota_ordered = {}
        self.winter_quota_plan = None
        self._warehouse_scanned = False

        # 第一步：检查岗位状态
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()

        # 滑动以看到岗位
        for _ in range(self.post_manage_swipe_count):
            self.post_manage_up_swipe(450)

        # 检查岗位状态
        time_vars = []
        post_index = 1

        # 按顺序检查所有岗位
        for post_id in self.post_buttons.keys():
            time_var_name = f'{self.time_prefix}{post_index}'
            time_vars.append(time_var_name)
            setattr(self, time_var_name, None)
            self.post_check(post_id, time_var_name)
            post_index += 1


        # 判断是否有需要安排的任务
        idle_posts = self.get_idle_posts()
        if idle_posts:
            self.get_warehouse_counts()
            self.prepare_winter_quota()
            # 如果有空闲岗位，重新进入岗位管理界面安排生产
            logger.info(f"[岛屿-制造业] 有 {len(idle_posts)} 个空闲岗位，开始安排生产")

            # 重新进入岗位管理界面
            self.goto_postmanage()
            self.post_manage_mode(POST_MANAGE_PRODUCTION)
            self.post_close()

            # 滑动以看到岗位
            for _ in range(self.post_manage_swipe_count):
                self.post_manage_up_swipe(450)

            # 安排生产
            self.schedule_manufacture()
        else:
            logger.info("[岛屿-制造业] 没有空闲岗位，跳过生产安排")

        # 设置任务延迟
        finish_times = []
        for var in time_vars:
            time_value = getattr(self, var)
            if time_value is not None:
                finish_times.append(time_value)
        hours_later = current_time() + timedelta(hours=6)
        finish_times.append(hours_later)
        finish_times.sort()
        self.config.task_delay(target=finish_times)

        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    # 以下方法重写以适配基类
    def process_meal_requirements(self, source_products):
        """处理套餐需求。

        制造业无需拆解套餐，直接透传输入需求。

        Args:
            source_products (dict[str, int]): 输入需求。

        Returns:
            dict[str, int]: 原始需求。
        """
        return source_products

    def schedule_production(self):
        """安排生产排期，调用制造业专属调度方法。"""
        self.schedule_manufacture()

    def process_away_cook(self):
        """处理常驻餐品模式，制造业无需常驻配置。"""
        # 制造业有自己的生产规则，不依赖常驻餐品
        self.to_post_products = {}
        logger.info("[岛屿-制造业] 制造业使用内置生产规则，不设置常驻餐品")

    def get_max_producible(self, product, requested_quantity, skip_zero_materials=False):
        """获取产品最大可生产数量。

        制造业生产数量由派遣界面材料检测决定。

        Args:
            product (str): 产品名称。
            requested_quantity (int): 请求数量。
            skip_zero_materials (bool, optional): 是否跳过零材料检查。

        Returns:
            int: 允许生产的数量。
        """
        return requested_quantity

    def check_special_materials(self, product, batch_size):
        """检查特殊材料限制，制造业无特殊材料直接返回原批次数。

        Args:
            product (str): 产品名称。
            batch_size (int): 计划批次数。

        Returns:
            int: 允许生产的批次数。
        """
        return batch_size

    def apply_special_material_constraints(self, requirements):
        """应用特殊材料约束，制造业无特殊限制直接返回。

        Args:
            requirements (dict[str, int]): 原始需求映射。

        Returns:
            dict[str, int]: 调整后需求映射。
        """
        return requirements

    def test(self):
        """测试制造业配置状态。"""
        if self.config.Industrial_Positions > 1:
            logger.info(2)


if __name__ == "__main__":
    az = IslandManufacture('alas', task='Alas')
    az.device.screenshot()
    az.run()
