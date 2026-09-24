"""
岛屿计划 - 经济数据库模块

提供五家餐饮店铺全部商品的经济数据查询：
材料配方、制作时间、体力成本、材料费用、售价、结算利润、利润/分钟。
数据来源：biligame 碧蓝航线 wiki「岛屿计划」页（2026-09 抓取，59 个餐饮商品）。

设计约束（Add by MHY, 岛屿经济闭环）：
- 纯数据模块，不依赖游戏 UI 与设备，可独立单测；
- 数值更新只改 ECONOMY_PRODUCTS（由 dev_tools 生成，勿手改数值）；
- 制造产线（木工/工业/电子/手工）走 PT 转化体系，不纳入金币经济，故不在本表。
"""

from module.logger import logger


# 店铺类型标识（与 IslandShopBase 子类的 shop_type 一致）
ECONOMY_SHOPS = ('restaurant', 'teahouse', 'juu_eatery', 'grill', 'juu_coffee')

# 店铺中文名（与 IslandBusiness.shops 的 name 一致）
SHOP_CN_NAMES = {
    'restaurant': '有鱼餐馆',
    'teahouse': '白熊饮品',
    'juu_eatery': '啾啾简餐',
    'grill': '乌鱼烤肉',
    'juu_coffee': '啾咖啡',
}

# 店铺等级参数（wiki 店铺等级表）：
# slots=餐品格数量, per_slot=每格餐品数量上限, sell_rate=基础售出系数(实际为加成系数, 除以1.6使用)
SHOP_LEVELS = {
    'bronze':   {'name': '铜牌店铺', 'slots': 2, 'per_slot': 5, 'sell_rate': 0.9},
    'silver':   {'name': '银牌店铺', 'slots': 2, 'per_slot': 6, 'sell_rate': 1.0},
    'gold':     {'name': '金牌店铺', 'slots': 3, 'per_slot': 6, 'sell_rate': 1.1},
    'diamond':  {'name': '钻石店铺', 'slots': 4, 'per_slot': 6, 'sell_rate': 1.15},
}

# 经营销售额加成角色（wiki 角色技能表, 技能 Lv.10）：
# key=店铺类型, value=[(角色代码名, 加成%)]
SALES_BOOST_CHARACTERS = {
    'restaurant': [('ChaoHo', 10)],
    'teahouse': [('Cheshire', 5)],
    'juu_eatery': [('Helena', 10), ('Eugen', 10)],
    'grill': [('Eugen', 10), ('August', 10)],
    'juu_coffee': [('Belfast', 10), ('Cheshire', 5)],
}

# 餐品格容量 +1 的角色（key=角色代码名, value=受益店铺类型列表）
CAPACITY_BOOST_CHARACTERS = {
    'ChangFeng': list(ECONOMY_SHOPS),          # 全店铺 +1
    'Cheshire': ['juu_coffee', 'teahouse'],    # 啾咖啡 & 白熊 +1
    'ChaoHo': ['restaurant'],                  # 有鱼 +1
    'Helena': ['juu_eatery'],                  # 简餐 +1
    'August': ['grill'],                       # 乌鱼 +1
}

# 经营店员推荐组合（Add by MHY, 按 wiki 满级技能设计；角色不存在时选人器自动回退）
# key=店铺类型, value=[(角色代码名, 定位说明)]
STAFF_RECOMMENDATIONS = {
    'restaurant': [('ChaoHo', '容量+1&销售+10%'), ('ChangFeng', '容量+1&体力-6%')],
    'teahouse': [('Cheshire', '容量+1&销售+5%'), ('ChangFeng', '容量+1')],
    'juu_eatery': [('Helena', '容量+1&利润+10%'), ('Eugen', '销售+10%')],
    'grill': [('August', '容量+1&销售+10%'), ('Eugen', '销售+10%')],
    'juu_coffee': [('Belfast', '利润+4%&生产加成'), ('Cheshire', '容量+1&销售+5%')],
}

