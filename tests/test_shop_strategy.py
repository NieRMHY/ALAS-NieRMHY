"""受限 Lua 风格商店策略的集中单元测试。"""

import unittest

from module.shop_strategy import (
    ShopCandidate,
    ShopContext,
    ShopStrategyError,
    compile_strategy,
    evaluate_source,
    evaluate_strategy,
    strategy_diagnostics,
    validate_strategy,
)


def candidate(identifier, key, price, **kwargs):
    """构造测试用商品，默认使用同一种活动货币。"""
    return ShopCandidate(identifier, key, price=price, cost='Pt', **kwargs)


class TestShopStrategyHappyPath(unittest.TestCase):
    def test_score_plan_combines_branch_budget_and_cap(self):
        source = """-- 活动商店优先购买 T4
local pool = candidates:where(function(item)
    return item.tier == 't4' and item.available
end):score(function(item)
    return 100 - item.price
end)
if context.domain == 'event' then
    return shop.plan {
        reserve = { Pt = 2 },
        max_spend = { Pt = 8 },
        candidates = pool:cap('key', 'Cube', 1):take(20),
    }
elseif context.currency['Pt'] > 0 then
    return shop.plan { candidates = candidates:take(20) }
else
    return shop.plan { candidates = candidates:take(0) }
end
"""
        plan = evaluate_source(
            source,
            [
                candidate('cube', 'Cube', 3, tier='t4', stock=3, max_quantity=3),
                candidate('book', 'Book', 4, tier='t4'),
                candidate('low', 'Low', 1, tier='t3'),
            ],
            # currency 是当前实际余额，spent 只用于 max_spend 的会话上限。
            ShopContext('event', currency={'Pt': 10}, spent={'Pt': 1}),
        )

        self.assertEqual(
            plan.actions,
            (
                # Cube 命中跨商品配额，只能购买一个。
                plan.actions[0].__class__('cube', 1, 'Pt', 3),
                plan.actions[1].__class__('book', 1, 'Pt', 4),
            ),
        )
        self.assertEqual(plan.reserve, {'Pt': 2})
        self.assertEqual(plan.max_spend, {'Pt': 8})
        self.assertEqual(plan.spent, {'Pt': 7})
        self.assertEqual(plan.remaining, {'Pt': 0})
        self.assertGreater(plan.search_states, 0)

    def test_local_scored_pipeline_can_add_take_when_returned(self):
        source = """local ranked = candidates:score(function(item)
    return item.price
end)
return shop.plan { candidates = ranked:take(2) }
"""
        plan = evaluate_source(
            source,
            [candidate('one', 'One', 1), candidate('three', 'Three', 3)],
            ShopContext('general', currency={'Pt': 4}),
        )

        self.assertEqual([action.candidate_id for action in plan.actions], ['three', 'one'])

    def test_unscored_order_is_stable_for_equal_values(self):
        source = """return shop.plan {
    candidates = candidates:order_by('price', 'asc'):take(10)
}"""
        plan = evaluate_source(
            source,
            [
                candidate('expensive', 'A', 3),
                candidate('first', 'B', 1),
                candidate('second', 'C', 1),
            ],
            ShopContext('general', currency={'Pt': 5}),
        )

        self.assertEqual(
            [action.candidate_id for action in plan.actions],
            ['first', 'second', 'expensive'],
        )

    def test_cap_is_a_cross_candidate_quantity_limit(self):
        source = """return shop.plan {
    candidates = candidates:cap('key', 'Cube', 2):take(10)
}"""
        plan = evaluate_source(
            source,
            [
                candidate('cube-a', 'Cube', 1, stock=10, max_quantity=10),
                candidate('cube-b', 'Cube', 1, stock=10, max_quantity=10),
                candidate('book', 'Book', 1, stock=10, max_quantity=10),
            ],
            ShopContext('general', currency={'Pt': 10}),
        )

        self.assertEqual(
            [(action.candidate_id, action.quantity) for action in plan.actions],
            [('cube-a', 2), ('book', 8)],
        )

    def test_cap_uses_cross_refresh_usage_when_prior_candidate_disappeared(self):
        """同类旧商品售罄后，新的候选不能绕过本会话 cap 配额。"""
        source = """return shop.plan {
    candidates = candidates:cap('key', 'Cube', 1):take(10)
}"""
        from module.shop_strategy.models import cap_usage_key

        plan = evaluate_source(
            source,
            [candidate('new-cube', 'Cube', 1, stock=3, max_quantity=3)],
            ShopContext(
                'general',
                currency={'Pt': 10},
                cap_usage={cap_usage_key('key', 'Cube'): 1},
            ),
        )

        self.assertEqual(plan.actions, ())

    def test_scored_planner_selects_best_feasible_combination(self):
        source = """return shop.plan {
    candidates = candidates:score(function(item) return item.price end):take(2)
}"""
        plan = evaluate_source(
            source,
            [candidate('six', 'Six', 6), candidate('four', 'Four', 4)],
            ShopContext('event', currency={'Pt': 10}),
        )

        self.assertEqual(
            [(action.candidate_id, action.quantity) for action in plan.actions],
            [('six', 1), ('four', 1)],
        )


