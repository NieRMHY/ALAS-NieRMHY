"""基于 uiautomator2 屏幕截图监听与差异保存工具。"""
import os
from datetime import datetime

from deploy.atomic import atomic_write
from module.base.base import ModuleBase, cv2, image_channel
from module.logger import logger


class ImageBroken(Exception):
    """图像编解码失败或图像为空异常。"""
    pass


class ImageNotSupported(Exception):
    """不支持进行图像处理计算的异常。"""
    pass


def image_encode(image, ext='png', encode=None):
    """根据指定格式对图像进行编码。

    Args:
        image (np.ndarray): 输入的图像数据数组。
        ext (str): 目标图像扩展名（如 'png', 'jpg'），默认为 'png'。
        encode (list[int] | None): 额外的 OpenCV 编码参数，默认为 None。

    Returns:
        np.ndarray: 编码后的字节缓冲区数组。

    Raises:
        ImageNotSupported: 通道数异常或文件扩展名不支持时抛出。
        ImageBroken: 图像编码失败时抛出。
    """
    channel = image_channel(image)
    if channel == 3:
        # RGB
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    elif channel == 0:
        # 灰度图保持原样
        pass
    elif channel == 4:
        # RGBA
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)
    else:
        raise ImageNotSupported(f'shape={image.shape}')

    # 准备编码参数
    ext = ext.lower()
    if encode is None:
        if ext == 'png':
            # 最高压缩等级 0~9
            encode = [cv2.IMWRITE_PNG_COMPRESSION, 9]
        elif ext == 'jpg' or ext == 'jpeg':
            # 最高画质
            encode = [cv2.IMWRITE_JPEG_QUALITY, 100]
        elif ext.lower() == '.webp':
            # 最高画质
            encode = [cv2.IMWRITE_WEBP_QUALITY, 100]
        elif ext == 'tiff' or ext == 'tif':
            # TIFF 的 LZW 压缩
            encode = [cv2.IMWRITE_TIFF_COMPRESSION, 5]
        else:
            raise ImageNotSupported(f'Unsupported file extension "{ext}"')

    # 编码
    ret, buf = cv2.imencode(f'.{ext}', image, encode)
    if not ret:
        raise ImageBroken('cv2.imencode failed')

    return buf


def image_save(image, file, encode=None):
    """原子化保存图像到指定文件。

    Args:
        image (np.ndarray): 图像数据数组。
        file (str): 目标文件保存路径。
        encode (list[int] | None): OpenCV 编码参数，默认为 None。
    """
    _, _, ext = file.rpartition('.')
    data = image_encode(image, ext=ext, encode=encode)
    atomic_write(file, data)


def now():
    """获取当前格式化时间戳字符串。

    Returns:
        str: 格式为 'YYYY-MM-DD_HH-MM-SS-ffffff' 的时间字符串。
    """
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")


class WatchScreen(ModuleBase):
    """屏幕变化监听与自动捕获器。"""

    def watch(self, similarity=0.98):
        """持续监听设备屏幕，当图像相似度低于阈值时保存变化后的截图。

        Args:
            similarity (float): 判断画面是否发生变化的相似度阈值，默认为 0.98。
        """
        start = now()
        before = self.device.screenshot()
        file = os.path.abspath(f'screenshots/{start}/{start}.png')
        image_save(before, file)
        for image in self.loop():
            res = cv2.matchTemplate(image, before, cv2.TM_CCOEFF_NORMED)
            _, sim, _, loca = cv2.minMaxLoc(res)

            if sim < similarity:
                name = now()
                file = os.path.abspath(f'screenshots/{start}/{name}.png')
                logger.info(f'Save file: {file}')
                image_save(image, file)
                before = image


if __name__ == '__main__':
    self = WatchScreen('alas')
    self.watch()
