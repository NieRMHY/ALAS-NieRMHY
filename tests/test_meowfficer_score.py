"""指挥喵天赋评分与识别的单元测试。

覆盖三块：
- 名字归一化与模糊匹配（OCR 会把「·」读成 ．，、 等形态，且常有错字）
- 四套评分口径的 x+y 记点与档位判定
- OCR 适配层的多变体合并、等级取高、猫名识别（用假 OCR 注入，不依赖模型）
"""

import unittest

import numpy as np

from module.meowfficer.score import evaluate, match_talent, normalize
from module.meowfficer.score_ocr import build_variants, recognize, recognize_talents
from module.meowfficer.score_report import render_text, render_summary


class _StubOcr:
    """假 OCR：直接返回预置的 ``det()`` 结果，用来验证适配层逻辑。"""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def det(self, image):
        self.calls.append(image.shape)
        return self.results


class TestNormalize(unittest.TestCase):
    """名字归一化。"""

    def test_separators_are_dropped(self):
        for text in ('熟练对空炮手·先锋', '熟练对空炮手，先锋',
                     '熟练对空炮手．先锋', '熟练对空炮手.先锋', '熟 练 对 空 炮 手 · 先 锋'):
            self.assertEqual(normalize(text), '熟练对空炮手先锋')

    def test_ocr_confusion_char(self):
        # OCR 常把「士」认成「土」
        self.assertEqual(normalize('新人雷击土·潜艇'), normalize('新人雷击士·潜艇'))


class TestMatchTalent(unittest.TestCase):
    """天赋匹配。"""

    def test_dirty_ocr_names(self):
        cases = {
            '无影手，潜艇': '无影手·潜艇',
            '雷 击 长 · 潜 艇': '雷击长·潜艇',
            '狼群之首': '狼群之首',
            '炮术长．主力': '炮术长·主力',
        }
        for text, expected in cases.items():
            ref = match_talent(text)
            self.assertIsNotNone(ref, text)
            self.assertEqual(ref.name, expected, text)

    def test_level_comes_from_name(self):
        # 每条天赋线三个等级各有独立名字，识别出名字等级就唯一确定
        self.assertEqual(match_talent('炮击新手·主力').level, 1)
        self.assertEqual(match_talent('熟练炮手·主力').level, 2)
        self.assertEqual(match_talent('炮术长·主力').level, 3)
        self.assertEqual(match_talent('炮术长·主力').line, '炮击新手·主力')

    def test_special_talent_is_not_upgradable(self):
        ref = match_talent('侵略如火')
        self.assertEqual(ref.kind, 'special')
        self.assertEqual(ref.level, 1)

    def test_ui_noise_is_rejected(self):
        for text in ('陪玩', '成长', '锁定', '后勤', '天赋点'):
            self.assertIsNone(match_talent(text), text)


class TestEvaluateSurface(unittest.TestCase):
    """主流水面猫口径。"""

    def test_y_counts_level(self):
        # 炮击新手·主力 Lv3 = 1.0×3；装填新手·战列 Lv3 = 0.5×3
        result = evaluate(['炮术长·主力', '无影手·战列'], cat='林德喵')
        surface = result.rubrics['surface']
        self.assertAlmostEqual(surface.y, 4.5, places=2)
        self.assertEqual(surface.x, 0)
        self.assertEqual(surface.tier, '零食（建议喂掉）')

    def test_ace_means_carrier(self):
        result = evaluate(['王牌机师', '航空新兵·空母', '新手整备士'], cat='莫里喵')
        self.assertIn('航母猫', ' '.join(result.rubrics['surface'].notes))

    def test_no_x_is_snack(self):
        result = evaluate(['新手观测士·主力'], cat='奥古喵')
        self.assertEqual(result.rubrics['surface'].x, 0)


