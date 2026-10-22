"""验证大世界地图事件的点击兜底与跨重启续查。

背景（用户实机日志）：明石刷新在左下角时会和“第一舰队 FLEET SELECT”等按钮
重合，点击坐标落进舰队选择栏而不是明石。旧代码在距离 <= 1 时直接调用
handle_akashi_supply_buy，内部的 ui_click 会一直等 is_in_map，点击永远等不到
商店，最后触发设备卡死检查抛 GameStuckError，游戏重启后这只猫就漏掉了。

这里的用例锁定两条需求：

1. 点击事件没反应时不能再无界空转：收起舰队栏、快速失败，交给换其他舰队，
   其他舰队都不行再升级强制移动（recovery=True 时不受“强制移动”开关限制）。
2. 已经看见事件、但点击/装置后续自律途中卡死重启时，把待办记进隐藏配置项，
   重启后先续查：装置已提交物品按模式补自律（敌人模式共 3 次——游戏可能把
   自律暂停，需要重新点击直到三次；资源模式 1 次收柱子，点完资源即消耗，
   不要求对应事件再次完成），卡死重启后只补记录里剩下的次数；其他情况先
   全图扫描、再强制移动，都没看到事件就清记录继续下一轮。
"""

import unittest
from contextlib import nullcontext
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from module.base.utils import location2node
from module.os.map import OSMap
from module.os.map_event_resume import PENDING_MAP_EVENT_KEY, MapEventResumeMixin

RESET = datetime(2026, 11, 1)


class ConfigStub:
    """替换 AzurLaneConfig 里续查记录用到的读写接口。"""

    SERVER = "cn"

    def __init__(self, data=None, command="OpsiHazard1Leveling", siren_fleet=0):
        self.data = dict(data or {})
        self.task = SimpleNamespace(command=command)
        self.siren_fleet = siren_fleet
        self.writes = 0

    def cross_get(self, keys, default=None):
        if keys.endswith("OpsiSirenBug.Siren_Fleet"):
            return self.siren_fleet
        return self.data.get(keys, default)

    def cross_set(self, keys, value):
        self.writes += 1
        self.data[keys] = value

    def temporary(self, **kwargs):
        return nullcontext()


class FleetSelectorStub:
    def __init__(self, current=1):
        self.current = current

    def get(self):
        return self.current


class GridStub:
    def __init__(self, location=(1, 2)):
        self.location = location


def make_state(**overrides):
    """构造一条合法的续查记录。"""
    state = {
        "version": 1,
        "reset": RESET.isoformat(),
        "server": "cn",
        "zone": 22,
        "type": "akashi",
        "node": "B3",
        "grid": [1, 2],
        "mode": None,
        "submitted": False,
        "remaining": 0,
        "fleet": 1,
        "created": "2026-10-20T02:00:00",
    }
    state.update(overrides)
    return state


class ResumeStub(MapEventResumeMixin):
    """只提供续查流程需要的属性，记录外部调用次数。"""

    def __init__(
        self,
        state=None,
        zone_id=22,
        server="cn",
        map_rescan_action=None,
        forced_action=None,
    ):
        self.config = ConfigStub(
            {PENDING_MAP_EVENT_KEY: state} if state is not None else {}
        )
        self.config.SERVER = server
        self.zone = SimpleNamespace(zone_id=zone_id)
        self.fleet_selector = FleetSelectorStub()
        self._solved_map_event = {"is_akashi"}
        self._solved_fleet_mechanism = True
        self._question_unreachable = False
        self.map_rescan_calls = []
        self.forced_calls = []
        self.followups = []
        self.finish_calls = []
        self.map_rescan_action = map_rescan_action
        self.forced_action = forced_action
        self.forced_question_unreachable = None

    def map_rescan(self, rescan_mode="full", drop=None):
        self.map_rescan_calls.append((rescan_mode, drop))
        if self.map_rescan_action is not None:
            self.map_rescan_action(self)
        return True

    def _execute_fixed_patrol_scan(
        self, ExecuteFixedPatrolScan=False, recovery=False, **kwargs
    ):
        self.forced_calls.append((ExecuteFixedPatrolScan, recovery))
        self.forced_question_unreachable = self._question_unreachable
        if self.forced_action is not None:
            self.forced_action(self)

    def _run_siren_followup_search(self, mode, drop=None, remaining=None):
        self.followups.append((mode, remaining, drop))

    def _finish_pending_map_event(self, event_type, node=None):
        self.finish_calls.append((event_type, node))
        MapEventResumeMixin._finish_pending_map_event(self, event_type, node=node)


