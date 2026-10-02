"""岛屿 JUU 咖啡店模块。

继承 IslandShopBase，配置咖啡店的商品列表与岗位参数。
包含冰咖啡、蛋卷、拿铁、柑橘咖啡等饮品的模板、选择与制作流程定义。
"""
from module.island_juu_coffee.assets import *
from module.island.island_shop_base import IslandShopBase
from module.island.assets import *
from module.ui.page import *
from module.logger import logger


class IslandJuuCoffee(IslandShopBase):
    """岛屿啾咖啡店自动化管理器。

    继承 IslandShopBase，管理啾咖啡的商品制作、牛奶库存约束与特定角色派遣。

    Attributes:
        shop_type (str): 店铺类型标识。
        time_prefix (str): 岗位完成时间前缀。
        chef_config (str): 厨师角色筛选配置。
        special_character (bool): 是否启用特殊角色制作配置。
        shop_items (list): 咖啡店商品配置列表。
        meal_compositions (dict): 套餐组成与所需单品数量。
        post_buttons (dict): 岗位按钮资源映射。
        filter_asset (str): 仓库筛选分类。
        post_manage_swipe_count (int): 岗位管理页面滑动次数。
        milk_stock (int): 当前牧场牛奶库存数量。
        special_materials (dict): 特殊材料库存映射。
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 设置店铺类型
        self.shop_type = "juu_coffee"
        self.time_prefix = "time_coffee"
        self.chef_config = self.config.IslandJuuCoffee_ChefFilter
        self.special_character = self.config.IslandJuuCoffee_Friedrich

        # 设置商品列表
        self.shop_items = [
            {'name': 'iced_coffee', 'template': TEMPLATE_ICED_COFFEE, 'var_name': 'iced_coffee',
             'selection': SELECT_ICED_COFFEE, 'selection_check': SELECT_ICED_COFFEE_CHECK,
             'post_action': POST_ICED_COFFEE},
            {'name': 'omelette', 'template': TEMPLATE_OMELETTE, 'var_name': 'omelette',
             'selection': SELECT_OMELETTE, 'selection_check': SELECT_OMELETTE_CHECK,
             'post_action': POST_OMELETTE},
            {'name': 'latte', 'template': TEMPLATE_LATTE, 'var_name': 'latte',
             'selection': SELECT_LATTE, 'selection_check': SELECT_LATTE_CHECK,
             'post_action': POST_LATTE},
            {'name': 'citrus_coffee', 'template': TEMPLATE_CITRUS_COFFEE, 'var_name': 'citrus_coffee',
             'selection': SELECT_CITRUS_COFFEE, 'selection_check': SELECT_CITRUS_COFFEE_CHECK,
             'post_action': POST_CITRUS_COFFEE},
            {'name': 'strawberry_milkshake', 'template': TEMPLATE_STRAWBERRY_MILKSHAKE,
             'var_name': 'strawberry_milkshake',
             'selection': SELECT_STRAWBERRY_MILKSHAKE, 'selection_check': SELECT_STRAWBERRY_MILKSHAKE_CHECK,
             'post_action': POST_STRAWBERRY_MILKSHAKE},
            {'name': 'morning_light', 'template': TEMPLATE_MORNING_LIGHT, 'var_name': 'morning_light',
             'selection': SELECT_MORNING_LIGHT, 'selection_check': SELECT_MORNING_LIGHT_CHECK,
             'post_action': POST_MORNING_LIGHT},
            {'name': 'wake_up_call', 'template': TEMPLATE_WAKE_UP_CALL, 'var_name': 'wake_up_call',
             'selection': SELECT_WAKE_UP_CALL, 'selection_check': SELECT_WAKE_UP_CALL_CHECK,
             'post_action': POST_WAKE_UP_CALL},
            {'name': 'fruity_fruitier', 'template': TEMPLATE_FRUITY_FRUITIER, 'var_name': 'fruity_fruitier',
             'selection': SELECT_FRUITY_FRUITIER, 'selection_check': SELECT_FRUITY_FRUITIER_CHECK,
             'post_action': POST_FRUITY_FRUITIER},
            {'name': 'cheese', 'template': TEMPLATE_CHEESE, 'var_name': 'cheese',
             'selection': SELECT_CHEESE, 'selection_check': SELECT_CHEESE_CHECK,
             'post_action': POST_CHEESE},
        ]

        # 设置套餐组成
        self.meal_compositions = {
            'morning_light': {
                'required': ['latte', 'omelette'],
                'quantity_per': 1
            },
            'wake_up_call': {
                'required': ['cheese', 'iced_coffee'],
                'quantity_per': 1
            },
            'fruity_fruitier': {
                'required': ['citrus_coffee', 'strawberry_milkshake'],
                'quantity_per': 1
            }
        }

        # 设置岗位按钮
        self.post_buttons = {
            'ISLAND_JUU_COFFEE_POST1': ISLAND_JUU_COFFEE_POST1,
            'ISLAND_JUU_COFFEE_POST2': ISLAND_JUU_COFFEE_POST2
        }

        # 设置筛选资产
        self.filter_asset = 'juu_coffee'

        # 设置配置前缀
        self.setup_config(
            config_meal_prefix="IslandJuuCoffee_Meal",
            config_number_prefix="IslandJuuCoffee_MealNumber",
            config_away_cook="IslandJuuCoffeeNextTask_AwayCook",
            config_post_number="IslandJuuCoffee_PostNumber"
        )

        # 设置滑动次数（JuuCoffee需要滑动两次）
        self.post_manage_swipe_count = 2  # run方法中滑动2次450

        # 特殊材料：牛奶
        self.milk_stock = 0
        self.special_materials = {'milk': 0}

        # 初始化店铺
        self.initialize_shop()

    def get_warehouse_counts(self):
        """获取咖啡店商品及牧场牛奶的仓库库存数量。

        Returns:
            dict[str, int]: 包含所有商品与牛奶库存的字典。
        """
        # 先调用父类方法获取基础库存
        super().get_warehouse_counts()

        # 额外获取milk数量（从牧场）
        self.warehouse_filter('ranch')
        image = self.device.screenshot()
        self.milk_stock = self.ocr_item_quantity(image, TEMPLATE_MILK)
        self.special_materials['milk'] = self.milk_stock
        logger.info(f"[岛屿-啾咖啡] 牛奶数量: {self.milk_stock}")

        # 将牛奶库存也存入warehouse_counts，便于统一处理
        self.warehouse_counts['milk'] = self.milk_stock

        return self.warehouse_counts

    def check_special_materials(self, product, batch_size):
        """检查特殊材料（牛奶）库存对生产批次的限制。

        Args:
            product (str): 目标商品名称。
            batch_size (int): 计划生产的批次数。

        Returns:
            int: 考虑牛奶库存限制后允许的最大批次数。
        """
        if batch_size <= 0:
            return 0

        # latte需要2个牛奶
        elif product == 'latte':
            milk_needed_per_batch = 2
            milk_available = self.milk_stock
            max_by_milk = milk_available // milk_needed_per_batch
            batch_size = min(batch_size, max_by_milk)
            logger.info(f"[岛屿-啾咖啡]   {self._item_cn(product)} 牛奶限制: 可用{milk_available}, 每批{milk_needed_per_batch}, 最大{max_by_milk}")

        # strawberry_milkshake需要1个牛奶
        elif product == 'strawberry_milkshake':
            milk_needed_per_batch = 1
            milk_available = self.milk_stock
            max_by_milk = milk_available // milk_needed_per_batch
            batch_size = min(batch_size, max_by_milk)
            logger.info(f"[岛屿-啾咖啡]   {self._item_cn(product)} 牛奶限制: 可用{milk_available}, 每批{milk_needed_per_batch}, 最大{max_by_milk}")

        # cheese需要8个牛奶
        if product == 'cheese':
            milk_needed_per_batch = 8
            milk_available = self.milk_stock
            max_by_milk = milk_available // milk_needed_per_batch
            batch_size = min(batch_size, max_by_milk)
            logger.info(f"[岛屿-啾咖啡]   {self._item_cn(product)} 牛奶限制: 可用{milk_available}, 每批{milk_needed_per_batch}, 最大{max_by_milk}")
        return batch_size

    def select_special_character(self, product):
        """为特定商品派遣特定厨师角色。

        芝士(cheese)优先大帝(Friedrich)制作，大帝不可选时回退普通厨师；
        醒神套餐(wake_up_call)必须由大帝制作。
        大帝需通过向下滚动查找，且体力必须大于 50。
        普通餐品先回到列表顶部再按配置选择。

        Args:
            product (str): 目标商品名称。

        Returns:
            bool: 是否成功选择并确认角色。
        """
        if product == 'wake_up_call':
            return self.select_specific_character_with_scroll("Friedrich", stamina_threshold=50)
        if product == 'cheese':
            if self.select_specific_character_with_scroll("Friedrich", stamina_threshold=50):
                return True
            # 大帝不可选（未找到/体力不足），回退普通厨师；先回到列表顶部再按配置选择
            self._swipe_character_list_to_top()
            return self.select_character(self.chef_config)
        # 普通餐品：先回到列表顶部再按配置选择，避免上个岗位遗留的滚动位置导致找不到黄鸡
        self._swipe_character_list_to_top()
        return self.select_character(self.chef_config)

    def deduct_materials(self, product, number):
        """扣除制作指定商品消耗的前置材料（包括牛奶和套餐原材料）。

        Args:
            product (str): 生产的商品名称。
            number (int): 生产的商品批次数。
        """
        # 先调用父类方法扣除套餐原材料
        super().deduct_materials(product, number)

        # latte需要扣除牛奶
        if product == 'latte':
            milk_needed = number * 2
            self.milk_stock = max(0, self.milk_stock - milk_needed)
            self.special_materials['milk'] = self.milk_stock
            if 'milk' in self.warehouse_counts:
                self.warehouse_counts['milk'] = self.milk_stock
            logger.info(f"[岛屿-啾咖啡] 扣除牛奶：{self._item_cn('milk')} -{milk_needed} (用于制作 {self._item_cn(product)})")

        # strawberry_milkshake需要扣除牛奶
        elif product == 'strawberry_milkshake':
            milk_needed = number * 1
            self.milk_stock = max(0, self.milk_stock - milk_needed)
            self.special_materials['milk'] = self.milk_stock
            if 'milk' in self.warehouse_counts:
                self.warehouse_counts['milk'] = self.milk_stock
            logger.info(f"[岛屿-啾咖啡] 扣除牛奶：{self._item_cn('milk')} -{milk_needed} (用于制作 {self._item_cn(product)})")
        # cheese需要扣除牛奶
        elif product == 'cheese':
            milk_needed = number * 8
            self.milk_stock = max(0, self.milk_stock - milk_needed)
            self.special_materials['milk'] = self.milk_stock
            if 'milk' in self.warehouse_counts:
                self.warehouse_counts['milk'] = self.milk_stock
            logger.info(f"[岛屿-啾咖啡] 扣除牛奶：{self._item_cn('milk')} -{milk_needed} (用于制作 {self._item_cn(product)})")

    def apply_special_material_constraints(self, requirements):
        """根据当前牛奶库存调整各商品的需求排产计划。

        按拿铁、草莓奶昔、芝士的优先级依次扣减分配可用牛奶。

        Args:
            requirements (dict[str, int]): 各商品的原始需求数量映射。

        Returns:
            dict[str, int]: 调整后受牛奶库存约束的需求数量映射。
        """
        result = requirements.copy()

        # 计算所有需要牛奶的产品总需求
        milk_demand = 0

        # latte需求（每个需要2牛奶）
        if 'latte' in result and result['latte'] > 0:
            milk_demand += result['latte'] * 2

        # strawberry_milkshake需求（每个需要1牛奶）
        if 'strawberry_milkshake' in result and result['strawberry_milkshake'] > 0:
            milk_demand += result['strawberry_milkshake'] * 1

        # cheese需求（每个需要8牛奶）
        if 'cheese' in result and result['cheese'] > 0:
            milk_demand += result['cheese'] * 8

        # 检查牛奶是否足够
        milk_available = self.milk_stock

        if milk_demand > milk_available:
            logger.info(f"[岛屿-啾咖啡] 牛奶不足：总需求{milk_demand}，可用{milk_available}")

            # 按优先级调整需求（这里可以根据需要调整优先级）
            # 例如：先满足latte，然后是strawberry_milkshake，最后是cheese
            remaining_milk = milk_available

            # 调整latte需求
            if 'latte' in result and result['latte'] > 0:
                latte_needed = result['latte']
                milk_for_latte = latte_needed * 2

                if remaining_milk < milk_for_latte:
                    max_latte = remaining_milk // 2
                    result['latte'] = max_latte
                    logger.info(f"[岛屿-啾咖啡] 牛奶不足完成{self._item_cn('latte')}，需求从{latte_needed}调整为{max_latte}，剩余牛奶{remaining_milk}调整为{remaining_milk - max_latte * 2}")
                    remaining_milk -= max_latte * 2
                else:
                    remaining_milk -= milk_for_latte
                    logger.info(f"[岛屿-啾咖啡] 牛奶足够完成{self._item_cn('latte')}，扣除{milk_for_latte}，剩余牛奶{remaining_milk}")
                    

            # 调整strawberry_milkshake需求
            if 'strawberry_milkshake' in result and result['strawberry_milkshake'] > 0:
                milkshake_needed = result['strawberry_milkshake']
                milk_for_milkshake = milkshake_needed * 1

                if remaining_milk < milk_for_milkshake:
                    max_milkshake = remaining_milk // 1
                    result['strawberry_milkshake'] = max_milkshake
                    logger.info(f"[岛屿-啾咖啡] 牛奶不足完成{self._item_cn('strawberry_milkshake')}，需求从{milkshake_needed}调整为{max_milkshake}，剩余牛奶{remaining_milk}调整为{remaining_milk - max_milkshake * 1}")
                    remaining_milk -= max_milkshake * 1
                else:
                    remaining_milk -= milk_for_milkshake
                    logger.info(f"[岛屿-啾咖啡] 牛奶足够完成{self._item_cn('strawberry_milkshake')}，扣除{milk_for_milkshake}，剩余牛奶{remaining_milk}")

            # 调整cheese需求
            if 'cheese' in result and result['cheese'] > 0:
                cheese_needed = result['cheese']
                milk_for_cheese = cheese_needed * 8

                if remaining_milk < milk_for_cheese:
                    max_cheese = remaining_milk // 8
                    result['cheese'] = max_cheese
                    logger.info(f"[岛屿-啾咖啡] 牛奶不足完成{self._item_cn('cheese')}，需求从{cheese_needed}调整为{max_cheese}，剩余牛奶{remaining_milk}调整为{remaining_milk - max_cheese * 8}")
                    remaining_milk -= max_cheese * 8
                else:
                    remaining_milk -= milk_for_cheese
                    logger.info(f"[岛屿-啾咖啡] 牛奶足够完成{self._item_cn('cheese')}，扣除{milk_for_cheese}，剩余牛奶{remaining_milk}")

        return result

    def process_meal_requirements(self, source_products):
        """处理套餐需求并计算所需原材料数量。

        Args:
            source_products (dict[str, int]): 原始商品与套餐需求映射。

        Returns:
            dict[str, int]: 拆解套餐后的最终单品与原材料需求映射。
        """
        logger.info(f"=== IslandJuuCoffee.process_meal_requirements ===")
        logger.info(f"[岛屿-啾咖啡] 传入的需求: {self._inv_cn(source_products)}")

        # 调用父类方法
        result = super().process_meal_requirements(source_products)

        logger.info(f"[岛屿-啾咖啡] 返回结果: {self._inv_cn(result)}")
        logger.info(f"[岛屿-啾咖啡] === 结束IslandJuuCoffee.process_meal_requirements ===")

        return result


if __name__ == "__main__":
    az = IslandJuuCoffee('alas', task='Alas')
    az.device.screenshot()
    az.run()
