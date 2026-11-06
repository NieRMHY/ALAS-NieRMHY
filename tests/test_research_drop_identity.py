"""科研领奖分组身份：一张队列页只 OCR 一次，各分组不重复识别。

``AzurStats.commit()`` 按 `research_groups` 逐组入库，每组都要一个（项目代号, 期数）。
队列页上 5 张卡都在同一张截图里，重复 OCR 会把识别耗时成倍压在领奖后的游戏线程上，
这里固定「一次 OCR 供应全部分组」这条约定；弧形科研列表只有一个已完成项目，各分组共用。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.statistics import research_drop


def make_image():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def make_parser(names):
    parser = SimpleNamespace(
        ocr=SimpleNamespace(ocr=Mock(return_value=names)),
        lookup={name: SimpleNamespace() for name in names},
        _correct_code=Mock(side_effect=lambda code: code),
    )
    return parser


class ReadResearchIdentitiesTest(unittest.TestCase):
    def test_queue_page_is_recognized_once_for_every_group(self):
        parser = make_parser(['G-531-MI', 'Q-051-MI', 'D-737-MI', 'T-101-MI', 'X-999-MI'])
        with patch.object(research_drop, 'get_parser', return_value=parser), \
                patch('module.research.assets.QUEUE_CHECK') as queue_check, \
                patch('module.research.series.match_series', return_value=5):
            queue_check.match.return_value = True
            identities = research_drop.read_research_identities(make_image(), 3)

        parser.ocr.ocr.assert_called_once()
        self.assertEqual([code for code, _ in identities], ['G-531-MI', 'Q-051-MI', 'D-737-MI'])
        self.assertEqual([series for _, series in identities], [5, 5, 5])

    def test_groups_beyond_the_visible_cards_stay_unknown(self):
        parser = make_parser(['G-531-MI', 'Q-051-MI'])
        with patch.object(research_drop, 'get_parser', return_value=parser), \
                patch('module.research.assets.QUEUE_CHECK') as queue_check, \
                patch('module.research.series.match_series', return_value=7):
            queue_check.match.return_value = True
            identities = research_drop.read_research_identities(make_image(), 4)

        self.assertEqual([code for code, _ in identities], ['G-531-MI', 'Q-051-MI', '', ''])
        self.assertEqual(identities[2:], [('', 0), ('', 0)])

    def test_curved_list_shares_the_finished_project(self):
        project = SimpleNamespace(name='D-737-MI', series='S5')
        with patch.object(research_drop, 'get_parser', return_value=make_parser([])), \
                patch('module.research.assets.QUEUE_CHECK') as queue_check, \
                patch('module.research.project.get_research_finished', return_value=1), \
                patch('module.research.project.research_detect', return_value=[None, project]):
            queue_check.match.return_value = False
            identities = research_drop.read_research_identities(make_image(), 2)

        self.assertEqual(identities, [('D-737-MI', 5), ('D-737-MI', 5)])

    def test_list_without_finished_project_reports_unknown(self):
        with patch.object(research_drop, 'get_parser', return_value=make_parser([])), \
                patch('module.research.assets.QUEUE_CHECK') as queue_check, \
                patch('module.research.project.get_research_finished', return_value=None), \
                patch('module.research.project.research_detect', return_value=[]):
            queue_check.match.return_value = False
            identities = research_drop.read_research_identities(make_image(), 2)

        self.assertEqual(identities, [('', 0), ('', 0)])


if __name__ == '__main__':
    unittest.main()