class AkashiStub:
    """只提供有界点击明石需要的属性。"""

    def __init__(self, results, bar=False, in_map=True):
        self.results = list(results)
        self.bar = bar
        self.in_map = in_map
        self.clicks = []
        self.bar_closed = 0
        self.config = ConfigStub()
        self.device = SimpleNamespace(click=self.clicks.append)

    def wait_until_walk_stable(self, **kwargs):
        return self.results.pop(0) if self.results else ""

    def _close_fleet_bar_if_open(self):
        if self.bar:
            self.bar = False
            self.bar_closed += 1
            return True
        return False

    def is_in_map(self):
        return self.in_map


class TestPendingRecord(unittest.TestCase):
    """续查记录的写入、校验与清除。"""

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_save_writes_event_and_keeps_single_record(self, _reset):
        stub = ResumeStub()
        grid = GridStub((1, 2))
        stub._save_pending_map_event("akashi", grid)

        state = stub._read_pending_map_event()
        self.assertEqual(state["type"], "akashi")
        self.assertEqual(state["node"], location2node((1, 2)))
        self.assertEqual(state["grid"], [1, 2])
        self.assertEqual(state["zone"], 22)
        self.assertEqual(state["server"], "cn")
        self.assertEqual(state["reset"], RESET.isoformat())
        self.assertIsNone(state["mode"])
        self.assertFalse(state["submitted"])

        # 同格的同一事件在多个摄像机视野里重复识别，不重复写配置
        writes = stub.config.writes
        stub._save_pending_map_event("akashi", grid)
        self.assertEqual(stub.config.writes, writes)

        # 换了事件格子才写入新记录
        stub._save_pending_map_event("scanning_device", GridStub((3, 4)))
        self.assertGreater(stub.config.writes, writes)
        self.assertEqual(stub._read_pending_map_event()["type"], "scanning_device")

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_valid_record_round_trip(self, _reset):
        stub = ResumeStub(state=make_state(mode="enemy", submitted=True))
        state = stub._load_pending_map_event()
        self.assertIsNotNone(state)
        self.assertEqual(stub._read_pending_map_event()["mode"], "enemy")

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_expired_or_mismatched_record_is_dropped(self, _reset):
        cases = {
            "reset": make_state(reset=datetime(2026, 12, 1).isoformat()),
            "server": make_state(server="en"),
            "zone": make_state(zone=44),
            "type": make_state(type="mystery"),
            "node": make_state(node=""),
            "mode": make_state(mode="weird"),
            "version": make_state(version=0),
        }
        for name, state in cases.items():
            with self.subTest(field=name):
                stub = ResumeStub(state=state)
                self.assertIsNone(stub._load_pending_map_event())
                self.assertIsNone(stub.config.data[PENDING_MAP_EVENT_KEY])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_finish_only_clears_matching_event(self, _reset):
        state = make_state()
        stub = ResumeStub(state=state)
        stub._finish_pending_map_event("scanning_device")
        self.assertEqual(stub._read_pending_map_event()["node"], "B3")
        stub._finish_pending_map_event("akashi", node="C4")
        self.assertEqual(stub._read_pending_map_event()["node"], "B3")
        stub._finish_pending_map_event("akashi", node="B3")
        self.assertIsNone(stub._read_pending_map_event())


class TestBoundedAkashiClick(unittest.TestCase):
    """明石点击必须有界：点不到就快速失败，别等设备卡死。"""

    def test_success_returns_true(self):
        stub = AkashiStub(["", "akashi"])
        self.assertTrue(OSMap._open_akashi_store(stub, GridStub()))
        self.assertEqual(len(stub.clicks), 2)

    def test_click_swallowed_by_fleet_bar_returns_false(self):
        stub = AkashiStub([""], bar=True)
        self.assertFalse(OSMap._open_akashi_store(stub, GridStub()))
        self.assertEqual(stub.bar_closed, 1)
        # 收起舰队栏后同一坐标再点还是按钮，不再重试
        self.assertEqual(len(stub.clicks), 1)

    def test_no_response_tries_bounded_then_fails(self):
        stub = AkashiStub(["", "", ""])
        self.assertFalse(OSMap._open_akashi_store(stub, GridStub()))
        self.assertEqual(len(stub.clicks), 3)

    def test_leaving_map_stops_retry(self):
        stub = AkashiStub([""], in_map=False)
        self.assertFalse(OSMap._open_akashi_store(stub, GridStub()))
        self.assertEqual(len(stub.clicks), 1)


