"""
aScreenCap 截图方法。

通过 aScreenCap 工具执行设备截图，是标准 `screencap` 命令的高性能替代方案。
aScreenCap 直接读取 Android 设备的 framebuffer，绕过系统 screencap 的额外处理，
截图速度更快、内存占用更低。支持原始压缩格式和 JPEG 编码两种模式。
需要先通过 ADB 将 aScreenCap 推送至设备并赋予执行权限。
"""
import os
from functools import partial

from adbutils.errors import AdbError

from module.base.utils import *
from module.device.connection import Connection
from module.device.method.retry import retry_backend, recover_adb, recover_truncated_image, recover_unknown
from module.device.method.utils import ImageTruncated
from module.exception import EmulatorNotRunningError, RequestHumanTakeover, ScriptError
from module.logger import logger


class AscreencapError(Exception):
    """aScreenCap 截图或通信异常。"""
    pass


def _retry_recover(self, error, trial):
    """aScreenCap 操作失败后的异常恢复策略。

    Args:
        self: 设备实例。
        error: 捕获的异常对象。
        trial: 当前重试轮次。

    Returns:
        可调用的恢复函数，若无法恢复则返回 None。
    """
    if isinstance(error, (ConnectionResetError, AdbError)):
        return recover_adb(self, error)
    if isinstance(error, AscreencapError):
        logger.error(error)
        return self.ascreencap_init
    if isinstance(error, ImageTruncated):
        return recover_truncated_image(self, error)
    return recover_unknown(error)


retry = partial(retry_backend, recover=_retry_recover, label='设备-aScreenCap')


