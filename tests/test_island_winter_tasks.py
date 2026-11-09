"""冬季 16 项赛季任务、WinterTaskEnabled/MealBuffer 与四语翻译。

数据以 module/island_planner/data.py 的 80001501-80001516 为参照：
任务名、物品 ID、需求数量必须逐项一致；物品 key 使用现有执行器/经济库的写法，
没有执行器产品的香囊/钟表/蓄电池用 sachet/clock/battery。
"""
import json
import unittest
from collections import Counter

from module.config.config_generated import GeneratedConfig
from module.config.utils import filepath_argument, read_file
from module.island import island_season_plan_data as D
from module.island.island_economy import ECONOMY_PRODUCTS
from module.island_planner.data import DIC_ISLAND_ITEM, DIC_ISLAND_TASK

GROUP = D.CONFIG_GROUP

# (任务 ID, 任务名, 物品 key, 物品 ID, 需求数量, 类型)
EXPECTED = [
    (80001501, '清茶储备', 'tea', 2014, 500, 'natural'),
    (80001502, '柑橘补给', 'citrus', 2017, 500, 'natural'),
    (80001503, '金芒入仓', 'mango', 2019, 250, 'natural'),
    (80001504, '牛油果香', 'avocado', 2021, 100, 'natural'),
    (80001505, '河鲜供应', 'freshwater_fish_meat', 2521, 100, 'natural'),
    (80001506, '海味入库', 'seawater_fish_meat', 2522, 100, 'natural'),
    (80001507, '丰盛拼盘', 'chicken_potato', 3030, 100, 'meal'),
    (80001508, '甜糯组合', 'rice_mango', 3025, 50, 'meal'),
    (80001509, '甜品储备', 'strawberry_charlotte', 3028, 25, 'meal'),
    (80001510, '银矿采集', 'silver', 2705, 25, 'natural'),
    (80001511, '良木入库', 'elegant_wood', 2803, 25, 'natural'),
    (80001512, '香囊供给', 'sachet', 3039, 10, 'manufacture'),
    (80001513, '餐具整备', 'cutlery', 3047, 10, 'manufacture'),
    (80001514, '文书配套', 'ink_cartridge', 3053, 10, 'manufacture'),
    (80001515, '时间管理', 'clock', 3054, 10, 'manufacture'),
    (80001516, '电力储备', 'battery', 3055, 10, 'manufacture'),
]
WINTER_ITEMS = [row[2] for row in EXPECTED]
NEED_DEFAULTS = {
    'tea': 500, 'citrus': 500, 'mango': 200, 'avocado': 100,
    'freshwater_fish_meat': 100, 'seawater_fish_meat': 100,
    'chicken_potato': 100, 'rice_mango': 50, 'strawberry_charlotte': 25,
    'silver': 25, 'elegant_wood': 25,
    'sachet': 10, 'cutlery': 10, 'ink_cartridge': 10, 'clock': 10, 'battery': 10,
}

# 每语种的新增文案（抽查项：物品名 + 选项名）
I18N_NAMES = {
    'zh-CN': {'Need_tea': '茶叶 · 需求数量', 'Done_battery': '蓄电池 · 已完成',
              'WinterTaskEnabled': '冬季任务模式', 'MealBuffer': '餐品缓冲'},
    'zh-TW': {'Need_tea': '茶葉 · 需求數量', 'Done_battery': '蓄電池 · 已完成',
              'WinterTaskEnabled': '冬季任務模式', 'MealBuffer': '餐品緩衝'},
    'en-US': {'Need_tea': 'Tea Leaves · Required', 'Done_battery': 'Battery · Done',
              'WinterTaskEnabled': 'Winter Task Mode', 'MealBuffer': 'Meal Buffer'},
    'ja-JP': {'Need_tea': '茶葉 · 必要数', 'Done_battery': '蓄電池 · 完了',
              'WinterTaskEnabled': '冬季任務モード', 'MealBuffer': '料理バッファ'},
}


class FakeConfig:
    """只实现 cross_get 的配置替身。"""

    def __init__(self, values=None):
        self.values = values or {}

    def cross_get(self, key, default=None):
        return self.values.get(key, default)


