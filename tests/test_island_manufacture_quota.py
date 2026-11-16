"""冬季制造任务有限配额：缺口、未知挂起、能力边界与执行集成。"""

import unittest
from unittest.mock import Mock, patch

from module.island import island_manufacture as manufacture_module
from module.island import island_manufacture_quota as quota
from module.island import island_season_plan_data as season_data
from module.island.island_manufacture import IslandManufacture
from module.island.island_shop_base import IslandShopBase
from module.island_planner.data import DIC_ISLAND_RECIPE


class FakeConfig:
    """只实现 cross_get 的配置桩，未配置的键返回调用方给的默认值。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.paths = []

    def cross_get(self, path, default=None):
        self.paths.append(path)
        return self.values.get(path, default)


def read_tasks(config=None):
    """读取默认冬季任务（need 取赛季表数量）。"""
    _, tasks = quota.read_winter_task_settings(config or FakeConfig())
    return tasks


def by_key(tasks, key):
    return next(task for task in tasks if task['key'] == key)


def base_state(**overrides):
    state = {
        'stock': {'cutlery': 0},
        'wip': {'cutlery': 0},
        'ordered': {},
        'post_unknown': False,
        'dependency_stock': {'cloth': None, 'sulfuric_acid': None},
    }
    state.update(overrides)
    return state


class QuotaCatalogTest(unittest.TestCase):
    def test_five_winter_tasks_and_ids(self):
        self.assertEqual([task['key'] for task in quota.WINTER_TASKS],
                         ['sachet', 'cutlery', 'ink_cartridge', 'clock', 'battery'])
        ids = {task['key']: task['item_id'] for task in quota.WINTER_TASKS}
        self.assertEqual(ids, {
            'sachet': 3039, 'cutlery': 3047, 'ink_cartridge': 3053,
            'clock': 3054, 'battery': 3055,
        })

    def test_catalog_reuses_season_data(self):
        """任务 ID/物品 ID/需求/中文名必须来自赛季表，不能各写一份。"""
        expected = [task for task in season_data.WINTER_TASKS
                    if task['type'] == season_data.TASK_TYPE_MANUFACTURE]
        self.assertEqual(len(quota.WINTER_TASKS), len(expected))
        for spec, source in zip(quota.WINTER_TASKS, expected):
            self.assertEqual(spec['item'], source['item'])
            self.assertEqual(spec['task_id'], source['task_id'])
            self.assertEqual(spec['item_id'], source['item_id'])
            self.assertEqual(spec['default_need'], source['need'])
            self.assertEqual(spec['cn'], season_data.ITEM_CN[source['item']])

    def test_batch_limit_comes_from_recipe(self):
        for spec in quota.WINTER_TASKS:
            limit = next(recipe['production_limit'] for recipe in DIC_ISLAND_RECIPE.values()
                         if spec['item_id'] in recipe.get('commission_product', {}))
            self.assertEqual(spec['batch_limit'], limit)

    def test_only_cutlery_is_dispatchable(self):
        dispatchable = [task['key'] for task in quota.WINTER_TASKS
                        if task['capability'] == quota.CAPABILITY_DISPATCHABLE]
        self.assertEqual(dispatchable, ['cutlery'])

    def test_asset_audit_matches_capabilities(self):
        tasks = {task['key']: task for task in quota.WINTER_TASKS}
        self.assertEqual(tasks['ink_cartridge']['capability'], quota.CAPABILITY_SELECT_ONLY)
        for key in ('sachet', 'clock', 'battery'):
            self.assertEqual(tasks[key]['capability'], quota.CAPABILITY_NO_ASSETS)
        self.assertEqual(quota.DEPENDENCY_ITEMS['cloth']['capability'],
                         quota.CAPABILITY_SELECT_ONLY)
        self.assertEqual(quota.DEPENDENCY_ITEMS['sulfuric_acid']['capability'],
                         quota.CAPABILITY_NO_ASSETS)

    def test_plum_blossom_sachet_is_not_used_for_sachet(self):
        for task in quota.WINTER_TASKS:
            self.assertNotIn('plum_blossom_sachet', task['item'])
        self.assertIn('4055', quota.WINTER_TASKS[0]['note'])
        self.assertIn('梅花香包', quota.WINTER_TASKS[0]['note'])


class QuotaSettingsTest(unittest.TestCase):
    def test_defaults_come_from_season_table(self):
        config = FakeConfig()
        enabled, tasks = quota.read_winter_task_settings(config)
        self.assertTrue(enabled)
        defaults = {task['item']: task['need'] for task in season_data.WINTER_TASKS
                    if task['type'] == season_data.TASK_TYPE_MANUFACTURE}
        for task in tasks:
            self.assertEqual(task['need'], defaults[task['item']])
            self.assertFalse(task['done'])

    def test_reads_cross_get_paths(self):
        config = FakeConfig({
            'IslandSeasonPlan.IslandSeasonPlan.Need_cutlery': 3,
            'IslandSeasonPlan.IslandSeasonPlan.Done_cutlery': True,
        })
        enabled, tasks = quota.read_winter_task_settings(config)
        self.assertTrue(enabled)
        cutlery = by_key(tasks, 'cutlery')
        self.assertEqual(cutlery['need'], 3)
        self.assertTrue(cutlery['done'])
        self.assertIn('IslandSeasonPlan.IslandSeasonPlan.Need_cutlery', config.paths)
        self.assertIn('IslandSeasonPlan.IslandSeasonPlan.Done_sachet', config.paths)

    def test_string_and_negative_need_values(self):
        config = FakeConfig({
            'IslandSeasonPlan.IslandSeasonPlan.Need_cutlery': '4',
            'IslandSeasonPlan.IslandSeasonPlan.Need_sachet': -2,
            'IslandSeasonPlan.IslandSeasonPlan.Done_clock': 'false',
            'IslandSeasonPlan.IslandSeasonPlan.Done_battery': 'true',
        })
        _, tasks = quota.read_winter_task_settings(config)
        self.assertEqual(by_key(tasks, 'cutlery')['need'], 4)
        self.assertEqual(by_key(tasks, 'sachet')['need'], 0)
        self.assertFalse(by_key(tasks, 'clock')['done'])
        self.assertTrue(by_key(tasks, 'battery')['done'])

    def test_winter_only_and_switch(self):
        self.assertTrue(quota.season_quota_enabled('winter', True))
        self.assertFalse(quota.season_quota_enabled('autumn', True))
        self.assertFalse(quota.season_quota_enabled('winter', False))
        self.assertFalse(quota.season_quota_enabled('winter', 'false'))


class QuotaPlanTest(unittest.TestCase):
    def plan(self, key, stock=0, wip=0, ordered=0, posts=2, post_unknown=False, **task_overrides):
        tasks = read_tasks()
        task = by_key(tasks, key)
        task.update(task_overrides)
        state = base_state(
            stock={task['item']: stock},
            wip={task['item']: wip},
            ordered={task['item']: ordered},
            post_unknown=post_unknown,
        )
        return quota.plan_winter_quota([task], state, {task['line']: posts})

    def test_gap_formula(self):
        decision = self.plan('cutlery', stock=3, wip=2, ordered=1)['items'][0]
        self.assertEqual(decision['gap'], 4)
        self.assertEqual(decision['status'], 'dispatch')

    def test_unknown_stock_suspends_instead_of_zero(self):
        decision = self.plan('cutlery', stock=None, posts=2)['items'][0]
        self.assertEqual(decision['status'], 'suspended')
        self.assertEqual(decision['reason'], 'unknown_stock')
        self.assertEqual(decision['batches'], [])

    def test_unknown_wip_suspends(self):
        decision = self.plan('cutlery', wip=None)['items'][0]
        self.assertEqual(decision['status'], 'suspended')
        self.assertEqual(decision['reason'], 'unknown_wip')

    def test_unknown_active_post_suspends_all_dispatch(self):
        decision = self.plan('cutlery', post_unknown=True)['items'][0]
        self.assertEqual(decision['status'], 'suspended')
        self.assertEqual(decision['reason'], 'unknown_active_post')

    def test_done_flag_removes_only_the_task_increment(self):
        decision = self.plan('cutlery', done=True)['items'][0]
        self.assertEqual(decision['status'], 'done')
        self.assertEqual(decision['reason'], 'done_flag')
        self.assertEqual(decision['batches'], [])

    def test_gap_zero_means_done(self):
        decision = self.plan('cutlery', stock=10)['items'][0]
        self.assertEqual(decision['status'], 'done')
        self.assertEqual(decision['reason'], 'gap_zero')

    def test_batches_are_finite_and_split_across_posts(self):
        plan = self.plan('cutlery', posts=2)
        self.assertEqual(plan['batches']['cutlery'], [5, 5])
        self.assertEqual(sum(plan['batches']['cutlery']), 10)

    def test_multi_post_does_not_duplicate_the_gap(self):
        plan = self.plan('cutlery', stock=7, posts=2)  # 缺口 3，两个空岗
        self.assertEqual(plan['batches']['cutlery'], [3])
        self.assertLessEqual(sum(plan['batches']['cutlery']), 3)

    def test_partial_last_batch(self):
        plan = self.plan('cutlery', stock=3, posts=2)  # 缺口 7 -> 5 + 2
        self.assertEqual(plan['batches']['cutlery'], [5, 2])

    def test_no_idle_post_waits(self):
        decision = self.plan('cutlery', posts=0)['items'][0]
        self.assertEqual(decision['status'], 'no_post')
        self.assertEqual(decision['batches'], [])

    def test_ink_cartridge_is_never_dispatched(self):
        plan = self.plan('ink_cartridge', stock=0, posts=2)
        decision = plan['items'][0]
        self.assertEqual(decision['status'], 'blocked')
        self.assertEqual(decision['reason'], quota.CAPABILITY_SELECT_ONLY)
        self.assertNotIn('ink_cartridge', plan['batches'])

    def test_missing_asset_items_are_not_dispatched(self):
        for key in ('sachet', 'clock', 'battery'):
            plan = self.plan(key, posts=2)
            self.assertEqual(plan['items'][0]['status'], 'blocked')
            self.assertEqual(plan['batches'], {})

    def test_unknown_dependency_suspends(self):
        tasks = read_tasks()
        task = by_key(tasks, 'sachet')
        task['capability'] = quota.CAPABILITY_DISPATCHABLE
        task['line'] = 'handmade'
        state = base_state(stock={'sachet': 0}, wip={'sachet': 0})
        decision = quota.plan_winter_quota([task], state, {'handmade': 2})['items'][0]
        self.assertEqual(decision['status'], 'suspended')
        self.assertEqual(decision['reason'], 'dependency_unknown:布料')

    def test_known_dependency_allows_dispatch(self):
        tasks = read_tasks()
        task = by_key(tasks, 'sachet')
        task['capability'] = quota.CAPABILITY_DISPATCHABLE
        task['line'] = 'handmade'
        state = base_state(
            stock={'sachet': 8}, wip={'sachet': 0},
            dependency_stock={'cloth': 2, 'sulfuric_acid': 0},
        )
        decision = quota.plan_winter_quota([task], state, {'handmade': 2})['items'][0]
        self.assertEqual(decision['status'], 'dispatch')
        self.assertEqual(decision['batches'], [2])


class QuotaIntegrationTest(unittest.TestCase):
    def setUp(self):
        patcher = patch('module.island.island_manufacture.logger')
        self.logger = patcher.start()
        self.addCleanup(patcher.stop)

    def make_factory(self):
        with patch.object(IslandManufacture, '__init__', lambda self: None):
            factory = IslandManufacture()
        factory.device = Mock()
        factory.device.screenshot = Mock(return_value=None)
        factory.device.click = Mock()
        factory.posts = {}
        factory.post_items = {}
        factory.post_check_meal = {}
        factory.winter_quota_ordered = {}
        factory.winter_quota_plan = None
        factory.unavailable_products = set()
        factory.post_manage_swipe_count = 2
        factory._item_cn = lambda name: name
        factory.name_to_config = {
            'cutlery': {
                'name': 'cutlery', 'template': object(), 'post_action': object(),
                'selection': 'SELECT_CUTLERY', 'selection_check': 'SELECT_CUTLERY_CHECK',
            },
        }
        factory.warehouse_counts = {}
        factory._warehouse_scanned = False
        factory.current_season = 'winter'
        factory.config = FakeConfig()
        return factory

    def prepare_selection_flow(self, factory):
        """把派遣界面相关方法打桩，只保留选品/数量/确认流程。"""
        factory.posts = {'POST1': {'status': 'idle', 'button': 'B1'}}
        factory.select_character = Mock(return_value=True)
        factory.confirm_selected_character = Mock(return_value=True)
        factory.select_product = Mock(return_value=True)
        factory.appear = Mock(side_effect=lambda button, **kwargs: (
            button is manufacture_module.ISLAND_SELECT_PRODUCT_CHECK))
        factory.appear_then_click = Mock(return_value=False)
        factory.post_add_one = Mock()
        factory.time_prefix = 'time_manufacture'
        for name in ('post_close', 'post_open', 'wait_until_appear', 'post_manage_up_swipe'):
            setattr(factory, name, Mock())

    def run_selection(self, factory, quantity, actual=5, color=(255, 255, 255),
                      colors=None):
        item = factory.name_to_config['cutlery']
        color_mock = Mock(side_effect=list(colors)) if colors else Mock(return_value=color)
        with patch.object(manufacture_module, 'get_color', color_mock), \
                patch.object(manufacture_module, 'Digit') as digit, \
                patch.object(manufacture_module, 'Duration') as duration, \
                patch.object(manufacture_module, 'current_time', Mock(return_value=0)):
            digit.return_value.ocr.return_value = actual
            duration.return_value.ocr.return_value = 0
            return factory.select_product_with_material_check(
                'POST1', [item], quantity=quantity)

    def test_finite_quantity_uses_add_one_not_post_max(self):
        factory = self.make_factory()
        self.prepare_selection_flow(factory)

        result = self.run_selection(factory, quantity=5, actual=5)

        self.assertEqual(result['name'], 'cutlery')
        factory.post_add_one.assert_called_once_with(4, interval=0.1)
        self.assertFalse(any(call.args[0] is manufacture_module.POST_MAX
                             for call in factory.appear_then_click.call_args_list))
        factory.device.click.assert_any_call(manufacture_module.POST_ADD_ORDER)
        self.assertEqual(factory._last_actual_number, 5)

    def test_finite_quantity_one_dispatches_without_add_clicks(self):
        factory = self.make_factory()
        self.prepare_selection_flow(factory)

        result = self.run_selection(factory, quantity=1, actual=1)

        self.assertEqual(result['name'], 'cutlery')
        factory.post_add_one.assert_not_called()
        factory.device.click.assert_any_call(manufacture_module.POST_ADD_ORDER)

    def test_grey_confirm_after_quantity_falls_back_to_one(self):
        """加到目标数量后确认变灰：退回按 1 件重派，不能硬点导致等待超时。"""
        factory = self.make_factory()
        self.prepare_selection_flow(factory)

        result = self.run_selection(
            factory, quantity=5, actual=1,
            colors=[(255, 255, 255), (153, 156, 156), (255, 255, 255)])

        self.assertEqual(result['name'], 'cutlery')
        factory.post_add_one.assert_called_once_with(4, interval=0.1)
        factory.device.click.assert_any_call(manufacture_module.POST_ADD_ORDER)
        factory.device.click.assert_any_call(manufacture_module.SELECT_UI_BACK)
        self.assertEqual(factory._last_actual_number, 1)

    def test_post_check_records_per_post_number(self):
        factory = self.make_factory()
        factory.posts = {'POST1': {'status': 'none', 'button': 'B1'}}

        def fake_base_post_check(inner_self, post_id, time_var_name):
            inner_self.posts[post_id]['status'] = 'working'
            product = inner_self.post_product_check()
            inner_self.post_check_meal[product] = inner_self.post_check_meal.get(product, 0) + 5

        with patch.object(IslandShopBase, 'post_check', fake_base_post_check), \
                patch.object(IslandShopBase, 'post_product_check', return_value='cutlery'):
            factory.post_check('POST1', 'time_manufacture1')

        self.assertEqual(factory.post_items['POST1'],
                         {'status': 'working', 'product': 'cutlery', 'number': 5})

    def test_post_category_groups_and_idle_lookup(self):
        factory = self.make_factory()
        self.assertEqual(factory.post_category('ISLAND_INDUSTRIAL_POST1'),
                         'industrial_production')
        self.assertIsNone(factory.post_category('P1'))
        factory.posts = {
            'ISLAND_INDUSTRIAL_POST1': {'status': 'idle'},
            'ISLAND_INDUSTRIAL_POST2': {'status': 'working'},
            'ISLAND_HANDMADE_POST1': {'status': 'idle'},
        }
        self.assertEqual(factory.get_idle_posts_by_category('industrial_production'),
                         ['ISLAND_INDUSTRIAL_POST1'])
        self.assertEqual(factory.get_idle_posts_by_category('handmade'),
                         ['ISLAND_HANDMADE_POST1'])
        self.assertEqual(factory.get_idle_posts_by_category('wood_processing'), [])

    def test_winter_quota_active_requires_winter_and_switch(self):
        factory = self.make_factory()
        self.assertTrue(factory.winter_quota_active())
        factory.current_season = 'autumn'
        self.assertFalse(factory.winter_quota_active())
        factory.current_season = 'winter'
        factory.config = FakeConfig({
            'IslandSeasonPlan.IslandSeasonPlan.WinterTaskEnabled': False,
        })
        self.assertFalse(factory.winter_quota_active())

    def test_prepare_uses_known_stock_and_gap(self):
        factory = self.make_factory()
        factory.posts = {'P1': {'status': 'idle'}, 'P2': {'status': 'idle'}}
        factory.post_items = {
            'P1': {'status': 'idle', 'product': None, 'number': None},
            'P2': {'status': 'idle', 'product': None, 'number': None},
        }
        factory._warehouse_scanned = True
        factory.warehouse_counts = {'cutlery': 3}
        factory.get_idle_posts_by_category = Mock(
            side_effect=lambda line: ['P1', 'P2'] if line == 'industrial_production' else [])

        plan = factory.prepare_winter_quota()

        self.assertEqual(plan['batches'], {'cutlery': [5, 2]})
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['gap'], 7)
        self.assertEqual(cutlery['status'], 'dispatch')
        self.assertEqual(by_key(plan['items'], 'ink_cartridge')['status'], 'blocked')

    def test_prepare_then_dispatch_end_to_end(self):
        factory = self.make_factory()
        factory.posts = {'P1': {'status': 'idle'}, 'P2': {'status': 'idle'}}
        factory.post_items = {
            'P1': {'status': 'idle', 'product': None, 'number': None},
            'P2': {'status': 'idle', 'product': None, 'number': None},
        }
        factory._warehouse_scanned = True
        factory.warehouse_counts = {'cutlery': 3}
        factory.get_idle_posts_by_category = Mock(
            side_effect=lambda line: ['P1', 'P2'] if line == 'industrial_production' else [])

        plan = factory.prepare_winter_quota()
        self.assertEqual(plan['batches'], {'cutlery': [5, 2]})

        calls = []

        def fake_select(post_id, product_list, quantity=None):
            calls.append((post_id, quantity))
            factory._last_actual_number = quantity
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)
        dispatched = factory.dispatch_winter_quota_batches('industrial_production')

        self.assertEqual(dispatched, 7)
        self.assertEqual(calls, [('P1', 5), ('P2', 2)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 7})

    def make_scheduling_factory(self, statuses, stock, products=''):
        """构造能跑 prepare + schedule 的工厂：派遣结果回写到岗位状态。"""
        factory = self.make_factory()
        factory.posts = {post: {'status': status, 'button': post}
                         for post, status in statuses.items()}
        factory.post_items = {post: {'status': status, 'product': None, 'number': None}
                              for post, status in statuses.items()}
        factory._warehouse_scanned = True
        factory.warehouse_counts = dict(stock)
        factory.config.Industrial_Products = products
        factory.manufacture = {
            'industrial_production': {
                'items': [{'name': 'iron_nail'}, {'name': 'cutlery'}],
            },
        }
        factory.get_idle_posts_by_category = Mock(side_effect=lambda line: (
            [post for post, info in factory.posts.items() if info['status'] == 'idle']
            if line == 'industrial_production' else []))
        calls = []

        def fake_select(post_id, product_list, quantity=None):
            calls.append((post_id, product_list[0]['name'], quantity))
            factory._last_actual_number = quantity if quantity is not None else 5
            factory.posts[post_id]['status'] = 'working'
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)
        return factory, calls

    def test_full_gap_uses_both_posts_once(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'idle', 'P2': 'idle'}, {'cutlery': 0})
        factory.prepare_winter_quota()
        factory.schedule_industrial_production()

        self.assertEqual(calls, [('P1', 'cutlery', 5), ('P2', 'cutlery', 5)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 10})
        self.assertTrue(all(info['status'] == 'working' for info in factory.posts.values()))

    def test_locked_post_leaves_other_post_available_for_quota(self):
        # Add by MHY, 锁定必须由真实巡检识别，并且跳过数量 OCR。
        locked = 'ISLAND_INDUSTRIAL_POST1'
        opened = 'ISLAND_INDUSTRIAL_POST2'
        factory, calls = self.make_scheduling_factory(
            {locked: 'none', opened: 'idle'}, {'cutlery': 8})
        factory.post_close = Mock()
        factory.post_open = Mock(return_value=False)
        factory.appear = Mock()
        factory.time_manufacture1 = object()

        factory.post_check(locked, 'time_manufacture1')

        self.assertEqual(factory.posts[locked]['status'], 'locked')
        self.assertIsNone(factory.time_manufacture1)
        factory.device.screenshot.assert_not_called()
        factory.appear.assert_not_called()
        plan = factory.prepare_winter_quota()
        self.assertEqual(plan['batches'], {'cutlery': [2]})
        factory.schedule_industrial_production()
        self.assertEqual(calls, [(opened, 'cutlery', 2)])

    def test_explicit_daily_orders_take_capacity_before_task(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'idle', 'P2': 'idle'}, {'cutlery': 0}, products='iron_nail > cutlery')
        factory.prepare_winter_quota()

        factory.schedule_industrial_production()

        self.assertEqual(calls, [('P1', 'iron_nail', None), ('P2', 'iron_nail', None)])
        self.assertEqual(factory.winter_quota_ordered, {})

    def test_task_recomputes_gap_after_actual_daily_order(self):
        # Add by MHY, 首岗日常派遣失败，次岗下单后再用首岗补有限缺口。
        for actual in (4, 0):
            with self.subTest(actual=actual):
                factory, calls = self.make_scheduling_factory(
                    {'P1': 'idle', 'P2': 'idle'}, {'cutlery': 3}, products='cutlery')
                factory.prepare_winter_quota()

                def fake_select(post_id, product_list, quantity=None):
                    calls.append((post_id, product_list[0]['name'], quantity))
                    if post_id == 'P1' and quantity is None:
                        return None
                    factory._last_actual_number = actual if quantity is None else quantity
                    factory.posts[post_id]['status'] = 'working'
                    return product_list[0]

                factory.select_product_with_material_check.side_effect = fake_select
                factory.schedule_industrial_production()

                expected = [('P1', 'cutlery', None), ('P2', 'cutlery', None)]
                if actual:
                    expected.append(('P1', 'cutlery', 3))
                    self.assertEqual(factory.winter_quota_ordered, {'cutlery': 3})
                else:
                    self.assertEqual(factory.winter_quota_ordered, {})
                    decision = by_key(factory.winter_quota_plan['items'], 'cutlery')
                    self.assertEqual(decision['reason'], 'unknown_wip')
                self.assertEqual(calls, expected)
                self.assertEqual(factory.post_items['P2']['number'], actual or None)

    def test_replanning_counts_new_finite_order_once(self):
        factory, calls = self.make_scheduling_factory({'P1': 'idle'}, {'cutlery': 3})
        factory.prepare_winter_quota()
        factory.dispatch_winter_quota_batches('industrial_production')
        self.assertEqual(calls, [('P1', 'cutlery', 5)])

        factory.posts['P2'] = {'status': 'idle', 'button': 'P2'}
        factory.post_items['P2'] = {'status': 'idle', 'product': None, 'number': None}
        plan = factory.prepare_winter_quota()
        self.assertEqual(plan['batches'], {'cutlery': [2]})
        factory.dispatch_winter_quota_batches('industrial_production')
        self.assertEqual(calls, [('P1', 'cutlery', 5), ('P2', 'cutlery', 2)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 7})

    def test_in_progress_gap_does_not_order_again(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'working', 'P2': 'working'}, {'cutlery': 0})
        factory.post_items = {
            'P1': {'status': 'working', 'product': 'cutlery', 'number': 5},
            'P2': {'status': 'working', 'product': 'cutlery', 'number': 5},
        }
        plan = factory.prepare_winter_quota()
        self.assertEqual(by_key(plan['items'], 'cutlery')['status'], 'done')
        self.assertEqual(by_key(plan['items'], 'cutlery')['reason'], 'gap_zero')

        factory.schedule_industrial_production()
        self.assertEqual(calls, [])

    def test_finished_gap_does_not_repeat_auto_cutlery(self):
        """任务达标后：配额不再下单，自动回退也不能继续造餐具。"""
        factory, calls = self.make_scheduling_factory(
            {'P1': 'idle', 'P2': 'idle'}, {'cutlery': 10})
        plan = factory.prepare_winter_quota()
        self.assertEqual(by_key(plan['items'], 'cutlery')['reason'], 'gap_zero')

        factory.schedule_industrial_production()
        self.assertEqual(calls, [('P1', 'iron_nail', None), ('P2', 'iron_nail', None)])

    def test_done_flag_does_not_repeat_auto_cutlery(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'idle', 'P2': 'idle'}, {'cutlery': 0})
        factory.config.values['IslandSeasonPlan.IslandSeasonPlan.Done_cutlery'] = True
        plan = factory.prepare_winter_quota()
        self.assertEqual(by_key(plan['items'], 'cutlery')['reason'], 'done_flag')

        factory.schedule_industrial_production()
        self.assertEqual(calls, [('P1', 'iron_nail', None), ('P2', 'iron_nail', None)])

    def test_explicit_products_baseline_is_preserved(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'idle'}, {'cutlery': 10}, products='cutlery > iron_nail')
        factory.prepare_winter_quota()
        factory.schedule_industrial_production()

        self.assertEqual(calls, [('P1', 'cutlery', None)])

    def test_unknown_wip_suspends_and_falls_back_to_iron_nail(self):
        factory, calls = self.make_scheduling_factory(
            {'P1': 'working', 'P2': 'idle'}, {'cutlery': 0})
        factory.post_items['P1'] = {'status': 'working', 'product': 'cutlery', 'number': None}
        plan = factory.prepare_winter_quota()
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['status'], 'suspended')
        self.assertEqual(cutlery['reason'], 'unknown_wip')

        factory.schedule_industrial_production()
        self.assertEqual(calls, [('P2', 'iron_nail', None)])

    def test_dispatch_underproduction_uses_remaining_gap(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch', 'gap': 7,
                'batches': [5, 2],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['P1', 'P2'])
        calls = []

        def fake_select(post_id, product_list, quantity=None):
            calls.append((post_id, quantity))
            factory._last_actual_number = 3 if post_id == 'P1' else quantity
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)

        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 7)
        # 第一岗实际只有 3：第二岗按剩余 4 件补，不会重复整批下单
        self.assertEqual(calls, [('P1', 5), ('P2', 4)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 7})

    def test_dispatch_overproduction_does_not_order_again(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch', 'gap': 3,
                'batches': [3],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['P1', 'P2'])
        calls = []

        def fake_select(post_id, product_list, quantity=None):
            calls.append((post_id, quantity))
            factory._last_actual_number = 5
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)

        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 5)
        self.assertEqual(calls, [('P1', 3)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 5})
        self.assertEqual(factory.winter_quota_plan['items'][0]['batches'], [])

    def test_dispatch_unknown_actual_does_not_fabricate(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch', 'gap': 5,
                'batches': [5],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['P1', 'P2'])

        def fake_select(post_id, product_list, quantity=None):
            factory._last_actual_number = 0
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)

        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 0)
        factory.select_product_with_material_check.assert_called_once()
        self.assertEqual(factory.winter_quota_ordered, {})
        # 读不到实际数量：不猜、不重复下单，缺口留到下一轮
        self.assertEqual(factory.winter_quota_plan['items'][0]['batches'], [])
        self.assertEqual(factory.post_items['P1'],
                         {'status': 'working', 'product': 'cutlery', 'number': None})

    def test_dispatch_records_post_state(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch', 'gap': 5,
                'batches': [5],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['P1'])

        def fake_select(post_id, product_list, quantity=None):
            factory._last_actual_number = 5
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)
        factory.dispatch_winter_quota_batches('industrial_production')

        self.assertEqual(factory.post_items['P1'],
                         {'status': 'working', 'product': 'cutlery', 'number': 5})

    def test_prepare_suspends_on_unknown_industrial_post(self):
        factory = self.make_factory()
        factory.posts = {'ISLAND_INDUSTRIAL_POST1': {'status': 'working'}}
        factory.post_items = {
            'ISLAND_INDUSTRIAL_POST1': {'status': 'working', 'product': None, 'number': None},
        }
        factory._warehouse_scanned = True
        factory.warehouse_counts = {'cutlery': 3}
        factory.get_idle_posts_by_category = Mock(
            side_effect=lambda line: (['ISLAND_INDUSTRIAL_POST2']
                                      if line == 'industrial_production' else []))

        plan = factory.prepare_winter_quota()

        self.assertEqual(plan['batches'], {})
        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['status'], 'suspended')
        self.assertEqual(cutlery['reason'], 'unknown_active_post')

    def test_unknown_post_on_other_line_does_not_block_cutlery(self):
        """手工线在产无识别图产品（布料）时，不能把工业线的餐具一起挂起。"""
        factory = self.make_factory()
        factory.posts = {'ISLAND_HANDMADE_POST1': {'status': 'working'}}
        factory.post_items = {
            'ISLAND_HANDMADE_POST1': {'status': 'working', 'product': None, 'number': None},
        }
        factory._warehouse_scanned = True
        factory.warehouse_counts = {'cutlery': 0}
        factory.get_idle_posts_by_category = Mock(
            side_effect=lambda line: (['ISLAND_INDUSTRIAL_POST1', 'ISLAND_INDUSTRIAL_POST2']
                                      if line == 'industrial_production' else []))

        plan = factory.prepare_winter_quota()

        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['status'], 'dispatch')
        self.assertEqual(plan['batches'], {'cutlery': [5, 5]})

    def test_prepare_suspends_on_unknown_stock(self):
        factory = self.make_factory()
        factory.post_items = {'P1': {'status': 'idle', 'product': None, 'number': None}}
        factory.get_idle_posts_by_category = Mock(
            side_effect=lambda line: ['P1'] if line == 'industrial_production' else [])

        plan = factory.prepare_winter_quota()

        cutlery = by_key(plan['items'], 'cutlery')
        self.assertEqual(cutlery['status'], 'suspended')
        self.assertEqual(cutlery['reason'], 'unknown_stock')
        self.assertEqual(plan['batches'], {})

    def test_prepare_disabled_outside_winter(self):
        factory = self.make_factory()
        factory.current_season = 'autumn'
        self.assertIsNone(factory.prepare_winter_quota())
        self.assertIsNone(factory.winter_quota_plan)

    def test_prepare_disabled_by_config(self):
        factory = self.make_factory()
        factory.config = FakeConfig({
            'IslandSeasonPlan.IslandSeasonPlan.WinterTaskEnabled': False,
        })
        self.assertIsNone(factory.prepare_winter_quota())

    def test_dispatch_consumes_batches_once(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch',
                'batches': [5, 2],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['POST1', 'POST2'])
        calls = []

        def fake_select(post_id, product_list, quantity=None):
            calls.append((post_id, quantity))
            factory._last_actual_number = quantity
            return product_list[0]

        factory.select_product_with_material_check = Mock(side_effect=fake_select)

        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 7)
        self.assertEqual(calls, [('POST1', 5), ('POST2', 2)])
        self.assertEqual(factory.winter_quota_ordered, {'cutlery': 7})
        self.assertEqual(factory.winter_quota_plan['items'][0]['batches'], [])

        calls.clear()
        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 0)
        self.assertEqual(calls, [])

    def test_dispatch_stops_when_selection_fails(self):
        factory = self.make_factory()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'cn': 'cutlery',
                'line': 'industrial_production', 'status': 'dispatch',
                'batches': [5, 5],
            }],
        }
        factory.get_idle_posts_by_category = Mock(return_value=['POST1', 'POST2'])
        factory.select_product_with_material_check = Mock(return_value=None)

        self.assertEqual(factory.dispatch_winter_quota_batches('industrial_production'), 0)
        factory.select_product_with_material_check.assert_called_once()
        self.assertEqual(factory.winter_quota_ordered, {})

    def test_schedule_industrial_dispatches_quota_before_fallback(self):
        factory = self.make_factory()
        factory.dispatch_winter_quota_batches = Mock(return_value=5)
        factory.configured_product_list = Mock(return_value=None)
        factory.get_idle_posts_by_category = Mock(return_value=['POST2'])
        factory.warehouse_counts = {'iron_nail': 0}
        factory.manufacture = {
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail'},
                    {'name': 'cutlery'},
                ],
            },
        }
        factory.select_product_with_material_check = Mock()

        factory.schedule_industrial_production()

        factory.dispatch_winter_quota_batches.assert_called_once_with('industrial_production')
        factory.select_product_with_material_check.assert_called_once()
        args = factory.select_product_with_material_check.call_args
        self.assertEqual(args.args[0], 'POST2')
        self.assertEqual([item['name'] for item in args.args[1]], ['iron_nail'])

    def test_schedule_industrial_explicit_products_keep_original_order(self):
        factory = self.make_factory()
        factory.dispatch_winter_quota_batches = Mock(return_value=0)
        configured = [{'name': 'cutlery'}, {'name': 'iron_nail'}]
        factory.configured_product_list = Mock(return_value=configured)
        factory._schedule_line = Mock()
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'line': 'industrial_production',
                'status': 'done', 'batches': [],
            }],
        }

        factory.schedule_industrial_production()

        factory._schedule_line.assert_called_once_with('industrial_production', configured)

    def test_schedule_industrial_done_stops_auto_cutlery_fallback(self):
        """任务 Done / 达标后，未配置 Products 时不再按铁钉库存自动造餐具。"""
        factory = self.make_factory()
        factory.dispatch_winter_quota_batches = Mock(return_value=0)
        factory.configured_product_list = Mock(return_value=None)
        factory.get_idle_posts_by_category = Mock(return_value=['POST1'])
        factory.warehouse_counts = {'iron_nail': 20}
        factory.manufacture = {
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail'},
                    {'name': 'cutlery'},
                ],
            },
        }
        factory.winter_quota_plan = {
            'items': [{
                'key': 'cutlery', 'item': 'cutlery', 'line': 'industrial_production',
                'status': 'done', 'batches': [],
            }],
        }
        factory.select_product_with_material_check = Mock()

        factory.schedule_industrial_production()

        factory.select_product_with_material_check.assert_called_once()
        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([item['name'] for item in product_list], ['iron_nail'])

    def test_schedule_industrial_offseason_keeps_auto_cutlery(self):
        factory = self.make_factory()
        factory.current_season = 'autumn'
        factory.dispatch_winter_quota_batches = Mock(return_value=0)
        factory.configured_product_list = Mock(return_value=None)
        factory.get_idle_posts_by_category = Mock(return_value=['POST1'])
        factory.warehouse_counts = {'iron_nail': 20}
        factory.manufacture = {
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail'},
                    {'name': 'cutlery'},
                ],
            },
        }
        factory.select_product_with_material_check = Mock()

        factory.schedule_industrial_production()

        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([item['name'] for item in product_list], ['cutlery', 'iron_nail'])

    def test_schedule_industrial_disabled_switch_keeps_auto_cutlery(self):
        factory = self.make_factory()
        factory.config = FakeConfig({
            'IslandSeasonPlan.IslandSeasonPlan.WinterTaskEnabled': False,
        })
        factory.dispatch_winter_quota_batches = Mock(return_value=0)
        factory.configured_product_list = Mock(return_value=None)
        factory.get_idle_posts_by_category = Mock(return_value=['POST1'])
        factory.warehouse_counts = {'iron_nail': 20}
        factory.manufacture = {
            'industrial_production': {
                'items': [
                    {'name': 'iron_nail'},
                    {'name': 'cutlery'},
                ],
            },
        }
        factory.select_product_with_material_check = Mock()

        factory.schedule_industrial_production()

        product_list = factory.select_product_with_material_check.call_args.args[1]
        self.assertEqual([item['name'] for item in product_list], ['cutlery', 'iron_nail'])


if __name__ == '__main__':
    unittest.main()
