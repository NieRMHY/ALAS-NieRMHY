"""商店高级策略适配层的纯单元测试。"""

from types import SimpleNamespace
from unittest import TestCase

from module.shop_strategy.adapter import (
    build_shop_context,
    project_shop_items,
    resolve_shop_plan,
    run_shop_strategy,
)
from module.shop_strategy.models import ShopAction, ShopCap, ShopPlan, cap_usage_key


def make_item(**overrides):
    """构造不依赖截图、设备或 OCR 的最小现有商品替身。"""
    values = {
        'name': 'Cube',
        'cost': 'Coin',
        'price': 10,
        'count': 3,
        'group': 'cube',
        'sub_genre': None,
        'tier': None,
        'is_valid': True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestShopStrategyAdapter(TestCase):
    """验证脚本边界和返回计划无法绕过 Python 侧硬规则。"""

    source = 'return shop.plan { candidates = candidates }'

    def test_projection_exposes_only_whitelisted_data(self):
        """原商品中的任意运行时对象均不会进入候选 DTO。"""
        item = make_item(secret=object(), device=object())

        projection = project_shop_items([item])

        candidate = projection.candidates[0]
        self.assertEqual(candidate.name, 'Cube')
        self.assertEqual(candidate.stock, 3)
        self.assertFalse(hasattr(candidate, 'secret'))
        self.assertFalse(hasattr(candidate, 'device'))
        self.assertIs(projection.item_for(candidate.id), item)

    def test_projection_applies_eligibility_and_quantity_limit(self):
        """不满足 Python 硬规则的商品不进入脚本，数量上限不能超过库存。"""
        denied = make_item(name='Denied')
        allowed = make_item(name='Allowed', count=4)

        projection = project_shop_items(
            [denied, allowed],
            eligible=lambda item: item.name == 'Allowed',
            max_quantity=lambda item: 7,
        )

        self.assertEqual(len(projection.candidates), 1)
        self.assertEqual(projection.candidates[0].name, 'Allowed')
        self.assertEqual(projection.candidates[0].max_quantity, 4)

    def test_projection_accepts_conservative_stock_without_item_count(self):
        """普通商店可在购买数量弹窗出现前传入保守库存，而不修改原商品。"""
        item = make_item()
        del item.count

        projection = project_shop_items([item], stock=9, max_quantity=4)

        self.assertEqual(projection.candidates[0].stock, 9)
        self.assertEqual(projection.candidates[0].max_quantity, 4)

    def test_projection_uses_candidate_id_as_empty_key_fallback(self):
        """无名称、无 key 的未识别商品仍只会得到字符串基本类型字段。"""
        projection = project_shop_items([make_item(name='', key=None)])

        candidate = projection.candidates[0]
        self.assertEqual(candidate.key, candidate.id)

    def test_projection_uses_stable_id_after_reorder_or_sold_out_refresh(self):
        """重排或货架前项消失后，后项不能错误继承前项的会话购买计数。"""
        first = make_item(name='First')
        second = make_item(name='Second')
        original = project_shop_items([first, second])

        reordered = project_shop_items([second, first])
        remaining = project_shop_items([second])

        first_id = next(item.id for item in original.candidates if item.name == 'First')
        second_id = next(item.id for item in original.candidates if item.name == 'Second')
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(
            next(item.id for item in reordered.candidates if item.name == 'First'),
            first_id,
        )
        self.assertEqual(
            next(item.id for item in reordered.candidates if item.name == 'Second'),
            second_id,
        )
        self.assertEqual(remaining.candidates[0].id, second_id)

        result = run_shop_strategy(
            self.source,
            [second],
            domain='general',
            currency={'Coin': 100},
            purchased={first_id: 3},
        )
        self.assertTrue(result.success)
        self.assertEqual(result.actions[0].quantity, 3)

    def test_projection_distinguishes_identical_items_by_stable_slot(self):
        """字段相同的多件商品可依靠货架位置跨重排保持不同的候选 ID。"""
        left = make_item(area=(100, 200, 160, 260))
        right = make_item(area=(300, 200, 360, 260))

        original = project_shop_items([left, right])
        reordered = project_shop_items([right, left])

        original_ids = {item.id for item in original.candidates}
        reordered_ids = {item.id for item in reordered.candidates}
        self.assertEqual(len(original_ids), 2)
        self.assertEqual(reordered_ids, original_ids)

    def test_projection_uses_occurrence_suffix_for_identical_items_without_slot(self):
        """无位置的完全同构商品只能按当前出现顺序区分，ID 仍是确定性的。"""
        projection = project_shop_items([make_item(), make_item()])

        first, second = projection.candidates
        self.assertTrue(second.id.startswith(first.id + '-'))

    def test_spent_is_only_used_for_max_spend_when_balance_is_reocrd(self):
        """重新 OCR 的余额不能再次扣除已消费金额，仍要遵守会话消费上限。"""
        source = '''
return shop.plan {
    reserve = { Coin = 20 },
    max_spend = { Coin = 50 },
    candidates = candidates:take(1),
}
'''

        result = run_shop_strategy(
            source,
            [make_item(count=4)],
            domain='general',
            currency={'Coin': 70},
            spent={'Coin': 30},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.actions[0].quantity, 2)
        self.assertEqual(result.plan.remaining, {'Coin': 0})

    def test_run_returns_bound_item_actions_without_exposing_items_to_script(self):
        """成功计划返回原对象供购买流程调用，并保留商品数量与金额。"""
        item = make_item(count=2)

        result = run_shop_strategy(
            self.source,
            [item],
            domain='general',
            currency={'Coin': 100},
        )

        self.assertTrue(result.success)
        self.assertIsNone(result.diagnostic)
        self.assertEqual(len(result.actions), 1)
        action = result.actions[0]
        self.assertIs(action.item, item)
        self.assertEqual(action.quantity, 2)
        self.assertEqual(action.total_price, 20)

    def test_run_keeps_domain_and_multi_currency_context(self):
        """策略可按商店域分支，未消费货币仍会保留在诊断余额中。"""
        source = '''
if context.domain == "event" then
    return shop.plan { candidates = candidates:take(1) }
else
    return shop.plan { candidates = candidates:take(0) }
end
'''

        result = run_shop_strategy(
            source,
            [make_item(count=2)],
            domain='event',
            currency={'Coin': 100, 'Pt': 500},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.plan.remaining, {'Coin': 80, 'Pt': 500})

    def test_run_honours_reserve_and_max_spend(self):
        """引擎计划与适配器复核均不允许超过保留额或会话消费上限。"""
        source = '''
return shop.plan {
    reserve = { Coin = 70 },
    max_spend = { Coin = 20 },
    candidates = candidates:take(1),
}
'''

        result = run_shop_strategy(
            source,
            [make_item(count=8)],
            domain='general',
            currency={'Coin': 100},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.actions[0].quantity, 2)
        self.assertEqual(result.plan.remaining, {'Coin': 0})

    def test_script_error_returns_nonthrowing_structured_failure(self):
        """无效脚本不能逃逸到状态循环，调用方可直接记录诊断。"""
        result = run_shop_strategy(
            'not valid lua',
            [make_item()],
            domain='general',
            currency={'Coin': 100},
        )

        self.assertFalse(result.success)
        self.assertEqual(result.diagnostic.code, 'syntax_error')
        self.assertEqual(result.actions, ())

    def test_plan_cannot_forge_price_or_remaining_balance(self):
        """即使未来引擎回归，适配器仍拒绝伪造金额或剩余余额的计划。"""
        item = make_item()
        projection = project_shop_items([item])
        candidate = projection.candidates[0]
        context = build_shop_context('general', {'Coin': 100})
        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 1, 'Coin', 1),),
            reserve={},
            max_spend={},
            spent={'Coin': 1},
            remaining={'Coin': 99},
        )

        with self.assertRaisesRegex(ValueError, '金额与商品实际价格不一致'):
            resolve_shop_plan(plan, projection, context)

        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 1, 'Coin', 10),),
            reserve={},
            max_spend={},
            spent={'Coin': 10},
            remaining={'Coin': 91},
        )

        with self.assertRaisesRegex(ValueError, 'remaining 与真实余额计算不一致'):
            resolve_shop_plan(plan, projection, context)

    def test_plan_cannot_exceed_python_quantity_limit(self):
        """手工构造的计划也无法突破投影时设置的每商品上限。"""
        item = make_item(count=5)
        projection = project_shop_items([item], max_quantity=2)
        candidate = projection.candidates[0]
        context = build_shop_context('general', {'Coin': 100})
        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 3, 'Coin', 30),),
            reserve={},
            max_spend={},
            spent={'Coin': 30},
            remaining={'Coin': 70},
        )

        with self.assertRaisesRegex(ValueError, '购买数量超出商品上限'):
            resolve_shop_plan(plan, projection, context)

    def test_zero_price_candidate_is_skipped_before_strategy_execution(self):
        """OCR 未稳定的零价格商品不能触发后续购买数量除法。"""
        eligibility_called = False

        def eligible(_item):
            nonlocal eligibility_called
            eligibility_called = True
            raise AssertionError('零价格候选不应进入宿主资格检查')

        result = run_shop_strategy(
            'return shop.plan { candidates = candidates:take(1) }',
            [make_item(price=0)],
            domain='general',
            currency={'Coin': 100},
            eligible=eligible,
        )

        self.assertTrue(result.success)
        self.assertFalse(eligibility_called)
        self.assertEqual((), result.candidates)
        self.assertEqual((), result.actions)

    def test_script_can_read_session_purchase_history_without_reducing_stock(self):
        """脚本可见的会话购买记录不应误作当前货架的库存扣减。"""
        source = '''
return shop.plan {
    candidates = candidates:where(function(item)
        return context.purchased[item.id] == 2
    end):take(1)
}
'''

        result = run_shop_strategy(
            source,
            [make_item(strategy_id='cube', count=3)],
            domain='general',
            currency={'Coin': 100},
            purchased={'item-cube': 2},
            inventory_purchased={'item-cube': 1},
        )

        self.assertTrue(result.success)
        self.assertEqual(result.actions[0].quantity, 2)

    def test_plan_cannot_repeat_quantity_already_purchased_on_current_stock(self):
        """未来引擎输出回归时，适配器仍会扣除当前货架已购数量。"""
        item = make_item(count=3)
        projection = project_shop_items([item])
        candidate = projection.candidates[0]
        context = build_shop_context(
            'general',
            {'Coin': 100},
            inventory_purchased={candidate.id: 2},
        )
        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 2, 'Coin', 20),),
            reserve={},
            max_spend={},
            spent={'Coin': 20},
            remaining={'Coin': 80},
        )

        with self.assertRaisesRegex(ValueError, '购买数量超出商品上限'):
            resolve_shop_plan(plan, projection, context)

    def test_plan_defensively_merges_duplicate_caps(self):
        """即使计划绕过运行时，重复 cap 仍按最严格上限且只记一次用量。"""
        item = make_item(count=3)
        projection = project_shop_items([item])
        candidate = projection.candidates[0]
        context = build_shop_context('general', {'Coin': 100})
        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 2, 'Coin', 20),),
            reserve={},
            max_spend={},
            spent={'Coin': 20},
            remaining={'Coin': 80},
            caps=(
                ShopCap('key', 'Cube', 3),
                ShopCap('key', 'Cube', 2),
            ),
        )

        actions = resolve_shop_plan(plan, projection, context)

        self.assertEqual(actions[0].quantity, 2)
        self.assertEqual(actions[0].cap_usage_keys, (cap_usage_key('key', 'Cube'),))

    def test_plan_revalidates_cross_refresh_cap_usage(self):
        """此前货架已消失的同类商品也会占用本会话的 cap 配额。"""
        item = make_item(count=3)
        projection = project_shop_items([item])
        candidate = projection.candidates[0]
        key = cap_usage_key('key', 'Cube')
        context = build_shop_context('general', {'Coin': 100}, cap_usage={key: 1})
        plan = ShopPlan(
            actions=(ShopAction(candidate.id, 2, 'Coin', 20),),
            reserve={},
            max_spend={},
            spent={'Coin': 20},
            remaining={'Coin': 80},
            caps=(ShopCap('key', 'Cube', 2),),
        )

        with self.assertRaisesRegex(ValueError, '超出分类数量配额'):
            resolve_shop_plan(plan, projection, context)

    def test_plan_rejects_unhashable_candidate_id_as_structured_error(self):
        """计划字段来自不可信边界，异常 ID 也必须转为可诊断的校验失败。"""
        projection = project_shop_items([make_item()])
        context = build_shop_context('general', {'Coin': 100})
        plan = ShopPlan(
            actions=(ShopAction([], 1, 'Coin', 10),),
            reserve={},
            max_spend={},
            spent={'Coin': 10},
            remaining={'Coin': 90},
        )

        with self.assertRaisesRegex(ValueError, '候选商品 ID 必须为非空字符串'):
            resolve_shop_plan(plan, projection, context)
