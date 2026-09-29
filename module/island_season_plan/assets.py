"""岛屿赛季「开发季」入口资源（Add by MHY）。

岛屿主页右上角图标行：商店 / 地图 / **开发季** / 科技 / 角色 / 管理
（中心 x = 768 / 860 / 954 / 1045 / 1136 / 1229，中心 y ≈ 42）。

坐标取自真机 1280x720 截图；其它服务器暂复用 cn 资源（与 island_daily_interact
的处理一致）。
"""
from module.base.button import Button

# 按钮区域收紧到图标本体（中心 954,43）：区域给太宽会被 offset 扩到图标外，
# 真机实测点空过（日志里点到了 y=4~22 的空白处）。
_ENTRY_AREA = (932, 21, 976, 65)

ISLAND_SEASON_ENTRY = Button(
    area={'cn': _ENTRY_AREA, 'en': _ENTRY_AREA, 'jp': _ENTRY_AREA, 'tw': _ENTRY_AREA},
    color={'cn': (221, 220, 218), 'en': (221, 220, 218),
           'jp': (221, 220, 218), 'tw': (221, 220, 218)},
    button={'cn': _ENTRY_AREA, 'en': _ENTRY_AREA, 'jp': _ENTRY_AREA, 'tw': _ENTRY_AREA},
    file={'cn': './assets/cn/island_season_plan/ISLAND_SEASON_ENTRY.png',
          'en': './assets/cn/island_season_plan/ISLAND_SEASON_ENTRY.png',
          'jp': './assets/cn/island_season_plan/ISLAND_SEASON_ENTRY.png',
          'tw': './assets/cn/island_season_plan/ISLAND_SEASON_ENTRY.png'},
    name='ISLAND_SEASON_ENTRY',
)
