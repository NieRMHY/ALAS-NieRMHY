"""原调度的石油控制：临时优先刷图，冷却时购粮，并恢复受阻领奖。"""
import time
from datetime import datetime, timedelta

from module.config.time_source import now
from module.logger import logger


FARM_TASKS = ('Main', 'Main2', 'Main3', 'Event', 'Event2', 'Event3')


class NativeOilControl:
    def __init__(self, runtime):
        self.runtime = runtime
        self.active = False
        self.check_pending = True
        self.observe_pending = True
        self.goal = None
        self.request_target = None
        self.oil = None
        self.tried = set()
        self.running_task = None
        self.blocked_task = None
        self.blocked_attempts = 0
        self.blocked_requested = False
        self.forced = False
        self.buy_attempts = 0
        self.retry_at = None
        self.action = ''
        self.result = None

    @property
    def config(self):
        return self.runtime.script.config

    @property
    def enabled(self):
        return self.runtime.mode == 'native' and self.config.cross_get('General.OilControl.Enable', False) is True

    @property
    def target(self):
        return int(self.config.cross_get('General.OilControl.Target', 24000))

    def is_farming(self, config):
        return self.runtime.mode == 'native' and self.active and self.running_task == config.task.command

    def latest_oil(self):
        row = self.runtime.store.observations(self.runtime.script.config_name).get('Oil', {})
        try:
            age = (now() - datetime.fromisoformat(row['observedAt'])).total_seconds()
        except (KeyError, ValueError, TypeError):
            return None
        value = row.get('Value')
        return value if type(value) is int and 0 <= value <= 25000 and 0 <= age <= 300 else None

    def recovery_due(self):
        config = self.config
        deadline = config.cross_get('Restart.Scheduler.NextRun')
        return config.is_task_enabled('Restart') and isinstance(deadline, datetime) and deadline <= now()

    def request_blocked(self, task):
        """领奖受阻后让出队首；每轮最多三次清理，之后延后五分钟。"""
        if not self.enabled:
            return False
        if task != self.blocked_task:
            self.blocked_task, self.blocked_attempts = task, 0
        if self.blocked_attempts >= 3:
            self.abort('清理三次后领奖仍受阻')
            return True
        self.blocked_attempts += 1
        self.blocked_requested = True
        self.forced = True
        self.active = True
        self.goal = None
        self.tried.clear()
        self.buy_attempts = 0
        self.observe_pending = True
        self.retry_at = None
        logger.attr('石油控制-受阻任务', task)
        return True

    def abort(self, reason):
        logger.warning(f'[石油控制] {reason}，五分钟后随现有任务再检查')
        self.retry_at = now() + timedelta(minutes=5)
        if self.blocked_task:
            self.config.task_delay(target=self.retry_at, task=self.blocked_task)
        self.active = False
        self.goal = None
        self.check_pending = True
        self.forced = False
        self.blocked_task, self.blocked_attempts = None, 0
        self.blocked_requested = False

    def finish(self):
        logger.attr('石油控制-完成', self.oil)
        self.active = False
        self.check_pending = False
        self.forced = False
        self.goal = None

    def perform(self, action):
        """观察和购粮复用任务异常出口与运行监护，不新建定时任务。"""
        script = self.runtime.script
        self.action, self.result = action, None
        previous = (getattr(script, '_watchdog_active', False), getattr(script, '_watchdog_task_start', 0),
                    getattr(script, '_watchdog_task_name', ''))
        script._watchdog_active, script._watchdog_task_start, script._watchdog_task_name = True, time.monotonic(), 'OilControl'
        try:
            success = script.run('oil_control')
            if success == 'recoverable':
                # 观察发生在首个业务任务之前，也必须执行实际请求的恢复。
                script.is_first_task = False
            return success is True and self.result is not None
        finally:
            script._watchdog_active, script._watchdog_task_start, script._watchdog_task_name = previous

    def run_action(self):
        from module.scheduler.resources import observe_oil
        if self.action == 'buy':
            from module.dorm.dorm import RewardDorm
            self.buy_attempts += 1
            dorm = RewardDorm(self.config, self.runtime.script.device)
            if not dorm.dorm_buy_oil_food(self.oil, self.goal):
                return
            self.result = observe_oil(self.config, self.runtime.script.device, publish=False)
            purchase = getattr(dorm, '_oil_food_purchase', None)
            if self.result is not None:
                if purchase and self.result < self.oil:
                    from module.statistics.resource_flow import record
                    record(self.config, {'Oil': -purchase[1], 'Food': purchase[0]}, '后宅购粮', task='OilControl')
                from module.log_res import LogRes
                LogRes(self.config).record('Oil', self.result, source='oil_control')
                self.config.save()
        else:
            self.result = observe_oil(self.config, self.runtime.script.device)

    def candidates(self):
        from module.config.config import Function
        from module.base.filter import Filter
        config = self.config
        config.load()
        order = Filter(regex=r'(.*)', attr=['command'])
        order.load(config.SCHEDULER_PRIORITY)
        tasks = [Function(config.data.get(name, {})) for name in FARM_TASKS]
        for task in order.apply(tasks):
            groups = config.data.get(task.command, {})
            deadline = self.runtime.script.task_restart_delays.get(task.command)
            if (task.enable and isinstance(task.next_run, datetime) and task.next_run <= now()
                    and task.command not in self.tried and (deadline is None or deadline <= now())
                    and groups.get('Campaign', {}).get('Mode') == 'normal'):
                yield task.command

    def select(self, original=None):
        """只在已有任务就绪或清理尚未完成时派发，不唤醒空闲实例。"""
        if not self.enabled:
            self.active = False
            return original
        stop = self.runtime.script.stop_event
        if stop is not None and stop.is_set():
            return original
        if original == 'Restart' or self.recovery_due():
            return 'Restart'
        # 仓库统计只读取物品，不消耗石油或领取奖励；保留检查状态给下一项业务。
        if original == 'StorageStatistics':
            return original
        if self.retry_at is not None and now() < self.retry_at:
            return original
        if original is None and not self.active:
            return None
        if original == self.blocked_task:
            self.blocked_requested = False
        if self.active or self.check_pending:
            if self.observe_pending or not self.active:
                if not self.perform('observe'):
                    self.abort('无法可靠识别石油')
                    return self.available_original(original)
                self.oil = self.result
                if not self.enabled or self.runtime.script.stop_event and self.runtime.script.stop_event.is_set():
                    self.active = False
                    return original
                self.observe_pending = False
                self.check_pending = False
                if self.forced and self.oil <= 500:
                    self.abort('石油已达安全下限，无法继续为领奖释放空间')
                    return self.available_original(original)
                if self.goal is None:
                    self.goal = min(self.target, max(500, self.oil - 499)) if self.forced else self.target
                    self.request_target = self.target
                if self.oil < self.goal or (not self.active and self.oil <= self.target):
                    self.finish()
                    return original
                self.active = True
            for task in self.candidates():
                self.tried.add(task)
                self.running_task = task
                floor = self.config.cross_get(f'{task}.StopCondition.OilLimit', 1000)
                self.runtime.overlay = {'StopCondition_OilLimit': max(floor, self.goal), 'TaskBalancer_Enable': False}
                self.runtime.attach(self.config)
                logger.attr('石油控制-优先刷图', task)
                return task
            previous = self.oil
            if self.buy_attempts >= 3 or not self.perform('buy') or self.result >= previous:
                self.abort('后宅购粮未能有效清理石油')
                return self.available_original(original)
            self.oil = self.result
            if self.oil < self.goal:
                self.finish()
                return original
            # 数量受限时有界地继续购粮，每批都重新验证实际消耗。
            return self.select(original)
        return original

    def available_original(self, task):
        """受阻任务已被延后时，要求父调度重新选队列。"""
        if self.recovery_due():
            return 'Restart'
        deadline = self.config.cross_get(f'{task}.Scheduler.NextRun') if task else None
        return None if isinstance(deadline, datetime) and deadline > now() else task

    def should_yield(self, config):
        if self.is_farming(config):
            config.load()
            if self.target != self.request_target:
                self.goal = None
                self.tried.clear()
                self.buy_attempts = 0
                return True
            if not self.enabled or self.runtime.program_changed() or self.recovery_due():
                return True
            deadline = config.cross_get(f'{config.task.command}.Scheduler.NextRun')
            if not config.is_task_enabled(config.task.command) or (isinstance(deadline, datetime) and deadline > now()):
                return True
            oil = self.latest_oil()
            return oil is not None and oil < self.goal
        if self.enabled and (self.retry_at is None or now() >= self.retry_at):
            oil = self.latest_oil()
            if oil is not None and oil > self.target:
                self.active, self.observe_pending = True, True
                self.goal = None
                self.tried.clear()
                self.buy_attempts = 0
                return True
        return None

    def target_reached(self, config, oil=None):
        if not self.is_farming(config):
            return False
        if oil is None:
            oil = self.latest_oil()
        return oil is not None and oil > 0 and oil < self.goal

    def task_finished(self, task, success):
        if task == self.running_task:
            self.running_task = None
            self.runtime.overlay = {}
            self.runtime.attach(self.config)
            self.config.bind(self.config.task)
            self.observe_pending = True
            if success is False:
                self.abort('刷图执行失败')
        elif task == self.blocked_task and not self.blocked_requested and success is True:
            self.blocked_task, self.blocked_attempts = None, 0
        if not self.active:
            self.check_pending = True