class TestEvaluateSubmarine(unittest.TestCase):
    """潜艇猫口径。"""

    def test_two_x_plus_command_is_perfect(self):
        result = evaluate(['狼群之首', '侵略如火', '新晋指挥官·潜艇'], cat='克雷喵')
        sub = result.rubrics['submarine']
        self.assertEqual(sub.x, 2)
        self.assertEqual(sub.tier, '完美猫')
        self.assertEqual(result.primary[0], 'submarine')

    def test_durability_line_scores_zero(self):
        result = evaluate(['狼群之首', '轮机长·潜艇'], cat='克雷喵')
        sub = result.rubrics['submarine']
        self.assertEqual(sub.x, 1)
        self.assertNotIn('轮机手·潜艇', sub.y_hits)
        self.assertTrue(any('轮机手·潜艇' in note for note in sub.notes))

    def test_command_talent_counts_as_y(self):
        result = evaluate(['新晋指挥官·潜艇'], cat='克雷喵')
        self.assertIn('新晋指挥官·潜艇 Lv1', result.rubrics['submarine'].y_hits)


class TestEvaluateOtherRubrics(unittest.TestCase):
    """低耗与雷暴口径。"""

    def test_destroyer_rubrics_selected(self):
        result = evaluate(['水雷魂', '新晋指挥官·驱逐', '熟练雷击士·驱逐'], cat='伯克喵')
        self.assertIn('torpedo', result.primary)
        self.assertIn('lowoil', result.primary)
        self.assertGreater(result.rubrics['torpedo'].score100, 0)

    def test_iron_blood_destroyer_not_lowoil_primary(self):
        # 低耗口径只对驱逐/航母生效
        result = evaluate(['侵略如火'], cat='林德喵')
        self.assertNotIn('lowoil', result.primary)


class TestScoreResult(unittest.TestCase):
    """结果对象与渲染。"""

    def test_maxed_detected_by_level_three(self):
        self.assertTrue(evaluate(['炮术长·主力'], cat='林德喵').maxed)
        self.assertFalse(evaluate(['炮术长·主力'] and ['炮击新手·主力'], cat='林德喵').maxed)

    def test_unknown_talent_is_kept(self):
        result = evaluate(['某个不存在的天赋'], cat='克雷喵')
        self.assertEqual(result.talents[0].kind, 'unknown')

    def test_points_spent_adds_reset_cost(self):
        text = render_text(evaluate(['狼群之首'], cat='克雷喵', points_spent=6))
        self.assertIn('12000', text)

    def test_render_text_contains_core_fields(self):
        text = render_text(evaluate(['狼群之首', '装填新手·潜艇'], cat='克雷喵'))
        self.assertIn('克雷喵', text)
        self.assertIn('x + y = 1 + 1.0', text)
        self.assertIn('28法则执行篇', text)


class TestRecognizeAdapter(unittest.TestCase):
    """OCR 适配层（注入假 OCR，不加载模型）。"""

    def setUp(self):
        self.image = np.zeros((120, 240, 3), dtype=np.uint8)
        self.square = [[0, 0], [10, 0], [10, 10], [0, 10]]

    def test_ui_noise_filtered_and_talents_deduped(self):
        stub = _StubOcr([
            ('狼 群 之 首', self.square, 0.9),
            ('无影手，潜艇', self.square, 0.9),
            ('陪 玩', self.square, 0.9),
            ('成 长', self.square, 0.9),
        ])
        talents, cat = recognize(self.image, ocr=stub, scale=1.0)
        self.assertEqual({t.name for t in talents}, {'狼群之首', '无影手·潜艇'})
        self.assertIsNone(cat)

    def test_higher_level_wins_within_one_line(self):
        stub = _StubOcr([
            ('新人雷击士·潜艇', self.square, 0.9),
            ('雷击长·潜艇', self.square, 0.9),
        ])
        talents, _ = recognize(self.image, ocr=stub, scale=1.0)
        self.assertEqual(len(talents), 1)
        self.assertEqual(talents[0].name, '雷击长·潜艇')
        self.assertEqual(talents[0].level, 3)

    def test_cat_name_detected(self):
        stub = _StubOcr([('克 雷 喵', self.square, 0.9), ('狼 群 之 首', self.square, 0.9)])
        talents, cat = recognize(self.image, ocr=stub, scale=1.0)
        self.assertEqual(cat, '克雷喵')
        self.assertEqual(len(talents), 1)

    def test_recognize_talents_wrapper(self):
        stub = _StubOcr([('狼 群 之 首', self.square, 0.9)])
        self.assertEqual(len(recognize_talents(self.image, ocr=stub, scale=1.0)), 1)

    def test_build_variants_shapes(self):
        variants = build_variants(self.image, scale=3.0)
        self.assertEqual(set(variants), {'plain', 'clahe'})
        self.assertEqual(variants['plain'].shape[:2], (360, 720))
        self.assertEqual(variants['clahe'].shape, variants['plain'].shape)

    def test_scale_is_capped(self):
        # 放大后长边不允许超过上限，避免大截图吃满内存
        from module.meowfficer.score_ocr import MAX_SIDE
        big = np.zeros((900, 1200, 3), dtype=np.uint8)
        variants = build_variants(big, scale=8.0)
        self.assertLessEqual(max(variants['plain'].shape[:2]), MAX_SIDE)


