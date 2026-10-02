"""地图网格与透视变换调试工具。

独立于主程序调用地图检测模块（module/map_detection/view.py），排查透视畸变与网格识别异常。
"""
import module.config.server as server

server.server = 'cn'  # 设置默认服务器为国服以防报错

import numpy as np
from PIL import Image

from module.config.config import AzurLaneConfig
from module.map_detection.view import View


class Config:
    """网格透视变换与峰值检测默认参数配置。"""
    # scipy.signal.find_peaks 参数
    # https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (150, 255 - 40),
        'width': (0.9, 10),
        'prominence': 10,
        'distance': 35,
    }
    EDGE_LINES_FIND_PEAKS_PARAMETERS = {
        'height': (255 - 24, 255),
        'prominence': 10,
        'distance': 50,
        # 'width': (0, 7),
        'wlen': 1000
    }
    # cv2.HoughLines 霍夫线变换参数
    INTERNAL_LINES_HOUGHLINES_THRESHOLD = 75
    EDGE_LINES_HOUGHLINES_THRESHOLD = 75
    # 线条初步清洗参数
    HORIZONTAL_LINES_THETA_THRESHOLD = 0.005
    VERTICAL_LINES_THETA_THRESHOLD = 18
    TRUST_EDGE_LINES = False  # True 表示使用边缘裁剪内部，False 表示使用内部裁剪边缘
    # 透视计算参数
    VANISH_POINT_RANGE = ((540, 740), (-3000, -1000))
    DISTANCE_POINT_X_RANGE = ((-3200, -1600),)
    # 线条精细清洗参数
    COINCIDENT_POINT_ENCOURAGE_DISTANCE = 3
    ERROR_LINES_TOLERANCE = (-10, 10)
    MID_DIFF_RANGE_H = (129 - 3, 129 + 3)
    MID_DIFF_RANGE_V = (129 - 3, 129 + 3)

    # 步骤 1：在此处粘贴待调试的自定义参数覆盖
    pass


# 步骤 2：在此处填入待测试的截图路径
file = ''
image = np.array(Image.open(file).convert('RGB'))


# 步骤 3：选择一种检测方式，取消注释代码并运行。
# 运行后会输出局部地图日志并弹出网格线示意图。

# ==============================
# 方式 1：透视检测后端 (perspective)
# ==============================
# cfg = Config()
# cfg.DETECTION_BACKEND = 'perspective'
# view = View(AzurLaneConfig('template').merge(cfg))
# view.load(image)
# view.predict()
# view.show()
# view.backend.draw()

# ==============================
# 方式 2：带实时透视计算的单应性矩阵 (homography)
# 当前默认推荐方式
# ==============================
cfg = Config()
cfg.DETECTION_BACKEND = 'homography'
view = View(AzurLaneConfig('template').merge(cfg))
view.load(image)
view.predict()
view.show()
view.backend.draw()

# ==============================
# 方式 3：使用预设透视数据 (HOMO_STORAGE) 的单应性检测
# 从日志或方式 2 的输出中获取 HOMO_STORAGE
# ==============================
# cfg = Config()
# cfg.DETECTION_BACKEND = 'homography'
# view = View(AzurLaneConfig('template').merge(cfg))
# homo_storage = ()  # 在此粘贴 HOMO_STORAGE 数据
# view.backend.load_homography(storage=homo_storage)
# view.load(image)
# view.predict()
# view.show()
# view.backend.draw()
