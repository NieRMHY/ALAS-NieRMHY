"""余烬 META 战斗管理模块。

处理大世界余烬（Ash）信标系统的 META 战斗，包括信标等级
OCR、伤害输出识别、META 战斗状态页面的检测与导航、奖励
领取、以及自动搜索可用信标并发起挑战的完整战斗流程。
"""
import re
from datetime import datetime, timedelta
from enum import Enum

import module.config.server as server
from module.base.decorator import cached_property
from module.base.timer import Timer
from module.combat.combat import BATTLE_PREPARATION
from module.config.config import TaskEnd
from module.config.time_source import now as current_time
from module.logger import logger
from module.meta_reward.meta_reward import MetaReward
from module.ocr.ocr import Digit, DigitCounter
from module.os_ash.ash import AshCombat
from module.os_ash.assets import *
from module.os_handler.map_event import MapEventHandler
from module.ui.assets import BACK_ARROW
from module.ui.page import page_reward
from module.ui.ui import UI


class MetaState(Enum):
    """META 页面状态枚举。"""
    INIT = 'no meta begin'
    ATTACKING = 'a meta under attack'
    COMPLETE = 'reward to be collected'
    UNDEFINED = 'a undefined page'


OCR_BEACON_TIER = Digit(BEACON_TIER, name='OCR_ASH_TIER')
if server.server != 'jp':
    OCR_META_DAMAGE = Digit(META_DAMAGE, name='OCR_META_DAMAGE')
else:
    OCR_META_DAMAGE = Digit(META_DAMAGE, letter=(201, 201, 201), name='OCR_META_DAMAGE')


class MetaDigitCounter(DigitCounter):
    """META 数字计数器，修正 OCR 常见识别错误。"""

    def after_process(self, result):
        """后处理 OCR 结果，修正常见误识别。

        处理逻辑：
        - "00/200" -> "100/200"（首位 0 被识别为数字 0）
        - "23" -> "2/3"（斜杠丢失，仅当首位为 0-3 时修正）
        - "1/40/1400" -> "140/1400"（多余的斜杠）

        Args:
            result (str): OCR 原始字符串。

        Returns:
            str: 修正后的字符串。
        """
        result = super().after_process(result)

        # "00/200" -> "100/200"
        if result.startswith('00/'):
            result = '100/' + result[3:]

        # "23" -> "2/3"
        if re.match(r'^[0123]3$', result):
            result = f'{result[0]}/{result[1]}'

        # "1/40/1400" -> "140/1400"
        for suffix in ['/1400', '/200']:
            if result.endswith(suffix):
                point = result[:-len(suffix)]
                point = point.replace('/', '')
                result = point + suffix

        return result


OCR_BEACON_REMAIN = MetaDigitCounter(BEACON_REMAIN, letter=(235, 235, 235), threshold=160)


