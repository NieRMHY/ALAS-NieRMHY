# 此文件专门用于处理设备端的文本输入功能。
# 封装了检查输入法窗口状态以及向安卓组件发送文本指令的逻辑。
from module.device.method.uiautomator_2 import Uiautomator2
from module.logger import logger


class Input(Uiautomator2):
    def ime_shown(self) -> bool:
        _, shown = self.u2_current_ime()
        return shown

    def text_input_and_confirm(self, text: str, clear: bool=False):
        for fail_count in range(3):
            try:
                self.u2_send_keys(text=text, clear=clear)
                self.u2_send_action(6)
                break
            except EnvironmentError as e:
                if fail_count >= 2:
                    raise e
                logger.exception(str(e) + f'Retrying {fail_count + 1}/3')