# 生产端工作速度推荐（Add by MHY, 烹饪类岗位按速度选人；评级工速 E0/D2/C5/B10/A15/S20+）
# 专属技能角色优先（应瑞-有鱼餐馆12%），其后按烹饪评级（需游戏内「烹饪」tab 确认，
# 监控脚本会持续收集）。非金币生产（制造/采集/种植）保持 WorkerJuu。
CHEF_SPEED_RECOMMENDATIONS = {
    'restaurant': [('YingSwei', '专属技能12%'), ('Shimakaze', 'A级15%'), ('Unicorn', 'A级15%'), ('Javelin', 'A级15%')],
    'teahouse': [('Shimakaze', 'A级15%'), ('Unicorn', 'A级15%'), ('Javelin', 'A级15%')],
    'juu_eatery': [('Javelin', 'A级15%'), ('Shimakaze', 'A级15%'), ('Unicorn', 'A级15%')],
    'grill': [('Unicorn', 'A级15%'), ('Shimakaze', 'A级15%'), ('Javelin', 'A级15%')],
    'juu_coffee': [('Unicorn', 'A级15%'), ('Shimakaze', 'A级15%'), ('Javelin', 'A级15%')],
}


# 自动生成自 biligame wiki 岛屿计划页（勿手改数值，更新走 dev_tools）
ECONOMY_PRODUCTS = {
    'persimmon_cake': dict(shop='restaurant', cn_name='柿子饼', materials={'persimmon': 1}, time_min=30.0, stamina=6, cost=45.0, price=210.0, profit=165.0, seasonal='秋季特产'),
    'matsutake_chicken_soup': dict(shop='restaurant', cn_name='松茸鸡汤', materials={'chicken': 2, 'matsutake': 1}, time_min=30.0, stamina=6, cost=10.0, price=900.0, profit=890.0, seasonal='秋季特产'),
    'asparagus_shrimp': dict(shop='restaurant', cn_name='芦笋炒虾仁', materials={'asparagus': 3, 'shrimp': 6}, time_min=20.0, stamina=4, cost=160.0, price=600.0, profit=440.0, seasonal='春季特产'),
    'amaranth_rice_ball': dict(shop='restaurant', cn_name='苋菜饭团', materials={'amaranth': 4, 'rice': 6}, time_min=30.0, stamina=6, cost=13.32, price=800.0, profit=786.68, seasonal='夏季特产'),
    'tomato_egg': dict(shop='restaurant', cn_name='番茄炒蛋', materials={'tomato': 4, 'egg': 8}, time_min=15.0, stamina=3, cost=90.64, price=200.0, profit=109.36, seasonal='夏季特产'),
    'tofu': dict(shop='restaurant', cn_name='豆腐', materials={'soybean': 15}, time_min=40.0, stamina=8, cost=33.33, price=340.0, profit=306.67, seasonal=''),
    'tofu_meat': dict(shop='restaurant', cn_name='肉沫烧豆腐', materials={'tofu': 2, 'pork': 1}, time_min=30.0, stamina=6, cost=70.0, price=1300.0, profit=1230.0, seasonal=''),
    'omurice': dict(shop='restaurant', cn_name='蛋包饭', materials={'egg': 4, 'rice': 9}, time_min=20.0, stamina=4, cost=25.3, price=355.0, profit=329.7, seasonal=''),
    'cabbage_tofu': dict(shop='restaurant', cn_name='白菜豆腐汤', materials={'tofu': 1, 'chinese_cabbage': 6}, time_min=30.0, stamina=6, cost=73.35, price=425.0, profit=351.65, seasonal=''),
    'salad': dict(shop='restaurant', cn_name='蔬菜沙拉', materials={'carrot': 2, 'chinese_cabbage': 3, 'corn': 1}, time_min=10.0, stamina=2, cost=36.68, price=105.0, profit=68.32, seasonal=''),
    'fish_chip': dict(shop='restaurant', cn_name='炸鱼薯条', materials={'sea_fish': 1, 'potato': 2}, time_min=5.0, stamina=1, cost=11.48, price=300.0, profit=288.52, seasonal=''),
    'onion_fish': dict(shop='restaurant', cn_name='洋葱蒸鱼', materials={'fresh_fish': 3, 'onion': 1}, time_min=30.0, stamina=6, cost=63.33, price=420.0, profit=356.67, seasonal=''),
    'fo_tiao': dict(shop='restaurant', cn_name='佛跳墙', materials={'sea_cucumber': 1, 'chicken': 3, 'sea_fish': 2}, time_min=60.0, stamina=12, cost=215.0, price=2000.0, profit=1785.0, seasonal=''),
    'tofu_combo': dict(shop='restaurant', cn_name='经典豆腐套餐', materials={'tofu_meat': 1, 'cabbage_tofu': 1}, time_min=10.0, stamina=2, cost=143.34, price=1735.0, profit=1591.66, seasonal=''),
    'double_bamboo_shoots': dict(shop='restaurant', cn_name='凉拌双笋', materials={'bamboo_shoot': 2, 'asparagus': 1}, time_min=15.0, stamina=3, cost=20.0, price=800.0, profit=780.0, seasonal='春季特产'),
    'hearty_meal': dict(shop='restaurant', cn_name='绵玉定食', materials={'omurice': 1, 'tofu': 1}, time_min=10.0, stamina=2, cost=58.63, price=695.0, profit=636.37, seasonal=''),
    'carrot_pear_juice': dict(shop='teahouse', cn_name='胡萝卜秋梨汁', materials={'pear': 3, 'carrot': 2}, time_min=30.0, stamina=6, cost=61.67, price=200.0, profit=138.33, seasonal='秋季特产'),
    'chrysanthemum_tea': dict(shop='teahouse', cn_name='菊花茶', materials={'chrysanthemum': 2}, time_min=30.0, stamina=6, cost=0.0, price=840.0, profit=840.0, seasonal='秋季特产'),
    'pineapple_juice': dict(shop='teahouse', cn_name='鲜榨菠萝汁', materials={'pineapple': 2}, time_min=10.0, stamina=2, cost=90.0, price=200.0, profit=110.0, seasonal='春季特产'),
    'spring_flower_tea': dict(shop='teahouse', cn_name='迎春花茶', materials={'winter_jasmine': 3, 'tea': 1}, time_min=40.0, stamina=8, cost=12.5, price=800.0, profit=787.5, seasonal='春季特产'),
    'cucumber_juice': dict(shop='teahouse', cn_name='黄瓜汁', materials={'cucumber': 4}, time_min=10.0, stamina=2, cost=80.0, price=100.0, profit=20.0, seasonal='夏季特产'),
    'watermelon_juice': dict(shop='teahouse', cn_name='西瓜汁', materials={'watermelon': 1}, time_min=10.0, stamina=2, cost=0.0, price=600.0, profit=600.0, seasonal='夏季特产'),
    'apple_juice': dict(shop='teahouse', cn_name='苹果汁', materials={'apple': 2}, time_min=10.0, stamina=2, cost=25.0, price=105.0, profit=80.0, seasonal=''),
    'banana_mango': dict(shop='teahouse', cn_name='香蕉芒果汁', materials={'banana': 1, 'mango': 1}, time_min=15.0, stamina=3, cost=40.0, price=215.0, profit=175.0, seasonal=''),
    'honey_lemon': dict(shop='teahouse', cn_name='蜂蜜柠檬水', materials={'fresh_honey': 1, 'lemon': 3}, time_min=10.0, stamina=2, cost=20.0, price=140.0, profit=120.0, seasonal=''),
    'strawberry_lemon': dict(shop='teahouse', cn_name='草莓蜜沁', materials={'strawberry': 5, 'lemon': 2}, time_min=20.0, stamina=4, cost=46.67, price=270.0, profit=223.33, seasonal=''),
    'lavender_tea': dict(shop='teahouse', cn_name='薰衣草茶', materials={'lavender': 4, 'tea': 6}, time_min=40.0, stamina=8, cost=155.0, price=1590.0, profit=1435.0, seasonal=''),
    'strawberry_honey': dict(shop='teahouse', cn_name='草莓蜂蜜冰沙', materials={'fresh_honey': 4, 'strawberry': 10}, time_min=30.0, stamina=6, cost=66.67, price=790.0, profit=723.33, seasonal=''),
    'floral_fruity': dict(shop='teahouse', cn_name='花香果韵', materials={'lavender_tea': 1, 'apple_juice': 1}, time_min=5.0, stamina=1, cost=180.0, price=1700.0, profit=1520.0, seasonal=''),
    'fruit_paradise': dict(shop='teahouse', cn_name='缤纷果乐园', materials={'banana_mango': 1, 'strawberry_honey': 1}, time_min=5.0, stamina=1, cost=106.67, price=1000.0, profit=893.33, seasonal=''),
    'sunny_honey': dict(shop='teahouse', cn_name='阳光蜜水', materials={'strawberry_lemon': 1, 'honey_lemon': 1}, time_min=5.0, stamina=1, cost=66.67, price=410.0, profit=343.33, seasonal=''),
    'corn_cup': dict(shop='juu_eatery', cn_name='玉米杯', materials={'corn': 3, 'milk': 1}, time_min=5.0, stamina=1, cost=9.17, price=45.0, profit=35.83, seasonal=''),
    'apple_pie': dict(shop='juu_eatery', cn_name='苹果派', materials={'apple': 3, 'wheat_flour': 5}, time_min=30.0, stamina=6, cost=70.85, price=385.0, profit=314.35, seasonal=''),
    'orange_pie': dict(shop='juu_eatery', cn_name='香橙派', materials={'citrus': 3, 'wheat_flour': 6}, time_min=30.0, stamina=6, cost=85.02, price=375.0, profit=289.98, seasonal=''),
    'rice_mango': dict(shop='juu_eatery', cn_name='芒果糯米饭', materials={'mango': 3, 'rice': 2}, time_min=20.0, stamina=4, cost=71.94, price=510.0, profit=438.06, seasonal=''),
    'banana_crepe': dict(shop='juu_eatery', cn_name='香蕉可丽饼', materials={'banana': 2, 'wheat_flour': 2}, time_min=15.0, stamina=3, cost=48.34, price=230.0, profit=181.66, seasonal=''),
    'strawberry_charlotte': dict(shop='juu_eatery', cn_name='草莓夏洛特', materials={'strawberry': 1, 'wheat_flour': 2, 'cheese': 2}, time_min=35.0, stamina=7, cost=60.01, price=1350.0, profit=1289.99, seasonal=''),
    'orchard_duo': dict(shop='juu_eatery', cn_name='果园二重奏', materials={'apple_pie': 1, 'banana_crepe': 1}, time_min=5.0, stamina=1, cost=119.19, price=615.0, profit=495.81, seasonal=''),
    'berry_orange': dict(shop='juu_eatery', cn_name='莓果香橙甜点组', materials={'orange_pie': 1, 'strawberry_charlotte': 1}, time_min=5.0, stamina=1, cost=145.03, price=1730.0, profit=1584.97, seasonal=''),
    'seafood_rice': dict(shop='juu_eatery', cn_name='海鲜饭', materials={'crab': 1, 'squid': 2, 'rice': 5}, time_min=30.0, stamina=6, cost=296.1, price=900.0, profit=603.9, seasonal=''),
    'succulently_sweet': dict(shop='juu_eatery', cn_name='香甜组合', materials={'corn_cup': 1, 'rice_mango': 1}, time_min=5.0, stamina=1, cost=81.11, price=560.0, profit=478.89, seasonal=''),
    'roasted_skewer': dict(shop='grill', cn_name='碳烤肉串', materials={'pork': 4}, time_min=20.0, stamina=4, cost=13.33, price=390.0, profit=376.67, seasonal=''),
    'chicken_potato': dict(shop='grill', cn_name='禽肉土豆拼盘', materials={'chicken': 5, 'potato': 6}, time_min=30.0, stamina=6, cost=29.44, price=370.0, profit=340.56, seasonal=''),
    'stir_fried_chicken': dict(shop='grill', cn_name='爆炒禽肉', materials={'chicken': 3, 'onion': 1}, time_min=25.0, stamina=5, cost=45.0, price=580.0, profit=480.0, seasonal=''),
    'carrot_omelette': dict(shop='grill', cn_name='胡萝卜厚蛋烧', materials={'egg': 5, 'carrot': 2}, time_min=10.0, stamina=2, cost=23.32, price=170.0, profit=146.68, seasonal=''),
    'steak_bowl': dict(shop='grill', cn_name='汉堡肉饭', materials={'pork': 6, 'rice': 12, 'chinese_cabbage': 2}, time_min=25.0, stamina=5, cost=59.95, price=845.0, profit=785.05, seasonal=''),
    'lemon_shrimp': dict(shop='grill', cn_name='柠檬虾', materials={'shrimp': 4, 'lemon': 1}, time_min=10.0, stamina=2, cost=73.3, price=500.0, profit=426.0, seasonal=''),
    'crayfish_stir_fry': dict(shop='grill', cn_name='爆炒小龙虾', materials={'crayfish': 5}, time_min=15.0, stamina=3, cost=125.0, price=720.0, profit=595.0, seasonal=''),
    'carnival': dict(shop='grill', cn_name='烤肉狂欢', materials={'roasted_skewer': 1, 'chicken_potato': 1}, time_min=10.0, stamina=2, cost=42.77, price=760.0, profit=717.23, seasonal=''),
    'double_energy': dict(shop='grill', cn_name='能量双拼套餐', materials={'stir_fried_chicken': 1, 'steak_bowl': 1}, time_min=10.0, stamina=2, cost=104.95, price=1430.0, profit=1325.05, seasonal=''),
    'omelette': dict(shop='juu_coffee', cn_name='欧姆蛋', materials={'egg': 1}, time_min=5.0, stamina=1, cost=1.33, price=50.0, profit=48.67, seasonal=''),
    'iced_coffee': dict(shop='juu_coffee', cn_name='冰咖啡', materials={'coffee_bean': 2}, time_min=15.0, stamina=3, cost=26.67, price=95.0, profit=68.33, seasonal=''),
    'cheese': dict(shop='juu_coffee', cn_name='芝士', materials={'milk': 8}, time_min=40.0, stamina=8, cost=20.0, price=550.0, profit=530.0, seasonal=''),
    'latte': dict(shop='juu_coffee', cn_name='拿铁', materials={'coffee_bean': 3, 'milk': 2}, time_min=20.0, stamina=4, cost=45.0, price=250.0, profit=205.0, seasonal=''),
    'citrus_coffee': dict(shop='juu_coffee', cn_name='柑橘咖啡', materials={'citrus': 1, 'coffee_bean': 3}, time_min=15.0, stamina=3, cost=55.0, price=190.0, profit=135.0, seasonal=''),
    'strawberry_milkshake': dict(shop='juu_coffee', cn_name='草莓奶绿', materials={'tea': 1, 'strawberry': 1, 'milk': 1}, time_min=20.0, stamina=4, cost=21.67, price=260.0, profit=238.33, seasonal=''),
    'morning_light': dict(shop='juu_coffee', cn_name='晨光活力套餐', materials={'omelette': 1, 'latte': 1}, time_min=10.0, stamina=2, cost=46.33, price=300.0, profit=253.67, seasonal=''),
    'wake_up_call': dict(shop='juu_coffee', cn_name='醒神套餐', materials={'iced_coffee': 1, 'cheese': 1}, time_min=10.0, stamina=2, cost=46.67, price=650.0, profit=603.34, seasonal=''),
    'fruity_fruitier': dict(shop='juu_coffee', cn_name='果香双杯乐', materials={'citrus_coffee': 1, 'strawberry_milkshake': 1}, time_min=10.0, stamina=2, cost=76.67, price=450.0, profit=373.33, seasonal=''),
}


