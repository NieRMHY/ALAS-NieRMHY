"""科研前置操作必须以项目已启动为前提。"""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from module.research.research import RewardResearch
from module.ui.page import page_research


class ResearchStartRequirementsTests(unittest.TestCase):
    def make_research(self, results):
        research = object.__new__(RewardResearch)
        research.config = SimpleNamespace(Research_RemainingCommissions=9)
        research.research_project_started = '原有状态'
        events = Mock()
        for name in ('research_project_start', 'storage_disassemble_equipment',
                     'ui_ensure', 'research_project_list_init'):
            setattr(research, name, getattr(events, name))
        research.research_project_start.side_effect = results
        return research, events

    def test_failed_initial_start_has_no_requirement_side_effects(self):
        for genre in ('E', 'T'):
            for result in (False, None):
                with self.subTest(genre=genre, result=result):
                    research, events = self.make_research([result])
                    project = SimpleNamespace(genre=genre, equipment_amount=3, commission_amount=4)
                    self.assertIs(research.research_project_start_with_requirements(project), result)
                    self.assertEqual(events.mock_calls,
                                     [call.research_project_start(project, add_queue=False)])
                    self.assertEqual(research.config.Research_RemainingCommissions, 9)
                    self.assertEqual(research.research_project_started, '原有状态')

    def test_equipment_requirements_follow_successful_start(self):
        for add_queue in (False, True):
            for result in (False, None, True):
                with self.subTest(add_queue=add_queue, result=result):
                    research, events = self.make_research([True, result])
                    project = SimpleNamespace(genre='E', equipment_amount=3)
                    self.assertIs(research.research_project_start_with_requirements(
                        project, add_queue=add_queue), result)
                    self.assertEqual(events.mock_calls, [
                        call.research_project_start(project, add_queue=False),
                        call.storage_disassemble_equipment(amount=3),
                        call.ui_ensure(page_research),
                        call.research_project_list_init(),
                        call.research_project_start(project, add_queue=add_queue),
                    ])

    def test_commission_project_records_requirement_after_start(self):
        research, events = self.make_research([True])
        project = SimpleNamespace(genre='T', commission_amount=4)
        self.assertFalse(research.research_project_start_with_requirements(project))
        self.assertEqual(research.config.Research_RemainingCommissions, 4)
        self.assertIsNone(research.research_project_started)
        self.assertEqual(events.mock_calls, [call.research_project_start(project, add_queue=False)])

    def test_regular_and_index_projects_keep_direct_start(self):
        for project in (2, SimpleNamespace(genre='D'), SimpleNamespace(genre='E', equipment_amount=0)):
            for result in (False, None, True):
                with self.subTest(project=project, result=result):
                    research, events = self.make_research([result])
                    self.assertIs(research.research_project_start_with_requirements(
                        project, add_queue=False), result)
                    self.assertEqual(events.mock_calls,
                                     [call.research_project_start(project, add_queue=False)])


if __name__ == '__main__':
    unittest.main()
