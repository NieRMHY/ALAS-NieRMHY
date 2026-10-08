"""大世界模拟器的实例校验与 WebSocket 接口服务。"""

from module.api.protocol import ApiError
from module.runtime.os_simulator import OSSimulatorManager
from module.runtime.process_manager import ProcessManager


class OpsiSimulatorService:
    def __init__(self, configs):
        self.configs = configs
        self.manager = OSSimulatorManager(configs.root / 'log/oss/figures')

    def status(self, instance, after=0):
        self.configs.path(instance)
        return self.manager.status(instance, after)

    def start(self, instance):
        self.configs.path(instance)
        # 与实例删除共用生命周期锁，防止启动和删除交错留下失去配置的模拟。
        with ProcessManager._get_lifecycle_lock(instance):
            data, _ = self.configs.read(instance)
            if not self.manager.start(instance, data):
                raise ApiError('SIMULATOR_RUNNING', '模拟正在进行，请先中断或等待完成')
            return self.manager.status(instance)

    def stop(self, instance):
        self.configs.path(instance)
        self.manager.stop(instance)
        return self.manager.status(instance)

    def figure(self, instance):
        self.configs.path(instance)
        return {'instance': instance, 'image': self.manager.figure(instance)}
