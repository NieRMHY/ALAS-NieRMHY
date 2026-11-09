"""冬季开发计划自然资源下限叠加：开关、Done、高日常底、鱼肉 keep 与未知库存。"""

import unittest
from unittest.mock import Mock, patch

import module.config.server as server

server.server = 'cn'

from module.island import island_season_plan_data as season_data  # noqa: E402
from module.island import island_winter_resources as winter  # noqa: E402
from module.island.farm_targets import overlay_targets  # noqa: E402
from module.island.island import Island  # noqa: E402
from module.island.island_farm import IslandFarm  # noqa: E402
from module.island.island_fish_meat import (  # noqa: E402
    FISH_MEAT_YIELD,
    FRESHWATER_FISH_MEAT,
    SALTWATER_FISH_MEAT,
    plan_fish_exchange,
)
from module.island.island_mine_forest import IslandMineForest  # noqa: E402


GROUP = 'IslandSeasonPlan.IslandSeasonPlan'


class FakeConfig:
    """只实现 cross_get 的配置替身。

    同时记录 cross_set 调用：叠加必须只在运行时生效，不能写回任何阈值配置。
    """

    def __init__(self, season='winter', values=None, **attrs):
        self.values = {'IslandPlan.IslandPlan.Season': season}
        self.values.update(values or {})
        self.writes = []
        self.__dict__.update(attrs)

    def cross_get(self, keys, default=None):
        return self.values.get(keys, default)

    def cross_set(self, keys, value):
        self.writes.append((keys, value))

    def cross_set_many(self, values):
        self.writes.extend(values.items())


def need(item, amount):
    return {f'{GROUP}.Need_{item}': amount}


def done(item):
    return {f'{GROUP}.Done_{item}': True}


def make_farm(season='winter', crop_targets=None, values=None, **attrs):
    crop_targets = crop_targets or {}
    config = FakeConfig(
        season=season,
        values=values,
        **{
            'IslandFarm_Positions': 1,
            'IslandOrchard_Positions': 1,
            'IslandNursery_Positions': 1,
            'IslandFarm_MinFarm': 660,
            'IslandOrchard_MinOrchard': 300,
            'IslandNursery_MinNursery': 0,
            'IslandFarm_CropTargets': crop_targets.get('farm', ''),
            'IslandOrchard_CropTargets': crop_targets.get('orchard', ''),
            'IslandNursery_CropTargets': crop_targets.get('nursery', ''),
            'IslandFarm_WorkerFilter': 'WorkerJuu',
            'IslandOrchard_WorkerFilter': 'WorkerJuu',
            'IslandNursery_WorkerFilter': 'WorkerJuu',
            'IslandOrchard_IgnoreAvocado': True,
            'IslandNursery_IgnorePineapple': True,
            'IslandFarm_PlantPotatoes': 0,
            'IslandFarm_DefaultCrop': 'wheat',
            'IslandOrchard_PlantRubber': 0,
            'IslandOrchard_DefaultCrop': 'rubber',
            'IslandNursery_PlantLavender': 0,
            'IslandNursery_DefaultCrop': 'lavender',
            **attrs,
        }
    )

    def init_island(farm, config, device=None, task=None):
        farm.config = config
        farm.device = Mock()

    with patch.object(Island, '__init__', init_island):
        return IslandFarm(config)


def prepare_farm(farm, inventories):
    farm.warehouse_inventory = Mock(side_effect=lambda category: dict(inventories[category]))
    farm.check_inventory_and_prepare_lists()
    return farm.to_plant_lists


def make_mine(season='winter', values=None, **attrs):
    config = FakeConfig(
        season=season,
        values=values,
        **{
            'IslandMine_WorkerFilter': 'WorkerJuu',
            'IslandForest_WorkerFilter': 'WorkerJuu',
            'IslandMine_MinSilver': 0,
            'IslandForest_MinElegant': 0,
            **attrs,
        }
    )

    def init_island(mine, config, device=None, task=None):
        mine.config = config
        mine.device = Mock()

    with patch.object(Island, '__init__', init_island):
        return IslandMineForest(config)


ORCHARD_STOCK = {
    'apple': 500, 'citrus': 100, 'banana': 500, 'mango': 100,
    'lemon': 500, 'avocado': 100, 'rubber': 500,
}
NURSERY_STOCK = {
    'carrot': 0, 'onion': 0, 'flax': 0, 'strawberry': 0, 'cotton': 0,
    'tea': 100, 'lavender': 0, 'pineapple': 0, 'asparagus': 0,
}


