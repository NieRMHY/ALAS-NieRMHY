"""大世界状态追踪模块。

管理大世界（Operation Siren）模式的状态信息，包括海域代币
（黄币/紫币）的 OCR 数值追踪、任务类型识别、子任务冷却（CD）
状态的实时计算，以及相关日志资源的记录。
"""
# 此文件用于管理大世界（Operation Siren）模式下的状态信息。
# 负责海域代币（黄币/紫币）的数值追踪、任务类型识别以及子任务冷却（CD）状态的实时计算。
import threading
import typing as t
from datetime import timedelta
from time import perf_counter

import numpy as np

from module.base.decorator import cached_property
import module.config.server as server
from module.base.timer import Timer
from module.base.utils import crop
from module.config.config import Function
from module.config.time_source import now as current_time
from module.config.utils import get_server_next_update
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.ocr.ocr import Digit, ocr_batch
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_SHIP
from module.os_shop.assets import OS_SHOP_CHECK, OS_SHOP_PURPLE_COINS, PORT_SUPPLY_CHECK, SHOP_PURPLE_COINS, SHOP_YELLOW_COINS
from module.os_handler.resource_state import effective_task, resource_fast_path
from module.os_handler.resource_read import BackgroundCoinRead, CoinReplenishRequired
from module.os_handler.resource_write import record_resources_background
from module.ui.ui import UI
from module.log_res.log_res import LogRes


if server.server != 'jp':
    OCR_SHOP_YELLOW_COINS = Digit(SHOP_YELLOW_COINS, letter=(239, 239, 239), threshold=160, name='OCR_SHOP_YELLOW_COINS')
else:
    OCR_SHOP_YELLOW_COINS = Digit(SHOP_YELLOW_COINS, letter=(201, 201, 201), threshold=200, name='OCR_SHOP_YELLOW_COINS')
OCR_SHOP_PURPLE_COINS = Digit(SHOP_PURPLE_COINS, letter=(255, 255, 255), name='OCR_SHOP_PURPLE_COINS')
OCR_OS_SHOP_PURPLE_COINS = Digit(OS_SHOP_PURPLE_COINS, letter=(255, 255, 255), name='OCR_OS_SHOP_PURPLE_COINS')