class TestWinterTaskData(unittest.TestCase):
    def test_sixteen_tasks_match_planner_ids_and_names(self):
        self.assertEqual(len(D.WINTER_TASKS), 16)
        actual = [(t['task_id'], t['name'], t['item'], t['item_id'], t['need'], t['type'])
                  for t in D.WINTER_TASKS]
        self.assertEqual(actual, EXPECTED)
        self.assertEqual([t['item'] for t in D.WINTER_TASKS], WINTER_ITEMS)

    def test_planner_data_targets_agree(self):
        for task_id, name, item, item_id, need, _ in EXPECTED:
            task = DIC_ISLAND_TASK[task_id]
            self.assertEqual(task['name']['cn'], name)
            self.assertEqual(task['target'], {item_id: need})
            self.assertEqual(DIC_ISLAND_ITEM[item_id]['name']['cn'], D.ITEM_CN[item])

    def test_plan_tasks_keeps_tuple_api(self):
        tuples = D.SEASON_PLAN_TASKS['winter']
        self.assertEqual(tuples, [(row[1], row[2], row[4]) for row in EXPECTED])
        tasks = D.plan_tasks('winter')
        self.assertEqual(len(tasks), 22)
        self.assertEqual(tasks[:16], tuples)
        self.assertEqual([row[0] for row in tasks[16:]], [row[0] for row in D.ORDER_MILESTONES])
        self.assertEqual(D.task_of_item('rice_mango', 'winter'), ('甜糯组合', 50))
        self.assertEqual(D.task_of_item(None, 'winter'), (None, 0))
        self.assertEqual(D.task_of_item('latte', 'winter'), (None, 0))

    def test_autumn_kept(self):
        autumn = D.SEASON_PLAN_TASKS['autumn']
        self.assertEqual(len(autumn), 16)
        self.assertEqual(autumn[0], ('麦田守望', 'wheat', 500))
        self.assertEqual(autumn[-1], ('便携快餐', 'steak_bowl', 50))
        self.assertNotIn('tea', [row[1] for row in autumn])
        self.assertNotIn('winter', [s for s in D.SEASON_PLAN_TASKS if s == 'spring'])

    def test_type_classification(self):
        self.assertEqual(Counter(t['type'] for t in D.WINTER_TASKS),
                         {'natural': 8, 'meal': 3, 'manufacture': 5})
        for item in WINTER_ITEMS:
            self.assertIn(D.task_type(item, 'winter'),
                          (D.TASK_TYPE_NATURAL, D.TASK_TYPE_MEAL, D.TASK_TYPE_MANUFACTURE))
        self.assertEqual(D.task_type('wheat', 'autumn'), D.TASK_TYPE_NATURAL)
        self.assertEqual(D.task_type('latte', 'autumn'), D.TASK_TYPE_MEAL)
        self.assertIsNone(D.task_type('tea', 'autumn'))
        self.assertIsNone(D.task_type(None, 'winter'))

    def test_winter_meals_are_visible_to_season_progress(self):
        from module.island.island_season_progress import season_dishes
        self.assertEqual(
            season_dishes('winter', set(ECONOMY_PRODUCTS)),
            [('chicken_potato', 100), ('rice_mango', 50), ('strawberry_charlotte', 25)])

    def test_canonical_keys_follow_existing_economy(self):
        for item in ('chicken_potato', 'rice_mango', 'strawberry_charlotte'):
            self.assertIn(item, ECONOMY_PRODUCTS)
            self.assertEqual(D.task_type(item, 'winter'), D.TASK_TYPE_MEAL)
        for item in ('tea', 'citrus', 'mango', 'avocado', 'silver', 'elegant_wood'):
            self.assertNotIn(item, ECONOMY_PRODUCTS)
        for item in ('sachet', 'clock', 'battery', 'cutlery', 'ink_cartridge'):
            self.assertNotIn(item, ECONOMY_PRODUCTS)
        # 香囊 3039 与梅花香包 4055 是不同物品，不能复用梅花香包的执行器 key
        self.assertNotEqual('sachet', 'plum_blossom_sachet')
        self.assertEqual(D.ITEM_CN['sachet'], '香囊')