class AScreenCap(Connection):
    __screenshot_method = [0, 1, 2]
    __screenshot_method_fixed = [0, 1, 2]
    __bytepointer = 0
    ascreencap_available = True

    def ascreencap_init(self):
        """初始化 aScreenCap：检查系统架构与 SDK 版本，推送对应的二进制文件并设置权限。

        Raises:
            RequestHumanTakeover: 当未找到适用于当前设备的 aScreenCap 二进制文件时抛出。
        """
        logger.hr('[设备-aScreenCap] aScreenCap初始化')
        self.__bytepointer = 0
        self.ascreencap_available = True

        arc = self.cpu_abi
        sdk = self.sdk_ver
        logger.info(f'[设备-aScreenCap] cpu_arc: {arc}, sdk_ver: {sdk}')

        if sdk in range(21, 26):
            ver = "Android_5.x-7.x"
        elif sdk in range(26, 28):
            ver = "Android_8.x"
        elif sdk == 28:
            ver = "Android_9.x"
        else:
            ver = "0"
        filepath = os.path.join(self.config.ASCREENCAP_FILEPATH_LOCAL, ver, arc, 'ascreencap')
        if not os.path.exists(filepath):
            self.ascreencap_available = False
            logger.error('[设备-aScreenCap] 该设备没有可用的 aScreenCap 库，请使用其他截图方案')
            raise RequestHumanTakeover

        logger.info(f'[设备-aScreenCap] 推送 {filepath}')
        self.adb_push(filepath, self.config.ASCREENCAP_FILEPATH_REMOTE)

        logger.info(f'[设备-aScreenCap] chmod 0777 {self.config.ASCREENCAP_FILEPATH_REMOTE}')
        self.adb_shell(['chmod', '0777', self.config.ASCREENCAP_FILEPATH_REMOTE])

    def uninstall_ascreencap(self):
        """从设备上删除 aScreenCap 可执行文件。"""
        logger.info('[设备-aScreenCap] 移除ascreencap')
        self.adb_shell(['rm', self.config.ASCREENCAP_FILEPATH_REMOTE])

    def _ascreencap_reposition_byte_pointer(self, byte_array):
        """重置并查找数据中的 BMZ1 头部指针，清理可能附带的链接器警告等杂质数据。

        Args:
            byte_array (bytes): aScreenCap 输出的原始字节流。

        Returns:
            bytes: 从 BMZ1 标识开始的有效数据流。

        Raises:
            AscreencapError: 未找到 BMZ1 标识，数据损坏。
        """
        while byte_array[self.__bytepointer:self.__bytepointer + 4] != b'BMZ1':
            self.__bytepointer += 1
            if self.__bytepointer >= len(byte_array):
                text = '重新定位字节指针失败，收到损坏的 aScreenCap 数据'
                logger.warning(text)
                if len(byte_array) < 500:
                    logger.warning(f'异常截图: {byte_array}')
                raise AscreencapError(text)
        return byte_array[self.__bytepointer:]

    def __load_screenshot(self, screenshot, method):
        """按指定的换行符规则转换截图数据。

        Args:
            screenshot (bytes): 截图字节流。
            method (int): 转换模式编号（0, 1, 2）。

        Returns:
            bytes: 处理后的字节流。

        Raises:
            ScriptError: 未知的转换模式。
        """
        if method == 0:
            return screenshot
        elif method == 1:
            return screenshot.replace(b'\r\n', b'\n')
        elif method == 2:
            return screenshot.replace(b'\r\r\n', b'\n')
        else:
            raise ScriptError(f'Unknown method to load screenshots: {method}')

    def __uncompress(self, screenshot):
        """解压并解析 aScreenCap 压缩数据为 RGB 图像。

        Args:
            screenshot (bytes): aScreenCap 输出的数据。

        Returns:
            np.ndarray: 解析并垂直翻转后的 RGB 图像。

        Raises:
            AscreencapError: 头部校验失败或数据不完整。
            ImageTruncated: 解压数据为空或截断。
        """
        raw_compressed_data = self._ascreencap_reposition_byte_pointer(screenshot)

        # 确保头部数据存在
        if raw_compressed_data is None or len(raw_compressed_data) < 20:
            text = 'aScreenCap 返回了不完整的数据或空载荷'
            logger.warning(text)
            if raw_compressed_data is not None and len(raw_compressed_data) < 500:
                logger.warning(f'异常截图: {raw_compressed_data}')
            raise AscreencapError(text)

        # 头部格式参考：
        # https://github.com/ClnViewer/Android-fast-screen-capture#streamimage-compressed---header-format-using
        compressed_data_header = np.frombuffer(raw_compressed_data[0:20], dtype=np.uint32)
        if compressed_data_header[0] != 828001602:
            compressed_data_header = compressed_data_header.byteswap()
            if compressed_data_header[0] != 828001602:
                text = f'aScreenCap 头部验证失败，收到损坏的图像。十六进制头部 = {compressed_data_header.tobytes().hex()}'
                logger.warning(text)
                raise AscreencapError(text)

        _, uncompressed_size, _, width, height = compressed_data_header
        channel = 3
        from lz4.block import decompress
        data = decompress(raw_compressed_data[20:], uncompressed_size=uncompressed_size)

        if data is None or len(data) == 0:
            raise ImageTruncated('Empty uncompressed data from aScreenCap')

        image = np.frombuffer(data, dtype=np.uint8)
        if image is None or image.size == 0:
            raise ImageTruncated('Empty image after reading from buffer')

        # 等同于 cv2.imdecode()
        try:
            image = image[-int(width * height * channel):].reshape(height, width, channel)
        except ValueError as e:
            # ValueError: cannot reshape array of size 0 into shape (720,1280,4)
            raise ImageTruncated(str(e))

        # 不使用 `dst=image` 进行翻转
        # np.frombuffer 创建的是只读内存视图，此处需要创建可写的副本
        image = cv2.flip(image, 0)
        if image is None:
            raise ImageTruncated('Empty image after cv2.flip')

        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, dst=image)
        if image is None:
            raise ImageTruncated('Empty image after cv2.cvtColor')

        return image

    def __process_screenshot(self, screenshot):
        """尝试多种换行符转换并解压截图数据。

        Args:
            screenshot (bytes): 待处理的数据。

        Returns:
            np.ndarray: 解压成功的 RGB 图像。

        Raises:
            ImageTruncated: 所有模式解压均失败。
        """
        from lz4.block import LZ4BlockError
        for method in self.__screenshot_method_fixed:
            try:
                result = self.__load_screenshot(screenshot, method=method)
                result = self.__uncompress(result)
                self.__screenshot_method_fixed = [method] + self.__screenshot_method
                return result
            except LZ4BlockError:
                self.__bytepointer = 0
                continue

        self.__screenshot_method_fixed = self.__screenshot_method
        if len(screenshot) < 500:
            logger.warning(f'异常截图: {screenshot}')
        raise ImageTruncated(f'cannot load screenshot')

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_ascreencap(self):
        """通过 aScreenCap 工具配合 ADB shell 截取屏幕图像。

        Returns:
            np.ndarray: RGB 格式的屏幕截图。
        """
        content = self.adb_shell([self.config.ASCREENCAP_FILEPATH_REMOTE, '--pack', '2', '--stdout'], stream=True)

        return self.__process_screenshot(content)

    @retry(on_exhausted=EmulatorNotRunningError)
    def screenshot_ascreencap_nc(self):
        """通过 aScreenCap 工具配合 netcat 直连截取屏幕图像。

        Returns:
            np.ndarray: RGB 格式的屏幕截图。
        """
        data = self.adb_shell_nc([self.config.ASCREENCAP_FILEPATH_REMOTE, '--pack', '2', '--stdout'])
        if len(data) < 500:
            logger.warning(f'异常截图: {data}')

        return self.__uncompress(data)