class WinterTargetTests(unittest.TestCase):
    def test_missing_keys_fall_back_to_defaults(self):
        config = FakeConfig()
        self.assertEqual(winter.active_task_needs(config), {
            'tea': 600, 'citrus': 600, 'mango': 350, 'avocado': 200,
            'freshwater_fish_meat': 200, 'seawater_fish_meat': 200,
            'silver': 125, 'elegant_wood': 125,
        })

    def test_done_removes_the_override(self):
        config = FakeConfig(values=done('tea'))
        self.assertNotIn('tea', winter.active_task_needs(config))
        self.assertEqual(winter.crop_task_targets(config, 'nursery'), {})

    def test_zero_need_removes_the_override(self):
        config = FakeConfig(values=need('citrus', 0))
        self.assertNotIn('citrus', winter.active_task_needs(config))
        self.assertEqual(winter.crop_task_targets(config, 'orchard')['mango'], 350)

    def test_disabled_or_offseason_keeps_legacy_behaviour(self):
        disabled = FakeConfig(values={f'{GROUP}.WinterTaskEnabled': False})
        self.assertEqual(winter.active_task_needs(disabled), {})
        autumn = FakeConfig(season='autumn')
        self.assertEqual(winter.active_task_needs(autumn), {})
        self.assertEqual(winter.ore_threshold(autumn, 'Silver', 0), 0)
        self.assertEqual(winter.exchange_targets(autumn, {FRESHWATER_FISH_MEAT: 0}),
                         {FRESHWATER_FISH_MEAT: 0})

    def test_mango_default_follows_season_table_and_config_can_override(self):
        # 缺键时按赛季表（游戏实际 250），配置默认 200 由 argument.yaml 决定
        self.assertEqual(winter.task_need(FakeConfig(), 'mango'), 250)
        configured = FakeConfig(values=need('mango', 200))
        self.assertEqual(winter.active_task_needs(configured)['mango'], 300)
        raised = FakeConfig(values=need('mango', 250))
        self.assertEqual(winter.active_task_needs(raised)['mango'], 350)

    def test_seawater_accepts_saltwater_alias(self):
        config = FakeConfig(values={'IslandSeasonPlan.IslandSeasonPlan.Need_saltwater_fish_meat': 50})
        self.assertEqual(winter.task_need(config, 'seawater_fish_meat'), 50)
        done_config = FakeConfig(values={'IslandSeasonPlan.IslandSeasonPlan.Done_saltwater_fish_meat': True})
        self.assertTrue(winter.task_done(done_config, 'seawater_fish_meat'))

    def test_crop_targets_belong_to_their_own_area(self):
        config = FakeConfig()
        self.assertEqual(winter.crop_task_targets(config, 'farm'), {})
        self.assertEqual(winter.protected_crops(config, 'nursery'), {'tea'})
        self.assertEqual(set(winter.protected_crops(config, 'orchard')),
                         {'citrus', 'mango', 'avocado'})

    def test_ore_threshold_never_lowers_the_daily_floor(self):
        config = FakeConfig()
        self.assertEqual(winter.ore_threshold(config, 'Silver', 0), 125)
        self.assertEqual(winter.ore_threshold(config, 'Elegant', 500), 500)
        self.assertEqual(winter.ore_threshold(config, 'Copper', 40), 40)

    def test_fish_meat_only_raises_the_exchange_target(self):
        config = FakeConfig()
        base = {FRESHWATER_FISH_MEAT: 0, SALTWATER_FISH_MEAT: 300}
        merged = winter.exchange_targets(config, base)
        self.assertEqual(merged, {FRESHWATER_FISH_MEAT: 200, SALTWATER_FISH_MEAT: 300})
        self.assertEqual(base, {FRESHWATER_FISH_MEAT: 0, SALTWATER_FISH_MEAT: 300})

    def test_fish_meat_never_enters_planting_targets(self):
        config = FakeConfig()
        crops = set()
        for area in ('farm', 'orchard', 'nursery'):
            crops |= set(winter.crop_task_targets(config, area))
        self.assertFalse(crops & {'freshwater_fish_meat', 'seawater_fish_meat'})
        self.assertEqual(winter.ore_task_target(config, 'freshwater_fish_meat'), 0)


