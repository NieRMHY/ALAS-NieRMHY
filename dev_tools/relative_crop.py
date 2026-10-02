import os
import time

import module.config.server as server
from module.base.utils import *

server.server = 'cn'  # 无需修改，用于避免服务器配置未初始化的异常。

from module.config.config import AzurLaneConfig
from module.map_detection.view import View
from module.base.utils import load_image


class Config:
    """地图临时配置类，用于模拟战役地图运行时的预测参数。"""
    MAP_SIREN_TEMPLATE = ['haorenlichade_m_zhanlie']
    MOVABLE_ENEMY_TURN = (2,)
    MAP_HAS_SIREN = True
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MAP_STORY = False
    MAP_HAS_FLEET_STEP = True
    MAP_HAS_AMBUSH = False
    MAP_HAS_MYSTERY = False
    MAP_CHAPTER_SWITCH_20241219 = True
    STAGE_ENTRANCE = ['half', '20240725']
    MAP_HAS_MODE_SWITCH = True
    STAGE_INCREASE_AB = True
    MAP_WALK_USE_CURRENT_FLEET = True


# 使用用户现有的配置（alas2.json），避免自动创建 alas.json
cfg = AzurLaneConfig('alas2')
# 合并地图文件的配置，使 predict 能标记塞壬格子
cfg = cfg.merge(Config())

# 临时图片保存目录
folder = './screenshots/relative_crop'
# 战役截图路径（将包含 A1 关卡或塞壬的截图放置于此）
file = './screenshots/266F9A78004631A264669859C3BDFF8D.png'

i = load_image(file)
grids = View(cfg)
grids.load(np.array(i))
grids.predict()
grids.show()


os.makedirs(folder, exist_ok=True)
for grid in grids:
    # 更多相对裁剪区域定义可参见 module/map/grid_predictor.py
    # 此处裁剪区域用于 predict_enemy_genre 敌舰类型预测
    piece = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))

    file = '%s_%s_%s.png' % (int(time.time()), grid.location[0], grid.location[1])
    file = os.path.join(folder, file)
    Image.fromarray(piece).save(file)
