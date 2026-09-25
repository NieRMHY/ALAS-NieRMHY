"""岛屿店铺基类模块。

为烧烤店、茶馆、餐厅、制造工坊等所有岛屿店铺提供通用的岗位管理与商品生产框架。
包含产品选择、厨师筛选、岗位填充循环、季节性商品处理等核心逻辑，是所有店铺模块的父类。
"""
from module.island.island import *
from collections import Counter
from datetime import timedelta

from module.config.time_source import now as current_time
from module.handler.login import LoginHandler
from module.island.warehouse import *
from module.logger import logger
from module.island.island_season import get_global_season_config

# Add by MHY, 岛屿经济闭环：AutoProfit 感知生产
from module.island.island_autoprofit import get_autoprofit_planner, merge_autoprofit_with_manual


class IslandShopBase(Island, WarehouseOCR):
    _MAX_FILL_LOOP = 10  # while 循环填岗最大迭代次数
    PRODUCT_SELECT_RETRY_LIMIT = 3  # 餐品选择识别失败后，退出重进的最大次数
    POST_PRODUCE_LIMIT = 7  # 餐馆每个岗位单次最多生产数量
    FILL_SPECIAL_FOOD = True  # 子类可关闭余岗的特殊餐品回退

    def __init__(self, config, device=None, task=None):
        # 分别初始化每个父类
        Island.__init__(self, config=config, device=device, task=task)
        WarehouseOCR.__init__(self)  # WarehouseOCR 可能不需要参数

        # 子类必须设置的属性
        self.shop_items = []  # 商品列表
        self.shop_type = ""  # 店铺类型：grill, teahouse, tailor, toolshop, furniture
        self.filter_asset = None  # 仓库筛选资产
        self.post_buttons = {}  # 岗位按钮
        self.time_prefix = "time_meal"  # 时间变量前缀
        self.special_character = False
        self.special_food = None
        # 角色选择配置
        self.chef_config = None

        # 通用属性
        self.name_to_config = {}
        self.posts = {}
        self.post_check_meal = {}  # 岗位生产中的产品
        self.post_products = []  # 有序列表，允许同名餐品出现在多个槽位
        self.warehouse_counts = {}  # 仓库识别到的产品
        self.to_post_products = {}
        self.current_totals = {}
        # 保留线目标 {产品: 断点前槽位最高目标}，
        # 排产时这些产品的仓库库存只能消耗超出自身目标的部分
        self._reserved_targets = {}

        # 特殊材料（子类可覆盖）
        self.special_materials = {}

        # 本轮因无可用角色而跳过生产的餐品（避免严格模式重复尝试）
        self.chef_unavailable_products = set()

        # 套餐组成（子类可覆盖）
        self.meal_compositions = {}

        # 配置前缀（子类可覆盖）
        self.config_meal_prefix = "Island_Meal"
        self.config_number_prefix = "Island_MealNumber"
        self.config_away_cook = "IslandNextTask_AwayCook"
        self.config_post_number = "Island_PostNumber"

        # 滑动配置（子类可覆盖）
        self.post_manage_swipe_count = 1  # 默认滑动1次450

        # Add by MHY, 岛屿经济闭环：AutoProfit 感知生产状态（默认关闭，子类启用）
        self.autoprofit_enabled = False
        self.autoprofit_planner = None
        self.autoprofit_level = 'diamond'
        self.autoprofit_unproducible = set()  # 账号未解锁/研发未完成的商品（持久化学习）
        self.autoprofit_fill_queue = []  # 空岗填充的原料保障队列（本轮优先生产）
        self.manual_products = set()  # 用户手动配置的商品，失败时不自动降级

    # ==================== 季节配置支持 ====================

    def _init_season_config(self):
        """初始化季节配置"""
        self.season_config = get_global_season_config(self.config)
        self.current_season = self.season_config.season
        self.season_name = self.season_config.season_name

        if self.season_config.is_seasonal_enabled:
            logger.info(f"[岛屿] 当前季节: {self.season_name}，季节限定已启用")
        else:
            logger.info("[岛屿] 季节限定未启用")

    def is_seasonal_item_enabled(self, item_name):
        """
        判断指定物品在当前季节是否启用

        如果季节限定未启用（none），则默认所有物品可用。
        如果季节限定启用，则只返回本季节的物品列表。

        Args:
            item_name: 物品名称

        Returns:
            bool
        """
        if not hasattr(self, 'season_config') or self.season_config is None:
            return True
        if not self.season_config.is_seasonal_enabled:
            return True
        # 检查物品是否在当前季节的列表中
        seasonal_items = self.season_config.get_seasonal_items(self.shop_type)
        if item_name in seasonal_items:
            return True
        # 不在当前季节列表中的季节性物品 → 禁用
        # 检查是否是其他季节的限定物品
        for season_key in ['spring', 'summer', 'autumn', 'winter']:
            if season_key == self.season_config.season:
                continue
            from module.island.island_season import SEASONAL_ITEMS
            other_items = SEASONAL_ITEMS.get(season_key, {}).get(self.shop_type, [])
            if item_name in other_items:
                logger.info(f"[岛屿] 物品 [{self._item_cn(item_name)}] 是 {season_key} 的限定品，当前 {self.season_name} 不可用")
                return False
        return True
    def produce_check(self):
        self.device.sleep(0.5)
        image = self.device.screenshot()
        area = (493, 597, 621, 643)
        color = get_color(image, area)
        if color_similar(color, (153, 156, 156), 80):
            return True
        else:
            return False
    def setup_config(self, config_meal_prefix, config_number_prefix,
                     config_away_cook, config_post_number):
        """从配置中读取餐品需求 - 修改为8种餐品"""
        # 设置配置前缀
        self.config_meal_prefix = config_meal_prefix
        self.config_number_prefix = config_number_prefix
        self.config_away_cook = config_away_cook
        self.config_post_number = config_post_number

        # 读取8种餐品需求
        self.post_products = []

        for i in range(1, 9):  # 1到8
            meal_key = f'{self.config_meal_prefix}{i}'
            number_key = f'{self.config_number_prefix}{i}'

            meal_name = getattr(self.config, meal_key, None)
            if meal_name is not None and meal_name != "None":
                meal_number = getattr(self.config, number_key, 0)
                self.post_products.append((meal_name, meal_number))

        # Add by MHY: 记录用户手动配置的商品，AutoProfit 只对自动选品做失败降级
        self.manual_products = {name for name, _ in self.post_products}

    def initialize_shop(self):
        """初始化店铺，子类必须在__init__中调用"""
        self.name_to_config = {item['name']: item for item in self.shop_items}

        # 初始化岗位状态
        for post_id, button in self.post_buttons.items():
            self.posts[post_id] = {'status': 'none', 'button': button}

    # ============ 通用方法 ============
    def post_check(self, post_id, time_var_name):
        """检查岗位状态（通用）"""
        post_button = self.posts[post_id]['button']
        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        image = self.device.screenshot()
        ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                alphabet='0123456789')
        if self.appear(ISLAND_WORK_COMPLETE, offset=1):
            self.posts[post_id]['status'] = 'idle'
            setattr(self, time_var_name, None)
        elif self.appear(ISLAND_WORKING):
            product = self.post_product_check()
            number = ocr_post_number.ocr(image)
            time_work = Duration(ISLAND_WORKING_TIME)
            time_value = time_work.ocr(self.device.image)
            finish_time = current_time() + time_value
            setattr(self, time_var_name, finish_time)
            self.posts[post_id]['status'] = 'working'
            if product is not None:
                if product in self.post_check_meal:
                    self.post_check_meal[product] += number
                else:
                    self.post_check_meal[product] = number
        elif self.appear(ISLAND_POST_SELECT):
            self.posts[post_id]['status'] = 'idle'
            setattr(self, time_var_name, None)
        self.post_get_and_close()
        self.device.sleep(0.5)

    def post_product_check(self):
        """检查岗位生产的产品（通用）"""
        for item in self.shop_items:
            if self.appear(item['post_action']):
                return item['name']
        return None

    def get_warehouse_counts(self):
        """获取仓库数量（通用）"""
        self.warehouse_filter(self.filter_asset)
        image = self.device.screenshot()

        for dish in self.shop_items:
            self.warehouse_counts[dish['name']] = self.ocr_item_quantity(image, dish['template'])
            if self.warehouse_counts[dish['name']]:
                logger.info(f"{self._item_cn(dish['name'])}: {self.warehouse_counts[dish['name']]}")
        return self.warehouse_counts
    def select_special_character(self,product):
        return self.select_character(character_list=self.chef_config)
    def produce_special_food(self):
        pass

    def is_manual_product(self, name):
        """商品是否来自用户手动配置（Meal1-8），手动配置不参与自动降级。"""
        return name in getattr(self, 'manual_products', set())

    def blacklist_autoprofit_product(self, name):
        """把连续选品失败的自动商品记入持久化不可生产名单。"""
        from module.island.island_autoprofit import add_unproducible
        add_unproducible(self.shop_type, name)
        self.autoprofit_unproducible.add(name)
        self.chef_unavailable_products.add(name)

    def release_unproducible_product(self, name):
        """解除禁用：该商品已在选品列表出现（账号已解锁）。"""
        from module.island.island_autoprofit import remove_unproducible
        remove_unproducible(self.shop_type, name)
        self.autoprofit_unproducible.discard(name)

    def probe_unproducible_products(self):
        """
        选品页探测：被禁商品出现在派单列表中说明账号已解锁，自动解除禁用。

        由 Island.select_product 在已截图的循环里调用，无额外截图开销；
        每次最多解除一个，其余留待后续轮次。
        """
        if not self.autoprofit_enabled or not self.autoprofit_unproducible:
            return
        for name in list(self.autoprofit_unproducible):
            item = self.name_to_config.get(name)
            if not item:
                continue
            check = item.get('selection_check') or item.get('selection')
            if check is None:
                continue
            try:
                if self.appear(check, offset=20):
                    self.release_unproducible_product(name)
                    return
            except Exception:
                continue

    def retry_product_selection_from_postmanage(self, post_button, product, failed_product, failed_count):
        """餐品选择失败后退出岗位，重新进入同一岗位走完整派遣流程。

        Returns:
            bool: True 已重进岗位可继续尝试；
                  False 自动选品判定为不可生产（未解锁），本轮跳过该商品。
        """
        if failed_count >= self.PRODUCT_SELECT_RETRY_LIMIT:
            # Add by MHY: AutoProfit 自动选的商品连续选不到（账号未解锁/研发未完成，
            # 派单列表里没有该图标）时，记入持久黑名单并跳过本轮，避免 GameStuckError
            # 触发游戏重启循环；用户手动配置的商品保持原有抛错行为。
            if self.autoprofit_enabled and not self.is_manual_product(failed_product):
                self.blacklist_autoprofit_product(failed_product)
                logger.warning(
                    f"[岛屿-AutoProfit] {self._item_cn(failed_product)} 连续{failed_count}次选品失败，"
                    f"判定为未解锁并跳过"
                )
                return False
            raise GameStuckError(
                f"{self._item_cn(product)}生产选择餐品时连续{failed_count}次未识别到 {self._item_cn(failed_product)}"
            )

        logger.warning(
            f"{self._item_cn(product)}生产选择餐品时未识别到 {self._item_cn(failed_product)}，"
            f"退出岗位后重新进入 ({failed_count}/{self.PRODUCT_SELECT_RETRY_LIMIT})"
        )
        if not self.back_to_postmanage_from_dispatch():
            raise GameStuckError(f"{self._item_cn(product)}生产选择餐品失败后无法返回岗位管理页")

        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_manage_swipe(self.post_manage_swipe_count)
        if not self.post_open(post_button):
            raise GameStuckError(f"{self._item_cn(product)}生产选择餐品失败后无法重新打开岗位")
        self.device.sleep(0.5)
        return True

    def increase_product_selection_failure(self, product_select_failures, failed_product):
        """记录单个餐品的选择失败次数。"""
        failed_count = product_select_failures.get(failed_product, 0) + 1
        product_select_failures[failed_product] = failed_count
        return failed_count

    def post_produce(self, post_id, product, number, time_var_name,product2=None):
        """生产产品（通用）"""
        post_button = self.posts[post_id]['button']
        self.post_close()
        self.post_open(post_button)
        self.device.sleep(0.5)
        time_work = Duration(ISLAND_WORKING_TIME)
        selection = self.name_to_config[product]['selection']
        selection_check = self.name_to_config[product]['selection_check']
        product_select_failures = {}
        for _ in self.loop(timeout=120, skip_first=False):
            if self.appear_then_click(ISLAND_POST_SELECT, offset=1):
                self.device.sleep(0.5)
                continue
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                if self.special_character:
                    selected = self.select_special_character(product)
                    character_filter = "special"
                else:
                    selected = self.select_character(character_list=self.chef_config)
                    character_filter = self.chef_config
                if selected:
                    if not self.confirm_selected_character(f"{self._item_cn(product)}生产派遣"):
                        self.back_to_postmanage_from_dispatch()
                        return 0
                else:
                    logger.warning(f"[岛屿] {self._item_cn(product)}生产派遣无可用角色: {character_filter}")
                    self.chef_unavailable_products.add(product)
                    self.back_to_postmanage_from_dispatch()
                    return 0
                continue
            if self.appear(ISLAND_SELECT_PRODUCT_CHECK, offset=1):
                if self.select_product(selection, selection_check):
                    self.device.sleep(0.5)
                    if self.produce_check():
                        logger.warning(f"[岛屿] 原料不足，无法生产 {self._item_cn(product)}")
                        self.device.sleep(0.5)
                        if product == self.special_food:
                            if product2:
                                selection2 = self.name_to_config[product2]['selection']
                                selection_check2 = self.name_to_config[product2]['selection_check']
                                if not self.select_product(selection2, selection_check2):
                                    failed_count = self.increase_product_selection_failure(
                                        product_select_failures, product2
                                    )
                                    if not self.retry_product_selection_from_postmanage(
                                            post_button, product, product2, failed_count):
                                        self.back_to_postmanage_from_dispatch()
                                        return 0
                                    continue
                                self.device.sleep(0.5)
                                if self.produce_check():
                                    logger.warning(f"[岛屿] 原料不足，无法生产 {self._item_cn(product2)}")
                                    self.device.click(ISLAND_BACK)
                                    self.device.sleep(0.5)
                                    return 0  # 返回0表示原料不足
                                else:
                                    self.post_add_one(number - 1)
                                    self.device.sleep(0.5)
                                    self.device.click(POST_ADD_ORDER)
                                    self.device.sleep(0.5)
                                    break
                            else:
                                self.device.click(ISLAND_BACK)
                                self.device.sleep(0.5)
                                return 0  # 返回0表示原料不足

                        else:
                            self.device.click(ISLAND_BACK)
                            self.post_close()
                            self.post_manage_swipe(self.post_manage_swipe_count)
                            self.device.sleep(0.5)
                            return 0  # 返回0表示原料不足
                    else:
                        self.post_add_one(number - 1)
                        self.device.sleep(0.5)
                        self.device.click(POST_ADD_ORDER)
                        self.device.sleep(0.5)
                        break
                else:
                    failed_count = self.increase_product_selection_failure(
                        product_select_failures, product
                    )
                    if not self.retry_product_selection_from_postmanage(
                            post_button, product, product, failed_count):
                        self.back_to_postmanage_from_dispatch()
                        return 0
                continue
        else:
            raise GameStuckError(f"{self._item_cn(product)}生产派遣流程超时")
        self.wait_until_appear(ISLAND_POSTMANAGE_CHECK)
        self.device.sleep(0.5)
        self.post_manage_swipe(self.post_manage_swipe_count)
        logger.info(post_button)
        self.post_open(post_button)
        self.device.sleep(0.5)
        image = self.device.screenshot()
        ocr_post_number = Digit(OCR_POST_NUMBER, letter=(57, 58, 60), threshold=100,
                                alphabet='0123456789')
        actual_number = ocr_post_number.ocr(image)
        time_value = time_work.ocr(self.device.image)
        finish_time = current_time() + time_value
        setattr(self, time_var_name, finish_time)
        self.posts[post_id]['status'] = 'working'
        # 扣除前置材料（子类可覆盖）
        self.deduct_materials(product, actual_number)
        logger.info(f"[岛屿] 已安排生产：{self._item_cn(product)} x{actual_number}")
        self.post_close()
        # 返回实际生产数量
        return actual_number

    def deduct_materials(self, product, number):
        """扣除前置材料（包括套餐原材料）"""
        # 扣除套餐原材料
        if product in self.meal_compositions:
            composition = self.meal_compositions[product]
            quantity_per = composition.get('quantity_per', 1)
            for material in composition['required']:
                material_needed = number * quantity_per
                if material in self.warehouse_counts:
                    self.warehouse_counts[material] -= material_needed
                    logger.info(f"[岛屿] 扣除原材料：{self._item_cn(material)} -{material_needed} (用于制作 {self._item_cn(product)})")

    def get_idle_posts(self):
        """获取空闲的岗位ID列表（通用）"""
        return [post_id for post_id, post_info in self.posts.items()
                if post_info['status'] == 'idle']

    # ============ 核心逻辑 ============

    def _schedule_and_track(self, produced_pass):
        """排产并将本轮产出记录到 produced_pass。
        produced_pass 跨多次排产累加，让后续 _compute_base_demands 的 current_totals
        能看到刚生产但未入库的量（不修改 warehouse_counts——仓库里确实还没有）。
        """
        if not self.to_post_products:
            return
        to_post_snapshot = dict(self.to_post_products)
        self.schedule_production()
        for name in to_post_snapshot:
            remaining = self.to_post_products.get(name, 0)
            produced_qty = to_post_snapshot[name] - remaining
            if produced_qty > 0:
                produced_pass[name] = produced_pass.get(name, 0) + produced_qty

    def _rebuild_current_totals(self, produced_pass):
        """重建当前总库存：仓库 + 在制品 + 本轮已下单未收获。

        必须使用"当前"仓库账（套餐下单时 deduct_materials 已实时扣减原料），
        而不是开跑前的库存快照，否则同一轮内被套餐消耗的原料
        会在下一轮被误判为仍然可用，导致原料槽位目标漏排。
        """
        totals = {}
        all_product_names = set(name for name, _ in self.post_products)
        for item in all_product_names | set(self.post_check_meal.keys()) | set(
                self.warehouse_counts.keys()):
            totals[item] = self.post_check_meal.get(item, 0) + self.warehouse_counts.get(item, 0)
        for name, qty in produced_pass.items():
            totals[name] = totals.get(name, 0) + qty
        return totals

    def _compute_base_demands(self, check_materials=False, force_skip=None):
        """计算基础需求：严格按槽位顺序处理，找到第一个有缺口的槽位
        即停止，后续槽位本轮不处理。

        保留线：取本轮已迭代槽位中各产品的最高目标（无缺口时覆盖全部
        槽位，全部达标时保留线取最大目标），扣除后 current_totals 为
        超额库存，可作为原料被后续槽位消费。

        Args:
            check_materials: False（默认）需求计算，原料为0不阻断，留给
                             process_meal_requirements 分解。
                             True 排产失败后使用，严格检查零库存来跳过缺口。
            force_skip: 强制跳过的产品名集合。排产多次失败（非原料原因如
                        角色被占）时使用，让本轮不再停留在这个缺口上。
        """
        # ============ 基础需求计算 ============
        logger.info("[岛屿] 阶段：基础需求" + ("（严格模式）" if check_materials else ""))

        self.to_post_products = {}
        virtual_totals = dict(self.current_totals)
        force_skip = force_skip or set()

        # 遍历槽位，找到第一个有缺口且可生产的就只处理它
        break_idx = len(self.post_products)
        for idx, (name, target) in enumerate(self.post_products):
            current = virtual_totals.get(name, 0)
            if current < target:
                if name in force_skip:
                    logger.info(f"[岛屿] 槽位{idx + 1} {self._item_cn(name)} 本轮已尝试失败，强制跳过")
                    continue
                if name in self.chef_unavailable_products:
                    logger.info(f"[岛屿] 槽位{idx + 1} {self._item_cn(name)} 无可用角色，本轮跳过")
                    continue
                deficit = target - current
                # check_materials=True 时严格检查零库存，用于跳过无法生产的缺口
                if self.get_max_producible(
                        name, min(self.POST_PRODUCE_LIMIT, deficit),
                        skip_zero_materials=not check_materials) <= 0:
                    logger.info(f"[岛屿] 槽位{idx + 1} {self._item_cn(name)} 材料完全不足，本轮跳过")
                    continue
                self.to_post_products[name] = deficit
                virtual_totals[name] = target
                break_idx = idx
                break

        # 保留线：只取已迭代槽位（含 break 点）中的最高目标
        max_targets = {}
        for name, target in self.post_products[:break_idx + 1]:
            max_targets[name] = max(max_targets.get(name, 0), target)
        # 记录保留线目标，供排产阶段限制套餐对其库存的消耗
        self._reserved_targets = dict(max_targets)
        for name, max_target in max_targets.items():
            current = self.current_totals.get(name, 0)
            if current < max_target:
                self.current_totals[name] = 0
            else:
                self.current_totals[name] = current - max_target

    def get_priority_production(self):
        """返回基础需求之前安排的产品及数量，由店铺声明季节规则。"""
        return {}

    # ==================== AutoProfit 感知生产（Add by MHY, 岛屿经济闭环） ====================

    def setup_autoprofit(self, level_config_key=None):
        """
        启用 AutoProfit 感知生产：按经济数据库利润排序动态生成 post_products。

        手动槽位（Meal1-8）仍作为兜底参与目标合并（同名取最大值），
        未开启或配置缺失时保持原有行为不变。

        Args:
            level_config_key: 店铺等级的配置键名；None 用默认 'diamond'
        """
        from module.island.island_economy import SHOP_LEVELS
        raw_level = 'diamond'
        if level_config_key:
            raw_level = getattr(self.config, level_config_key, 'diamond') or 'diamond'
        if raw_level not in SHOP_LEVELS:
            logger.warning(f"[岛屿-AutoProfit] 未知店铺等级 {raw_level}，回退钻石档")
            raw_level = 'diamond'
        self.autoprofit_level = raw_level
        self.autoprofit_planner = get_autoprofit_planner(
            self.shop_type, shop_level=raw_level)
        self.autoprofit_enabled = self.autoprofit_planner is not None
        if self.autoprofit_enabled:
            # 载入历史学到的不可生产商品（未解锁），排产时排除
            from module.island.island_autoprofit import load_unproducible
            self.autoprofit_unproducible = load_unproducible(self.shop_type)
            if self.autoprofit_unproducible:
                logger.info(f"[岛屿-AutoProfit] 已排除不可生产商品: "
                            f"{sorted(self.autoprofit_unproducible)}")
        if self.autoprofit_enabled:
            logger.info(
                f"[岛屿-AutoProfit] {self.shop_type} 已启用 "
                f"（等级: {raw_level}, 容量: {self.autoprofit_planner.capacity}）")

    def economy_top_product(self):
        """返回本店利润/分钟最高且可生产的商品名（AutoProfit 空岗填充用）。"""
        if not self.autoprofit_enabled or self.autoprofit_planner is None:
            return None
        season = self.current_season if hasattr(self, 'current_season') else None
        items = self.autoprofit_planner.economy.recommend_products(
            self.shop_type, season=season, top=1,
            exclude=set(self.autoprofit_unproducible))
        if not items:
            return None
        name = items[0]['name']
        return name if name in self.name_to_config else None

    def refresh_autoprofit_targets(self):
        """
        感知生产入口：读取仓库与在制品，重建 post_products。

        在 run() 的 get_warehouse_counts 之后调用：AutoProfit 计划与
        手动槽位目标合并（同名取最大），保证手动配置的保底线不被压低。
        """
        if not self.autoprofit_enabled or self.autoprofit_planner is None:
            return
        manual_targets = dict(self.post_products)
        # available 传本店实际有按钮资源的商品，过滤经济库中代码未实现的条目
        # （如 grill 的 lemon_shrimp），否则排产到它会在 post_produce 里 KeyError
        try:
            auto_plan = self.autoprofit_planner.build_plan(
                warehouse_counts=self.warehouse_counts,
                in_production=self.post_check_meal,
                season=self.current_season if hasattr(self, 'current_season') else None,
                available=set(self.name_to_config),
                exclude=set(self.autoprofit_unproducible),
            )
            merged = merge_autoprofit_with_manual(auto_plan, manual_targets)
            if merged:
                self.post_products = merged
                logger.info(f"[岛屿-AutoProfit] 合并后槽位目标: {self._products_cn(self.post_products)}")
        except Exception:
            # Add by MHY: AutoProfit 是可选增强层，任何异常都只回退手动模式，
            # 不能让规划错误升级成未处理异常→游戏重启→死循环（真机事故教训）
            self.autoprofit_enabled = False
            logger.exception("[岛屿-AutoProfit] 规划异常，本轮回退手动模式")
            return

    def run(self):
        self.island_error = False
        self.chef_unavailable_products.clear()
        self.unavailable_characters.clear()
        # 在制品和保留线每轮重新建立，不能累加同一实例上轮的识别结果。
        self.post_check_meal.clear()
        self._reserved_targets.clear()
        self.goto_postmanage()
        self.post_manage_mode(POST_MANAGE_PRODUCTION)
        self.post_close()
        self.post_manage_swipe(self.post_manage_swipe_count)

        # 检查岗位状态
        post_count = getattr(self.config, self.config_post_number, 2)
        time_vars = []
        for i in range(post_count):
            time_var_name = f'{self.time_prefix}{i + 1}'
            time_vars.append(time_var_name)
            setattr(self, time_var_name, None)
            post_id = f'ISLAND_{self.shop_type.upper()}_POST{i + 1}'
            self.post_check(post_id, time_var_name)

        # 获取空闲岗位
        idle_posts = self.get_idle_posts()

        if idle_posts:
            self.get_warehouse_counts()
            self.goto_postmanage()
            self.post_manage_mode(POST_MANAGE_PRODUCTION)
            self.post_close()
            self.post_manage_swipe(self.post_manage_swipe_count)

            # Add by MHY, 岛屿经济闭环：AutoProfit 按当前库存重建生产目标
            self.refresh_autoprofit_targets()

            # 计算当前总库存
            self.current_totals = self._rebuild_current_totals({})

            # ============ 调试信息 ============
            logger.info(f"[岛屿] === 调试信息 ===")
            logger.info(f"[岛屿] 仓库库存: {self._inv_cn(self.warehouse_counts)}")
            logger.info(f"[岛屿] 生产中库存: {self._inv_cn(self.post_check_meal)}")
            logger.info(f"[岛屿] 当前总库存: {self._inv_cn(self.current_totals)}")
            logger.info(f"[岛屿] 基础需求配置（共{len(self.post_products)}个槽位）: {self._products_cn(self.post_products)}")
            logger.info("===============")

            self._compute_base_demands()

            logger.info(f"[岛屿] 待完成备餐: {self._inv_cn(self.to_post_products)}")
            logger.info(f"[岛屿] 当前剩余库存: {self._inv_cn(self.current_totals)}")
            # ============ 处理套餐分解 ============
            if self.to_post_products:
                self.to_post_products = self.process_meal_requirements(self.to_post_products)
                logger.info(f"[岛屿] 基础需求生产计划: {self._inv_cn(self.to_post_products)}")

            # ============ 安排基础需求生产（循环直到无空岗或无缺口） ============
            _produced_pass = {}  # 本次 run() 调用中已生产的累计
            _force_skip_run = set()  # 排产多次无法生产的缺口（非原料原因），本轮强制跳过
            _loop_count = 0

            # 季节优先排产也记入本轮在制品；基础需求必须按扣料后的库存重算。
            priority_products = self.get_priority_production()
            if priority_products:
                self.to_post_products = priority_products
                logger.info(f"[岛屿] 季节优先生产计划: {self._inv_cn(priority_products)}")
                self._schedule_and_track(_produced_pass)
                self.current_totals = self._rebuild_current_totals(_produced_pass)
                self._compute_base_demands()
                if self.to_post_products:
                    self.to_post_products = self.process_meal_requirements(self.to_post_products)

            self._schedule_and_track(_produced_pass)

            while self.get_idle_posts():
                _loop_count += 1
                if _loop_count > self._MAX_FILL_LOOP:
                    logger.warning(f"[岛屿] [循环] 已达最大迭代次数 {self._MAX_FILL_LOOP}，强制退出")
                    break
                self.current_totals = self._rebuild_current_totals(_produced_pass)

                self._compute_base_demands(force_skip=_force_skip_run)
                if not self.to_post_products:
                    logger.info("[岛屿] 所有槽位需求已满足")
                    break

                self.to_post_products = self.process_meal_requirements(self.to_post_products)
                logger.info(f"[岛屿] 基础需求生产计划: {self._inv_cn(self.to_post_products)}")

                prev_pass_total = sum(_produced_pass.values())
                self._schedule_and_track(_produced_pass)

                if sum(_produced_pass.values()) == prev_pass_total and self.to_post_products:
                    # 先切严格模式（绕"原料真没有"的坎儿）
                    logger.info("[岛屿] [循环] 当前缺口排产失败，切换严格模式扫描")
                    self.to_post_products = {}
                    self.current_totals = self._rebuild_current_totals(_produced_pass)
                    # 严格模式必须传入已有的 force_skip 集合；否则之前已被标记
                    # 卡住的产品（如 seafood_rice）会被再次扫描、再次 schedule，
                    # 造成 UI 层无效点击。
                    self._compute_base_demands(check_materials=True, force_skip=_force_skip_run)
                    if not self.to_post_products:
                        break
                    self.to_post_products = self.process_meal_requirements(self.to_post_products)
                    logger.info(f"[岛屿] 基础需求生产计划（严格模式）: {self._inv_cn(self.to_post_products)}")

                    strict_prev_total = sum(_produced_pass.values())
                    self._schedule_and_track(_produced_pass)

                    if sum(_produced_pass.values()) == strict_prev_total and self.to_post_products:
                        # 严格模式也无产出 → 非原料原因（角色被占等），强制跳过
                        stuck_now = set(self.to_post_products.keys())
                        logger.info(f"[岛屿] [循环] 严格模式也无产出，强制跳过: {stuck_now}")
                        _force_skip_run.update(stuck_now)
                        self.to_post_products = {}
                    continue

            # ============ 检查是否还有空闲岗位，安排特殊餐品或常驻餐品 ============
            # 重新检查空闲岗位（因为可能部分岗位被基础需求占用）
            idle_posts_after_basic = self.get_idle_posts()

            # 获取特殊餐品和常驻餐品配置
            special_food = self.special_food if self.FILL_SPECIAL_FOOD else None
            away_cook = getattr(self.config, self.config_away_cook, None)

            # Add by MHY, 岛屿经济闭环：AutoProfit 开启且未配置常驻餐品时，
            # 空闲岗位自动填本店利润/分钟最高的商品（岗位不闲置，持续赚金币）。
            # 用户手动配置的 AwayCook 优先级更高，不覆盖。
            autoprofit_filled_away_cook = False
            if (self.autoprofit_enabled and idle_posts_after_basic
                    and (not away_cook or away_cook == 'None')):
                # 异常保护：AutoProfit 异常只回退手动模式，不升级为游戏重启
                try:
                    top = self.economy_top_product()
                except Exception:
                    top = None
                    logger.exception("[岛屿-AutoProfit] 选品异常，本轮回退手动模式")
                    self.autoprofit_enabled = False
                if top:
                    away_cook = top
                    autoprofit_filled_away_cook = True
                    logger.info(f"[岛屿-AutoProfit] 空岗自动填充常驻餐品: {self._item_cn(top)}")

            # Add by MHY, 岛屿经济闭环：填充商品的原料保障。
            # 填充商品（如醒神套餐）高于目标库存时不会进基础需求，其原料
            # （冰咖啡/香橙派）可能为 0 → post_produce 返回 0 → 岗位一直空着。
            # 这里先算出缺失的可自产原料，本轮优先生产它们，下轮再产成品。
            self.autoprofit_fill_queue = []
            self.autoprofit_fill_fallbacks = []
            if (self.autoprofit_enabled and idle_posts_after_basic
                    and autoprofit_filled_away_cook
                    and away_cook in self.name_to_config):
                try:
                    support = self.autoprofit_planner.support_plan(
                        away_cook, self.warehouse_counts, self.post_check_meal,
                        exclude=set(self.autoprofit_unproducible),
                        available=set(self.name_to_config))
                except Exception:
                    support = []
                    logger.exception("[岛屿-AutoProfit] 原料保障规划异常，跳过填充")
                # 安全网：只保留本店有按钮资源的商品，防止 KeyError 死循环
                support = [(n, q) for n, q in support if n in self.name_to_config]
                if support:
                    self.autoprofit_fill_queue = [n for n, _ in support]
                    logger.info(
                        f"[岛屿-AutoProfit] 填充商品 {self._item_cn(away_cook)} 缺原料，"
                        f"本轮优先生产: {[self._item_cn(n) for n in self.autoprofit_fill_queue]}")
                # 备选商品：队列耗尽后主商品仍缺料时，用其他可生产的高利润商品填岗，
                # 避免第二个岗位空着（真机：简餐 POST2 闲置）
                try:
                    fallback_items = self.autoprofit_planner.economy.recommend_products(
                        self.shop_type,
                        season=self.current_season if hasattr(self, 'current_season') else None,
                        top=6, exclude=set(self.autoprofit_unproducible))
                except Exception:
                    fallback_items = []
                    logger.exception("[岛屿-AutoProfit] 备选商品查询异常，跳过")
                for item in fallback_items:
                    name = item['name']
                    if (name in self.name_to_config and name != away_cook
                            and name not in self.autoprofit_fill_queue):
                        self.autoprofit_fill_fallbacks.append(name)

            # 检查特殊餐品是否为有效值（不为None且不为"None"）
            has_special_food = (special_food and special_food != "None" and
                                special_food in self.name_to_config)

            # 检查常驻餐品是否为有效值（不为None且不为"None"）
            has_away_cook = (away_cook and away_cook != "None" and
                             away_cook in self.name_to_config)

            if idle_posts_after_basic and (has_special_food or has_away_cook):
                logger.info(f"[岛屿] 基础需求完成后，还有 {len(idle_posts_after_basic)} 个空闲岗位")

                # 根据不同情况安排生产
                for post_id in idle_posts_after_basic:
                    post_num = post_id[-1]
                    time_var_name = f'{self.time_prefix}{post_num}'

                    if has_special_food and has_away_cook:
                        # 情况1：既有特殊餐品又有常驻餐品
                        logger.info(f"[岛屿] 同时有特殊餐品 {self._item_cn(special_food)} 和常驻餐品 {self._item_cn(away_cook)}")
                        logger.info(f"[岛屿] 优先尝试生产特殊餐品，如果原料不足则生产常驻餐品")

                        # 尝试生产特殊餐品（如果原料不足会自动尝试常驻餐品）
                        result = self.post_produce(
                            post_id,
                            product=special_food,
                            number=self.POST_PRODUCE_LIMIT,
                            time_var_name=time_var_name,
                            product2=away_cook
                        )

                        if result == 0:
                            # 特殊餐品和常驻餐品都原料不足
                            logger.info(f"[岛屿] 特殊餐品 {self._item_cn(special_food)} 和常驻餐品 {self._item_cn(away_cook)} 都原料不足，保持岗位空闲")
                            break
                        else:
                            logger.info(f"[岛屿] 已为岗位 {post_id} 安排生产")

                    elif has_special_food and not has_away_cook:
                        # 情况2：只有特殊餐品，没有常驻餐品
                        logger.info(f"[岛屿] 只有特殊餐品 {self._item_cn(special_food)}，没有常驻餐品")

                        result = self.post_produce(
                            post_id,
                            product=special_food,
                            number=self.POST_PRODUCE_LIMIT,
                            time_var_name=time_var_name
                        )

                        if result == 0:
                            # 特殊餐品原料不足
                            logger.info(f"[岛屿] 特殊餐品 {self._item_cn(special_food)} 原料不足，保持岗位空闲")
                            break
                        else:
                            logger.info(f"[岛屿] 已为岗位 {post_id} 安排生产特殊餐品")

                    elif not has_special_food and has_away_cook:
                        # 情况3：只有常驻餐品，没有特殊餐品
                        # Add by MHY: AutoProfit 原料保障队列优先（缺什么原料先造什么）
                        fill_product = away_cook
                        if self.autoprofit_fill_queue:
                            fill_product = self.autoprofit_fill_queue.pop(0)
                            logger.info(
                                f"[岛屿-AutoProfit] 岗位 {post_id} 优先生产缺失原料 "
                                f"{self._item_cn(fill_product)}")
                        elif (self.autoprofit_fill_fallbacks
                              and self.get_max_producible(away_cook, 1) <= 0):
                            # 主商品原料不足：改用备选的可生产商品填岗，避免岗位空闲
                            while self.autoprofit_fill_fallbacks:
                                cand = self.autoprofit_fill_fallbacks.pop(0)
                                if self.get_max_producible(cand, 1) > 0:
                                    fill_product = cand
                                    logger.info(
                                        f"[岛屿-AutoProfit] 岗位 {post_id} 改产可生产商品 "
                                        f"{self._item_cn(cand)}")
                                    break
                        else:
                            logger.info(f"[岛屿] 只有常驻餐品 {self._item_cn(away_cook)}，没有特殊餐品")

                        # 检查材料限制
                        batch_size = self.POST_PRODUCE_LIMIT
                        batch_size = self.get_max_producible(fill_product, batch_size)

                        if batch_size > 0:
                            result = self.post_produce(
                                post_id,
                                product=fill_product,
                                number=batch_size,
                                time_var_name=time_var_name
                            )

                            if result == 0:
                                logger.info(f"[岛屿] {self._item_cn(fill_product)} 原料不足，保持岗位空闲")
                                break
                            else:
                                logger.info(f"[岛屿] 已为岗位 {post_id} 安排 {self._item_cn(fill_product)} x{batch_size}")
                        else:
                            logger.info(f"[岛屿] 生产 {self._item_cn(fill_product)} 的材料不足，跳过岗位 {post_id}")
                            break

                    else:
                        # 情况4：既没有特殊餐品也没有常驻餐品
                        logger.info("[岛屿] 未设置特殊餐品或常驻餐品，保持空闲")
                        break  # 退出循环，不再处理其他空闲岗位

            elif idle_posts_after_basic:
                # 有空闲岗位但没有设置特殊餐品或常驻餐品
                logger.info(f"[岛屿] 有 {len(idle_posts_after_basic)} 个空闲岗位，但未设置特殊餐品或常驻餐品，保持空闲")

        # ============ 设置任务延迟 ============
        finish_times = []
        for var in time_vars:
            time_value = getattr(self, var)
            if time_value is not None:
                finish_times.append(time_value)
        # Modify by MHY, 岛屿经济闭环：AutoProfit 开启时兜底延时从 6h 缩短到 2h。
        # 原因：生产目标达成后任务长眠 6h，但经营端在持续售卖消耗库存，
        # 下午库存被卖空却无人补产。2h 兜底让"售空→补产"链路闭环；
        # 岗位在产时 OCR 完成时间（约70分钟/批）早于兜底，不受影响。
        fallback_hours = 2 if self.autoprofit_enabled else 6
        hours_later = current_time() + timedelta(hours=fallback_hours)
        finish_times.append(hours_later)
        finish_times.sort()
        self.config.task_delay(target=finish_times)
        if self.island_error:
            from module.exception import GameBugError
            raise GameBugError("检测到岛屿ERROR1，需要重启")

    def process_meal_requirements(self, source_products):
        """处理套餐需求（修正版）"""
        logger.info(f"[岛屿] === 进入process_meal_requirements ===")
        logger.info(f"[岛屿] 传入的需求: {self._inv_cn(source_products)}")

        result = {}

        # 1. 将需求分为套餐需求和基础餐品需求
        meal_demands = {}
        base_demands = {}

        for product, quantity in source_products.items():
            if quantity <= 0:
                continue
            if product in self.meal_compositions:
                meal_demands[product] = quantity
                logger.info(f"[岛屿]   识别为套餐: {self._item_cn(product)} x{quantity}")
            else:
                base_demands[product] = quantity
                logger.info(f"[岛屿]   识别为基础餐品: {self._item_cn(product)} x{quantity}")

        logger.info(f"[岛屿] 套餐需求: {self._inv_cn(meal_demands)}")
        logger.info(f"[岛屿] 基础需求: {self._inv_cn(base_demands)}")

        # 2. 处理套餐需求 - 直接加入结果（套餐可以直接生产）
        # 注意：这里传入的已经是净需求，不需要再扣除库存
        for meal, meal_quantity in meal_demands.items():
            if meal_quantity > 0:
                result[meal] = meal_quantity
                logger.info(f"[岛屿]   套餐直接生产: {self._item_cn(meal)} x{meal_quantity}")

        # 3. 处理基础需求（这些可能是套餐的原材料）
        material_needs = {}

        # 计算所有套餐需要的原材料总量
        for meal, meal_quantity in meal_demands.items():
            if meal_quantity > 0 and meal in self.meal_compositions:
                composition = self.meal_compositions[meal]
                for material in composition['required']:
                    needed = meal_quantity * composition.get('quantity_per', 1)
                    material_needs[material] = material_needs.get(material, 0) + needed
                    logger.info(f"[岛屿]   套餐 {self._item_cn(meal)} 需要原材料: {self._item_cn(material)} x{needed}")

        logger.info(f"[岛屿] 原材料总需求: {self._inv_cn(material_needs)}")

        # 4. 处理基础需求，并考虑原材料需求
        for base_product, base_quantity in base_demands.items():
            logger.info(f"[岛屿]   处理基础餐品 {self._item_cn(base_product)}: 基础需求={base_quantity}")

            # 总需求 = 基础需求（已经是净需求） + 套餐原材料需求
            total_needed = base_quantity

            # 如果这个基础餐品也是套餐的原材料，需要加上原材料需求
            if base_product in material_needs:
                # 注意：原材料需求需要扣除库存（因为之前没扣过）
                raw_material_needed = material_needs[base_product]

                # 检查原材料库存
                current_stock = self.current_totals.get(base_product, 0)
                logger.info(f"[岛屿]     原材料需求: +{raw_material_needed}, 当前库存: {current_stock}")

                # 计算原材料净需求
                net_raw_needed = max(0, raw_material_needed - current_stock)
                total_needed += net_raw_needed

                logger.info(f"[岛屿]     原材料净需求: {net_raw_needed}, 总需求: {total_needed}")

                # 从material_needs中移除，避免重复计算
                del material_needs[base_product]
            else:
                # 不是原材料，直接使用基础需求
                logger.info(f"[岛屿]     总需求: {total_needed}")

            if total_needed > 0:
                result[base_product] = total_needed
                logger.info(f"[岛屿]     添加到生产计划: {self._item_cn(base_product)} x{total_needed}")
            else:
                logger.info(f"[岛屿]     不需要生产")

        # 5. 处理剩余的原材料需求（这些基础餐品不在基础需求列表中）
        for material, material_quantity in material_needs.items():
            logger.info(f"[岛屿]   处理剩余原材料 {self._item_cn(material)}: 需求={material_quantity}")

            current_stock = self.current_totals.get(material, 0)
            logger.info(f"[岛屿]     当前总库存: {current_stock}")

            net_needed = max(0, material_quantity - current_stock)
            if net_needed > 0:
                result[material] = net_needed
                logger.info(f"[岛屿]     添加到生产计划: {self._item_cn(material)} x{net_needed}")
            else:
                logger.info(f"[岛屿]     库存充足，不需要生产")

        logger.info(f"[岛屿] 无特殊材料限制下的生产计划: {self._inv_cn(result)}")
        # 6. 考虑特殊材料限制
        result = self.apply_special_material_constraints(result)

        logger.info(f"[岛屿] 最终生产计划: {self._inv_cn(result)}")
        logger.info(f"[岛屿] === 离开process_meal_requirements ===")

        return result

    def _get_usable_stock(self, material, material_stock):
        """获取套餐原料的可用库存。

        保留线内产品（_reserved_targets）只能消耗仓库库存中超出自身
        目标的部分，避免套餐消耗其尚未达标的保底库存；其余材料直接用
        仓库库存。在产数量不计入可用量（做套餐查原料时在产不算）。

        Args:
            material: 原料名称
            material_stock: 仓库实际库存

        Returns:
            int: 可被套餐消耗的库存量
        """
        if material in self._reserved_targets:
            return max(0, material_stock - self._reserved_targets[material])
        return material_stock

    def get_max_producible(self, product, requested_quantity, skip_zero_materials=False):
        """获取最大可生产数量。

        Args:
            product: 产品名称
            requested_quantity: 请求生产数量
            skip_zero_materials: 需求计算阶段为 True，原料库存为 0 时不阻断套餐，
                                 交给 process_meal_requirements 分解需求。
                                 排产阶段为 False，严格检查避免游戏层拒绝导致 stalled。
        """
        max_producible = requested_quantity
        logger.info(f"[岛屿] 检查 {self._item_cn(product)} 的最大可生产数量，需求: {requested_quantity}")

        # 1. 如果是套餐，检查原材料库存
        if product in self.meal_compositions:
            composition = self.meal_compositions[product]
            for material in composition['required']:
                # 使用仓库实际库存（生产会消耗仓库库存）
                material_stock = self.warehouse_counts.get(material, 0)
                quantity_per = composition.get('quantity_per', 1)
                if quantity_per == 0:
                    continue
                # 保留线内的产品只能消耗"仓库超额库存"（见 _get_usable_stock），
                # 否则套餐会在前置项目因材料不足被跳过时，把其本就不够的
                # 保底库存吃掉。
                usable_stock = self._get_usable_stock(material, material_stock)
                max_by_material = usable_stock // quantity_per
                if max_by_material <= 0:
                    if skip_zero_materials and material_stock == 0:
                        # 需求计算阶段且真零库存：不阻断，留给 process_meal_requirements 分解
                        logger.info(f"[岛屿]   {self._item_cn(product)} 原材料 {self._item_cn(material)} 库存为 0，需求计算阶段跳过此原料限制")
                        continue
                    else:
                        # 排产阶段 或 有但不满足一批：严格处理
                        if material in self._reserved_targets:
                            logger.info(f"[岛屿]   {self._item_cn(product)} 原材料 {self._item_cn(material)} 无超额库存（仓库未超出目标 {self._reserved_targets[material]}），暂不消耗其保底库存")
                        else:
                            logger.info(f"[岛屿]   {self._item_cn(product)} 缺少原材料: {self._item_cn(material)} (库存: {material_stock})")
                        return 0
                max_producible = min(max_producible, max_by_material)
                logger.info(f"[岛屿]   {self._item_cn(product)} 原材料 {self._item_cn(material)}: 库存 {material_stock}，可用 {usable_stock}，每个需要 {quantity_per}，最大生产 {max_by_material}")

        # 2. 检查岗位数量限制
        max_producible = min(max_producible, self.POST_PRODUCE_LIMIT)
        logger.info(f"[岛屿] 岗位限制: 最多生产{self.POST_PRODUCE_LIMIT}个，当前限制后: {max_producible}")

        # 3. 检查特殊材料（被子类覆盖）
        max_producible = self.check_special_materials(product, max_producible)
        logger.info(f"[岛屿] 特殊材料检查后: {max_producible}")

        return max_producible

    def apply_special_material_constraints(self, requirements):
        """应用特殊材料限制（需求阶段）。子类可覆盖此方法。

        Args:
            requirements: 字典，{产品名: 需求数量}

        Returns:
            调整后的需求字典
        """
        return requirements

    def process_away_cook(self):
        """处理常驻餐品"""
        away_cook = getattr(self.config, self.config_away_cook, None)

        # 检查 away_cook 是否有效
        if away_cook and away_cook != "None" and away_cook in self.name_to_config:
            self.to_post_products = {away_cook: 9999}
            logger.info(f"[岛屿] 常驻餐品模式：生产 {self._item_cn(away_cook)}")
        else:
            self.to_post_products = {}
            if away_cook is None or away_cook == "None":
                logger.info("[岛屿] 未设置常驻餐品，保持空闲")
            elif away_cook not in self.name_to_config:
                logger.info(f"[岛屿] 常驻餐品 '{self._item_cn(away_cook)}' 不在商品列表中，保持空闲")

    def schedule_production(self):
        """安排生产，利用所有空闲岗位"""
        if not self.to_post_products:
            logger.info("[岛屿] 没有需要生产的餐品")
            return

        # 获取空闲岗位
        idle_posts = self.get_idle_posts()
        if not idle_posts:
            logger.info("[岛屿] 没有空闲的岗位")
            return

        # 检查是否为常驻餐品模式（无限数量生产）
        is_away_cook_mode = False
        away_cook_product = None
        for product, quantity in self.to_post_products.items():
            if quantity == 9999:  # 常驻餐品模式的标识
                is_away_cook_mode = True
                away_cook_product = product
                break

        if is_away_cook_mode:
            logger.info(f"[岛屿] 常驻餐品模式：为所有空闲岗位安排生产 {self._item_cn(away_cook_product)}")
            # 为每个空闲岗位安排生产
            for post_id in idle_posts:
                # 检查材料限制
                batch_size = self.POST_PRODUCE_LIMIT
                batch_size = self.get_max_producible(away_cook_product, batch_size)

                if batch_size <= 0:
                    logger.info(f"[岛屿] 生产 {self._item_cn(away_cook_product)} 的前置材料不足，跳过岗位 {post_id}")
                    continue

                # 分配生产
                post_num = post_id[-1]
                time_var_name = f'{self.time_prefix}{post_num}'
                self.post_produce(post_id, away_cook_product, batch_size, time_var_name)

            logger.info("[岛屿] 常驻餐品模式：已为所有空闲岗位安排生产")
            return

        # 非常驻餐品模式：处理所有产品需求
        products_to_process = list(self.to_post_products.items())

        # 如果有多个产品需求，按槽位顺序排序（原料优先）
        if len(products_to_process) > 1:
            # 构建槽位顺序映射
            slot_index = {}
            idx = 0
            for name, _ in self.post_products:
                if name not in slot_index:
                    slot_index[name] = idx
                    idx += 1

            # 原料取其服务套餐中最早槽位的索引
            for meal, comp in self.meal_compositions.items():
                if meal in slot_index:
                    meal_slot = slot_index[meal]
                    for mat in comp['required']:
                        if mat not in slot_index or slot_index[mat] > meal_slot:
                            slot_index[mat] = meal_slot

            # 按槽位顺序排序，同槽位内原料优先于成品
            # 从套餐组成中提取所有原料名，避免双重身份产品被误判为非原料
            material_names = set()
            for comp in self.meal_compositions.values():
                material_names.update(comp['required'])

            # 未在 slot_index 中的产品默认排在已知槽位之后
            default_slot = len(slot_index) + 1

            def slot_priority(item):
                product, _ = item
                slot = slot_index.get(product, default_slot)
                is_material = product in material_names
                return (slot, 0 if is_material else 1)

            products_to_process.sort(key=slot_priority)

        # 为每个空闲岗位分配生产任务
        _produced_any = set()  # 本轮至少产出了1个的产品
        post_index = 0
        total_idle_posts = len(idle_posts)

        for product, required_quantity in products_to_process:
            if required_quantity <= 0:
                continue

            # 获取当前还有需求的量
            remaining_need = self.to_post_products.get(product, 0)
            if remaining_need <= 0:
                continue

            logger.info(f"[岛屿] 尝试安排生产 {self._item_cn(product)}，需求: {remaining_need}")

            # 为每个空闲岗位分配生产（直到需求满足或没有空闲岗位）
            while remaining_need > 0 and post_index < total_idle_posts:
                post_id = idle_posts[post_index]

                # 计算最大可生产数量
                max_producible = self.get_max_producible(
                    product, min(self.POST_PRODUCE_LIMIT, remaining_need))

                if max_producible <= 0:
                    logger.info(f"[岛屿] 生产 {self._item_cn(product)} 的材料暂时不足，保留在计划中等待下一轮")
                    # 标记为本轮已在排产阶段确认原料不足，后续 _compute_base_demands
                    # 会通过 chef_unavailable_products 检查直接跳过，避免同一 run()
                    # 内再次计算并实际 UI 点击（get_max_producible 对基础餐品漏算
                    # 底层食材时，每轮都会重新加入计划造成重复尝试）
                    self.chef_unavailable_products.add(product)
                    break  # 跳过当前产品，但保留在 to_post_products 中

                # 分配生产
                post_num = post_id[-1]
                time_var_name = f'{self.time_prefix}{post_num}'

                # 安排生产并获取实际生产数量
                actual_number = self.post_produce(post_id, product, max_producible, time_var_name)

                # 如果实际生产数量为0，说明原料不足
                if actual_number == 0:
                    logger.info(f"[岛屿] 生产 {self._item_cn(product)} 时检测到原料不足，保留在计划中等待下一轮")
                    # 游戏 UI 层实际拒绝了生产（常见于基础餐品 get_max_producible 未建模
                    # 的底层食材，如海鲜饭的米/海鲜料）。标记为本轮不可用，后续所有
                    # _compute_base_demands 扫描都会直接跳过，避免同一 run() 内在
                    # while 循环、严格模式中反复执行无效 UI 点击
                    self.chef_unavailable_products.add(product)
                    break  # 跳过当前产品，但保留在 to_post_products 中

                # 记录已产出（部分生产不算停滞）
                _produced_any.add(product)
                # 更新需求
                if product in self.to_post_products:
                    self.to_post_products[product] -= actual_number
                    if self.to_post_products[product] <= 0:
                        del self.to_post_products[product]

                # 更新剩余需求
                remaining_need = self.to_post_products.get(product, 0)

                # 移动到下一个岗位
                post_index += 1

            # 如果所有岗位都已分配，退出循环
            if post_index >= total_idle_posts:
                break

        if self.to_post_products:
            logger.info(f"[岛屿] 生产安排完成，剩余需求: {self._inv_cn(self.to_post_products)}")
        else:
            logger.info("[岛屿] 所有可安排的产品已安排生产")

    def check_special_materials(self, product, batch_size):
        """检查特殊材料（子类可覆盖）"""
        # 默认实现不检查特殊材料
        return batch_size
