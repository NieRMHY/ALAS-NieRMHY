"""作战委托模块。

在主线关卡页启动「作战委托」：消耗石油与作战全权委托书，让舰队离线自动
执行指定主线关卡若干次，委托结束后再领取掉落。委托期间出击类任务（主线、
活动）都会失败，只有大世界照常可用，因此本任务排在调度优先级的末尾。

流程：
1. 查一次停服维护时间（OperationHandover.MaintainOverride 开启时）：按当前游戏
   服务器（cn/en/jp/tw）取对应公告，维护就在今天时，当天 0 点起就整体切到维护
   模式——忽略「委托次数」和「一键消耗委托书」，把下一次运行排到维护前 10 分钟，
   到点后用「次数拉满」跑最后一次；维护时间已经过去、或是别的日子，按下面的
   正常流程走
2. 委托次数为 0 时这个任务只在需要一键消耗委托书时才动：未开启一键消耗就
   直接关掉本任务，开启了就把下次运行排到触发时间
3. 进入主线关卡页
4. 上一次的委托没结束时，目标关卡进关卡页直接弹出「作战委托 INFORM」弹窗，
   其他关卡先弹阻止页，点它的「查看委托」进同一个弹窗
5. 弹窗里委托仍在进行（HANDOVER_STOP_CHECK）则关掉弹窗，按剩余时间推迟
6. 已完成（HANDOVER_PASS_CLICK）则领取奖励，领完退回章节选择页，
   重新点一次关卡把上面的流程再走一遍，继续开下一个委托
7. 检测该关卡是否支持作战委托（HANDOVER_TAB / HANDOVER_TAB_UNSUPPORTED）
8. 记录当前石油数量，低于 OperationHandover.OilLimit 时直接推迟
9. 打开作战委托面板定次数：维护前拉满 > 一键消耗按委托书数量 >
   配置里的次数（见 handover_consume_all_book）
10. 比较「需要时间」与「剩余可用时间」，判断剩余时间能否完成委托
11. 时间不足且启用了自动补充时，用作战全权委托书兑换可用时间（1 本 = 1 小时）
12. 把面板上的「预计消耗」石油和当前石油比较，不够就关掉面板推迟，不点「开始」
13. 启用了使用委托书时，把委托书投入量拉到最大
14. 点击「开始」，确认面板真的关掉了才算成功

配置路径: Campaign.Name, OperationHandover.Count,
         OperationHandover.AutoSupplementTime, OperationHandover.UseHandoverBook,
         OperationHandover.OilLimit, OperationHandover.ConsumeAllBook,
         OperationHandover.ConsumeAllBookWeekday, OperationHandover.ConsumeAllBookTime,
         OperationHandover.MaintainOverride
"""

import math
import re
from datetime import datetime, timedelta, timezone

import requests

from module.base.timer import Timer
from module.base.utils import crop
from module.campaign.run import CampaignRun
from module.config.time_source import now as current_time
from module.config.utils import SERVER_TO_TIMEZONE
from module.handler.assets import POPUP_CONFIRM
from module.handler.fast_forward import to_map_file_name
from module.logger import logger
from module.map.assets import (FLEET_PREPARATION, HANDOVER_BOOK_AMOUNT_OCR,
                               HANDOVER_BOOK_COUNT_OCR, HANDOVER_BOOK_ITEM,
                               HANDOVER_BOOK_MAX, HANDOVER_CHECK, HANDOVER_COUNT_INPUT,
                               HANDOVER_COUNT_MAX, HANDOVER_COUNT_MINUS,
                               HANDOVER_COUNT_OCR, HANDOVER_COUNT_PLUS,
                               HANDOVER_DIALOG_CLOSE, HANDOVER_EXCHANGE_TIME,
                               HANDOVER_OIL_COST_OCR, HANDOVER_PANEL_CLOSE,
                               HANDOVER_PASS_CLICK, HANDOVER_REWARD, HANDOVER_REWARD_CHECK,
                               HANDOVER_START_CLICK, HANDOVER_STOP_CHECK, HANDOVER_STOP_TIME_OCR,
                               HANDOVER_TAB, HANDOVER_TAB_UNSUPPORTED,
                               HANDOVER_TIME_NEEDED_OCR, HANDOVER_TIME_REMAINING_OCR)
from module.ocr.models import OCR_MODEL
from module.ocr.ocr import Digit, Duration

OCR_HANDOVER_COUNT = Digit(HANDOVER_COUNT_OCR, letter=(255, 255, 255), threshold=128, alphabet='0123456789')
OCR_HANDOVER_BOOK_COUNT = Digit(HANDOVER_BOOK_COUNT_OCR, letter=(255, 255, 255), threshold=128,
                                alphabet='0123456789')