class TestWinterBuffers(unittest.TestCase):
    def test_defaults_apply_to_winter_only(self):
        self.assertTrue(D.winter_task_enabled())
        self.assertEqual(D.meal_buffer(), D.DEFAULT_MEAL_BUFFER)
        self.assertEqual(D.planning_need('winter', 'tea', 500), 600)
        self.assertEqual(D.planning_need('winter', 'chicken_potato', 100), 120)
        self.assertEqual(D.planning_need('winter', 'sachet', 10), 10)
        for season in ('autumn', 'spring', 'summer'):
            self.assertEqual(D.planning_need(season, 'tea', 500), 500)
            self.assertEqual(D.planning_need(season, 'chicken_potato', 100), 100)

    def test_natural_reserve_is_fixed(self):
        cfg = FakeConfig({D.MEAL_BUFFER_KEY: 0})
        self.assertEqual(D.configured_planning_need(cfg, 'winter', 'citrus', 500), 600)
        self.assertEqual(D.configured_planning_need(cfg, 'winter', 'silver', 25), 125)
        self.assertEqual(D.configured_planning_need(cfg, 'winter', 'elegant_wood', 25), 125)
        self.assertEqual(D.configured_planning_need(cfg, 'winter', 'mango', 200), 300)

    def test_meal_buffer_can_be_zero_and_is_non_negative(self):
        zero = FakeConfig({D.MEAL_BUFFER_KEY: 0})
        self.assertEqual(D.meal_buffer(zero), 0)
        self.assertEqual(D.configured_planning_need(zero, 'winter', 'rice_mango', 50), 50)
        negative = FakeConfig({D.MEAL_BUFFER_KEY: -5})
        self.assertEqual(D.meal_buffer(negative), 0)
        invalid = FakeConfig({D.MEAL_BUFFER_KEY: 'abc'})
        self.assertEqual(D.meal_buffer(invalid), D.DEFAULT_MEAL_BUFFER)
        numeric = FakeConfig({D.MEAL_BUFFER_KEY: '7'})
        self.assertEqual(D.meal_buffer(numeric), 7)
        self.assertEqual(D.planning_need('winter', 'rice_mango', 50, meal_buffer_value='abc'),
                         D.DEFAULT_MEAL_BUFFER + 50)
        self.assertEqual(D.planning_need('winter', 'rice_mango', 'abc'), 0)

    def test_nonfinite_config_uses_default_need_and_buffer(self):
        # Add by MHY, 非有限值既不是无限需求，也不应中断整轮排产。
        for raw in (float('inf'), float('-inf'), float('nan'), '1e400', 10 ** 400):
            with self.subTest(raw=str(raw)):
                config = FakeConfig({f'{GROUP}.Need_cutlery': raw, D.MEAL_BUFFER_KEY: raw})
                self.assertEqual(D.configured_need(config, 'cutlery', 10), 10)
                self.assertEqual(D.meal_buffer(config), D.DEFAULT_MEAL_BUFFER)

    def test_winter_switch_disables_all_buffers(self):
        for value in (False, 'false', '0', 0):
            cfg = FakeConfig({D.WINTER_ENABLED_KEY: value, D.MEAL_BUFFER_KEY: 20})
            self.assertFalse(D.winter_task_enabled(cfg))
            self.assertEqual(D.configured_planning_need(cfg, 'winter', 'tea', 500), 500)
            self.assertEqual(D.configured_planning_need(cfg, 'winter', 'chicken_potato', 100), 100)
            self.assertEqual(D.winter_plan_tasks(cfg), [])
        for value in (True, 'true', '1', 1):
            cfg = FakeConfig({D.WINTER_ENABLED_KEY: value})
            self.assertTrue(D.winter_task_enabled(cfg))

    def test_winter_plan_tasks_uses_configured_need(self):
        cfg = FakeConfig({
            f'{GROUP}.Need_mango': 200,
            f'{GROUP}.Need_tea': 0,
            D.MEAL_BUFFER_KEY: 0,
        })
        rows = {row['item']: row for row in D.winter_plan_tasks(cfg)}
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows['mango']['need'], 200)
        self.assertEqual(rows['mango']['target'], 300)
        self.assertEqual(rows['tea']['target'], 0)  # Need 0 表示不补，不加自然储备
        self.assertEqual(rows['chicken_potato']['target'], 100)
        self.assertEqual(rows['battery']['target'], 10)
        self.assertEqual(rows['sachet']['type'], D.TASK_TYPE_MANUFACTURE)
        default_rows = {row['item']: row for row in D.winter_plan_tasks()}
        self.assertEqual(default_rows['mango']['need'], 250)
        self.assertEqual(default_rows['mango']['target'], 350)
        self.assertEqual(default_rows['chicken_potato']['target'], 120)