class Meta(UI, MapEventHandler):
    """META 战斗基础模块，处理地图事件和 OCR 识别。"""

    def digit_ocr_point_and_check(self, button: Button, check_number: int):
        """OCR 读取按钮上的数字，判断是否达到阈值。

        Args:
            button (Button): 要识别的按钮区域。
            check_number (int): 判断阈值。

        Returns:
            bool: 识别值是否 >= 阈值。
        """
        point_ocr = MetaDigitCounter(button, letter=(235, 235, 235), threshold=160, name='POINT_OCR')
        point, _, _ = point_ocr.ocr(self.device.image)
        if point >= check_number:
            return True
        return False

    def handle_map_event(self, drop=None):
        """处理 META 地图中的各种事件弹窗。

        处理自动攻击完成确认、误入帮助页面、误入战斗准备页面等情况。

        Args:
            drop (DropImage, optional): 掉落图像处理器。

        Returns:
            bool: 是否采取了行动。
        """
        if super().handle_map_event(drop):
            return True
        if self.appear_then_click(META_AUTO_CONFIRM, offset=(20, 20), interval=2):
            logger.info('[META作战] 检测到自动攻击完成')
            return True
        if self.appear(HELP_CONFIRM, offset=(30, 30), interval=2):
            logger.info('[META作战] 误入帮助确认页面')
            self.device.click(BACK_ARROW)
            return True
        if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
            logger.info('[META作战] 误入战斗准备页面')
            self.device.click(BACK_ARROW)
            return True
        if self.handle_popup_cancel('META'):
            return True
        if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
            return True
        return False

    @cached_property
    def ash_combat(self):
        """复用同一个 AshCombat 实例，跨多场战斗保持战前/战后装备状态。"""
        return AshCombat(config=self.config, device=self.device)

    def _in_meta_page(self):
        """判断当前是否在 META 相关页面（主页面、信标或档案）。

        Returns:
            bool: 是否在 META 相关页面。
        """
        return self.appear(ASH_SHOWDOWN, offset=(30, 30)) \
               or self.appear(BEACON_LIST, offset=(20, 20)) \
               or self.appear(DOSSIER_LIST, offset=(20, 20))

    def _in_meta_assist_page(self):
        """判断当前是否在信标协助页面。

        Returns:
            bool: 是否在信标协助页面。
        """
        return self.appear(BEACON_MY, offset=(20, 20))

    def handle_ash_equipment_after(self, skip_first_screenshot=True):
        """在 META 出击全部结束后，进入战斗准备界面恢复战后装备并退回。

        普通信标显示模拟战斗时，确认模拟入口后借用同一编队恢复装备。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否完成了战后装备恢复。

        Pages:
            in: META 主页面、信标页、档案页、协助页或战斗准备页
            out: 信标页或 META 主页面；协助处理器返回协助页
        """
        # 最后一场可能是档案战斗，但此前普通信标的装备仍然需要恢复。
        if not self.ash_combat.equipment_handle_before_flag:
            return False

        logger.hr('META战后装备恢复', level=2)
        timeout = Timer(15, count=30).start()
        fallback_from = None
        simulate_requested = False

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(BATTLE_PREPARATION, offset=(30, 30)):
                if self.ash_combat.is_dossier:
                    if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                        self.device.click(BACK_ARROW)
                    continue
                break
            if timeout.reached():
                logger.warning('[META作战] 无法进入战斗准备页面恢复装备，跳过战后换装')
                return False

            if simulate_requested and self.handle_popup_confirm('META_EQUIPMENT_SIMULATE'):
                continue

            if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
                self.device.click(META_MAIN_BEACON_ENTRANCE)
                continue

            # 档案使用独立编队，必须先返回普通信标，不能借用档案出击入口。
            if self.appear(DOSSIER_LIST, offset=(20, 20)):
                self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                continue

            # 支援列表为空，或已显示出击入口但次数耗尽，才借用「我的信标」。
            if self.appear(BEACON_MY, offset=(20, 20)):
                self.ash_combat.is_dossier = False
                if self.appear(BEACON_EMPTY, offset=(20, 20)) or (
                        self.appear(ASH_START, offset=(30, 30))
                        and not self.digit_ocr_point_and_check(BEACON_REMAIN, 1)):
                    if fallback_from == 'beacon':
                        logger.warning('[META作战] 无法进入战斗准备页面恢复装备，跳过战后换装')
                        return False
                    fallback_from = 'assist'
                    self.appear_then_click(BEACON_MY, offset=(20, 20), interval=2)
                    continue

            # 用领奖或解析入口正向确认当前信标不可出击，避免加载中误切换。
            if self.appear(BEACON_LIST, offset=(20, 20)):
                self.ash_combat.is_dossier = False
                # 已结束的信标仍可通过模拟战斗进入普通编队，冷却中也不切换备用入口。
                if self.appear(ASH_SIMULATE, offset=(30, 30)):
                    if self.appear_then_click(ASH_SIMULATE, offset=(30, 30), interval=2):
                        simulate_requested = True
                    continue
                if self.appear(BEACON_REWARD, offset=(30, 30)) or self.appear(META_BEGIN_ENTRANCE, offset=(20, 20)):
                    if fallback_from == 'assist':
                        logger.warning('[META作战] 无法进入战斗准备页面恢复装备，跳过战后换装')
                        return False
                    fallback_from = 'beacon'
                    self.appear_then_click(BEACON_LIST, offset=(20, 20), interval=2)
                    continue

            if self.appear_then_click(ASH_START, offset=(30, 30), interval=2):
                continue

        self.ash_combat.equipment_handle_after()

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if isinstance(self, AshBeaconAssist):
                if self._in_meta_assist_page():
                    break
                if self.appear_then_click(BEACON_LIST, offset=(20, 20), interval=2):
                    continue
                if self.appear(DOSSIER_LIST, offset=(20, 20)):
                    self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                    continue
                if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
                    self.device.click(META_MAIN_BEACON_ENTRANCE)
                    continue
            else:
                if self._in_meta_page():
                    break
                if self.appear_then_click(BEACON_MY, offset=(20, 20), interval=2):
                    continue
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

        return True


