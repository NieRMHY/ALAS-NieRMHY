"""共享船坞数据与扫描范围接口；浏览和配置不会启动游戏任务。"""
import json
from contextlib import contextmanager

from deploy.atomic import atomic_write
from module.api.protocol import ApiError
from module.config.transaction import config_transaction
from module.runtime import dock_data, fleet_tech
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseAlreadyImported, FleetDatabaseConflict


class DockService:
    def __init__(self, configs):
        self.configs = configs

    def report(self, instance):
        data, _ = self.configs.read(instance)
        fields = data.get('DockScan', {}).get('Dock', {})
        state = FleetDatabase(self.configs.path(instance)).load(include_pending=True, include_import_status=True)
        report = dock_data.report_snapshot(state)
        # 旧记录同样呈现当前满星默认值，浏览不改写逐船数据或累计科技。
        report['ships'] = [dict(ship, full_star=fleet_tech.full_star_state(ship)) for ship in report['ships']]
        # 控制项显示下一次扫描的配置，快照覆盖范围另附在 scan_range 中。
        return dict(report, instance=instance, legacy_imported=state['legacy_imported'],
                    pending_revision=state.get('pending_revision'), pending_changes=state.get('pending_changes', []),
                    pending_read=state.get('pending_read'),
                    scan_range=dict(min_level=report['min_level'], max_level=report['max_level']),
                    min_level=fields.get('MinLevel', 1), max_level=fields.get('MaxLevel', 125))

    def configure(self, instance, min_level, max_level):
        if not 1 <= min_level <= max_level <= 125:
            raise ApiError('INVALID_PARAMS', '扫描等级范围必须满足 1 ≤ 最低等级 ≤ 最高等级 ≤ 125')
        with self.configs.lock, config_transaction(self.configs.path(instance)):
            data, _ = self.configs.read(instance)
            fields = data.setdefault('DockScan', {}).setdefault('Dock', {})
            fields.update(MinLevel=min_level, MaxLevel=max_level)
            atomic_write(str(self.configs.path(instance)), json.dumps(data, ensure_ascii=False, indent=2))
            return self.report(instance)

    @contextmanager
    def _mutation(self, instance, invalid_message):
        """Keep instance deletion and database edits under the same lifecycle locks."""
        path = self.configs.path(instance)
        with self.configs.lock, config_transaction(path):
            self.configs.path(instance)
            try:
                yield FleetDatabase(path)
            except FleetDatabaseConflict as exc:
                raise ApiError('CONFLICT', str(exc)) from exc
            except (ValueError, TypeError, KeyError) as exc:
                raise ApiError('INVALID_PARAMS', f'{invalid_message}：{exc}') from exc

    def patch(self, instance, expected_revision, changes):
        """只更新用户明确编辑的物理副本。"""
        with self._mutation(instance, '舰船修改无效') as database:
            database.patch_cards(changes, expected_revision)
        return self.report(instance)

    def review(self, instance, expected_revision, pending_revision, decisions):
        """按候选项逐条采纳或拒绝，并同时检查数据和候选版本。"""
        with self._mutation(instance, '审核决定无效') as database:
            database.review(decisions, expected_revision, pending_revision)
        return self.report(instance)

    def stage_import(self, instance, expected_revision, ships):
        """File and screenshot readings share the ordinary pending-review workflow."""
        with self._mutation(instance, '导入数据无效') as database:
            database.stage_import(ships, expected_revision)
        return self.report(instance)

    def import_legacy(self, instance, expected_revision):
        """显式读取旧 JSON 生成候选变化，原文件保留供用户核对。"""
        from module.runtime.fleet_legacy import convert_legacy

        path = self.configs.path(instance)
        with self.configs.lock, config_transaction(path):
            self.configs.path(instance)
            database = FleetDatabase(path)
            try:
                # 仅迁移按钮读取原文件，不经过模板或旧字段回退。
                original = json.loads(path.read_text(encoding='utf-8-sig'))
                database.stage_legacy(convert_legacy(original), expected_revision)
            except FleetDatabaseConflict as exc:
                raise ApiError('CONFLICT', '舰船数据已更新，请重新载入后导入') from exc
            except FleetDatabaseAlreadyImported as exc:
                raise ApiError('ALREADY_IMPORTED', '本实例已完成旧数据迁移') from exc
            except (ValueError, TypeError, KeyError) as exc:
                raise ApiError('INVALID_PARAMS', f'旧舰船数据无法迁移：{exc}') from exc
        return self.report(instance)
