"""
舰船强化系统。

提供船坞中舰船装备强化的完整流程，包括按舰船类型分类强化、
推荐材料选择、强化确认、失败重试等操作。通过 DFA（确定性有限自动机）
状态机模式驱动强化流程，自动处理战斗中、无材料等异常情况。

当退役模式为 enhance 时，优先执行强化；强化完成或失败后
可回退到退役流程。
"""

from random import choice

import cv2

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import area_pad
from module.combat.assets import GET_ITEMS_1
from module.exception import GameStuckError, ScriptError
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.retire.assets import *
from module.retire.dock import Dock
from module.ui.assets import BACK_ARROW

VALID_SHIP_TYPES = ['dd', 'ss', 'cl', 'ca', 'bb', 'cv', 'repair', 'others']
if server.server != 'jp':
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(255, 255, 255), threshold=192)
else:
    OCR_DOCK_AMOUNT = DigitCounter(
        DOCK_AMOUNT, letter=(201, 201, 201), threshold=192)


class Enhancement(Dock):
    """舰船强化处理器。

    继承 Dock 类，在船坞页面中执行装备强化操作。
    使用 DFA 状态机模式管理强化流程，支持按舰船类型
    分类处理、推荐材料自动选择、强化失败后的自动翻页重试。

    Attributes:
        _retire_amount (property): 根据退役模式配置计算的退役数量上限。
    """
    @property
    def _retire_amount(self):
        if self.config.Retirement_RetireMode == 'one_click_retire':
            return 3000
        if self.config.Retirement_RetireMode == 'old_retire':
            if self.config.OldRetire_RetireAmount == 'retire_all':
                return 3000
            if self.config.OldRetire_RetireAmount == 'retire_10':
                return 10
        return 3000

    @property
    def _retire_keep_common_cv(self):
        """获取需要保留的普通航母类型名称。

        Returns:
            str: "any" 或指定舰船名；未启用 GemsFarming 任务时返回空字符串。
        """
        if not self.config.is_task_enabled('GemsFarming'):
            return ''
        return self.config.cross_get('GemsFarming.GemsFarming.CommonCV', default='any')

    def _enhance_enter(self, favourite=False, ship_type=None):
        """进入舰船强化界面并选中第一艘可强化舰船。

        Args:
            favourite (bool): 是否仅筛选喜爱舰船。默认为 False。
            ship_type (str, optional): 筛选的舰船类型。默认为 None。

        Returns:
            bool: 成功进入并选中舰船返回 True；筛选后船坞为空返回 False。

        Pages:
            in: page_dock
            out: page_ship_enhance
        """
        if favourite:
            self.dock_favourite_set(enable=True, wait_loading=False)

        if ship_type is not None:
            ship_type = str(ship_type)
            self.dock_filter_set(extra='enhanceable', index=ship_type)
        else:
            self.dock_filter_set(extra='enhanceable')

        if self.appear(DOCK_EMPTY, offset=(30, 30)):
            return False

        return self.dock_enter_first()

    def _enhance_quit(self):
        """退出舰船强化界面，恢复船坞默认筛选并返回船坞主界面。

        Pages:
            in: page_ship_enhance
            out: page_dock
        """
        self.ui_back(DOCK_CHECK)
        self.dock_favourite_set(enable=False, wait_loading=False)
        self.dock_filter_set()

    def _enhance_confirm(self, skip_first_screenshot=True):
        """确认强化并等待完成提示和弹窗处理。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: EQUIP_CONFIRM
            out: page_ship_enhance（无提示条）
        """

        confirm_timer = Timer(1.5, count=3).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(EQUIP_CONFIRM, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear_then_click(EQUIP_CONFIRM_2, offset=(30, 30), interval=3):
                confirm_timer.reset()
                continue
            if self.appear(GET_ITEMS_1, interval=2):
                self.device.click(GET_ITEMS_1_RETIREMENT_SAVE)
                self.interval_reset(ENHANCE_CONFIRM)
                confirm_timer.reset()
                continue

            # 判定结束
            if self.appear(ENHANCE_CONFIRM, offset=(30, 30)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

    def _enhance_get_deselect_cv(self, first_slot=False):
        """在强化材料槽位中寻找需要反选（保留）的普通航母。

        Args:
            first_slot (bool): True 仅检查第一个槽位，False 检查全部槽位。默认为 False。

        Returns:
            Button | None: 找到匹配的普通航母按钮；未找到返回 None。
        """
        cv = self._retire_keep_common_cv
        if not cv:
            return None
        dict_template = {
            'bogue': TEMPLATE_ENHANCE_BOGUE,
            'hermes': TEMPLATE_ENHANCE_HERMES,
            'langley': TEMPLATE_ENHANCE_LANGLEY,
            'ranger': TEMPLATE_ENHANCE_RANGER,
        }
        if cv == 'custom':
            # 自定义模式：使用 GemsFarming 过滤器中列出的常见航母
            filter_string = self.config.cross_get(
                'GemsFarming.GemsFarming.CommonCVFilter', default='')
            names = [n.strip().lower() for n in str(filter_string).split('>')]
            dict_template = {n: dict_template[n]
                             for n in names if n in dict_template}
            if not dict_template:
                logger.warning(
                    '[退役-强化] 自定义过滤器中无可用航母模板，跳过反选')
                return None
        elif cv != 'any':
            if cv not in dict_template:
                # 例如 eagle 等暂无模板的类型，跳过反选而不是抛异常
                logger.warning(f'[退役-强化] 未支持的常见航母类型: {cv}，跳过反选')
                return None
            dict_template = {cv: dict_template[cv]}

        if first_slot:
            # 向外扩 22 像素覆盖到槽位边缘
            area = area_pad(EMPTY_ENHANCE_SLOT_PLUS.area, pad=-22)
        else:
            area = ENHANCE_AREA_FULL.area
        image = self.image_crop(area, copy=False)

        for cv, template in dict_template.items():
            sim, button = template.match_result(image)
            if sim > 0.85:
                button = button.move(area[:2])
                return Button(area=button.area, color=button.color, button=button.area,
                              name=f'TEMPLATE_ENHANCE_{cv.upper()}_RETIRE')

        return None

    def _enhance_deselect_cv(self):
        """在强化材料槽位中反选普通航母，避免误消耗。

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance
        """
        cv = self._enhance_get_deselect_cv()
        if cv is None:
            return

        logger.info('强化反选普通航母')
        # 获取航母槽位，根据匹配中心向外扩展区域
        area = cv.area
        center = ((area[0] + area[2]) / 2, (area[1] + area[3]) / 2)
        radius = abs(EMPTY_ENHANCE_SLOT_PLUS.area[3] - EMPTY_ENHANCE_SLOT_PLUS.area[1]) / 2
        radius = radius + 22
        search = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)

        self.interval_clear(ENHANCE_RECOMMEND, interval=2)
        EMPTY_ENHANCE_SLOT_PLUS.ensure_template()
        # 返回次数上限，避免反复点返回把界面越退越远
        back_count = 0
        for _ in self.loop():
            image = self.image_crop(search, copy=False)
            result = cv2.matchTemplate(EMPTY_ENHANCE_SLOT_PLUS.image, image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv2.minMaxLoc(result)
            if similarity > 0.85:
                logger.info('强化反选普通航母完成')
                break

            # 误入船坞界面处理
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                logger.info(f'{DOCK_CHECK} -> {BACK_ARROW}')
                self.device.click(BACK_ARROW)
                continue
            if self.appear(ENHANCE_RECOMMEND, offset=(5, 5), interval=5):
                self.device.click(cv)
                continue

            # 点击材料槽位偶尔会打开船坞选择界面：此时推荐按钮与材料槽一并消失，
            # 反选无从继续，循环也不会自行结束（最终卡死到 GameStuckError）。
            # DOCK_CHECK 匹配标题栏，出现即说明已离开强化界面，
            # 点左上角返回箭头退回强化界面后重新反选。
            # 计数按「检测到离开强化界面」累加而非按点击成功累加，
            # 否则返回箭头不可见时（如被弹窗遮挡）计数不增长、依然会转到卡死
            if self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
                back_count += 1
                if back_count > 3:
                    logger.warning('[退役-强化] 多次返回仍未回到强化界面，放弃反选')
                    break
                if self.appear_then_click(BACK_ARROW, offset=(30, 30), interval=3):
                    logger.warning(
                        f'[退役-强化] 误入船坞界面，点返回退回强化界面 ({back_count}/3)')
                    continue

    def _enhance_choose(self, ship_count, skip_first_screenshot=True):
        """使用有限状态机（DFA）执行单艘舰船的强化材料选择与强化。

        根据状态在等待推荐、反选、确认强化、滑动到下一艘之间转移。

        Args:
            ship_count (int): 当前类别下剩余可检查的舰船数量（正整数）。
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            tuple[bool, int]: (是否强化成功, 剩余检查舰船数量)。

        Pages:
            in: page_ship_enhance
            out: page_ship_enhance
        """
        need_to_skip: bool = False

        def state_enhance_check():
            # 基础条件检查：若达到上限则退出，否则切换到就绪状态
            nonlocal need_to_skip
            need_to_skip = False
            if ship_count <= 0:
                logger.info(
                    '[退役-强化] 已达到最大检查次数，退出当前分类')
                return "state_enhance_exit"
            if not self.equip_side_navbar_ensure(bottom=4):
                return "state_enhance_check"

            self.wait_until_appear(ENHANCE_RECOMMEND, offset=(
                5, 5), skip_first_screenshot=True)
            return "state_enhance_ready"

        def state_enhance_ready():
            # 等待一键推荐按钮出现并点击
            if self.appear_then_click(ENHANCE_RECOMMEND, offset=(5, 5), interval=0.3):
                logger.info('按推荐设置强化材料')
                return "state_enhance_recommend"

            return "state_enhance_ready"

        def state_enhance_recommend():
            # 判断是否填充了强化材料
            if not EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(20, 20)):
                if self._retire_keep_common_cv:
                    # 若第一格为普通 CV 且第二格为空，视为无材料，
                    # 避免"推荐→反选"死循环；第二格在左侧 92px 处
                    if EMPTY_ENHANCE_SLOT_PLUS.match(self.device.image, offset=(72, -20, 112, 20)) \
                            and self._enhance_get_deselect_cv(first_slot=True):
                        logger.info('[退役-强化] 仅 1 个普通 CV 材料，视为无强化材料')
                        logger.info('[退役-强化] 强化失败，滑动到下一艘舰船（如可行）')
                        return "state_enhance_fail"
                    # 反选已填充的普通 CV
                    self._enhance_deselect_cv()

                logger.info('找到材料，尝试强化...')
                return "state_enhance_attempt"
            elif self.info_bar_count():
                logger.info('未找到强化材料')
                logger.info('[退役-强化] 强化失败，滑动到下一艘舰船（如可行）')
                return "state_enhance_fail"

            return "state_enhance_ready"

        def state_enhance_attempt():
            # 等待强化确认按钮出现并点击
            if (self.appear_then_click(ENHANCE_CONFIRM, offset=(5, 5), interval=0.3)
                    or self.appear(EQUIP_CONFIRM, offset=(30, 30))
                    or self.info_bar_count()
                    or self.handle_popup_confirm('ENHANCE')):
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_confirm():
            # 若出现装备确认弹窗说明强化成功，否则失败
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                logger.info('强化成功')
                self._enhance_confirm()
                return "state_enhance_success"
            elif self.info_bar_count():
                logger.info(
                    '[退役-强化] 强化不可行，舰船当前在战斗中，滑动到下一艘舰船（如可行）')
                nonlocal need_to_skip
                need_to_skip = True
                return "state_enhance_fail"
            elif self.handle_popup_confirm('ENHANCE'):
                logger.info('尝试临时舰船')
                return "state_enhance_confirm"

            return "state_enhance_attempt"

        def state_enhance_fail():
            # 避免因网络延迟导致误判
            if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                return "state_enhance_confirm"

            # 尝试滑动到下一艘舰船
            if self.equip_view_next(check_button=ENHANCE_RECOMMEND):
                if not need_to_skip:
                    nonlocal ship_count
                    ship_count -= 1
                return "state_enhance_check"
            else:
                # 避免因网络延迟导致误判
                if self.appear(EQUIP_CONFIRM, offset=(30, 30)):
                    return "state_enhance_confirm"
                else:
                    logger.info('滑动失败，退出当前分类')
                    return "state_enhance_exit"

        def state_enhance_success():
            return True

        def state_enhance_exit():
            return False

        state = "state_enhance_check"
        state_list = []
        while isinstance(state, str):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            logger.info(f'调用状态函数: {state}')

            if state == "state_enhance_check":
                # 避免因多次无材料尝试触发 too_many_click 异常
                if state_list[-2:] == ["state_enhance_recommend", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'EQUIP_SWIPE', 'SHIP_SWIPE']):
                        self.device.click_record.pop()
                # 避免因出击中舰船强化失败触发 too_many_click 异常
                elif state_list[-3:] == ["state_enhance_attempt", "state_enhance_confirm", "state_enhance_fail"]:
                    while self.device.click_record and (self.device.click_record[-1] in ['ENHANCE_RECOMMEND', 'EQUIP_SWIPE', 'SHIP_SWIPE', 'ENHANCE_CONFIRM']):
                        self.device.click_record.pop()
                state_list.clear()
            state_list.append(state)
            if len(state_list) > 30:
                logger.critical(f'[退役] 状态机循环次数过多: {state_list}')
                raise GameStuckError('状态机循环次数过多')

            try:
                state_func = locals()[state]
            except KeyError:
                # 只捕获状态名不存在的情况。状态函数内部抛出的 KeyError
                # 必须原样向上抛出，否则会被误报成"未知的状态函数"
                logger.warning(f'未知的状态函数: {state}')
                raise ScriptError(f'未知的状态函数: {state}')
            state = state_func()

        return state, ship_count

    def enhance_ships(self, favourite=None):
        """按配置的舰种顺序批量强化目标舰船。

        Args:
            favourite (bool, optional): 是否仅强化喜爱舰船。默认为 None（使用配置值）。

        Returns:
            int: 消耗材料完成强化的总估算数。

        Pages:
            in: page_dock
            out: page_dock
        """
        if favourite is None:
            favourite = self.config.Enhance_ShipToEnhance == 'favourite'

        logger.hr('按类型强化')
        total = 0

        # 将强化顺序字符串解析为舰种列表
        if self.config.Enhance_Filter is not None:
            ship_types = [s.strip().lower()
                          for s in self.config.Enhance_Filter.split('>')]
            ship_types = list(filter(''.__ne__, ship_types))
            if len(ship_types) == 0:
                ship_types = [None]
        else:
            ship_types = [None]
        logger.attr('强化顺序', ship_types)

        # 排除已指定的舰种，用于未识别类型的随机补位
        available_ship_types = VALID_SHIP_TYPES.copy()
        [available_ship_types.remove(s)
         for s in ship_types if s in available_ship_types]

        for ship_type in ship_types:
            # 检查非空：若未指定则跳过，若指定了未识别类型则随机抽取一个有效舰种
            if ship_type is not None and ship_type not in VALID_SHIP_TYPES:
                if len(available_ship_types) == 0:
                    logger.info(
                        '[退役-强化] 无可选舰船类型，跳过本次迭代')
                    continue
                ship_type = choice(available_ship_types)
                available_ship_types.remove(ship_type)

            logger.info(f'收藏={favourite}, 舰船类型={ship_type}')

            # 至少有一张卡片可选时继续，否则跳到下一个舰种
            if not self._enhance_enter(favourite=favourite, ship_type=ship_type):
                logger.hr(f'[退役-强化] 船坞为空，舰船类型: {ship_type}')
                continue

            current_count = self.config.Enhance_CheckPerCategory
            try:
                while 1:
                    choose_result, current_count = self._enhance_choose(
                        ship_count=current_count)
                    if not choose_result:
                        break
                    total += 10
                    if total >= self._retire_amount:
                        break
            finally:
                # 强化流程抛出异常时也要退出强化界面，
                # 否则后续流程会因为没有回到船坞而卡在角色详情页
                self.ui_back(DOCK_CHECK)

        self._enhance_quit()
        return total

    def _enhance_handler(self):
        """处理船坞已满时触发的强化流程，返回强化轮次和剩余船坞容量。

        Returns:
            tuple[int, int]: (强化消耗材料总数, 船坞剩余空位)。

        Pages:
            in: RETIRE_APPEAR / DOCK_CHECK
            out: 退役弹窗出现前的页面
        """
        total = self.enhance_ships()
        _, remain, _ = OCR_DOCK_AMOUNT.ocr(self.device.image)

        self.dock_quit()
        self.config.DOCK_FULL_TRIGGERED = True

        return total, remain