def _server_support():
    """当前服务器是否支持信标和求援后自行作战。

    Returns:
        bool: 当前服务器是否支持。
    """
    return server.server in ['cn', 'en', 'jp', 'tw']


def _server_support_dossier_auto_attack():
    """当前服务器是否支持档案自动攻击。

    Returns:
        bool: 当前服务器是否支持。
    """
    return server.server in ['cn', 'en']


class OpsiAshBeacon(Meta):
    """META 统一任务，处理支援、信标、档案及共用装备的恢复。"""
    _meta_receive = []
    _meta_category = "undefined"
    _assist_pending = False
    _meta_waiting = False
    _meta_delay = None

    @cached_property
    def ash_assist(self):
        """支援沿用当前任务的配置与战斗实例，跨阶段只应用一次装备方案。"""
        assist = AshBeaconAssist(config=self.config, device=self.device)
        assist.ash_combat = self.ash_combat
        return assist

    def _delay_meta(self, **kwargs):
        """任务内先汇总等待条件，支援结束后再合并十分钟重试并写入排期。"""
        if self._meta_delay is not None:
            if 'minute' in kwargs and 'minute' in self._meta_delay:
                kwargs['minute'] = min(kwargs['minute'], self._meta_delay['minute'])
            self._meta_delay.update(kwargs)
            return
        if self._assist_pending:
            kwargs['minute'] = min(kwargs.get('minute', 10), 10)
        self.config.task_delay(**kwargs)

    def _is_dossier_active(self, skip_first_screenshot=True):
        """支援前领取待结算的档案奖励，仅在确认档案未开启后放行。

        Args:
            skip_first_screenshot (bool): 是否复用进入档案页后的当前截图。

        Returns:
            bool: 档案仍开启时返回 True；只有确认解析入口时返回 False。

        Pages:
            in: in_meta
            out: in_meta, DOSSIER_LIST
        """
        self.ensure_dossier_page()
        while True:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_event():
                continue
            if self.appear(DOSSIER_LIST, offset=(20, 20)):
                # 领奖仍占用已开启的档案，点击后必须用新截图确认解析入口。
                if self.appear(BEACON_REWARD, offset=(20, 20)):
                    if self.appear_then_click(BEACON_REWARD, offset=(20, 20), interval=2):
                        logger.info('[META作战] 支援前领取档案奖励，等待确认档案未开启')
                        if 'dossier' not in self._meta_receive:
                            self._meta_receive.append('dossier')
                    continue
                if self.appear(META_AUTO_ATTACKING, offset=(20, 20)) \
                        or self.appear(HELP_ENTER, offset=(30, 30)):
                    return True
                if self.appear(META_BEGIN_ENTRANCE, offset=(20, 20)):
                    return False

    def _attack_meta(self, skip_first_screenshot=True):
        """处理 META 攻击的完整流程。

        根据页面状态分发：INIT 时选择信标或档案，ATTACKING 时执行攻击，
        COMPLETE 时领取奖励。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Pages:
            in: in_meta
            out: in_meta
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_event():
                continue
            state = self._get_state()
            logger.info('[META作战] 页面状态: ' + state.name)
            if MetaState.UNDEFINED == state:
                continue
            if MetaState.INIT == state:
                if self._begin_meta():
                    continue
                else:
                    # 正常结束
                    break
            if MetaState.ATTACKING == state:
                # 仅档案模式下退出信标页面
                if self.config.OpsiAshBeacon_AttackMode == 'current_dossier_only' \
                        and self.appear(BEACON_LIST, offset=(20, 20)):
                    self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                    continue
                if not self._pre_attack():
                    continue
                if self._satisfy_attack_condition():
                    self._make_an_attack()
                    continue
                break
            if MetaState.COMPLETE == state:
                if self.appear(BEACON_LIST, offset=(20, 20)):
                    self._meta_category = "beacon"
                elif self.appear(DOSSIER_LIST, offset=(20, 20)):
                    self._meta_category = "dossier"
                self._handle_ash_beacon_reward()
                if self._meta_category == 'beacon':
                    self._reset_assist_request_state()
                    if self.ash_combat.equipment_handle_before_flag and not self._check_beacon_point():
                        self.handle_ash_equipment_after()
                if not self._meta_category in self._meta_receive:
                    self._meta_receive.append(self._meta_category)
                # 击杀 META 后检查其他任务是否需要切换
                try:
                    self.config.check_task_switch()
                except TaskEnd:
                    # 保留调度器的切换信号，交接前先尝试恢复本任务借用的装备。
                    self.handle_ash_equipment_after()
                    raise
                continue

    def _make_an_attack(self):
        """
        执行一次 META 战斗。

        战斗期间处理误入战斗准备页面和帮助页面的异常情况，
        战斗结束后确认回到 META 页面。

        Pages:
            in: in_meta, ASH_START
            out: in_meta, ASH_START or BEACON_REWARD
        """
        logger.hr('META作战战斗', level=2)

        def expected_end():
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info('[META作战] 误入战斗准备页面')
                self.device.click(BACK_ARROW)
                return False
            # 误入帮助确认页面，点击帮助入口返回
            if self.appear(HELP_CONFIRM, offset=(30, 30), interval=3):
                logger.info('[META作战] 误入帮助确认页面')
                self.device.click(HELP_ENTER)
                return False
            # 已回到 META 页面，战斗结束
            if self._in_meta_page():
                logger.info('[META作战] 战斗结束并回到正确页面')
                return True

            return False

        # 执行战斗（档案使用独立编队，不触发自动换装）
        self.ash_combat.is_dossier = self.appear(DOSSIER_LIST, offset=(20, 20))
        self.ash_combat.combat(expected_end=expected_end, save_get_items=False, emotion_reduce=False)

    def _handle_ash_beacon_reward(self, skip_first_screenshot=True):
        """
        领取 META 击杀奖励。

        点击奖励按钮直到奖励界面消失，回到 META 页面。

        Pages:
            in: in_meta, BEACON_REWARD
            out: in_meta
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：奖励按钮消失且回到 META 页面
            if not self.appear(BEACON_REWARD, offset=(30, 30)):
                if self._in_meta_page():
                    break

            # 点击领取奖励
            if self.appear_then_click(BEACON_REWARD, offset=(30, 30), interval=2):
                logger.info('[META作战] 领取 META 奖励')
                continue
            # 处理随机事件
            if self.handle_map_event():
                continue
            # 误回到主页面时，点击奖励入口返回
            if self.ui_main_appear_then_click(page_reward, interval=2):
                continue
            if self.appear(META_ENTRANCE, offset=(20, 300), interval=2):
                continue

    def _satisfy_attack_condition(self):
        """
        检查当前 META 是否满足攻击条件。

        信标模式下：首刀后按求援次数与等待时间决定是否自行收尾。
        档案模式下：META 正在自动攻击时，不再手动攻击。

        Returns:
            bool: 是否满足攻击条件；等待时登记排期，由统一任务收尾。
        """
        if self.appear(BEACON_LIST, offset=(20, 20)):
            limit = self.config.OpsiAshBeacon_AssistRequestLimit
            if _server_support() and limit >= 0:
                count, next_request = self._get_assist_request_state()
                if limit > 0 and count >= limit and current_time() >= next_request:
                    logger.info(f'[META作战] 已求援 {count} 轮仍未完成，开始自行击破')
                    return True
                damage = self._get_meta_damage()
                if damage > 0:
                    logger.info(f'[META作战] 当前 META 已造成 {damage} 伤害，等待支援后再检查')
                    if limit > 0 and next_request is not None:
                        self._delay_meta(target=next_request)
                    else:
                        self._delay_meta(minute=30)
                    self._meta_waiting = True
                    return False
        if self.appear(DOSSIER_LIST, offset=(20, 20)):
            # META 正在自动攻击中
            if self.appear(META_AUTO_ATTACKING, offset=(20, 20)):
                logger.info('[META作战] 当前 META 正在自动攻击，15 分钟后检查')
                self._delay_meta(minute=15)
                self._meta_waiting = True
                return False
        return True

    def _get_assist_request_state(self):
        """读取本轮信标的求援断点；损坏记录重新求援，避免提前消耗作战资源。"""
        state = self.config.OpsiAshBeacon_AssistRequestState
        if state is None:
            return 0, None
        if isinstance(state, dict):
            count = state.get('count')
            try:
                next_request = datetime.fromisoformat(state['next_request'])
            except (KeyError, TypeError, ValueError):
                next_request = None
            if type(count) is int and count > 0 and next_request is not None and next_request.tzinfo is None:
                return count, next_request
        logger.warning('[META作战] 求援记录无效，将重新累计本轮信标的求援次数')
        return 0, None

    def _reset_assist_request_state(self):
        """确认信标已领奖或为空时清除断点，不让下一信标继承求援次数。"""
        if self.config.OpsiAshBeacon_AssistRequestState is not None:
            self.config.OpsiAshBeacon_AssistRequestState = None

    def _get_meta_damage(self):
        """
        获取当前 META 已造成的伤害值。

        Returns:
            int: OCR 识别的伤害数值。
        """
        self._ensure_meta_inner_page_damage()
        return OCR_META_DAMAGE.ocr(self.device.image)

    def _ensure_meta_inner_page_damage(self, skip_first_screenshot=True):
        """切换 META 内部页面到伤害标签页。

        如果当前在详情页，则点击切换到伤害页。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Pages:
            in: in_meta, ASH_START
            out: in_meta, META_INNER_PAGE_DAMAGE, ASH_START
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.match_template_color(META_INNER_PAGE_DAMAGE, offset=(20, 20)):
                logger.info('[META作战] 已在伤害页面')
                break
            if self.match_template_color(META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20)):
                logger.info('[META作战] 当前在详情页面，切换到伤害页面')
                self.appear_then_click(META_INNER_PAGE_NOT_DAMAGE, offset=(20, 20), interval=2)
                continue

    def _pre_attack(self):
        """攻击前的准备工作。

        信标模式下：根据配置请求协助。
        档案模式下：cn/en 服务器支持自动攻击，其他服务器暂不处理。

        Returns:
            bool: 是否准备就绪。
        """
        # 信标页面
        if self.appear(BEACON_LIST, offset=(20, 20)):
            limit = self.config.OpsiAshBeacon_AssistRequestLimit
            if limit >= 0 or self.config.OpsiAshBeacon_RequestAssist:
                if limit > 0:
                    count, next_request = self._get_assist_request_state()
                    # 首刀后立即回到此分支时仍在求援冷却；最后一轮也要留足等待时间。
                    if count >= limit or (next_request is not None and current_time() < next_request):
                        return True
                if not self._ask_for_help():
                    return False
                if limit > 0:
                    self.config.OpsiAshBeacon_AssistRequestState = {
                        'count': count + 1,
                        'next_request': (current_time() + timedelta(minutes=30)).isoformat(),
                    }
                    logger.attr('META求援轮数', f'{count + 1}/{limit}')
            return True
        # 档案页面
        if self.appear(DOSSIER_LIST, offset=(20, 20)):
            # 支持自动攻击且未在自动攻击中
            if _server_support_dossier_auto_attack() and self.config.OpsiAshBeacon_DossierAutoAttackMode \
                    and self.appear(META_AUTO_ATTACK_START, offset=(5, 5)):
                return self._dossier_auto_attack()
            return True
        return False

    def _ask_for_help(self):
        """
        请求协助，从好友、大舰队和世界频道发起求助。

        依次点击三个求助按钮，然后确认。

        Returns:
            bool: 是否成功发起协助。如果 META 在请求协助后刚好完成则返回 False。

        Pages:
            in: is_in_meta
            out: is_in_meta
        """
        # 进入帮助页面
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：帮助确认页面出现
            if self.appear(HELP_CONFIRM, offset=(20, 20)):
                break
            # 点击帮助入口
            if self.appear_then_click(HELP_ENTER, offset=(20, 20), interval=3):
                continue
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

        # 依次点击三个求助按钮，无需确认选中状态
        self.device.click(HELP_3)
        self.device.sleep((0.1, 0.3))
        self.device.click(HELP_2)
        self.device.sleep((0.1, 0.3))
        self.device.click(HELP_1)

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：帮助确认页面消失
            # 有时帮助弹窗没有黑色模糊背景，HELP_CONFIRM 和 HELP_ENTER 同时出现
            if not self.appear(HELP_CONFIRM, offset=(30, 30)):
                if self.appear(HELP_ENTER, offset=(30, 30)):
                    return True
                # META 刚好在请求协助后完成
                if self.appear(BEACON_REWARD, offset=(30, 30)):
                    logger.info('[META支援] 请求协助后 META 刚好完成，忽略本次支援')
                    return False
            # 点击确认
            if self.appear_then_click(HELP_CONFIRM, offset=(30, 30), interval=3):
                continue

    def _dossier_auto_attack(self):
        """
        启动档案自动攻击。

        点击自动攻击开始按钮并确认，直到出现自动攻击中的标记。

        Returns:
            bool: 是否成功开启自动攻击。

        Pages:
            in: is_in_meta & not auto attacking
            out: is_in_meta
        """
        timeout = Timer(10, count=20).start()
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束条件：自动攻击中
            if self.appear(META_AUTO_ATTACKING, offset=(5, 5)):
                return True
            if timeout.reached():
                logger.warning('[META作战] 档案自动攻击启动超时，可能未找到自动攻击开始按钮')
                return False
            # 已被他人击杀
            if self.appear(BEACON_REWARD, offset=(30, 30)):
                return False

            # 点击自动攻击确认和开始按钮
            if self.appear_then_click(META_AUTO_ATTACK_CONFIRM, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(META_AUTO_ATTACK_START, offset=(5, 5), interval=3):
                continue
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                self.device.click(BACK_ARROW)
                continue

    def _begin_meta(self):
        """
        无论当前在哪个 META 页面，选择或开始一个 META 战斗。

        META 主页面下：选择信标或档案入口进入。
        信标/档案页面下：开始新的 META 战斗，或返回主页面。

        Returns:
            bool: 是否需要继续循环。
        """
        
        attack_mode = self.config.OpsiAshBeacon_AttackMode
        # META 主页面
        if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
            # 信标入口
            if attack_mode != 'current_dossier_only':
                if self._check_beacon_point():
                    self.device.click(META_MAIN_BEACON_ENTRANCE)
                    logger.info('[META作战] 选择信标入口进入')
                    return True
            # 档案入口

            if _server_support() \
                    and attack_mode != 'current' \
                    and self._check_dossier_point():
                if self.appear_then_click(META_MAIN_DOSSIER_ENTRANCE, offset=(20, 20), interval=2):
                    logger.info('[META作战] 选择档案入口进入')
                    return True
                else:
                    logger.info('[META作战] 未选择档案')
            return False
        # 信标页面
        elif self.appear(BEACON_LIST, offset=(20, 20), interval=2):
            if attack_mode == 'current_dossier_only':
                self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                return True
            # 只有 INIT 状态会进入这里；主 META 入口不能证明旧信标已消失。
            self._reset_assist_request_state()
            if self._check_beacon_point():
                self.device.click(META_BEGIN_ENTRANCE)
                logger.info('[META作战] 开始信标')
            else:
                self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
            return True
        # 档案页面
        elif _server_support() \
                and self.appear(DOSSIER_LIST, offset=(20, 20), interval=2):
            if attack_mode != 'current' \
                    and self._check_dossier_point():
                if self.appear_then_click(META_BEGIN_ENTRANCE, offset=(20, 20), interval=2):
                    logger.info('[META作战] 开始档案')
                    return True
                else:
                    logger.info('[META作战] 未选择档案')
            self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
            return True
        # 未知页面
        else:
            return True

    def _check_beacon_point(self) -> bool:
        """
        检查信标积分是否 >= 100。

        Returns:
            bool: 积分是否满足开启条件。
        """
        if self.appear(META_BEACON_FLAG, offset=(180, 20)):
            META_BEACON_DATA.load_offset(META_BEACON_FLAG)
            return self.digit_ocr_point_and_check(META_BEACON_DATA.button, 100)
        return False

    def _check_dossier_point(self) -> bool:
        """
        检查档案积分是否 >= 100。

        Returns:
            bool: 积分是否满足开启条件。
        """
        if self.appear(META_DOSSIER_FLAG, offset=(180, 20)):
            META_DOSSIER_DATA.load_offset(META_DOSSIER_FLAG)
            return self.digit_ocr_point_and_check(META_DOSSIER_DATA.button, 100)
        return False

    def _get_state(self):
        """
        判断当前 META 页面状态。

        Returns:
            MetaState: 当前页面状态枚举值。
        """
        # 未知页面
        if not self._in_meta_page():
            return MetaState.UNDEFINED
        # 信标或档案页面
        elif self.appear(BEACON_LIST, offset=(20, 20)) \
                or self.appear(DOSSIER_LIST, offset=(20, 20)):
            if self.appear(HELP_ENTER, offset=(30, 30)):
                return MetaState.ATTACKING
            elif self.appear(BEACON_REWARD, offset=(20, 20)):
                return MetaState.COMPLETE
            return MetaState.INIT
        elif self.appear(ASH_SHOWDOWN, offset=(30, 30)):
            return MetaState.INIT
        return MetaState.UNDEFINED

    def _ensure_meta_page(self, skip_first_screenshot=True):
        """确保当前在 META 页面，不在则通过点击入口进入。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否成功进入 META 页面。

        Pages:
            in: page_reward
            out: in_meta
        """
        logger.info('[META作战] 确保进入信标攻击页面')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_page():
                logger.info('[META作战] 已在 META 页面')
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(BEACON_MY, offset=(20, 20), interval=2):
                continue
            if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
                continue

    def ensure_dossier_page(self, skip_first_screenshot=True):
        """确保当前在档案页面。

        先导航到奖励页面，再进入 META 页面，最后切换到档案标签。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否成功进入档案页面。

        Pages:
            in: page_reward
            out: in_meta, DOSSIER_LIST
        """
        self.ui_ensure(page_reward)
        self._ensure_meta_page()
        logger.info('[META作战] 确保进入档案 META 页面')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DOSSIER_LIST, offset=(20, 20)):
                logger.info('[META作战] 已在档案页面')
                return True
            if self.handle_map_event():
                continue
            if self.appear(ASH_SHOWDOWN, offset=(30, 30)):
                self.appear_then_click(META_MAIN_DOSSIER_ENTRANCE, offset=(20, 20), interval=2)
                continue
            if self.appear(BEACON_LIST, offset=(20, 20)):
                self.appear_then_click(ASH_QUIT, offset=(10, 10), interval=2)
                continue

    def _begin_beacon(self):
        """开始信标攻击流程，确保进入 META 页面后执行攻击。"""
        logger.hr('META作战')
        if not _server_support():
            logger.info("当前服务器暂不支持档案信标和一刀模式，请联系开发者")
        self._ensure_meta_page()
        self._attack_meta()

    def run(self):
        """先处理信标和档案，再按实际档案状态决定支援，统一恢复装备、领奖并排期。

        Pages:
            in: 任意可导航页面
            out: page_main
        """
        self._meta_receive = []
        self._assist_pending = False
        self._meta_waiting = False
        self._meta_delay = {}
        self.ui_ensure(page_reward)
        try:
            self._begin_beacon()
            if self.config.OpsiAshAssist_Enable:
                if self.config.OpsiAshBeacon_DossierSkipAssist and self._is_dossier_active():
                    logger.info('[META支援] 档案仍处于开启状态，暂停支援，15 分钟后检查')
                    self._delay_meta(minute=15)
                    self._meta_waiting = True
                else:
                    self._assist_pending = not self.ash_assist._begin_meta_assist()
                    # 支援中途找不到下一信标时，也领取此前已取得的同步奖励。
                    self._meta_receive.append('beacon')
        except TaskEnd:
            self._meta_delay = None
            self.handle_ash_equipment_after()
            raise
        self.handle_ash_equipment_after()
        self.ui_goto_main()

        with self.config.multi_set():
            for meta in dict.fromkeys(self._meta_receive):
                MetaReward(self.config, self.device).run(category=meta)
            self._meta_receive = []
            if not self._meta_waiting:
                self._delay_meta(server_update=True)
            delay = self._meta_delay
            self._meta_delay = None
            self._delay_meta(**delay)
        # MetaReward 会导航到 META/档案页面，领取完毕后需返回主界面，
        # 否则下一个任务启动时游戏仍在 META 页面导致页面识别失败而卡死
        self.ui_goto_main()


class AshBeaconAssist(Meta):
    """META 作战内的支援阶段，不单独调度或恢复共用装备。"""

    def _attack_meta(self, skip_first_screenshot=True):
        """协助攻击 META 信标。

        在信标列表中查找可用的信标，检查剩余协助次数后发起攻击。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否已确认当天支援次数耗尽；无信标或读数不可信时返回 False。

        Pages:
            in: in_meta_assist
            out: in_meta_assist
        """
        timeout = Timer(3, count=9).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_map_event():
                continue
            if self._in_meta_assist_page():
                remain, _, total = OCR_BEACON_REMAIN.ocr(self.device.image)
                # OCR 失败返回 0/0，不能据此把未完成的支援当作当天已完成。
                if total == 3 and remain == 0:
                    logger.info('[META支援] 支援次数不足，任务完成')
                    return True
                if total == 3 and remain > 0 and self.appear(ASH_START, offset=(20, 20)):
                    self._ensure_meta_level()
                    self._make_an_attack()
                    timeout.reset()
                    continue
            if timeout.reached():
                logger.info('[META支援] 未找到可支援的 META 信标或有效次数，延迟任务')
                return False

    def _make_an_attack(self):
        """执行一次 META 协助战斗。

        战斗结束后确认回到协助页面，处理误入战斗准备和主页的异常情况。

        Pages:
            in: in_meta_assist
            out: in_meta_assist
        """
        logger.hr('META支援战斗', level=2)

        def expected_end():
            # 误入战斗准备页面，点击返回
            if self.appear(BATTLE_PREPARATION, offset=(30, 30), interval=2):
                logger.info('[META支援] 误入战斗准备页面')
                self.device.click(BACK_ARROW)
                return False
            # 协助后被重定向到自己的未完成信标，切换回信标列表
            if self.appear_then_click(BEACON_LIST, offset=(-20, -5, 300, 5), interval=2):
                return False
            # 回到 META 主页面，点击信标入口
            if self.appear(ASH_SHOWDOWN, offset=(30, 30), interval=2):
                logger.info('[META支援] 战斗结束并回到 META 对决页面')
                self.device.click(META_MAIN_BEACON_ENTRANCE)
            # 已回到协助页面
            if self._in_meta_assist_page():
                logger.info('[META支援] 战斗结束并回到正确页面')
                return True

            return False

        # 执行战斗
        self.ash_combat.is_dossier = False
        self.ash_combat.combat(expected_end=expected_end, save_get_items=False, emotion_reduce=False)

    def _ensure_meta_level(self):
        """选择满足等级要求的 META 信标。

        等待信标等级数字显示后，通过 OCR 读取等级，
        不满足则翻页查找，最多尝试 5 次。
        """
        # 等待 BEACON_TIER 显示——进入信标列表时等级数字不会立即出现
        tier = self.config.OpsiAshAssist_Tier
        logger.info(f'[META支援] 开始查找等级 {tier} 的 META 信标')
        for n in range(10):
            if self.image_color_count(BEACON_TIER, color=(0, 0, 0), threshold=30, count=50):
                break

            self.device.screenshot()
            if n >= 9:
                logger.warning('[META支援] 等待信标等级显示超时')
        # 选择信标
        current = -1
        for _ in range(5):
            current = OCR_BEACON_TIER.ocr(self.device.image)
            if current >= tier:
                break
            else:
                self.device.click(BEACON_NEXT)
                self.device.sleep((0.3, 0.5))
                self.device.screenshot()
        if current < tier:
            logger.info(f'[META支援] 5 次尝试后未找到等级 {tier} 的信标，使用当前信标')
        logger.info(f'[META支援] 找到等级 {current} 的信标')

    def _ensure_meta_assist_page(self, skip_first_screenshot=True):
        """确保当前在信标协助页面。

        从 META 入口进入，处理各种中间页面跳转。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认 True。

        Returns:
            bool: 是否成功进入信标协助页面。

        Pages:
            in: page_reward or in_meta
            out: in_meta_assist
        """
        logger.info('[META支援] 确保进入信标支援页面')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._in_meta_assist_page():
                logger.info('[META支援] 已在信标支援页面')
                return True
            if self.handle_map_event():
                continue
            if self.appear_then_click(META_ENTRANCE, offset=(20, 300), interval=2):
                continue
            if self.appear(ASH_SHOWDOWN, offset=(20, 20), interval=2):
                self.device.click(META_MAIN_BEACON_ENTRANCE)
                logger.info('[META支援] 已在 META 主页面')
                continue
            if self.appear_then_click(BEACON_LIST, offset=(300, 20), interval=2):
                continue
            if self.appear_then_click(DOSSIER_LIST, offset=(20, 20), interval=2):
                logger.info('[META支援] 已在 META 档案页面')
                continue

    def _begin_meta_assist(self):
        """开始信标协助流程，确保进入协助页面后执行攻击。

        Returns:
            bool: 是否已确认当天支援次数耗尽。
        """
        logger.hr('META支援')
        self._ensure_meta_assist_page()
        return self._attack_meta(skip_first_screenshot=False)