OCR_HANDOVER_BOOK_AMOUNT = Digit(HANDOVER_BOOK_AMOUNT_OCR, letter=(255, 255, 255), threshold=128,
                                 alphabet='0123456789')
OCR_HANDOVER_TIME_NEEDED = Duration(HANDOVER_TIME_NEEDED_OCR, letter=(255, 255, 255), threshold=128)
# 剩余可用时间是绿色字 (110,184,48)，面板上其余文字都是白/浅灰。extract_letters() 对
# 白色 letter 走「按最小通道取反」的快速分支，非白色走逐通道差值分支；绿字用白色会把
# 文字和深色背景一起提成纯白，送模图成为空白图，OCR 恒返回 0:00:00。
OCR_HANDOVER_TIME_REMAINING = Duration(HANDOVER_TIME_REMAINING_OCR, letter=(110, 184, 48), threshold=128)
# 进行中委托的剩余时间同样是绿色字 (99,215,131)，理由同上
OCR_HANDOVER_STOP_TIME = Duration(HANDOVER_STOP_TIME_OCR, letter=(99, 215, 131), threshold=128)

# 一本作战全权委托书可兑换 1 小时可用时间
HANDOVER_BOOK_HOURS = 1
HANDOVER_BOOK_SECONDS = HANDOVER_BOOK_HOURS * 3600

# 一键消耗委托书的周几选项，下标与 datetime.weekday() 一致（周一 = 0）
HANDOVER_WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
HANDOVER_WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

# 触发日当天还没开始时，隔多久再看一眼。直接用「推迟到次日」会跳到触发日之后，
# 整周都错过一键消耗
HANDOVER_CONSUME_RETRY_MINUTES = 30

# 停服维护时间接口，顶层是国服公告的聚合结果，servers 里按 cn/jp/en/tw 分别给出
# maintenance_date(YYYY-MM-DD) 与 start_time(HH:MM)
HANDOVER_MAINTAIN_API = 'https://api-blhx-maintain.nanoda.work/api/maintenance'
# 接口里服务器时区的形状，如 `UTC+8`、`UTC-7`、`UTC+08:00`
HANDOVER_MAINTAIN_TIMEZONE = re.compile(r'^UTC([+-])(\d{1,2})(?::?(\d{2}))?$')
# 维护开始前多久跑最后一次作战委托
HANDOVER_MAINTAIN_LEAD_MINUTES = 10