class OSStatus(UI):
    _shop_yellow_coins = 0
    _shop_purple_coins = 0
    _cache_lock = threading.Lock()
    _last_yellow_coins = 0

    def _background_coin_identity(self):
        return (getattr(self.config, 'config_name', None), server.server,
                getattr(self.config, '_opsi_coin_revision', 0))

    def poll_background_resources(self, *, sample=False):
        """无等待验收后台结果；只在已确认的地图画面提交下一张截图。"""
        if not resource_fast_path(self.config):
            return
        state = self.__dict__.get('_coin_background')
        if state is None:
            if not sample:
                return
            state = self._coin_background = BackgroundCoinRead()
        in_map = sample and self.is_in_map()
        if (in_map and state.frame is not None and not np.array_equal(
                crop(self.device.image, OCR_SHOP_YELLOW_COINS.buttons[0]),
                crop(state.frame, OCR_SHOP_YELLOW_COINS.buttons[0]))):
            # 奖励后数字已变化，不能把开工前完成的两次 OCR 当作当前预算。
            state.invalidate()
        try:
            reading = state.poll(self._background_coin_identity())
        except Exception:
            # 无效或失败的观察不覆盖最后一次成功读数，下个地图帧重新尝试。
            logger.exception('[大世界-资源后台] 货币识别失败')
            reading = None
        if state.last_result is not None:
            result, state.last_result = state.last_result, None
            apply_ap = getattr(self, 'apply_background_action_point', None)
            if apply_ap is not None:
                apply_ap(result)
        if reading is not None:
            self._last_yellow_coins = self._shop_yellow_coins = reading.yellow
            self._last_yellow_owner = reading.identity[:2]
            self._yellow_coin_read = (
                (*reading.identity[:2], 'map', reading.identity[2]),
                crop(state.frame, OCR_SHOP_YELLOW_COINS.buttons[0]).copy(), reading.yellow,
            )
            record_resources_background(
                self.config, {'YellowCoin': reading.yellow},
                observed_at=reading.observed_at,
            )
        ap_due = bool(sample and getattr(self, 'action_point_check_due', lambda: False)())
        if in_map and (state.wanted or ap_due) and not self.handle_map_event():
            readers = [OCR_SHOP_YELLOW_COINS]
            if ap_due:
                from module.os_handler.action_point import OCR_ACTION_POINT_REMAIN_OS
                readers.append(OCR_ACTION_POINT_REMAIN_OS)
            state.submit(self.device.image, readers, self._background_coin_identity(),
                         ap_epoch=self.__dict__.get('_ap_read_epoch', 0), ap_spent=self.__dict__.get('_ap_spent', 0))

    def get_routine_yellow_coins(self):
        """数字未变化时复用确认值；变化后双读确认，避免旧预算影响调度。"""
        state = self.__dict__.get('_coin_background')
        if state is not None:
            state.request()
        self.poll_background_resources(sample=True)
        return self.get_yellow_coins(reuse=True)

    def background_coin_replenish_required(self):
        """按最新保留值判断，补币任务不被自己的低黄币观察打断。"""
        # 短猫同样需要消费后台结果；只有低币中断限定为侵蚀一。
        self.poll_background_resources(sample=self.is_in_map())
        if not self.is_running_cl1_leveling:
            return False
        state = self.__dict__.get('_coin_background')
        reading = state.accepted if state is not None else None
        if reading is None or reading.identity != self._background_coin_identity():
            return False
        smart = getattr(self, 'is_running_smart_scheduling_task', lambda: False)()
        preserve = (self._get_smart_scheduling_operation_coins_preserve() if smart else
                    self.config.OpsiHazard1Leveling_OperationCoinsPreserve)
        return reading.yellow < preserve

    def handle_background_coin_interrupt(self, drop=None):
        """后台只报告读数；主线程通过现有退出循环安全返回地图。"""
        if not self.background_coin_replenish_required():
            return
        # 地图的自律 ON/OFF 外观可能同时匹配。保留低币请求，等加载/暂停
        # 状态进入原有退出循环；事件已结束则由下一轮调度直接切换补币。
        if self.is_in_map():
            return
        logger.info('[大世界-资源后台] 黄币不足，中断本轮计划作战并返回补黄币决策')
        self.interrupt_auto_search(goto_main=False, end_task=False, drop=drop)
        self.device.screenshot_interval_set()
        raise CoinReplenishRequired()

    @property
    def is_in_task_explore(self) -> bool:
        return self.config.task.command in ('OpsiExplore', 'OpsiExploreCleanup')

    @property
    def is_in_task_cl1_leveling(self) -> bool:
        return self.config.task.command == 'OpsiHazard1Leveling'

    @property
    def is_running_cl1_leveling(self) -> bool:
        """判断当前执行上下文是否是侵蚀1练级。"""
        return (
            self.is_in_task_cl1_leveling
            or getattr(self.config, '_bind_task_override', None) == 'OpsiHazard1Leveling'
        )

    @property
    def is_in_task_meow(self) -> bool:
        """判断当前任务是否是耄耋相接任务"""
        return self.config.task.command == 'OpsiMeowfficerFarming'

    @property
    def is_cl1_enabled(self) -> bool:
        return self.config.is_task_enabled('OpsiHazard1Leveling')

    @property
    def is_cl1_mode_enabled(self) -> bool:
        """判断侵蚀1相关策略是否启用，包括智能调度代理模式。"""
        is_smart_scheduling_enabled = getattr(self, 'is_smart_scheduling_enabled', None)
        return self.is_cl1_enabled or (
            is_smart_scheduling_enabled is not None
            and is_smart_scheduling_enabled()
        )

    @property
    def is_meow_enabled(self) -> bool:
        """判断耄耋相接任务是否启用"""
        return self.config.is_task_enabled('OpsiMeowfficerFarming')

    @property
    def cl1_enough_yellow_coins(self) -> bool:
        return self.get_yellow_coins() >= self.config.cross_get(
            keys='OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve')

    @property
    def nearest_task_cooling_down(self) -> t.Optional[Function]:
        """
        获取一小时内结束冷却的大世界任务，例如侦察扫描、潜艇呼叫冷却。

        已到期任务不属于冷却任务，不能将其过去的运行时间传给代理任务，
        否则防止行动力溢出等高优先级任务会立即重跑并阻塞其他任务。
        """
        now = current_time()
        update = get_server_next_update('00:00')
        cd_tasks = [
            'OpsiObscure',
            'OpsiAbyssal',
            'OpsiStronghold',
            'OpsiDaily',
        ]

        def func(task: Function):
            if task.command in cd_tasks and task.enable:
                if task.next_run != update and now < task.next_run <= now + timedelta(minutes=60):
                    return True

            return False

        tasks = SelectedGrids(self.config.pending_task + self.config.waiting_task).filter(func).sort('next_run')
        return tasks.first_or_none()

    @property
    def bought_all_yellow_coin_items_in_port_shop(self) -> bool:
        return self.config.cross_get("OpsiShop.Storage.Storage.BoughtAllYellowCoinItems", False)

    @cached_property
    def yellow_coins_preserve(self):
        if self.is_cl1_enabled and not self.bought_all_yellow_coin_items_in_port_shop:
            return 100000
        else:
            return 35000

    def get_yellow_coins(self, *, with_purple=False, reuse=False) -> int:
        """
        通过 OCR 获取当前拥有的作战补给凭证（黄币）数量。

        采用连续两次稳定比对校验，若超时未能获取则降级使用缓存的最近有效值。

        Returns:
            int: 黄币数量。
        """
        started = perf_counter()
        fast = resource_fast_path(self.config)
        if self.appear(OS_SHOP_CHECK):
            page_kind = 'port'
            purple_ocr = OCR_OS_SHOP_PURPLE_COINS
        else:
            page_kind = 'akashi' if self.appear(PORT_SUPPLY_CHECK) else 'map'
            purple_ocr = OCR_SHOP_PURPLE_COINS
        cache_key = (getattr(self.config, 'config_name', None), server.server, page_kind,
                     getattr(self.config, '_opsi_coin_revision', 0))
        image = self.device.image
        cached = self.__dict__.get('_yellow_coin_read')
        if fast and reuse and not with_purple and cached is not None and isinstance(image, np.ndarray):
            if cache_key == cached[0] and np.array_equal(crop(image, OCR_SHOP_YELLOW_COINS.buttons[0]), cached[1]):
                logger.info('[大世界处理-状态] 复用本轮已确认的黄币读数')
                return cached[2]

        yellow_coins = 0
        timeout = Timer(5, count=10).start()  # 增加超时时间和重试次数
        last_valid_value = None
        purple_region = None
        if fast and with_purple:
            self._paired_purple_read = (0, False)
        
        for _ in self.loop():
            # 结束
            if self.appear_then_click(GET_ITEMS_1, offset=True, interval=1):
                last_valid_value = None
                timeout.reset()
                continue
            if self.appear_then_click(GET_ITEMS_2, offset=True, interval=1):
                last_valid_value = None
                timeout.reset()
                continue
            # GET_SHIP 素材已随上游更新，需补 offset 容差，否则弹窗可能关不掉
            if self.appear_then_click(GET_SHIP, offset=(20, 20), interval=1):
                last_valid_value = None
                timeout.reset()
                continue

            if fast and with_purple:
                region = crop(self.device.image, purple_ocr.buttons[0])
                if purple_region is not None and np.array_equal(region, purple_region):
                    current_value = OCR_SHOP_YELLOW_COINS.ocr(self.device.image)
                else:
                    current_value, purple = ocr_batch(self.device.image, [OCR_SHOP_YELLOW_COINS, purple_ocr])
                    valid = bool(getattr(purple_ocr, 'last_valid', False))
                    self._paired_purple_read = (purple, valid)
                    purple_region = region.copy() if valid else None
            else:
                current_value = OCR_SHOP_YELLOW_COINS.ocr(self.device.image)
            if timeout.reached():
                logger.warning('[大世界处理-状态] 获取黄币超时')
                break

            if current_value == 0 or not bool(getattr(OCR_SHOP_YELLOW_COINS, 'last_valid', False)):
                last_valid_value = None
                # 界面未完全渲染或弹窗遮挡顶部栏时 OCR 可能识别为 0
                logger.info('[大世界处理-状态] 黄币为 0，可能是 OCR 错误或界面未加载')
                continue
            else:
                # 验证识别稳定性：连续两次识别相同才确认
                if last_valid_value is None:
                    last_valid_value = current_value
                elif last_valid_value == current_value:
                    yellow_coins = current_value
                    break
                else:
                    last_valid_value = current_value
        
        # 如果最终仍未获取到有效数值，使用上次缓存的值（线程安全）
        observed = yellow_coins > 0
        if observed:
            self._last_yellow_owner = self._background_coin_identity()[:2]
        if observed and '_coin_background' in self.__dict__:
            self._coin_background.invalidate()
        with self._cache_lock:
            if yellow_coins == 0:
                same_owner = self.__dict__.get('_last_yellow_owner') == self._background_coin_identity()[:2]
                yellow_coins = self._last_yellow_coins if same_owner else 0
                logger.info(f'[大世界处理-状态] 使用同实例缓存的黄币值: {yellow_coins}')
            
            # 缓存当前值用于降级
            self._last_yellow_coins = yellow_coins
        
        recognized = perf_counter()
        options = {'defer_history': True} if fast else {}
        if fast and observed:
            record_resources_background(self.config, {'YellowCoin': yellow_coins})
        else:
            LogRes(self.config).record('YellowCoin', yellow_coins, observed=observed, **options)
        if fast and observed and isinstance(self.device.image, np.ndarray):
            self._yellow_coin_read = (
                cache_key, crop(self.device.image, OCR_SHOP_YELLOW_COINS.buttons[0]).copy(), yellow_coins,
            )
        logger.info(f'[大世界处理-状态] 黄币: {yellow_coins}')
        logger.info(f'[大世界-货币耗时] OCR={recognized - started:.3f}s，'
                    f'黄币记录={perf_counter() - recognized:.3f}s')

        return yellow_coins

    def get_purple_coins(self) -> int:
        """
        通过 OCR 获取当前拥有的特别兑换凭证（紫币）数量。

        Returns:
            int: 紫币数量。
        """
        if self.appear(OS_SHOP_CHECK):
            ocr = OCR_OS_SHOP_PURPLE_COINS
        else:
            ocr = OCR_SHOP_PURPLE_COINS
        purple_coins = ocr.ocr(self.device.image)
        options = {'defer_history': True} if resource_fast_path(self.config) else {}
        if resource_fast_path(self.config) and bool(getattr(ocr, 'last_valid', False)):
            record_resources_background(self.config, {'PurpleCoin': purple_coins})
        else:
            LogRes(self.config).record('PurpleCoin', purple_coins, observed=bool(getattr(ocr, 'last_valid', False)), **options)
        return purple_coins

    def os_shop_get_coins(self):
        """
        同时获取大世界黄币与紫币数量，并保存历史快照数据。
        """
        started = perf_counter()
        fast = resource_fast_path(self.config)
        if fast:
            self._shop_yellow_coins = self.get_yellow_coins(with_purple=True)
            self._shop_purple_coins, valid = self._paired_purple_read
            if valid:
                record_resources_background(self.config, {'PurpleCoin': self._shop_purple_coins})
        else:
            self._shop_yellow_coins = self.get_yellow_coins()
            self._shop_purple_coins = self.get_purple_coins()
        recorded = perf_counter()
        logger.info(f'[大世界处理-状态] 黄币: {self._shop_yellow_coins}, 紫币: {self._shop_purple_coins}')

        # 记录凭证快照到数据库（用于 WebUI 凭证变化曲线图）
        try:
            instance_name = getattr(self.config, 'config_name', 'default')
            task = effective_task(self.config)
            source = 'cl1' if task == 'OpsiHazard1Leveling' else ('meow' if task == 'OpsiMeowfficerFarming' else 'other')
            from module.statistics.cl1_database import db as cl1_db
            writer = cl1_db.async_add_coins_snapshot if fast else cl1_db.add_coins_snapshot
            writer(
                instance_name,
                self._shop_yellow_coins,
                self._shop_purple_coins,
                source=source
            )
            queued = perf_counter()
            # 常规资源由后台保存；同步提交与资源无关的业务配置修改。
            if not fast or self.config.modified:
                self.config.save()
            logger.info(f'[大世界-货币耗时] 识别与即时记录={recorded - started:.3f}s，'
                        f'历史快照提交={queued - recorded:.3f}s，配置={perf_counter() - queued:.3f}s')
        except Exception:
            logger.exception('[大世界处理-状态] 记录凭证快照失败')