# ==================== 查询 API ====================


class EconomyDatabase:
    """
    岛屿餐饮经济数据库

    提供按店铺/利润/材料的商品查询与排序，供 AutoProfit 感知生产决策使用。
    只读数据，不持有游戏状态；实例轻量可随时重建。
    """

    # Add by MHY: 规划器直接访问原始表用
    economy_products = ECONOMY_PRODUCTS

    def __init__(self, season=None):
        """
        Args:
            season: 当前季节（'spring'/'summer'/'autumn'/'winter'），None 表示不过滤季节
        """
        self.season = season
        self._seasonal_cn = {
            'spring': '春季特产', 'summer': '夏季特产',
            'autumn': '秋季特产', 'winter': '冬季特产',
        }

    # ---------- 基础查询 ----------

    def get_product(self, name):
        """
        获取单个商品的经济数据。

        Args:
            name: 商品英文名（如 'tofu_combo'）

        Returns:
            dict 或 None
        """
        return ECONOMY_PRODUCTS.get(name)

    def get_products_by_shop(self, shop):
        """
        获取店铺全部商品。

        Args:
            shop: 店铺类型标识（restaurant/teahouse/juu_eatery/grill/juu_coffee）

        Returns:
            list[dict]: 按 profit_per_min 降序
        """
        items = [dict(v, name=k) for k, v in ECONOMY_PRODUCTS.items() if v['shop'] == shop]
        items.sort(key=lambda x: -x['profit_per_min'])
        return items

    def cn_name(self, name):
        """商品英文名 → 中文名（日志用），未知返回原名。"""
        info = ECONOMY_PRODUCTS.get(name)
        return info['cn_name'] if info else name

    # ---------- 利润与选品 ----------

    def profit_per_min(self, name):
        """商品利润/分钟，未知商品返回 0。"""
        info = ECONOMY_PRODUCTS.get(name)
        if not info or not info['time_min']:
            return 0.0
        return info['profit'] / info['time_min']

    def sort_by_profit(self, names, reverse=True):
        """按利润/分钟排序商品名列表。"""
        return sorted(names, key=lambda n: self.profit_per_min(n), reverse=reverse)

    def is_seasonal(self, name):
        """商品是否季节限定。"""
        info = ECONOMY_PRODUCTS.get(name)
        return bool(info and info['seasonal'])

    def filter_products(self, names, season=None):
        """
        过滤掉非当前季节的限定商品。

        Args:
            names: 商品英文名列表
            season: 季节；None 用实例季节；'none' 表示剔除所有季节限定
        """
        season = season if season is not None else self.season
        if season is None:
            return list(names)
        keep_cn = self._seasonal_cn.get(season)
        out = []
        for n in names:
            info = ECONOMY_PRODUCTS.get(n)
            if info and info['seasonal'] and info['seasonal'] != keep_cn:
                continue
            out.append(n)
        return out

    def recommend_products(self, shop, season=None, top=3, exclude=()):
        """
        为店铺推荐利润最高的常驻商品（季节限定需当季才推荐）。

        Args:
            shop: 店铺类型标识
            season: 季节；None 用实例季节；None 且实例也无季节时含全部
            top: 推荐数量
            exclude: 排除的商品名集合

        Returns:
            list[dict]: 含 name 键，按利润/分钟降序
        """
        season = season if season is not None else self.season
        keep_cn = self._seasonal_cn.get(season) if season else None
        items = []
        for k, v in ECONOMY_PRODUCTS.items():
            if v['shop'] != shop or k in exclude:
                continue
            if v['seasonal'] and keep_cn and v['seasonal'] != keep_cn:
                continue
            items.append(dict(v, name=k, profit_per_min=v['profit'] / v['time_min']))
        items.sort(key=lambda x: -x['profit_per_min'])
        return items[:top]

    # ---------- 材料需求 ----------

    def expand_materials(self, name, quantity=1, _depth=0):
        """
        递归展开商品的全部基础材料需求（套餐分解到农产品/畜产层）。

        Args:
            name: 商品英文名
            quantity: 需求数量
            _depth: 递归深度（内部用，防循环依赖）

        Returns:
            dict: {材料名: 数量}；未知商品返回 {name: quantity}
        """
        if _depth > 8:
            return {name: quantity}
        info = ECONOMY_PRODUCTS.get(name)
        if not info:
            return {name: quantity}
        out = {}
        for mat, num in info['materials'].items():
            need = num * quantity
            if mat in ECONOMY_PRODUCTS:
                sub = self.expand_materials(mat, need, _depth + 1)
                for k, v in sub.items():
                    out[k] = out.get(k, 0) + v
            else:
                out[mat] = out.get(mat, 0) + need
        return out

    def batch_materials(self, plan):
        """
        批量展开生产计划的材料需求。

        Args:
            plan: {商品名: 数量}

        Returns:
            dict: {材料名: 数量}
        """
        out = {}
        for name, qty in plan.items():
            for mat, num in self.expand_materials(name, qty).items():
                out[mat] = out.get(mat, 0) + num
        return out

    # ---------- 店铺等级 ----------

    @staticmethod
    def shop_capacity(shop_level, boost_chars=()):
        """
        店铺餐品总容量（餐品格 × 每格数量）。

        Args:
            shop_level: 'bronze'/'silver'/'gold'/'diamond'
            boost_chars: 经营店员角色代码名列表（容量+1技能生效）

        Returns:
            (slots, per_slot, capacity)
        """
        lv = SHOP_LEVELS.get(shop_level, SHOP_LEVELS['bronze'])
        per_slot = lv['per_slot'] + (1 if boost_chars else 0)
        return lv['slots'], per_slot, lv['slots'] * per_slot

    @staticmethod
    def sales_boost(shop, chars):
        """
        计算店员组合的销售额加成合计（%）。

        Args:
            shop: 店铺类型标识
            chars: 角色代码名列表

        Returns:
            float: 加成百分比（如 10.0）
        """
        boost_map = dict(SALES_BOOST_CHARACTERS.get(shop, []))
        return sum(boost_map.get(c, 0) for c in chars)


# ==================== 全局单例 ====================

_global_economy = None


def get_global_economy(season=None):
    """
    获取全局经济数据库单例（与 island_season 的单例模式一致）。

    Args:
        season: 首次创建时传入的季节；后续调用只刷新季节
    """
    global _global_economy
    if _global_economy is None:
        _global_economy = EconomyDatabase(season=season)
    elif season is not None:
        _global_economy.season = season
    return _global_economy