class TestAutoFollowHelpers(unittest.TestCase):
    """自动跟拍模式的辅助逻辑。"""

    def test_fingerprint_is_stable_and_change_sensitive(self):
        from module.meowfficer.score_task import MeowfficerScore

        base = np.zeros((64, 64, 3), dtype=np.uint8)
        same = base.copy()
        changed = base.copy()
        changed[0, 0] = 255  # 指纹按每 8 像素采样，(0,0) 会被采到

        self.assertEqual(MeowfficerScore._fingerprint(base),
                         MeowfficerScore._fingerprint(same))
        self.assertNotEqual(MeowfficerScore._fingerprint(base),
                            MeowfficerScore._fingerprint(changed))


class TestScoreReport(unittest.TestCase):
    """HTML 报告渲染。"""

    @staticmethod
    def _html(talents, cat='克雷喵'):
        from module.meowfficer.score_report import render_html
        return render_html([('sample', evaluate(talents, cat=cat))], generated_at='test')

    def test_self_contained(self):
        html = self._html(['狼群之首', '装填新手·潜艇'])
        # 单文件自包含：不带外链、不带脚本，双击即可打开
        self.assertNotIn('http://', html)
        self.assertNotIn('https://', html)
        self.assertNotIn('<script', html)

    def test_contains_key_parts(self):
        html = self._html(['狼群之首', '装填新手·潜艇'])
        for token in ('class="ring"', 'class="chip', 'table class="mini"', '狼群之首', '潜艇猫'):
            self.assertIn(token, html)

    def test_unknown_talent_is_escaped(self):
        html = self._html(['<b>奇怪的天赋</b>'])
        self.assertNotIn('<b>奇怪的天赋</b>', html)
        self.assertIn('&lt;b&gt;', html)

    def test_multiple_cats_stack(self):
        from module.meowfficer.score_report import render_html
        results = [('a', evaluate(['狼群之首'], cat='克雷喵')),
                   ('b', evaluate(['一发入魂'], cat='奥古喵'))]
        html = render_html(results)
        self.assertEqual(html.count('<div class="card">'), 2)


class TestRenderSummary(unittest.TestCase):
    """单行摘要（日志用）。"""

    def test_summary_line(self):
        text = render_summary(evaluate(['狼群之首', '装填新手·潜艇'], cat='克雷喵'))
        self.assertIn('克雷喵', text)
        self.assertIn('潜艇猫', text)
        self.assertIn('x+y=1+1.0', text)
        self.assertIn('狼群之首', text)
        self.assertEqual(text.count('\n'), 0)

    def test_summary_marks_maxed(self):
        text = render_summary(evaluate(['炮术长·主力'], cat='林德喵'))
        self.assertIn('成品猫', text)


