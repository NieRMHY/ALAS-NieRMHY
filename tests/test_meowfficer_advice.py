"""``module.meowfficer.advice`` 的测试：洗点推荐的四种结论与目标推导。"""

import unittest

from module.meowfficer.advice import (VERDICT_FEED, VERDICT_KEEP, VERDICT_PENDING,
                                      VERDICT_REROLL, estimate_points_spent, missing_targets,
                                      reset_advice)
from module.meowfficer.score import RESET_COST, RubricResult, ScoreResult, Talent, evaluate


class EstimatePointsTests(unittest.TestCase):
    """按天赋等级推算已投入点数（初始 Lv1 免费，每升一级 1 点，上限 6）。"""

    def test_counts_only_above_level_one(self):
        # 天赋名自带等级：「无影手·潜艇」是「装填新手·潜艇」线的 Lv3
        result = evaluate(['无影手·潜艇'])
        self.assertEqual(result.talents[0].level, 3)
        self.assertEqual(estimate_points_spent(result), 2)

    def test_level_one_talents_cost_nothing(self):
        result = evaluate(['装填新手·潜艇', '侵略如火'])
        self.assertEqual(estimate_points_spent(result), 0)


class MissingTargetsTests(unittest.TestCase):
    """目标来自评分用的权重表：权重最高但没命中的那几个。"""

    def test_lists_missing_high_weight_specials(self):
        result = evaluate(['其徐如林'])
        targets = missing_targets(result, 'submarine')
        self.assertTrue(any('狼群之首' in t or '侵略如火' in t for t in targets))

    def test_empty_when_rubric_unknown(self):
        result = evaluate(['侵略如火'])
        self.assertEqual(missing_targets(result, 'no_such_rubric'), [])


def _result(tier, level=1, points_spent=None, rubric_key='surface'):
    """直接构造一个评分结果，用来确定性地覆盖决策表的四个分支。"""
    rubric = RubricResult(key=rubric_key, label='主流水面猫（战列/航母/巡洋）',
                          x=1, y=3.0, tier=tier, score100=70, source='测试口径')
    talents = [Talent(name='侵略如火', line='侵略如火', level=level, kind='special')]
    return ScoreResult(
        talents=talents, cat='测试猫', rubrics={rubric_key: rubric}, primary=[rubric_key],
        maxed=any(t.level >= 3 for t in talents), points_spent=points_spent)


class ResetAdviceTests(unittest.TestCase):
    """决策只看两件事：主口径档位、有没有投过天赋点（maxed）。"""

    def test_feed_when_bad_tier_without_investment(self):
        advice = reset_advice(_result('零食（建议喂掉）', level=1))
        self.assertEqual(advice.verdict, VERDICT_FEED)
        self.assertIsNone(advice.cost)
        self.assertEqual(advice.targets, [], '喂掉就不该再列该补什么')

    def test_reroll_when_bad_tier_with_investment(self):
        advice = reset_advice(_result('无彩（建议喂掉）', level=3, points_spent=3))
        self.assertEqual(advice.verdict, VERDICT_REROLL)
        self.assertEqual(advice.cost, RESET_COST[3])
        self.assertFalse(advice.cost_estimated, '调用方给了投入点数就不算推算')
        self.assertTrue(advice.targets, '洗点要给可执行的目标')

    def test_pending_when_decent_tier_without_investment(self):
        advice = reset_advice(_result('准毕业', level=1))
        self.assertEqual(advice.verdict, VERDICT_PENDING)
        self.assertIsNone(advice.cost)
        self.assertTrue(advice.targets)

    def test_keep_when_good_tier_and_invested(self):
        advice = reset_advice(_result('准毕业（偏上）', level=3, points_spent=4))
        self.assertEqual(advice.verdict, VERDICT_KEEP)
        self.assertEqual(advice.targets, [], '保留就不再列该补什么，否则自相矛盾')
        self.assertEqual(advice.cost, RESET_COST[4])

    def test_cost_is_estimated_when_points_unknown(self):
        advice = reset_advice(_result('准毕业', level=3, points_spent=None))
        self.assertEqual(advice.points_spent, 2, 'Lv3 推算为 2 点')
        self.assertEqual(advice.cost, RESET_COST[2])
        self.assertTrue(advice.cost_estimated)

    def test_torpedo_rubric_has_no_rainbow_count_in_reason(self):
        advice = reset_advice(_result('雷暴可用', level=3, points_spent=2, rubric_key='torpedo'))
        self.assertEqual(advice.verdict, VERDICT_KEEP)
        self.assertNotIn('个彩天赋', advice.reason)

    def test_returns_none_without_rubric(self):
        class _Empty:
            primary = []
            rubrics = {}

        self.assertIsNone(reset_advice(_Empty()))

    def test_real_evaluation_end_to_end(self):
        """和真实评分串起来也成立：风帆那套是保留档。"""
        result = evaluate(['航海长·小型舰', '炮火覆盖·V', '其徐如林', '既定的命运', '不动如山'],
                          cat='风帆')
        advice = reset_advice(result)
        self.assertEqual(advice.verdict, VERDICT_KEEP)
        self.assertEqual(advice.label, result.rubrics[result.primary[0]].label)


if __name__ == '__main__':
    unittest.main()
