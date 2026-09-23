"""行动力仪表盘口径回归测试。

防止行动力溢出任务会在 temporary(OS_ACTION_POINT_BOX_USE=False) 上下文中代跑
大世界子任务。若此时把受开关影响的 total 写进 Dashboard.ActionPoint.Total，
WebUI 的「总行动力」会退化成当前行动力，整段时间都不显示。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from module.os_handler.action_point import ActionPointHandler


class TestActionPointDashboardTotal(unittest.TestCase):
    """action_point_update() 写入仪表盘的总行动力必须恒含体力箱。"""

    current = 186
    # OIL_ITEM 一格雷 500 + ACTION_POINT_ITEMS 三格 0/1/2，按 ACTION_POINT_BOX 折算共 250
    box = (0, 1, 2)
    box_sum = 250

    def update(self, box_use):
        handler = ActionPointHandler.__new__(ActionPointHandler)
        handler.device = SimpleNamespace(image=None)
        handler.config = SimpleNamespace(
            OS_ACTION_POINT_BOX_USE=box_use,
            update=MagicMock(),
            override=MagicMock(),
        )
        log_res = MagicMock()
        with patch('module.os_handler.action_point.LogRes', return_value=log_res), \
                patch('module.os_handler.action_point.OIL_ITEM') as oil_item, \
                patch('module.os_handler.action_point.ACTION_POINT_ITEMS') as items, \
                patch('module.os_handler.action_point.OCR_ACTION_POINT_REMAIN') as ocr:
            oil_item.predict.return_value = [SimpleNamespace(amount=500)]
            items.predict.return_value = [SimpleNamespace(amount=amount) for amount in self.box]
            ocr.ocr.return_value = self.current
            handler.action_point_update()
        return handler, log_res

    def test_total_includes_box_when_box_use_enabled(self):
        handler, log_res = self.update(box_use=True)

        self.assertEqual(log_res.ActionPoint, {'Value': self.current, 'Total': self.current + self.box_sum})
        self.assertEqual(handler._action_point_total, self.current + self.box_sum)

    def test_total_still_includes_box_when_box_use_disabled(self):
        # 防溢出任务临时关闭开箱开关，业务判据照旧不含箱，但仪表盘口径不应随之退化
        handler, log_res = self.update(box_use=False)

        self.assertEqual(log_res.ActionPoint, {'Value': self.current, 'Total': self.current + self.box_sum})
        self.assertEqual(handler._action_point_total, self.current)


if __name__ == '__main__':
    unittest.main()