class TestSirenFollowup(unittest.TestCase):
    """装置提交物品后的自律：敌人模式 3 次，资源模式 1 次。"""

    def run_followup(self, mode, siren_fleet=0, remaining=None, state=None):
        stub = ResumeStub(state=state)
        stub.fleet_sets = []
        stub.search_calls = []
        stub.fleet_set = stub.fleet_sets.append
        stub.os_auto_search_run = lambda drop=None: stub.search_calls.append(drop)
        stub.config.siren_fleet = siren_fleet
        # ResumeStub 覆盖了续查方法用于记录，这里直接验证真实实现
        MapEventResumeMixin._run_siren_followup_search(
            stub, mode, drop=None, remaining=remaining
        )
        return stub

    def test_enemy_mode_switches_fleet_and_runs_three_times(self):
        stub = self.run_followup("enemy", siren_fleet=2)
        self.assertEqual(stub.search_calls, [None, None, None])
        self.assertEqual(stub.fleet_sets, [2, 1])

    def test_enemy_mode_without_configured_fleet_runs_three_times(self):
        stub = self.run_followup("enemy", siren_fleet=0)
        self.assertEqual(stub.search_calls, [None, None, None])
        self.assertEqual(stub.fleet_sets, [])

    def test_enemy_mode_resume_runs_only_remaining_times(self):
        stub = self.run_followup("enemy", siren_fleet=2, remaining=2)
        self.assertEqual(stub.search_calls, [None, None])
        self.assertEqual(stub.fleet_sets, [2, 1])

    def test_enemy_mode_records_remaining_after_each_run(self):
        state = make_state(
            type="scanning_device", mode="enemy", submitted=True, remaining=3
        )
        stub = self.run_followup("enemy", siren_fleet=2, state=state)
        self.assertEqual(stub.search_calls, [None, None, None])
        self.assertEqual(stub._read_pending_map_event()["remaining"], 0)

    def test_resource_mode_runs_once(self):
        stub = self.run_followup("resource")
        self.assertEqual(stub.search_calls, [None])
        self.assertEqual(stub.fleet_sets, [])

    def test_unknown_mode_runs_once(self):
        stub = self.run_followup(None)
        self.assertEqual(stub.search_calls, [None])

    def test_collected_mode_does_not_run(self):
        stub = self.run_followup("collected")
        self.assertEqual(stub.search_calls, [])
        self.assertEqual(stub.fleet_sets, [])


class TestResumePendingEvent(unittest.TestCase):
    """重启后续查的分支。"""

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_no_record_does_nothing(self, _reset):
        stub = ResumeStub()
        stub._resume_pending_map_event()
        self.assertEqual(stub.map_rescan_calls, [])
        self.assertEqual(stub.forced_calls, [])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_submitted_device_resumes_remaining_searches(self, _reset):
        state = make_state(
            type="scanning_device", mode="enemy", submitted=True, remaining=1
        )
        stub = ResumeStub(state=state)
        stub._resume_pending_map_event()
        self.assertEqual(stub.followups, [("enemy", 1, None)])
        self.assertEqual(stub.finish_calls, [("scanning_device", "B3")])
        self.assertEqual(stub.map_rescan_calls, [])
        self.assertEqual(stub.forced_calls, [])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_legacy_submitted_record_without_remaining_runs_full_mode(self, _reset):
        state = make_state(type="scanning_device", mode="enemy", submitted=True)
        state.pop("remaining")
        stub = ResumeStub(state=state)
        stub._resume_pending_map_event()
        self.assertEqual(stub.followups, [("enemy", 3, None)])
        self.assertEqual(stub.finish_calls, [("scanning_device", "B3")])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_full_scan_found_by_scan(self, _reset):
        stub = ResumeStub(state=make_state())
        stub.map_rescan_action = lambda s: s._clear_pending_map_event()
        stub._resume_pending_map_event()
        self.assertEqual(stub.map_rescan_calls, [("full", None)])
        self.assertEqual(stub.forced_calls, [])
        self.assertEqual(stub.finish_calls, [])
        # 续查先把上一轮的已处理标记清空，避免“已解决”挡住真正的重扫
        self.assertEqual(stub._solved_map_event, set())
        self.assertFalse(stub._solved_fleet_mechanism)

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_scan_not_found_escalates_to_forced_move(self, _reset):
        stub = ResumeStub(state=make_state())
        stub.forced_action = lambda s: s._clear_pending_map_event()
        stub._resume_pending_map_event()
        self.assertEqual(stub.map_rescan_calls, [("full", None)])
        self.assertEqual(stub.forced_calls, [(True, True)])
        # 事件已经看见了：挪舰队不受行动力门槛限制
        self.assertTrue(stub.forced_question_unreachable)
        self.assertEqual(stub.finish_calls, [])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_not_found_after_full_sweep_clears_and_continues(self, _reset):
        stub = ResumeStub(state=make_state())
        stub._resume_pending_map_event()
        self.assertEqual(stub.forced_calls, [(True, True)])
        self.assertEqual(stub.finish_calls, [("akashi", "B3")])
        self.assertIsNone(stub.config.data[PENDING_MAP_EVENT_KEY])

    @mock.patch("module.os.map_event_resume.get_os_next_reset", return_value=RESET)
    def test_invalid_record_clears_without_touching_map(self, _reset):
        stub = ResumeStub(state=make_state(zone=44))
        stub._resume_pending_map_event()
        self.assertEqual(stub.map_rescan_calls, [])
        self.assertEqual(stub.forced_calls, [])
        self.assertIsNone(stub.config.data[PENDING_MAP_EVENT_KEY])