class OperationHandover(CampaignRun):
    """作战委托执行器。

    继承 CampaignRun 以复用 load_campaign()，拿到 self.campaign（config 已
    deepcopy 合并过的 CampaignBase 实例），借它的 ensure_campaign_ui() 与
    fleet_preparation() 复用战役 UI 能力。全程不调用 self.campaign.run()，
    因此不会进入地图战斗。

    Attributes:
        campaign: 战役执行实例，由 CampaignRun.load_campaign() 提供。
    """

    def run(self):
        """执行一次作战委托。

        Pages: in: any, out: 关卡页
        """
        logger.hr('作战委托', level=1)
        count = self.config.OperationHandover_Count
        auto_supplement = self.config.OperationHandover_AutoSupplementTime
        use_book = self.config.OperationHandover_UseHandoverBook
        oil_limit = self.config.OperationHandover_OilLimit
        consume_all, reason = self.handover_consume_all_book_state()
        maintain, maintain_reason = self.handover_maintain_state()
        # 维护当天从 0 点起就整体切到维护模式：忽略「委托次数」和「一键消耗委托书」，
        # 下一次运行只排到维护前 HANDOVER_MAINTAIN_LEAD_MINUTES 分钟那一次
        maintain_run = maintain is not None
        logger.attr('委托关卡', self.config.Campaign_Name)
        logger.attr('委托次数', count)
        logger.attr('自动补充时间', auto_supplement)
        logger.attr('使用作战全权委托书', use_book)
        logger.attr('石油低于 X 后推迟', oil_limit)
        logger.attr('一键消耗作战全权委托书', '是' if consume_all else f'否（{reason}）')
        logger.attr('维护当天作战委托', f'是（{maintain_reason}）' if maintain_run
                    else f'否（{maintain_reason}）')

        if maintain_run:
            run_at = maintain - timedelta(minutes=HANDOVER_MAINTAIN_LEAD_MINUTES)
            if current_time() < run_at:
                logger.info(f'[作战委托] 还没到维护前的运行时间，推迟到 {run_at}')
                self.config.task_delay(target=run_at)
                return
            logger.info(f'[作战委托] 到维护前 {HANDOVER_MAINTAIN_LEAD_MINUTES} 分钟了，'
                        f'作战次数拉满跑最后一次')

        # 委托次数为 0：不开一键消耗委托书的话这个任务没事可做，直接关掉；
        # 开着就只在触发时间运行，中间不用进游戏
        if count <= 0 and not maintain_run:
            if not self.config.OperationHandover_ConsumeAllBook:
                logger.warning('[作战委托] 委托次数为 0 且未开启一键消耗委托书，'
                               '这个任务没有事可做，直接关闭')
                self.config.cross_set(keys='OperationHandover.Scheduler.Enable', value=False)
                self.config.task_stop('委托次数为 0 且未开启一键消耗委托书')

            if not consume_all:
                target = self.handover_consume_all_book_next_time()
                if target is None:
                    logger.warning('[作战委托] 委托次数为 0，但读不到一键消耗的触发时间，'
                                   '按普通间隔重试')
                    self.handover_delay()
                    return
                logger.info(f'[作战委托] 委托次数为 0，只等一键消耗委托书，下次运行 {target}'
                            f'（{reason}）')
                self.config.task_delay(target=target)
                return

        # 进入主线关卡页，并按 Fleet 组准备编队
        self.handover_enter()

        # 上一次的委托仍在进行，不打断它，关掉弹窗等它做完再回来领取
        self.device.screenshot()
        if self.appear(HANDOVER_STOP_CHECK, offset=(20, 20)):
            remaining = OCR_HANDOVER_STOP_TIME.ocr(self.device.image)
            logger.attr('委托剩余时间', remaining)
            self.device.click(HANDOVER_DIALOG_CLOSE)
            self.handover_delay(remaining)
            return

        # 上一次的委托已完成，领取奖励。领完退回章节选择页，要重新点一次关卡
        if self.handover_reward():
            self.handover_enter()

        # 检测该关卡是否支持作战委托
        if not self.handover_check_support():
            self.handover_delay()
            return

        # 面板打开后就看不到顶栏的石油了，先把当前油量读出来备用
        oil = self.get_oil()
        logger.attr('当前石油', oil)
        if oil_limit and oil < oil_limit:
            logger.warning(f'[作战委托] 石油 {oil} 低于设定值 {oil_limit}，推迟任务')
            self.handover_delay()
            return

        # 打开作战委托面板
        self.handover_panel_enter()

        # 次数怎么定：维护前拉满 > 一键消耗按委托书数量 > 配置里的次数
        if maintain_run:
            if self.handover_count_max() < 0:
                self.handover_close_panel()
                self.handover_delay()
                return
        elif consume_all:
            if not self.handover_consume_all_book():
                self.handover_close_panel()
                self.handover_delay()
                return
        else:
            self.handover_set_count(count)

        # 判断剩余可用时间能否完成委托
        self.device.screenshot()
        needed, remaining = self.handover_get_time()
        if needed > remaining:
            if not auto_supplement:
                logger.warning('[作战委托] 剩余可用时间不足以完成委托，且未启用自动补充时间')
                self.handover_close_panel()
                self.handover_delay()
                return
            if not self.handover_exchange_time(needed - remaining):
                self.handover_close_panel()
                self.handover_delay()
                return
            # 兑换弹窗关闭后画面已更新，重新截图供后续使用
            self.device.screenshot()

        # 点击确定前按需把委托书投入量拉满。一键消耗委托书那条路上面已经拉满过了
        if use_book and not (consume_all and not maintain_run):
            self.handover_book_max()

        # 点「开始」之前用面板上的「预计消耗」核对油量：油不够时游戏不会关面板，
        # 只会在面板里提示「资源不足，无法开始」，面板留在屏幕上会把后面所有
        # 任务的页面识别都带崩
        self.device.screenshot()
        if not self.handover_oil_enough(oil):
            self.handover_close_panel()
            self.handover_delay()
            return

        if not self.handover_start():
            self.handover_close_panel()
            self.handover_delay()
            return

        if consume_all and not maintain_run:
            self.handover_consume_all_book_record()
        self.config.task_delay(minute=needed.total_seconds() / 60)

    def handover_enter(self):
        """进入主线关卡页，并按 Fleet 组准备编队。

        进入方式与地图模块 MapOperation.enter_map() 一致：ensure_campaign_ui()
        只切换章节，不会点开关卡节点，必须再点击一次 ENTRANCE 才进得了关卡页。
        编队栏与舰队准备都在关卡页上，不在章节选择页上。

        上一次的委托还在时，进关卡页会弹出「作战委托 INFORM」弹窗，或是先弹出
        阻止页，点它的「查看委托」进弹窗，两种情况都在这里收住，交给 run() 判断
        委托是完成了还是仍在进行。

        Pages: in: any, out: 关卡页 / 作战委托弹窗
        """
        name = to_map_file_name(self.config.Campaign_Name)
        self.load_campaign(name, folder='campaign_main')

        self.device.screenshot()
        self.campaign.ensure_campaign_ui(name=self.stage, mode='normal', skip_first_screenshot=True)

        campaign_timer = Timer(5)
        fleet_timer = Timer(5)
        while 1:
            self.device.screenshot()

            # 舰队准备。与 enter_map() 相同，只有编队准备界面出现时才调用
            # fleet_preparation()，在章节选择页上调用会卡死在 FleetOperator.clear()。
            if fleet_timer.reached() and self.campaign.appear(FLEET_PREPARATION, offset=(20, 50)):
                if not self.campaign.map_fleet_checked:
                    self.campaign.fleet_preparation()
                    self.campaign.map_fleet_checked = True
                fleet_timer.reset()
                campaign_timer.reset()
                continue

            # 已到关卡页
            if self.appear(HANDOVER_TAB) or self.appear(HANDOVER_TAB_UNSUPPORTED):
                break

            # 上一次的委托还在，弹出了作战委托弹窗
            if self.handover_dialog_appear():
                break

            # 委托进行中的阻止页，点「查看委托」进弹窗
            if self.appear_then_click(HANDOVER_CHECK, offset=(20, 20), interval=3):
                continue

            # 进入关卡
            if campaign_timer.reached() and self.campaign.appear_then_click(self.campaign.ENTRANCE):
                campaign_timer.reset()
                continue

        logger.info('[作战委托] 已进入关卡页')

    def handover_dialog_appear(self):
        """「作战委托 INFORM」弹窗是否出现。

        弹窗里显示委托的剩余时间与完成次数，底部按钮是「领取奖励」（已完成）或
        「终止作战」（仍在进行），用它判断委托做完了没有。

        Returns:
            bool: 弹窗出现返回 True。
        """
        return (
            self.appear(HANDOVER_PASS_CLICK, offset=(20, 20))
            or self.appear(HANDOVER_STOP_CHECK, offset=(20, 20))
        )

    def handover_check_support(self):
        """检测当前关卡是否支持作战委托。

        HANDOVER_TAB 与 HANDOVER_TAB_UNSUPPORTED 的区域完全相同，只有填充色不同，
        因此用颜色判定区分。

        Returns:
            bool: 该关卡支持作战委托返回 True。
        """
        self.device.screenshot()
        if self.appear(HANDOVER_TAB):
            logger.info('[作战委托] 该关卡支持作战委托')
            return True
        if self.appear(HANDOVER_TAB_UNSUPPORTED):
            logger.warning('[作战委托] 该关卡不支持作战委托')
            return False
        logger.warning('[作战委托] 未找到作战委托入口')
        return False

    def handover_panel_appear(self):
        """作战委托设置面板是否已打开。

        「最大」按钮只在面板内出现，用它作为面板标志物。该按钮与次数加号等
        按钮颜色相同，因此必须用模板匹配而不是颜色判定。

        Returns:
            bool: 面板已打开返回 True。
        """
        return self.appear(HANDOVER_COUNT_MAX, offset=(20, 20))

    def handover_panel_enter(self, skip_first_screenshot=True):
        """点击作战委托入口，打开作战委托面板。

        Pages: in: 关卡页, out: 作战委托面板
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handover_panel_appear():
                break

            if self.appear_then_click(HANDOVER_TAB, interval=2):
                continue

        logger.info('[作战委托] 已打开作战委托面板')

    def handover_reward(self):
        """领取上一次已完成委托的奖励。

        委托完成后弹窗底部的按钮是「领取奖励」。点击后可能先弹出大讲堂熟练度溢出
        之类的通用信息弹窗，用通用确认按钮关掉，再点掉领取结算界面。全部收掉后
        游戏退回章节选择页，关卡入口按钮重新出现，此时才算领完。

        Pages: in: 作战委托弹窗, out: 章节选择页

        Returns:
            bool: 本次领取了奖励返回 True。
        """
        self.device.screenshot()
        if not self.appear(HANDOVER_PASS_CLICK, offset=(20, 20)):
            return False

        logger.info('[作战委托] 上一次的委托已完成，领取奖励')
        while 1:
            self.device.screenshot()

            # 领取结算界面，点「确定」收起
            if self.appear(HANDOVER_REWARD_CHECK, offset=(20, 20)):
                self.appear_then_click(HANDOVER_REWARD, offset=(20, 20), interval=3)
                continue

            # 大讲堂熟练度溢出等通用信息弹窗
            if self.handle_popup_confirm('HANDOVER'):
                continue

            # 弹窗上的按钮先判，保证弹窗还在时不会误判成已经退回章节选择页
            if self.appear_then_click(HANDOVER_PASS_CLICK, offset=(20, 20), interval=3):
                continue

            # 退回章节选择页，关卡入口重新出现，委托已经没有了
            if self.campaign.appear(self.campaign.ENTRANCE):
                break

            # 关卡页
            if self.appear(HANDOVER_TAB) or self.appear(HANDOVER_TAB_UNSUPPORTED):
                break

        logger.info('[作战委托] 已领取委托奖励')
        return True

    def handover_set_count(self, count):
        """把委托次数设置到指定值。

        ui_ensure_index() 以游戏显示的次数为唯一依据点击加减号，点击丢失时能自行补齐。

        count 为 0 时改成反复点减号降到游戏允许的最小值：游戏的最少次数不一定是
        0，用 ui_ensure_index() 会一直点不到目标值而空转，最后只能靠卡死检测报错。

        Args:
            count (int): 目标委托次数，0 表示降到最小。
        """
        if count == 0:
            self.handover_click_until_stable(
                HANDOVER_COUNT_MINUS, OCR_HANDOVER_COUNT, '作战次数(最小)')
            return

        self.ui_ensure_index(
            count,
            letter=OCR_HANDOVER_COUNT,
            next_button=HANDOVER_COUNT_PLUS,
            prev_button=HANDOVER_COUNT_MINUS,
            skip_first_screenshot=True,
        )

    def handover_get_time(self):
        """识别委托需要的时间和当天剩余可用时间。

        Returns:
            tuple[timedelta, timedelta]: (需要时间, 剩余可用时间)。
        """
        needed = OCR_HANDOVER_TIME_NEEDED.ocr(self.device.image)
        remaining = OCR_HANDOVER_TIME_REMAINING.ocr(self.device.image)
        logger.attr('需要时间', needed)
        logger.attr('剩余可用时间', remaining)
        return needed, remaining

    def handover_exchange_time(self, deficit):
        """用作战全权委托书兑换可用时间。

        Pages: in: 作战委托面板, out: 作战委托面板

        Args:
            deficit (timedelta): 缺少的时间。

        Returns:
            bool: 兑换成功返回 True。
        """
        need = math.ceil(deficit.total_seconds() / HANDOVER_BOOK_SECONDS)
        logger.info(f'[作战委托] 剩余时间不足，需补充 {need} 小时，即 {need} 本作战全权委托书')

        # 点击「兑换可用时间」打开兑换弹窗
        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(POPUP_CONFIRM, offset=self._popup_offset):
                break

            if self.appear_then_click(HANDOVER_EXCHANGE_TIME, interval=2):
                continue

        # 识别持有的委托书数量，判断是否足够
        current = OCR_HANDOVER_BOOK_AMOUNT.ocr(self.device.image)
        logger.attr('作战全权委托书', f'持有 {current}')
        if current < need:
            logger.critical(f'[作战委托] 作战全权委托书不足，需要 {need} 本，持有 {current} 本')
            self.handle_popup_cancel('HANDOVER')
            return False

        # 点击委托书道具，累计到需要的本数
        clicked = 0
        while clicked < need:
            self.device.screenshot()
            if self.appear_then_click(HANDOVER_BOOK_ITEM, offset=(20, 20), interval=1):
                clicked += 1

        # 通用的确认按钮
        while 1:
            self.device.screenshot()
            if not self.handle_popup_confirm('HANDOVER'):
                break

        logger.info(f'[作战委托] 已补充 {need} 小时可用时间')
        return True

    def handover_click_until_stable(self, button, ocr, name):
        """反复点同一个按钮，直到数值不再变化。

        读两次数值相同就认为已经到头，多按几次也不会出错。

        Args:
            button (Button): 要点的按钮，比如「最大」或减号。
            ocr (Ocr): 读取当前数值的 OCR。
            name (str): 日志里显示的名字。

        Returns:
            int: 最终数值，未找到按钮返回 -1。
        """
        if not self.appear(button, offset=(20, 20)):
            logger.warning(f'[作战委托] 未找到{name}的按钮')
            return -1

        value = -1
        while 1:
            self.device.screenshot()
            current = ocr.ocr(self.device.image)
            if current == value:
                break
            value = current

            if self.appear_then_click(button, offset=(20, 20), interval=2):
                continue

        logger.attr(name, value)
        return value

    def handover_book_max(self):
        """把作战全权委托书的投入量拉到最大。

        Pages: in: 作战委托面板

        Returns:
            bool: 找到并使用「最大」按钮返回 True。
        """
        return self.handover_click_until_stable(
            HANDOVER_BOOK_MAX, OCR_HANDOVER_BOOK_COUNT, '投入作战全权委托书') >= 0

    def handover_count_max(self):
        """把作战次数拉到最大。

        Pages: in: 作战委托面板

        Returns:
            int: 拉满后的作战次数，失败返回 -1。
        """
        return self.handover_click_until_stable(HANDOVER_COUNT_MAX, OCR_HANDOVER_COUNT, '作战次数(最大)')

    def handover_input_count(self, count):
        """用输入法把作战次数改成指定值。

        点一下次数文本框聚焦，把原来的数字删掉再输入新值，最后回车收起输入法。
        输入法弹出来会挡住面板下半屏，所以输入完要等它收起来再截图。

        这里用颜色判定而不是模板匹配：框里的数字是每次都会变的，模板里带着数字
        就只会在数字刚好一样时才命中。

        Pages: in: 作战委托面板

        Args:
            count (int): 目标作战次数。

        Returns:
            bool: 输入后读回的次数正确返回 True。
        """
        self.device.screenshot()
        if not self.appear(HANDOVER_COUNT_INPUT):
            logger.warning('[作战委托] 未找到作战次数输入框')
            return False

        self.appear_then_click(HANDOVER_COUNT_INPUT)
        self.device.sleep(0.5)

        text = str(count)
        clear = ' '.join(['KEYCODE_DEL'] * (len(text) + 10))
        self.device.adb_shell(f'input keyevent KEYCODE_MOVE_END {clear}', timeout=5)
        self.device.adb_shell(f'input text {text}', timeout=5)
        self.device.adb_shell('input keyevent KEYCODE_ENTER', timeout=1)

        # 等输入法收起来再核对，最多等 5 秒
        timeout = Timer(5).start()
        while 1:
            self.device.screenshot()
            current = OCR_HANDOVER_COUNT.ocr(self.device.image)
            if current == count:
                logger.attr('作战次数(输入后)', current)
                return True
            if timeout.reached():
                logger.warning(f'[作战委托] 作战次数输入失败，期望 {count}，识别到 {current}')
                return False

    def handover_consume_all_book(self):
        """一键消耗作战全权委托书。

        作战次数拉满 → 使用委托书拉满 → 读出投入的委托书数量 → 把作战次数改成
        这个数量，让这次委托正好把委托书用光。

        Pages: in: 作战委托面板, out: 作战委托面板

        Returns:
            bool: 次数已设置好返回 True。
        """
        # 作战次数先拉满：使用委托书的上限受作战次数限制，次数太小委托书拉不满
        if self.handover_count_max() < 0:
            return False

        # 委托书拉满后的数值，就是要设置的作战次数
        book = self.handover_click_until_stable(HANDOVER_BOOK_MAX, OCR_HANDOVER_BOOK_COUNT,
                                       '投入作战全权委托书')
        if book <= 0:
            logger.warning('[作战委托] 没有可投入的作战全权委托书')
            return False

        return self.handover_input_count(book)

    @staticmethod
    def handover_week_key(time):
        """把时间换算成「年+周数」字符串，用来判断本周是否已经触发过。

        刻意不带连字符，避免被配置系统当成日期解析。

        Args:
            time (datetime.datetime): 时间。

        Returns:
            str: 如 `2026W37`。
        """
        year, week, _ = time.isocalendar()
        return f'{year}W{week:02d}'

    def handover_maintain_query(self):
        """查询停服维护接口，取出当前游戏服务器的那一份公告。

        接口顶层是国服新闻聚合出来的结果，各服务器自己的公告在 `servers` 里，
        并且带各自的时区。只有拿不到 `servers`（旧版接口）时才退回顶层数据。

        Returns:
            tuple[dict | None, datetime.timedelta, str]:
                (维护公告, 公告时间所用的兜底时区, 失败原因)。取不到公告时公告为 None。
        """
        server = self.config.SERVER
        try:
            response = requests.get(HANDOVER_MAINTAIN_API, timeout=10).json()
        except Exception as e:
            logger.warning(f'[作战委托] 查询维护时间失败，按不维护处理: {e}')
            return None, timedelta(), '查询维护时间失败'

        data = response.get('data') or {}
        if not data:
            detail = response.get('message') or response.get('status')
            logger.warning(f'[作战委托] 维护接口没有返回数据，按不维护处理: {detail}')
            return None, timedelta(), '维护接口没有返回数据'

        servers = data.get('servers')
        if not isinstance(servers, dict) or not servers:
            # 顶层公告来自国服新闻，退回它时只能按国服时区解释
            logger.warning('[作战委托] 维护接口没有按服务器返回数据，退回顶层公告（国服）')
            return data, SERVER_TO_TIMEZONE['cn'], ''

        payload = servers.get(server)
        if not payload:
            reason = (data.get('server_errors') or {}).get(server) or '接口未返回该服务器'
            logger.warning(f'[作战委托] {server} 的维护公告查询失败，按不维护处理: {reason}')
            return None, timedelta(), f'{server} 维护公告查询失败'

        return payload, SERVER_TO_TIMEZONE.get(server, SERVER_TO_TIMEZONE['cn']), ''

    def handover_maintain_timezone(self, payload, default):
        """解析维护公告所用的服务器时区。

        接口在每条服务器公告里给了 timezone（如 `UTC+8`），以它为准；缺失或者
        格式不认识时用兜底时区。

        Args:
            payload (dict): 一条服务器维护公告。
            default (datetime.timedelta): 兜底时区偏移。

        Returns:
            datetime.timedelta: 相对 UTC 的时区偏移。
        """
        text = str(payload.get('timezone', '')).strip().upper()
        match = HANDOVER_MAINTAIN_TIMEZONE.match(text)
        if not match:
            logger.warning(f'[作战委托] 无法识别的服务器时区 {text!r}，按 {default} 处理')
            return default

        offset = timedelta(hours=int(match.group(2)), minutes=int(match.group(3) or 0))
        return offset if match.group(1) == '+' else -offset

    def handover_maintain_state(self):
        """今天有没有停服维护，有的话返回维护开始时间。

        数据来自 api-blhx-maintain，按当前游戏服务器取对应公告。公告里的时间是
        服务器本地时间，先换算成本机时间再和当前时间比较；时间不是今天的、或者
        已经过去的都当作没有维护。

        Returns:
            tuple[datetime.datetime | None, str]: (维护开始时间, 原因)。
        """
        if not self.config.OperationHandover_MaintainOverride:
            return None, '开关未开启'

        payload, default, error = self.handover_maintain_query()
        if payload is None:
            return None, error

        try:
            start = datetime.strptime(
                f"{payload.get('maintenance_date', '')} {payload.get('start_time', '')}",
                '%Y-%m-%d %H:%M')
        except ValueError:
            logger.warning(f'[作战委托] 维护公告时间无法识别，按不维护处理: '
                           f"{payload.get('maintenance_date')} {payload.get('start_time')}")
            return None, '维护公告时间无法识别'

        # 服务器本地时间 → 本机时间，后续调度用的都是本机时间
        offset = self.handover_maintain_timezone(payload, default)
        start = start.replace(tzinfo=timezone(offset)).astimezone().replace(tzinfo=None)

        now = current_time()
        if start <= now:
            return None, f'{start} 已经过去'
        if start.date() != now.date():
            return None, f'下次维护 {start}，不是今天'

        name = payload.get('name') or self.config.SERVER
        return start, (f'今天 {start} 停服维护（{name}），'
                       f'维护前 {HANDOVER_MAINTAIN_LEAD_MINUTES} 分钟运行')

    def handover_consume_all_book_trigger(self):
        """解析一键消耗委托书的触发配置。

        Returns:
            tuple[int, int, int] | None: (周几, 时, 分)，配置不合法返回 None。
        """
        weekday = self.config.OperationHandover_ConsumeAllBookWeekday
        if weekday not in HANDOVER_WEEKDAYS:
            logger.warning(f'[作战委托] 无法识别的星期: {weekday}')
            return None

        trigger = str(self.config.OperationHandover_ConsumeAllBookTime)
        try:
            hour, minute = [int(part) for part in trigger.split(':')[:2]]
            if not 0 <= hour < 24 or not 0 <= minute < 60:
                raise ValueError
        except ValueError:
            logger.warning(f'[作战委托] 无法识别的触发时间: {trigger}')
            return None

        return HANDOVER_WEEKDAYS.index(weekday), hour, minute

    def handover_consume_all_book_state(self):
        """当前该不该执行一键消耗委托书，以及不执行的原因。

        周几和几点几分由用户配置，本周成功触发过一次就不再触发。委托没开起来
        （比如触发时正好有委托在进行）不算触发过，下一次运行会接着试。

        Returns:
            tuple[bool, str]: (是否执行, 不执行的原因)。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False, '开关未开启'

        now = current_time()
        if self.config.OperationHandover_ConsumeAllBookRecord == self.handover_week_key(now):
            return False, '本周已触发过'

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False, '触发日或触发时间配置不合法'
        weekday, hour, minute = trigger

        if now.weekday() != weekday:
            name = HANDOVER_WEEKDAY_NAMES[weekday]
            if now.weekday() < weekday:
                return False, f'还没到{name}'
            else:
                return False, f'{name}已经过了，等下周'

        if (now.hour, now.minute) < (hour, minute):
            return False, f'还没到触发时间 {hour:02d}:{minute:02d}'

        return True, ''

    def handover_consume_all_book_waiting(self):
        """一键消耗委托书今天还有机会触发吗。

        今天就是触发日、本周又还没触发过时，本次没开成委托也不能把任务推迟到
        次日——次日已经过了触发日，这一周的一键消耗就整个没了。

        Returns:
            bool: 应该稍后重试而不是等次日返回 True。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False

        now = current_time()
        if self.config.OperationHandover_ConsumeAllBookRecord == self.handover_week_key(now):
            return False

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False
        return now.weekday() == trigger[0]

    def handover_consume_all_book_next_time(self):
        """下一次一键消耗委托书的触发时刻。

        委托次数为 0 时用这个时间当下一次运行时间，中间不用进游戏。今天就是
        触发日但时间已经过了（或者本周已经触发过）时顺延到下周。

        Returns:
            datetime.datetime | None: 下一次触发时刻，触发配置不合法返回 None。
        """
        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return None

        weekday, hour, minute = trigger
        now = current_time()
        target = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        return target

    def handover_consume_all_book_record(self):
        """记下本周已经触发过一键消耗委托书。"""
        week = self.handover_week_key(current_time())
        self.config.OperationHandover_ConsumeAllBookRecord = week
        logger.info(f'[作战委托] 本周已触发一键消耗委托书，记录 {week}')

    def handover_oil_cost(self):
        """识别面板上的「预计消耗」石油数量。

        这个数字油够时是白色、不够时变红，颜色不固定，而 Ocr 类的 letter 参数
        要求固定颜色，所以直接用不带颜色要求的 AlOcr 识别。

        Pages: in: 作战委托面板

        Returns:
            int: 预计消耗的石油，读不到返回 0。
        """
        text = OCR_MODEL.azur_lane.ocr_for_single_line(
            crop(self.device.image, HANDOVER_OIL_COST_OCR.area))
        digits = ''.join(char for char in text if char.isdigit())
        if not digits:
            logger.warning(f'[作战委托] 预计消耗石油识别失败: {text!r}')
            return 0
        return int(digits)

    def handover_oil_enough(self, oil):
        """点「开始」之前，用面板上的「预计消耗」核对油量。

        Args:
            oil (int): 打开面板之前读到的石油数量。

        Returns:
            bool: 油量足够（或读不到预计消耗）返回 True。
        """
        cost = self.handover_oil_cost()
        logger.attr('预计消耗石油', cost)
        if cost <= 0:
            logger.warning('[作战委托] 读不到预计消耗石油，跳过油量检查')
            return True
        if oil < cost:
            logger.warning(f'[作战委托] 石油不足，需要 {cost}，当前 {oil}')
            return False
        return True

    def handover_close_panel(self, skip_first_screenshot=True):
        """关掉作战委托面板，回到关卡页。

        面板留在屏幕上会让后面所有任务的页面识别都失败，所以每个「本次不开始
        委托」的出口都要先把面板关掉。

        Pages: in: 作战委托面板, out: 关卡页
        """
        timeout = Timer(10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if not self.handover_panel_appear():
                logger.info('[作战委托] 已关闭作战委托面板')
                return

            if timeout.reached():
                logger.warning('[作战委托] 关闭作战委托面板失败')
                return

            if self.appear_then_click(HANDOVER_PANEL_CLOSE, offset=(20, 20), interval=2):
                continue

    def handover_start(self, skip_first_screenshot=True):
        """点击「开始」，并确认委托真的开起来了。

        资源不足时游戏不会关掉面板，只在面板里显示「资源不足，无法开始」，
        所以不能只看「开始」按钮消失就当作成功——那样面板会留在屏幕上，
        后面所有任务的页面识别都会失败。这里以「面板关掉」作为成功的依据。

        Pages: in: 作战委托面板, out: 关卡页

        Returns:
            bool: 委托已开始返回 True。
        """
        clicked = False
        timeout = Timer(10).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_popup_confirm('HANDOVER_START'):
                continue

            # 面板关掉了，委托已经开始
            if not self.handover_panel_appear():
                logger.info('[作战委托] 委托已开始，委托期间无法出击主线与活动关卡')
                return True

            if clicked and timeout.reached():
                logger.warning('[作战委托] 点击开始后面板没有关闭，委托没有开起来')
                return False

            if self.appear_then_click(HANDOVER_START_CLICK, offset=(20, 20), interval=3):
                if not clicked:
                    clicked = True
                    timeout.reset()
                continue

    def handover_delay(self, delay=None):
        """本次无法开始委托，推迟下次运行。

        作战委托的可用时间额度每天 0 点重置，因此没开始委托时统一推迟到次日。
        但一键消耗委托书如果今天才轮到触发、本周又还没触发过，就不能跳到次日
        （次日已经过了触发日），改成隔一段时间重试。

        Args:
            delay (timedelta): 进行中委托的剩余时间。None 表示本次未开始委托。
        """
        if delay is None:
            if self.handover_consume_all_book_waiting():
                logger.warning(f'[作战委托] 本次未开始委托，一键消耗委托书今天还没触发，'
                               f'{HANDOVER_CONSUME_RETRY_MINUTES} 分钟后再试')
                self.config.task_delay(minute=HANDOVER_CONSUME_RETRY_MINUTES)
            else:
                logger.warning('[作战委托] 本次未开始委托，推迟到下一个可用时间额度刷新')
                self.config.task_delay(server_update=True)
        else:
            logger.info(f'[作战委托] 委托仍在进行，{delay} 后回来领取奖励')
            self.config.task_delay(minute=delay.total_seconds() / 60)
