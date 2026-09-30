"""岛屿运行时状态文件的统一路径（Add by MHY）。

这些文件原先平铺在 config/ 下，而 ALAS 的 alas_instance()（module/config/utils.py）
会把 config/ 顶层每个 xxx.json 都当成一个「实例」。真机实测后果：

    $ list_instances  ->  ["ALAS", "island_away_cook_default", "island_season_notified",
                           "island_season_plan_last", "island_season_plan_page",
                           "island_unproducible", "island_verified", ...]
    每日备份日志      ->  16 个文件里有 6 个是这些状态文件

即 WebUI 实例下拉框出现 6 个假实例，每日备份也把它们当用户配置备份。

移到 config/island/ 子目录即可避开——alas_instance() 只扫顶层、且要求扩展名为
.json。首次访问时把旧位置的同名文件迁移过来，避免丢掉已验证名单等既有数据。
"""
import os
import shutil

STATE_DIR = os.path.join('config', 'island')


def state_file(name):
    """
    返回岛屿状态文件的路径，必要时先把旧位置的同名文件迁移过来。

    Args:
        name (str): 文件名，如 'island_verified.json'

    Returns:
        str: 形如 config/island/island_verified.json；迁移失败时退回旧路径
    """
    path = os.path.join(STATE_DIR, name)
    legacy = os.path.join('config', name)
    if not os.path.exists(path) and os.path.exists(legacy):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            shutil.move(legacy, path)
        except OSError:
            # 迁移失败（文件被占用等）就继续用旧路径：宁可留个假实例，也别丢数据
            return legacy
    return path