class TestScorePayload(unittest.TestCase):
    """机器可读 JSON 载荷（WebUI 面板消费）。"""

    @staticmethod
    def _payload():
        from module.meowfficer.score_report import to_payload
        results = [('a.png', evaluate(['狼群之首', '装填新手·潜艇'], cat='克雷喵', points_spent=2)),
                   ('b.png', evaluate(['一发入魂'], cat='奥古喵'))]
        return to_payload(results, generated_at='2026-09-20 12:00:00')

    def test_shape(self):
        payload = self._payload()
        self.assertEqual(payload['count'], 2)
        self.assertEqual(payload['generatedAt'], '2026-09-20 12:00:00')
        self.assertEqual([c['cat'] for c in payload['cats']], ['克雷喵', '奥古喵'])

    def test_primary_rubric_first(self):
        cat = self._payload()['cats'][0]
        self.assertEqual(cat['primary'], 'submarine')
        self.assertTrue(cat['rubrics'][0]['primary'])
        self.assertEqual(cat['rubrics'][0]['key'], 'submarine')

    def test_json_serializable(self):
        import json
        text = json.dumps(self._payload(), ensure_ascii=False)
        self.assertIn('克雷喵', text)
        self.assertIn('潜艇猫', text)

    def test_weighted_rubric_has_label_instead_of_xy(self):
        """雷暴口径是加权点制：不该给出 x/y，也不该把加权命中标成「有用普通」。"""
        from module.meowfficer.score_report import to_payload

        payload = to_payload([('b.png', evaluate(['水雷魂', '新晋指挥官·驱逐'], cat='伯克喵'))])
        rubrics = {item['key']: item for item in payload['cats'][0]['rubrics']}
        torpedo = rubrics['torpedo']
        self.assertIsNone(torpedo['x'])
        self.assertIsNone(torpedo['y'])
        self.assertEqual(torpedo['xHits'], [])
        self.assertIn('加权命中', torpedo['yLabel'])
        # 其余口径仍然照常给出 x/y
        self.assertIsInstance(rubrics['lowoil']['x'], int)

    def test_talent_fields(self):
        cat = self._payload()['cats'][0]
        names = [t['name'] for t in cat['talents']]
        self.assertIn('狼群之首', names)
        special = [t for t in cat['talents'] if t['name'] == '狼群之首'][0]
        self.assertEqual(special['kind'], 'special')
        self.assertIn('SSR', cat['tags'])


class TestReportRoute(unittest.TestCase):
    """`/reports/meowfficer_score` 这条 HTTP 路由：没报告给 404，有报告返回 HTML。"""

    def setUp(self):
        import tempfile
        from starlette.testclient import TestClient
        from module.api.app import create_app
        from tests.test_api import fixture

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = fixture(temporary.name)
        self.client = TestClient(create_app(root=self.root, password='',
                                            manage_runtime=False, mount_mcp=False))

    def test_missing_report_is_404(self):
        response = self.client.get('/reports/meowfficer_score')
        self.assertEqual(response.status_code, 404)

    def test_existing_report_is_served(self):
        log = self.root / 'log'
        log.mkdir(parents=True, exist_ok=True)
        (log / 'meowfficer_score.html').write_text('<html><body>评分报告</body></html>',
                                                   encoding='utf-8')
        response = self.client.get('/reports/meowfficer_score')
        self.assertEqual(response.status_code, 200)
        self.assertIn('评分报告', response.text)
        self.assertTrue(response.headers['content-type'].startswith('text/html'))
        self.assertEqual(response.headers['cache-control'], 'no-cache')

    def test_healthz_still_works(self):
        # 新路由不能影响既有路由
        self.assertEqual(self.client.get('/healthz').status_code, 200)


