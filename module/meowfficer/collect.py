"""指挥喵收集模块。

处理指挥喵训练完成后的收集操作，包括：
- 检测并收集已训练完成的指挥喵（单个或全部）
- 处理指挥喵获取界面的各种弹窗和过渡动画
- 检测指挥喵是否拥有特殊天赋（金色/紫色品质专属）
- 金色指挥喵的锁定/解锁处理（防止被误用作强化材料）

特殊天赋检测机制：
- 检查天赋网格中的图标，通过颜色分析区分普通天赋和特殊天赋
- 屏幕可能发生随机左移，通过 `MEOWFFICER_SHIFT_DETECT` 检测并适配
- 支持天赋截图记录（通过 `DropRecord_MeowfficerTalent` 配置）

配置项前缀：`MeowfficerTrain_*`、`DropRecord_*`
"""

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase
from module.meowfficer.collect_score import MeowfficerCollectScore
from module.ui.switch import Switch

MEOWFFICER_TALENT_GRID_1 = ButtonGrid(
    origin=(875, 559), delta=(105, 0), button_shape=(16, 16), grid_shape=(3, 1),
    name='MEOWFFICER_TALENT_GRID_1')
MEOWFFICER_TALENT_GRID_2 = MEOWFFICER_TALENT_GRID_1.move(vector=(-40, -20),
                                                         name='MEOWFFICER_TALENT_GRID_2')
MEOWFFICER_SHIFT_DETECT = Button(
    area=(1260, 669, 1280, 720), color=(117, 106, 84), button=(1260, 669, 1280, 720),
    name='MEOWFFICER_SHIFT_DETECT')

SWITCH_LOCK = Switch(name='Meowfficer_Lock', offset=(40, 40))
SWITCH_LOCK.add_state(
    'lock',
    check_button=MEOWFFICER_APPLY_UNLOCK,
    click_button=MEOWFFICER_APPLY_LOCK
)
SWITCH_LOCK.add_state(
    'unlock',
    check_button=MEOWFFICER_APPLY_LOCK,
    click_button=MEOWFFICER_APPLY_UNLOCK
)