class WinterDataConsistencyTests(unittest.TestCase):
    """冬季自然资源清单必须复用赛季表，不能各写一份 ID/默认值。"""

    def test_catalog_reuses_season_plan_data(self):
        natural = [task for task in season_data.WINTER_TASKS
                   if task['type'] == season_data.TASK_TYPE_NATURAL]
        self.assertEqual(list(winter.WINTER_TASK_ITEMS), [task['item'] for task in natural])
        for task in natural:
            info = winter.WINTER_TASK_ITEMS[task['item']]
            self.assertEqual(info['item_id'], task['item_id'])
            self.assertEqual(info['default_need'], task['need'])
            self.assertEqual(info['cn_name'], season_data.ITEM_CN[task['item']])

    def test_buffer_and_group_share_season_data(self):
        self.assertEqual(winter.TASK_BUFFER, season_data.WINTER_NATURAL_RESERVE)
        self.assertEqual(winter.GROUP, season_data.CONFIG_GROUP)

    def test_fish_meat_ids_match_exchange_module(self):
        self.assertEqual(winter.WINTER_TASK_ITEMS['freshwater_fish_meat']['meat_id'],
                         FRESHWATER_FISH_MEAT)
        self.assertEqual(winter.WINTER_TASK_ITEMS['seawater_fish_meat']['meat_id'],
                         SALTWATER_FISH_MEAT)

    def test_done_accepts_string_flags(self):
        on = FakeConfig(values={f'{GROUP}.Done_tea': 'true'})
        off = FakeConfig(values={f'{GROUP}.Done_tea': 'false'})
        self.assertTrue(winter.task_done(on, 'tea'))
        self.assertFalse(winter.task_done(off, 'tea'))

    def test_invalid_need_falls_back_and_negative_is_zero(self):
        invalid = FakeConfig(values=need('tea', 'abc'))
        negative = FakeConfig(values=need('citrus', -5))
        decimal = FakeConfig(values=need('tea', '250.0'))
        self.assertEqual(winter.task_need(invalid, 'tea'), 500)
        self.assertEqual(winter.task_need(negative, 'citrus'), 0)
        self.assertEqual(winter.task_need(decimal, 'tea'), 250)
        self.assertNotIn('citrus', winter.active_task_needs(negative))

    def test_switch_accepts_string_false(self):
        config = FakeConfig(values={f'{GROUP}.WinterTaskEnabled': 'false'})
        self.assertFalse(winter.winter_task_enabled(config))
        self.assertEqual(winter.active_task_needs(config), {})


class OverlayTargetsTests(unittest.TestCase):
    def test_missing_crop_uses_the_area_threshold_as_floor(self):
        self.assertEqual(overlay_targets({}, {'citrus': 600}, 300), {'citrus': 600})
        self.assertEqual(overlay_targets({}, {'silver': 100}, 500), {'silver': 500})

    def test_existing_higher_target_is_kept(self):
        self.assertEqual(overlay_targets({'citrus': 700}, {'citrus': 600}, 300), {'citrus': 700})

    def test_input_is_not_modified(self):
        targets = {'citrus': 100}
        overlay_targets(targets, {'citrus': 600}, 300)
        self.assertEqual(targets, {'citrus': 100})


class FarmOverlayTests(unittest.TestCase):
    def test_winter_tasks_are_restocked_even_for_ignored_avocado(self):
        farm = make_farm()
        lists = prepare_farm(farm, {
            'farm': {}, 'orchard': ORCHARD_STOCK, 'nursery': NURSERY_STOCK,
        })
        self.assertEqual(set(lists['orchard']), {'citrus', 'mango', 'avocado'})
        self.assertEqual(lists['nursery'], ['tea'])
        # 叠加只在运行时生效：配置里的 CropTargets 与阈值都没被改写
        self.assertEqual(farm.crop_targets['orchard'], {})
        self.assertEqual(farm.config.writes, [])
        self.assertEqual(farm.config.IslandOrchard_MinOrchard, 300)

    def test_disabled_task_returns_to_ignore_avocado(self):
        farm = make_farm(values={f'{GROUP}.WinterTaskEnabled': False})
        lists = prepare_farm(farm, {
            'farm': {}, 'orchard': ORCHARD_STOCK, 'nursery': NURSERY_STOCK,
        })
        self.assertEqual(set(lists['orchard']), {'citrus', 'mango'})
        self.assertEqual(lists['nursery'], [])

    def test_non_winter_season_keeps_old_behaviour(self):
        farm = make_farm(season='summer')
        lists = prepare_farm(farm, {
            'farm': {}, 'orchard': ORCHARD_STOCK, 'nursery': NURSERY_STOCK,
        })
        self.assertEqual(set(lists['orchard']), {'citrus', 'mango'})
        self.assertEqual(lists['nursery'], [])

    def test_higher_daily_crop_target_is_not_lowered(self):
        farm = make_farm(crop_targets={'orchard': 'citrus: 700'})
        stock = dict(ORCHARD_STOCK, citrus=650)
        lists = prepare_farm(farm, {'farm': {}, 'orchard': stock, 'nursery': NURSERY_STOCK})
        # 650 < 700 所以仍然补种；若叠加把目标压到 600 就会漏掉
        self.assertIn('citrus', lists['orchard'])
        self.assertEqual(farm.crop_targets['orchard'], {'citrus': 700})

    def test_repeated_runs_do_not_accumulate(self):
        farm = make_farm()
        inventories = {'farm': {}, 'orchard': ORCHARD_STOCK, 'nursery': NURSERY_STOCK}
        prepare_farm(farm, inventories)
        first = {category: list(crops) for category, crops in farm.to_plant_lists.items()}
        prepare_farm(farm, inventories)
        self.assertEqual(farm.to_plant_lists, first)
        self.assertEqual(farm.config.writes, [])

    def test_done_task_stops_the_override(self):
        farm = make_farm(values=done('tea'))
        lists = prepare_farm(farm, {
            'farm': {}, 'orchard': ORCHARD_STOCK, 'nursery': NURSERY_STOCK,
        })
        self.assertEqual(lists['nursery'], [])