class RecoverAkashiStub:
    """只提供明石兜底需要的属性。"""

    def __init__(self):
        self.config = SimpleNamespace(
            task=SimpleNamespace(command="OpsiHazard1Leveling")
        )
        self._opsi_meowfficer_cleanup = False
        self._unreachable_event_nodes = set()
        self.forced_calls = []
        self.marked = []

    def _goto_akashi_with_other_fleets(self, drop=None):
        return False

    def _mark_event_unreachable(self, node):
        self.marked.append(node)

    def _execute_fixed_patrol_scan(
        self, ExecuteFixedPatrolScan=False, recovery=False, **kwargs
    ):
        self.forced_calls.append((ExecuteFixedPatrolScan, recovery))


class TestRecoverAkashiEscalation(unittest.TestCase):
    def test_all_fleets_failed_escalates_to_recovery_forced_move(self):
        stub = RecoverAkashiStub()
        self.assertFalse(OSMap._recover_unreachable_akashi(stub, None, "B3"))
        self.assertEqual(stub.marked, ["B3"])
        self.assertEqual(stub.forced_calls, [(True, True)])


class PatrolRecoveryStub:
    """只提供强制移动恢复旁路需要的属性。"""

    _FIXED_PATROL_L2_AP = OSMap._FIXED_PATROL_L2_AP
    _question_unreachable = True

    def __init__(self, enabled):
        self.config = SimpleNamespace(
            OpsiFleet_Fleet=1,
            task=SimpleNamespace(command="OpsiHazard1Leveling"),
        )
        self.map = SimpleNamespace(grids=[object()])
        self.enabled = enabled
        self.fleet_sets = []
        self.scan_calls = 0
        self.move_calls = 0

    def _forced_move_enabled(self):
        return self.enabled

    def map_init(self, map_=None):
        pass

    def clear_question_any_fleet(self, drop=None):
        self.scan_calls += 1
        return False

    def _move_fleets_and_rescan(self):
        self.move_calls += 1
        return False

    def fleet_set(self, index=1):
        self.fleet_sets.append(index)


class TestFixedPatrolRecoveryBypass(unittest.TestCase):
    """看见了事件时，强制移动开关关着也要执行恢复。"""

    def test_switch_off_still_skips_normal_round(self):
        stub = PatrolRecoveryStub(enabled=False)
        OSMap._execute_fixed_patrol_scan(
            stub, ExecuteFixedPatrolScan=True, recovery=False
        )
        self.assertEqual(stub.scan_calls, 0)
        self.assertEqual(stub.move_calls, 0)

    def test_switch_off_runs_when_recovering_seen_event(self):
        stub = PatrolRecoveryStub(enabled=False)
        OSMap._execute_fixed_patrol_scan(
            stub, ExecuteFixedPatrolScan=True, recovery=True
        )
        self.assertEqual(stub.scan_calls, 1)
        self.assertEqual(stub.move_calls, 1)


if __name__ == "__main__":
    unittest.main()
