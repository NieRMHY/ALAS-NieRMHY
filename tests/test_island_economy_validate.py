"""
岛屿经济表自检测试（Add by MHY）：validate_economy 现表必须返回空列表，
并对各类坏数据（profit 不符、店铺/时间非法、自产材料写错名）能报出问题。

经济数据的查询 API 测试见 test_island_economy.py。
"""
import unittest

from module.island.island_economy import (
    BASE_MATERIALS,
    ECONOMY_PRODUCTS,
    validate_economy,
)


def _broken_copy():
    """现表的浅拷贝（内层 dict 也复制，避免污染全局表）。"""
    return {k: dict(v) for k, v in ECONOMY_PRODUCTS.items()}


class TestValidateEconomy(unittest.TestCase):
    """经济表自检"""

    def test_current_table_passes(self):
        """现表应无问题：profit == price - cost、时间/店铺/材料均合法"""
        self.assertEqual(validate_economy(), [])

    def test_profit_mismatch_is_reported(self):
        """profit 与 price - cost 不符要报错（回归：苹果派曾写成 314.35）"""
        table = _broken_copy()
        table['apple_pie']['profit'] = 314.35
        problems = validate_economy(table)
        self.assertTrue(any('apple_pie' in p for p in problems), problems)

    def test_unknown_material_is_reported(self):
        """自产材料名写错要报错，不能退化成"未知基础材料"被静默放过"""
        table = _broken_copy()
        table['tofu_combo']['materials'] = {'tofu_meatt': 1, 'cabbage_tofu': 1}
        problems = validate_economy(table)
        self.assertTrue(any('tofu_meatt' in p for p in problems), problems)

    def test_bad_shop_and_time_are_reported(self):
        table = _broken_copy()
        table['tofu'] = dict(table['tofu'], shop='sushi', time_min=0.0)
        problems = validate_economy(table)
        self.assertTrue(any('sushi' in p for p in problems), problems)
        self.assertTrue(any('生产时间' in p for p in problems), problems)

    def test_base_materials_do_not_overlap_products(self):
        """基础材料白名单与商品表不应重叠，重叠说明分类写错了"""
        self.assertEqual(BASE_MATERIALS & set(ECONOMY_PRODUCTS), set())


if __name__ == '__main__':
    unittest.main()
