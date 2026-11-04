"""独立舰队科技的实例隔离、事务编辑与显式底稿并集接口。"""
from module.config.transaction import config_transaction
from module.api.protocol import ApiError
from module.runtime import fleet_tech as tech
from module.runtime import dock_data
from module.runtime.fleet_cultivation import mind_costs_100_to_120
from module.runtime.fleet_database import FleetDatabase, FleetDatabaseConflict


class FleetTechService:
    def __init__(self, configs):
        self.configs = configs

    def catalog(self, instance):
        self.configs.path(instance)
        return dict(tech.public_catalog(), mind_costs_100_to_120=mind_costs_100_to_120())

    def report(self, instance):
        data = FleetDatabase(self.configs.path(instance)).load()
        return dict(instance=instance, **tech.report(dock_data.technology_record(data)))

    def patch(self, instance, expected_revision, changes, nations):
        path = self.configs.path(instance)
        with self.configs.lock, config_transaction(path):
            self.configs.path(instance)
            try:
                FleetDatabase(path).patch_technology(
                    [change.model_dump(exclude_unset=True) for change in changes], nations, expected_revision)
            except FleetDatabaseConflict as exc:
                raise ApiError('CONFLICT', str(exc)) from exc
            except (ValueError, TypeError, KeyError) as exc:
                raise ApiError('INVALID_PARAMS', str(exc)) from exc
        return self.report(instance)


    def merge_ships(self, instance, expected_revision):
        """用户显式合并舰船正向事实，保留已有科技里程碑。"""
        path = self.configs.path(instance)
        with self.configs.lock, config_transaction(path):
            self.configs.path(instance)
            try:
                FleetDatabase(path).merge_ship_technology(expected_revision)
            except FleetDatabaseConflict as exc:
                raise ApiError('CONFLICT', str(exc)) from exc
            except (ValueError, TypeError, KeyError) as exc:
                raise ApiError('INVALID_PARAMS', str(exc)) from exc
        return self.report(instance)
