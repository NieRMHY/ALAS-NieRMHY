# Modify by NieRMHY: 将游戏更新窗口逻辑独立成模块，降低主调度器的合并冲突概率。
from datetime import datetime, timedelta

from module.config.deep import deep_get
from module.config.utils import DEFAULT_TIME
from module.logger import logger


# Modify by NieRMHY: 维护窗口中允许继续运行的任务列表，使用显式复选框配置，便于后续维护与合并。
GAME_UPDATE_KEEP_TASKS = (
    ('Commission', 'GameUpdateTasks_KeepCommission'),
    ('Tactical', 'GameUpdateTasks_KeepTactical'),
    ('Research', 'GameUpdateTasks_KeepResearch'),
    ('Dorm', 'GameUpdateTasks_KeepDorm'),
    ('Meowfficer', 'GameUpdateTasks_KeepMeowfficer'),
    ('Guild', 'GameUpdateTasks_KeepGuild'),
    ('Reward', 'GameUpdateTasks_KeepReward'),
    ('Awaken', 'GameUpdateTasks_KeepAwaken'),
    ('Island', 'GameUpdateTasks_KeepIsland'),
    ('Exercise', 'GameUpdateTasks_KeepExercise'),
    ('ShopFrequent', 'GameUpdateTasks_KeepShopFrequent'),
    ('ShopOnce', 'GameUpdateTasks_KeepShopOnce'),
    ('Shipyard', 'GameUpdateTasks_KeepShipyard'),
    ('Gacha', 'GameUpdateTasks_KeepGacha'),
    ('Freebies', 'GameUpdateTasks_KeepFreebies'),
    ('Minigame', 'GameUpdateTasks_KeepMinigame'),
    ('PrivateQuarters', 'GameUpdateTasks_KeepPrivateQuarters'),
    ('EventShop', 'GameUpdateTasks_KeepEventShop'),
    ('OpsiShop', 'GameUpdateTasks_KeepOpsiShop'),
    ('OpsiVoucher', 'GameUpdateTasks_KeepOpsiVoucher'),
    ('OpsiAshAssist', 'GameUpdateTasks_KeepOpsiAshAssist'),
)


class GameUpdateManager:
    # Modify by NieRMHY: 维护前置停止时长的兜底值，当前端配置缺失或非法时使用。
    DEFAULT_DELAY_HOURS = 2

    @classmethod
    def _ensure_datetime(cls, value):
        # Modify by NieRMHY: 配置文件中的时间可能是字符串，统一转换后再参与维护窗口判断。
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _matches_target_time(cls, value, target_time):
        # Modify by NieRMHY: 即使时间字符串解析失败，只要文本上已等于目标时间，也视为无需重复保存。
        parsed_value = cls._ensure_datetime(value)
        if parsed_value is not None:
            return parsed_value >= target_time

        if isinstance(value, str):
            normalized = value.strip()
            target_candidates = {
                str(target_time),
                target_time.isoformat(sep=' '),
                target_time.isoformat(),
            }
            return normalized in target_candidates

        return False

    @classmethod
    def _get_update_value(cls, config, group, key, fallback=None):
        # Modify by NieRMHY: 维护窗口配置存放在 UpdateDate 任务下，不能依赖当前绑定任务读取。
        return deep_get(config.data, keys=f'UpdateDate.{group}.{key}', default=fallback)

    @classmethod
    def get_allowed_tasks(cls, config):
        # Modify by NieRMHY: 从独立复选框配置中收集维护期间允许继续运行的任务。
        allowed_tasks = set()
        for task_name, attr_name in GAME_UPDATE_KEEP_TASKS:
            option_name = attr_name.replace('GameUpdateTasks_', '', 1)
            if cls._get_update_value(config, 'GameUpdateTasks', option_name, getattr(config, attr_name, False)):
                allowed_tasks.add(task_name)
        return allowed_tasks

    @classmethod
    def get_delay_hours(cls, config):
        # Modify by NieRMHY: 允许前端配置提前进入维护模式的小时数，同时兼容旧配置与异常值。
        delay_hours = cls._get_update_value(
            config,
            'GameUpdate',
            'StopBeforeHours',
            getattr(config, 'GameUpdate_StopBeforeHours', cls.DEFAULT_DELAY_HOURS),
        )
        try:
            delay_hours = float(delay_hours)
        except (TypeError, ValueError):
            return cls.DEFAULT_DELAY_HOURS

        return delay_hours if delay_hours >= 0 else cls.DEFAULT_DELAY_HOURS

    @classmethod
    def get_state(cls, config):
        # Modify by NieRMHY: 统一计算维护窗口状态，供调度器在取任务前复用。
        if not cls._get_update_value(config, 'GameUpdate', 'Enable', getattr(config, 'GameUpdate_Enable', False)):
            return None

        start_time = cls._get_update_value(
            config,
            'GameUpdate',
            'StartTime',
            getattr(config, 'GameUpdate_StartTime', DEFAULT_TIME),
        )
        end_time = cls._get_update_value(
            config,
            'GameUpdate',
            'EndTime',
            getattr(config, 'GameUpdate_EndTime', DEFAULT_TIME),
        )
        start_time = cls._ensure_datetime(start_time)
        end_time = cls._ensure_datetime(end_time)
        if start_time is None or end_time is None:
            return None
        if end_time <= start_time:
            return None

        now = datetime.now().replace(microsecond=0)
        delay_hours = cls.get_delay_hours(config)
        window_start = (start_time - timedelta(hours=delay_hours)).replace(microsecond=0)
        if now < window_start or now >= end_time:
            return None

        return {
            'delay_hours': delay_hours,
            'window_start': window_start,
            'start': start_time.replace(microsecond=0),
            'end': end_time.replace(microsecond=0),
            'allowed_tasks': cls.get_allowed_tasks(config),
        }

    @classmethod
    def apply(cls, config):
        # Modify by NieRMHY: 在维护窗口内将未勾选的任务推迟到维护结束，结束后自动恢复正常调度。
        state = cls.get_state(config)
        if state is None:
            return None

        end_time = state['end']
        allowed_tasks = state['allowed_tasks']
        delayed_tasks = []

        for task_name, task_data in config.data.items():
            if not deep_get(task_data, keys='Scheduler.Enable', default=False):
                continue

            command = deep_get(task_data, keys='Scheduler.Command', default='Unknown')
            if command in allowed_tasks:
                continue

            next_run = deep_get(task_data, keys='Scheduler.NextRun', default=DEFAULT_TIME)
            if cls._matches_target_time(next_run, end_time):
                continue

            logger.info(f'游戏更新窗口已生效，推迟任务 `{command}` 到 {end_time}')
            config.modified[f'{task_name}.Scheduler.NextRun'] = end_time
            delayed_tasks.append(command)

        if delayed_tasks:
            kept = sorted(allowed_tasks)
            logger.info(f'游戏更新窗口期间保留任务: {kept if kept else "无"}')
            config.save()

        return state