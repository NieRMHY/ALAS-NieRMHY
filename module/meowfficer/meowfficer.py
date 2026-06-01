from module.meowfficer.buy import MeowfficerBuy
from module.meowfficer.fort import MeowfficerFort
from module.meowfficer.train import MeowfficerTrain
from module.ui.page import page_meowfficer
from module.meowfficer.assets import MEOWFFICER_BUY_ENTER


class RewardMeowfficer(MeowfficerBuy, MeowfficerFort, MeowfficerTrain):
    def wait_meowfficer_buttons(self, skip_first_screenshot=True):
        """
        等待指挥喵 UI 完全加载。

        MEOWFFICER_INFO 和 MEOWFFICER_BUY_ENTER 的加载速度慢于 MEOWFFICER_CHECK，
        需要等待它们出现后才能进行后续操作。
        """
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                break

            # MEOWFFICER_INFO
            if self.ui_additional():
                continue

    def run(self):
        """
        执行指挥喵的购买、强化、训练和小屋操作（仅执行配置中启用的操作）。

        Pages:
            in: 任意页面
            out: page_meowfficer
        """
        if self.config.Meowfficer_BuyAmount <= 0 \
                and self.config.Meowfficer_OverflowCoins == -1 \
                and not self.config.Meowfficer_FortChoreMeowfficer \
                and not self.config.MeowfficerTrain_Enable:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.ui_ensure(page_meowfficer)
        self.wait_meowfficer_buttons()  # 等待 UI 完全加载

        if self.config.Meowfficer_BuyAmount > 0 \
                or self.config.Meowfficer_OverflowCoins != -1:
            self.meow_buy()
        if self.config.Meowfficer_FortChoreMeowfficer:
            self.meow_fort()

        # 训练
        if self.config.MeowfficerTrain_Enable:
            self.meow_train()
            if self.config.MeowfficerTrain_Mode == 'seamlessly':
                self.meow_enhance()
            elif self.meow_is_sunday():
                self.meow_enhance()
            else:
                pass

        # 调度
        if self.config.MeowfficerTrain_Enable:
            # 指挥喵训练时长：
            # - 蓝色品质，2.0h ~ 2.5h
            # - 紫色品质，5.5h ~ 6.5h
            # - 金色品质，9.5h ~ 10.5h
            # 有指挥喵正在训练时，延迟 2.5h ~ 3.5h
            self.config.task_delay(minute=(150, 210), server_update=True)
        else:
            self.config.task_delay(server_update=True)
