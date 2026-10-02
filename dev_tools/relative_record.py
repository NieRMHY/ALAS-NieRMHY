import os

from PIL import Image
from tqdm import tqdm

import module.config.server as server

server.server = 'cn'  # 无需修改，用于避免服务器配置未初始化的异常。

from module.base.base import ModuleBase
from module.base.utils import *
from module.config.config import AzurLaneConfig
from module.map_detection.view import View


class Config:
    """透视与网格峰值检测参数配置类。"""
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (80, 255 - 17),
        'width': (0.9, 10),
        'prominence': 10,
        'distance': 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (255 - 17, 255),
        'prominence': 10,
        'distance': 50,
        'wlen': 1000
    }
    HOMO_EDGE_COLOR_RANGE = (0, 17)


"""
使用说明：
    - 进入游戏战役地图并定位塞壬精英。
    - 手动确认该塞壬在当前局部地图视野中对应的网格节点坐标（例如 E6）。
    - 首先运行 relative_record.py，连续截取足够数量的帧序列图片。
    - 然后运行 relative_record_gif2.py，根据帧序列自动生成 GIF 动态模板文件。
    - 在 <FOLDER>/<NAME>_gif 目录中挑选最佳模板，理想模板应满足：
        不包含塞壬面部，仅包含躯干/舰装特征；
        背景尽量不包含海面波纹；
        在保证特征的前提下帧数尽可能少。
    - 将选中的模板复制到 assets/<server>/template 目录并运行 button_extract.py。
    - 在战役地图配置中引用新模板，例如：
        MAP_HAS_SIREN = True
        MAP_SIREN_TEMPLATE = ['U73', 'U81']

参数说明：
    CONFIG: 加载的 Alas 实例配置名。
    FOLDER: 截图保存根目录。
    NAME: 塞壬模板名称，图片将保存在 <FOLDER>/<NAME> 中。
    NODE: 当前地图视野中待裁剪的格子节点坐标。
"""
CONFIG = 'alas2'
FOLDER = './screenshots/record'
NAME = 'haorenlichade_m_qianting'
NODE = 'E6'

if __name__ == '__main__':
    for folder in [FOLDER, os.path.join(FOLDER, NAME)]:
        if not os.path.exists(folder):
            os.mkdir(folder)

    cfg = AzurLaneConfig(CONFIG).merge(Config())
    al = ModuleBase(cfg)
    al.device.disable_stuck_detection()
    al.device.screenshot_interval_set(0.11)
    view = View(cfg)
    al.device.screenshot()
    view.load(al.device.image)
    grid = view[node2location(NODE.upper())]

    print('请检查弹出的预览图是否裁剪了正确的目标区域')
    print('如果正确，请等待截图录制完成')
    print('如果不正确，请停止进程，修改 `NODE` 参数后重新运行')
    image = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
    image = Image.fromarray(image, mode='L').show()

    images = []
    for n in tqdm(range(300)):
        images.append(al.device.screenshot())
    for n, image in enumerate(images):
        grid.image = np.array(image)
        image = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))
        image = Image.fromarray(image, mode='L')
        image.save(os.path.join(FOLDER, NAME, f'{n}.png'))

    print('relative_record 录制完成')