class TestShopStrategyValidation(unittest.TestCase):
    def test_empty_script_is_valid_configuration_but_not_executable(self):
        self.assertEqual(strategy_diagnostics(''), [])
        self.assertEqual(validate_strategy(''), {'valid': True, 'diagnostics': []})
        with self.assertRaises(ShopStrategyError) as caught:
            compile_strategy('')
        self.assertEqual(caught.exception.diagnostic.code, 'empty_script')

    def test_diagnostic_has_displayable_location(self):
        result = validate_strategy("return shop.plan { candidates = candidates:where(function(item) return item.hidden end):take(1) }")

        self.assertFalse(result['valid'])
        diagnostic = result['diagnostics'][0]
        self.assertEqual(diagnostic['code'], 'unknown_candidate_field')
        self.assertEqual(diagnostic['line'], 1)
        self.assertIsInstance(diagnostic['column'], int)
        self.assertGreaterEqual(diagnostic['column'], 1)

    def test_rejects_assignment_loop_and_arbitrary_call(self):
        cases = {
            "changed = 1; return shop.plan { candidates = candidates }": 'forbidden_statement',
            "for i = 1, 2 do end; return shop.plan { candidates = candidates }": 'forbidden_statement',
            "return os.execute('anything')": 'invalid_plan_call',
        }
        for source, code in cases.items():
            with self.subTest(source=source):
                with self.assertRaises(ShopStrategyError) as caught:
                    compile_strategy(source)
                self.assertEqual(caught.exception.diagnostic.code, code)

    def test_scored_pipeline_requires_bounded_take(self):
        cases = {
            "return shop.plan { candidates = candidates:score(function(item) return item.price end) }": 'score_requires_take',
            "return shop.plan { candidates = candidates:score(function(item) return item.price end):take(21) }": 'score_take_limit',
            "return shop.plan { candidates = candidates:take(1):score(function(item) return item.price end) }": 'score_before_take',
        }
        for source, code in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(ShopStrategyError) as caught:
                    compile_strategy(source)
                self.assertEqual(caught.exception.diagnostic.code, code)

    def test_rejects_more_than_sixteen_pipeline_steps(self):
        chain = 'candidates' + ':where(function(item) return item.available end)' * 17
        source = f'return shop.plan {{ candidates = {chain} }}'

        with self.assertRaises(ShopStrategyError) as caught:
            compile_strategy(source)

        self.assertEqual(caught.exception.diagnostic.code, 'pipeline_limit')


class TestShopStrategyPlannerLimits(unittest.TestCase):
    def test_scored_planner_stops_at_state_limit(self):
        source = """return shop.plan {
    candidates = candidates:score(function(item) return item.price end):take(20)
}"""
        candidates = [
            candidate(str(index), str(index), 1, stock=2, max_quantity=2)
            for index in range(20)
        ]

        with self.assertRaises(ShopStrategyError) as caught:
            evaluate_source(source, candidates, ShopContext('event', currency={'Pt': 40}))

        self.assertEqual(caught.exception.diagnostic.code, 'planner_limit')

    def test_numeric_expression_and_exponent_are_bounded(self):
        """受限解释器不能因极大算术值或幂指数耗尽运行资源。"""
        source = '''return shop.plan {
    candidates = candidates:where(function(item) return 10 ^ 1000000000 > item.price end):take(1)
}'''

        with self.assertRaises(ShopStrategyError) as caught:
            evaluate_source(source, [candidate('one', 'One', 1)], ShopContext('general', currency={'Pt': 1}))

        self.assertEqual(caught.exception.diagnostic.code, 'exponent_limit')

        source = '''return shop.plan {
    candidates = candidates:where(function(item) return 1000000000000 * 1000000000000 > item.price end):take(1)
}'''
        with self.assertRaises(ShopStrategyError) as caught:
            evaluate_source(source, [candidate('one', 'One', 1)], ShopContext('general', currency={'Pt': 1}))

        self.assertEqual(caught.exception.diagnostic.code, 'number_required')

    def test_precompiled_strategy_accepts_only_pure_models(self):
        compiled = compile_strategy('return shop.plan { candidates = candidates:take(1) }')
        plan = evaluate_strategy(
            compiled,
            [candidate('one', 'One', 1)],
            ShopContext('general', currency={'Pt': 1}),
        )

        self.assertEqual(plan.actions[0].candidate_id, 'one')
        with self.assertRaises(TypeError):
            evaluate_strategy(compiled, [object()], ShopContext('general', currency={'Pt': 1}))