class TestConfigEntries(unittest.TestCase):
    def test_argument_yaml_has_winter_options_and_slots(self):
        args = read_file(filepath_argument('argument'))['IslandSeasonPlan']
        self.assertEqual(args['WinterTaskEnabled']['value'], True)
        self.assertEqual(args['WinterTaskEnabled']['option'], [True, False])
        self.assertEqual(args['MealBuffer']['value'], 20)
        self.assertEqual(args['MealBuffer']['validate'], [0, 999])
        for item in WINTER_ITEMS:
            need_key = f'Need_{item}'
            done_key = f'Done_{item}'
            self.assertIn(need_key, args)
            self.assertEqual(args[need_key]['value'], NEED_DEFAULTS[item])
            self.assertIn(done_key, args)
            self.assertEqual(args[done_key]['value'], False)
        self.assertNotIn('Need_Silver', args)
        self.assertNotIn('Need_Elegant', args)

    def test_generated_args_and_template(self):
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            args = json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']
        with open('config/template.json', encoding='utf-8') as f:
            template = json.load(f)['IslandSeasonPlan']['IslandSeasonPlan']
        self.assertEqual(args['MealBuffer']['value'], 20)
        self.assertEqual(template['MealBuffer'], 20)
        self.assertTrue(template['WinterTaskEnabled'])
        for item in WINTER_ITEMS:
            self.assertEqual(args[f'Need_{item}']['value'], NEED_DEFAULTS[item])
            self.assertEqual(template[f'Need_{item}'], NEED_DEFAULTS[item])
            self.assertFalse(template[f'Done_{item}'])

    def test_generated_config_class(self):
        self.assertTrue(GeneratedConfig.IslandSeasonPlan_WinterTaskEnabled)
        self.assertEqual(GeneratedConfig.IslandSeasonPlan_MealBuffer, 20)
        self.assertEqual(GeneratedConfig.IslandSeasonPlan_Need_mango, 200)
        self.assertEqual(GeneratedConfig.IslandSeasonPlan_Need_silver, 25)
        self.assertEqual(GeneratedConfig.IslandSeasonPlan_Need_elegant_wood, 25)
        self.assertFalse(GeneratedConfig.IslandSeasonPlan_Done_battery)


class TestTranslations(unittest.TestCase):
    def test_four_languages_have_complete_new_entries(self):
        for lang in ('zh-CN', 'zh-TW', 'en-US', 'ja-JP'):
            with open(f'module/config/i18n/{lang}.json', encoding='utf-8') as f:
                group = json.load(f)['IslandSeasonPlan']
            self.assertIn('_info', group)
            for key, expected_name in I18N_NAMES[lang].items():
                self.assertEqual(group[key]['name'], expected_name, (lang, key))
            for item in WINTER_ITEMS:
                for prefix in ('Need_', 'Done_'):
                    key = f'{prefix}{item}'
                    self.assertIn(key, group, (lang, key))
                    self.assertTrue(group[key]['name'])
                    self.assertTrue(group[key]['help'])
                    self.assertNotIn('IslandSeasonPlan.', group[key]['name'])
                    self.assertNotIn('IslandSeasonPlan.', group[key]['help'])
                self.assertIn(group[f'Done_{item}']['True'], ('开启', '開啟', 'On', 'オン'))
                self.assertIn(group[f'Done_{item}']['False'], ('关闭', '關閉', 'Off', 'オフ'))
            self.assertNotEqual(group['WinterTaskEnabled']['True'], 'True')
            self.assertNotEqual(group['WinterTaskEnabled']['False'], 'False')


if __name__ == '__main__':
    unittest.main()