class MeowfficerCollect(MeowfficerCollectScore, MeowfficerBase):
    """指挥喵收集处理器。

    负责从训练完成界面收集已训练的指挥喵，并根据品质和天赋决定是否保留。

    Attributes:
        config.MeowfficerTrain_RetainTalentedGold (bool): 是否保留有特殊天赋的金色指挥喵。
        config.MeowfficerTrain_RetainTalentedPurple (bool): 是否保留有特殊天赋的紫色指挥喵。
        config.DropRecord_MeowfficerTalent (str): 指挥喵天赋截图记录模式。
    """
    def _meow_detect_shift(self, skip_first_screenshot=True):
        """检测指挥喵获取完成界面的加载及左偏偏移。

        界面加载期间，画面可能随机向左偏移，通过等待颜色稳定检测偏移状态。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Returns:
            bool: 画面发生向左偏移返回 True，未偏移返回 False。
        """
        flag = False
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束 - 画面随机向左偏移
            if self.image_color_count(MEOWFFICER_SHIFT_DETECT,
                                      color=MEOWFFICER_SHIFT_DETECT.color, threshold=30, count=650):
                if not flag:
                    confirm_timer.reset()
                    flag = True
                if confirm_timer.reached():
                    break
                continue

            # 判定结束 - 画面未偏移
            if self.appear(MEOWFFICER_GET_CHECK, offset=(40, 40)):
                if flag:
                    confirm_timer.reset()
                    flag = False
                if confirm_timer.reached():
                    break
        return flag

    def _meow_check_popup_exit(self):
        """检查退出锁定弹窗或天赋详情面板后是否处于正确界面。

        Returns:
            bool: 处于指挥喵获取界面或训练开始界面返回 True，否则返回 False。
        """
        if self.match_template_color(MEOWFFICER_GET_CHECK, offset=(40, 40)):
            return True

        if self.appear(MEOWFFICER_TRAIN_START, offset=(20, 20)):
            return True

        return False

    def _meow_talent_cap_handle(self, btn, drop=None):
        """处理天赋详情面板展开、截图记录与评分识别。

        Args:
            btn (Button): 天赋图标按钮。
            drop (DropImage, optional): 掉落统计截图记录对象。默认为 None。
        """
        self.ui_click(btn, check_button=MEOWFFICER_TALENT_CLOSE,
                      appear_button=MEOWFFICER_GET_CHECK, offset=(40, 40),
                      skip_first_screenshot=True)
        drop.add(self.device.image)
        # 评分开关打开时，顺手从这张天赋详情面板里识别天赋名
        self.meow_score_capture(self.device.image)
        self.ui_click(MEOWFFICER_TALENT_CLOSE, check_button=self._meow_check_popup_exit,
                      appear_button=MEOWFFICER_TALENT_CLOSE, skip_first_screenshot=True)
        self.device.click_record.pop()
        self.device.click_record.pop()

    def _meow_is_special_talented(self, drop=None):
        """检查获取的指挥喵是否拥有至少一个特殊天赋。

        Args:
            drop (DropImage, optional): 掉落统计截图记录对象。默认为 None。

        Returns:
            bool: 拥有特殊天赋返回 True，否则返回 False。
        """
        # 等待界面完全加载后再检查天赋
        logger.info('[指挥喵-收集] 等待加载完成并检查基础天赋')

        special_talent = False
        grid = MEOWFFICER_TALENT_GRID_2 if self._meow_detect_shift() else MEOWFFICER_TALENT_GRID_1
        handle_drop = self.config.DropRecord_MeowfficerTalent != 'do_not'
        # 开了评分就同样需要展开天赋详情面板，即使没开截图记录
        score_enabled = self.meow_score_enabled()
        open_detail = handle_drop or score_enabled
        if score_enabled:
            self.meow_score_reset()
        if handle_drop:
            drop.add(self.device.image)

        for btn in grid.buttons:
            # 空槽位：白色像素较多
            if self.image_color_count(btn, color=(255, 255, 247), threshold=30, count=200):
                continue

            # 非空槽位：白色像素较少（如罗马数字）
            if self.image_color_count(btn, color=(255, 255, 255), threshold=30, count=25):
                if open_detail:
                    self._meow_talent_cap_handle(btn, drop)
                continue

            # 发现特殊天赋
            if open_detail:
                self._meow_talent_cap_handle(btn, drop)
            special_talent = True

        if score_enabled:
            self.meow_score_finish()

        log_insert = '发现' if special_talent else '未发现'
        logger.info(f'[指挥喵-收集] {log_insert}指挥喵拥有特殊天赋')
        return special_talent

    def _meow_skip_lock(self):
        """对金色指挥喵跳过锁定流程。

        仅适用于金色指挥喵，触发锁定确认弹窗后点击取消并返回。
        """

        def additional():
            """处理结算界面弹窗。"""
            if self.appear(MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_TRAIN_EVALUATE)
                return True
            return False

        # 触发锁定弹窗出现以启动流程
        self.ui_click(MEOWFFICER_TRAIN_CLICK_SAFE_AREA,
                      appear_button=MEOWFFICER_GET_CHECK, check_button=MEOWFFICER_CONFIRM, additional=additional,
                      offset=(40, 40), retry_wait=3, skip_first_screenshot=True)

        self.ui_click(MEOWFFICER_CANCEL, check_button=self._meow_check_popup_exit, additional=additional,
                      offset=(40, 20), retry_wait=3, skip_first_screenshot=True)
        self.device.click_record.pop()
        self.device.click_record.pop()

    def _meow_apply_lock(self, lock=True):
        """设置当前获取指挥喵的锁定状态，防止被当作强化材料。

        Args:
            lock (bool): True 为加锁，False 为解锁。默认为 True。
        """
        # 设置指定的锁定状态
        SWITCH_LOCK.set('lock' if lock else 'unlock', main=self)

        # 等待提示条消失
        self.ensure_no_info_bar(timeout=1)

    def _meow_skip_popup_after_locking(self, skip_first_screenshot=True):
        """处理锁定后的确认弹窗。

        自 2023-11-16 更新后，即使已锁定的金色指挥喵仍会弹出提示弹窗。
        本方法处理该弹窗并确认退出。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 下一只指挥喵的 MEOWFFICER_APPLY_LOCK 加载快于 MEOWFFICER_GET_CHECK，确保使用完整截图退出
            if self.appear(MEOWFFICER_GET_CHECK, offset=(40, 40)):
                if self.appear(MEOWFFICER_APPLY_LOCK, offset=(40, 40)):
                    break
            # 意外退出获取队列
            if self.appear(MEOWFFICER_TRAIN_START, offset=(20, 20)):
                logger.info('[指挥喵-收集] 锁定后弹窗处理意外退出至 MEOWFFICER_TRAIN_START')
                break

            if self.appear(MEOWFFICER_APPLY_UNLOCK, offset=(40, 40), interval=3):
                self.device.click(MEOWFFICER_TRAIN_CLICK_SAFE_AREA)
                continue
            if self.appear(MEOWFFICER_CONFIRM, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CONFIRM)
                continue
            elif self.appear(MEOWFFICER_CANCEL, offset=(40, 20), interval=3):
                self.device.click(MEOWFFICER_CONFIRM)
                continue
            if self.appear(MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_TRAIN_EVALUATE)
                continue

        self.device.click_record.pop()
        self.device.click_record.pop()
        self.interval_reset((MEOWFFICER_GET_CHECK, MEOWFFICER_APPLY_LOCK,
                             MEOWFFICER_CONFIRM, MEOWFFICER_CANCEL))

    def meow_get(self, skip_first_screenshot=True):
        """循环处理所有已训练完成指挥喵的获取界面。

        逐只识别品质、检查特殊天赋并按配置执行锁定或跳过锁定。

        Args:
            skip_first_screenshot (bool): 是否跳过首次截图。默认为 True。

        Pages:
            in: MEOWFFICER_GET_CHECK
            out: MEOWFFICER_TRAIN
        """
        # 循环处理可能出现的界面转换
        confirm_timer = Timer(1.5, count=3).start()
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 判定结束
            if self.appear(MEOWFFICER_TRAIN_START, offset=(20, 20)):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            if self.handle_meow_popup_dismiss():
                confirm_timer.reset()
                continue
            if self.appear(MEOWFFICER_GET_CHECK, offset=(40, 40), interval=3):
                if self.appear(MEOWFFICER_APPLY_UNLOCK, offset=(40, 40)):
                    self._meow_skip_popup_after_locking(skip_first_screenshot=True)
                    confirm_timer.reset()
                    # 意外退出获取队列
                    if self.appear(MEOWFFICER_TRAIN_START, offset=(20, 20)):
                        continue

                count += 1
                logger.attr('[指挥喵-收集] 获取次数', count)
                with self.stat.new(
                        genre="meowfficer_talent",
                        method=self.config.DropRecord_MeowfficerTalent
                ) as drop:
                    special_talent = self._meow_is_special_talented(drop=drop)
                    # 开了评分门槛时，评分不达标同样不锁定，交给强化消化掉
                    score_passed = self.meow_score_passes()
                    if self.appear(MEOWFFICER_GOLD_CHECK, offset=(40, 40)):
                        if not self.config.MeowfficerTrain_RetainTalentedGold \
                                or not special_talent or not score_passed:
                            self._meow_skip_lock()
                            skip_first_screenshot = True
                            confirm_timer.reset()
                            continue
                        self._meow_apply_lock()

                    if self.appear(MEOWFFICER_PURPLE_CHECK, offset=(40, 40)):
                        if self.config.MeowfficerTrain_RetainTalentedPurple \
                                and special_talent and score_passed:
                            self._meow_apply_lock()

                    # 连续收集多只时易触发异常，通过弹出 click_record 缓解
                    self.device.click(MEOWFFICER_TRAIN_CLICK_SAFE_AREA)
                    self.device.click_record.pop()
                    confirm_timer.reset()
                    self.interval_reset(MEOWFFICER_GET_CHECK)
                    continue

            # 点击全部完成时会进入评价界面
            if self.appear(MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
                self.device.click(MEOWFFICER_TRAIN_EVALUATE)
                continue

    def meow_collect(self, collect_all=True):
        """收集单个或全部训练完成的指挥喵。

        训练完成的槽位会自动排在队列最上方，只检查左上角首个槽位。

        Args:
            collect_all (bool): 是否全部收集。True 为一键完成全部，False 为只收单个。默认为 True。

        Returns:
            bool: 成功执行了收集返回 True，无已完成指挥喵返回 False。

        Pages:
            in: MEOWFFICER_TRAIN
            out: MEOWFFICER_TRAIN
        """
        logger.hr('指挥喵收集', level=2)

        if self.appear(MEOWFFICER_TRAIN_COMPLETE, offset=(20, 20)):
            # 今天是周日则全部完成，否则只领取单个
            if collect_all:
                logger.info('收集所有训练完成的指挥喵')
                button = MEOWFFICER_TRAIN_FINISH_ALL
            else:
                logger.info('收集单个训练完成的指挥喵')
                button = MEOWFFICER_TRAIN_COMPLETE
            self.ui_click(button, check_button=MEOWFFICER_GET_CHECK,
                          additional=self.handle_meow_popup_dismiss,
                          offset=(40, 40), skip_first_screenshot=True)

            # 循环收集训练完成的指挥喵
            self.meow_get()
            return True
        return False