class MineForestOverlayTests(unittest.TestCase):
    def test_winter_need_raises_the_threshold(self):
        mine = make_mine()
        self.assertEqual(mine._get_threshold('Silver'), 125)
        self.assertEqual(mine._get_threshold('Elegant'), 125)
        self.assertEqual(mine._get_threshold('Copper'), 0)

    def test_higher_daily_threshold_is_kept(self):
        mine = make_mine(IslandMine_MinSilver=500)
        self.assertEqual(mine._get_threshold('Silver'), 500)

    def test_disabled_task_and_non_winter_keep_the_configured_value(self):
        mine = make_mine(IslandMine_MinSilver=40, IslandForest_MinElegant=30,
                         values={f'{GROUP}.WinterTaskEnabled': False})
        self.assertEqual(mine._get_threshold('Silver'), 40)
        summer = make_mine(season='summer', IslandMine_MinSilver=40, IslandForest_MinElegant=30)
        self.assertEqual(summer._get_threshold('Silver'), 40)
        self.assertEqual(summer._get_threshold('Elegant'), 30)

    def test_done_flag_returns_to_the_configured_threshold(self):
        mine = make_mine(IslandMine_MinSilver=40, IslandForest_MinElegant=30,
                         values=done('silver'))
        self.assertEqual(mine._get_threshold('Silver'), 40)
        self.assertEqual(mine._get_threshold('Elegant'), 125)

    def test_zero_need_returns_to_the_configured_threshold(self):
        mine = make_mine(IslandMine_MinSilver=40, values=need('silver', 0))
        self.assertEqual(mine._get_threshold('Silver'), 40)

    def test_inventory_check_plans_silver_production(self):
        mine = make_mine()
        mine.posts = {}
        mine.mine_post_ids = []
        mine.forest_post_ids = []
        mine.warehouse_inventory = Mock(side_effect=lambda category: (
            {'Copper': 0, 'Aluminium': 0, 'Iron': 0, 'Sulphur': 0, 'Silver': 120}
            if category == 'mine' else
            {'Elegant': 120, 'Practical': 0, 'Selected': 0}))
        needs = mine.check_inventory_and_prepare_lists()
        self.assertIn('Silver', needs['mine'])
        self.assertIn('Elegant', needs['forest'])
        self.assertEqual(mine.needs_count[('mine', 'Silver')], 5)


class FishMeatOverlayTests(unittest.TestCase):
    def test_unknown_inventory_stays_unknown(self):
        config = FakeConfig()
        merged = winter.exchange_targets(config, {FRESHWATER_FISH_MEAT: -1, SALTWATER_FISH_MEAT: 0})
        self.assertEqual(merged[FRESHWATER_FISH_MEAT], -1)
        self.assertEqual(merged[SALTWATER_FISH_MEAT], 200)

    def test_done_flag_keeps_the_original_exchange_target(self):
        config = FakeConfig(values=done('freshwater_fish_meat'))
        self.assertEqual(
            winter.exchange_targets(config, {FRESHWATER_FISH_MEAT: 0}),
            {FRESHWATER_FISH_MEAT: 0})

    def test_zero_need_keeps_the_original_exchange_target(self):
        config = FakeConfig(values=need('seawater_fish_meat', 0))
        self.assertEqual(
            winter.exchange_targets(config, {SALTWATER_FISH_MEAT: 0}),
            {SALTWATER_FISH_MEAT: 0})

    def test_keep_is_honoured_when_target_is_raised(self):
        fish_id = 5002  # catfish
        per_fish = FISH_MEAT_YIELD[fish_id]
        amounts = plan_fish_exchange({fish_id: 5}, per_fish * 3, keep={fish_id: 4})
        self.assertEqual(amounts, {fish_id: 1})

    def test_unknown_fish_stock_is_not_exchanged(self):
        self.assertEqual(plan_fish_exchange({5002: -1}, 100, keep={5002: 0}), {})


if __name__ == '__main__':
    unittest.main()