class TestMeowfficerScoreApi(unittest.TestCase):
    """指挥喵评分报告的只读接口。"""

    def setUp(self):
        import tempfile

        from module.api.config_service import ConfigService
        from tests.test_api import fixture

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = fixture(temporary.name)
        self.configs = ConfigService(self.root)

    def _write_report(self, payload):
        import json

        from module.api.meowfficer_service import report_path

        path = report_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def test_missing_report_is_business_error(self):
        from module.api.meowfficer_service import report
        from module.api.protocol import ApiError

        with self.assertRaises(ApiError) as ctx:
            report(self.configs, 'testpilot')
        self.assertEqual(ctx.exception.code, 'NOT_FOUND')

    def test_clear_removes_all_three_products(self):
        """清空要连 md / html 一起删，否则「查看完整报告」链接会指向不存在的文件。"""
        from module.api.meowfficer_service import clear, report_path

        base = report_path(self.root)
        base.parent.mkdir(parents=True, exist_ok=True)
        for path in (base, base.with_suffix('.md'), base.with_suffix('.html')):
            path.write_text('x', encoding='utf-8')

        result = clear(self.configs, 'testpilot')

        self.assertTrue(result['cleared'])
        self.assertCountEqual(result['removed'],
                              ['meowfficer_score.json', 'meowfficer_score.md', 'meowfficer_score.html'])
        for path in (base, base.with_suffix('.md'), base.with_suffix('.html')):
            self.assertFalse(path.exists(), f'{path.name} 应该被删掉')

    def test_clear_without_report_is_not_an_error(self):
        """重复点清空不该报错。"""
        from module.api.meowfficer_service import clear

        result = clear(self.configs, 'testpilot')
        self.assertFalse(result['cleared'])
        self.assertEqual(result['removed'], [])

    def test_invalid_instance_is_rejected(self):
        from module.api.meowfficer_service import report
        from module.api.protocol import ApiError

        self._write_report({'cats': []})
        with self.assertRaises(ApiError) as ctx:
            report(self.configs, '../etc/passwd')
        self.assertEqual(ctx.exception.code, 'INVALID_PARAMS')

    def test_reads_payload_and_applies_limit(self):
        from module.api.meowfficer_service import report

        self._write_report({'generatedAt': 'T', 'count': 2,
                            'cats': [{'cat': 'A'}, {'cat': 'B'}]})
        result = report(self.configs, 'testpilot', limit=1)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['cats'][0]['cat'], 'B')  # 取最新的一只
        self.assertEqual(result['instance'], 'testpilot')

    def test_broken_report_is_business_error(self):
        from module.api.meowfficer_service import report, report_path
        from module.api.protocol import ApiError

        path = report_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{ not json', encoding='utf-8')
        with self.assertRaises(ApiError) as ctx:
            report(self.configs, 'testpilot')
        self.assertEqual(ctx.exception.code, 'INTERNAL')

    def test_method_registered_as_readonly(self):
        from module.api import protocol as p
        from module.api.router import Router

        entry = Router(self.configs, None).methods.get('meowfficer.scoreReport')
        self.assertIsNotNone(entry)
        # 只读：DEMO 模式下也能查询，不会被 READ_ONLY 拦掉
        self.assertFalse(entry.mutates)
        self.assertIs(entry.params, p.MeowfficerScoreReportParams)

    def test_clear_method_is_registered_and_marked_mutating(self):
        """清空是写操作：方法名要能被分发到，而且 DEMO 模式必须拦得住。"""
        from module.api import protocol as p
        from module.api.router import Router

        router = Router(self.configs, None)
        entry = router.methods.get('meowfficer.clearReport')
        self.assertIsNotNone(entry, '前端调的就是 meowfficer.clearReport，名字必须一致')
        self.assertTrue(entry.mutates, '删除产物算写操作，演示模式要拦住')
        self.assertIs(entry.params, p.MeowfficerClearReportParams)

    def test_dispatch_clear_actually_deletes(self):
        """走一次真正的分发，确认「未知 API 方法」不会出现。"""
        import json

        from module.api.meowfficer_service import report_path
        from module.api.router import Router

        base = report_path(self.root)
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(json.dumps({'generatedAt': 'x', 'count': 0, 'cats': []}),
                        encoding='utf-8')

        result = Router(self.configs, None).dispatch('meowfficer.clearReport', {'instance': 'testpilot'})

        self.assertTrue(result['cleared'])
        self.assertFalse(base.exists())


if __name__ == '__main__':
    unittest.main()
