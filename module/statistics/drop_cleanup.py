"""掉落记录截图的保留天数清理（Drop Record Retention）。

掉落记录模块会写入两类截图，默认都永久保留：

    - ``DropRecord_SaveFolder``（默认 ``./screenshots``）下按 genre 分子目录
      保存的掉落截图，文件名是 13 位毫秒时间戳（见 ``AzurStats.commit()``）；
    - ``log/commission_rewards/<实例>/<YYYY-MM>/`` 下供统计页「查看截图」
      使用的委托收益截图。

用户在「掉落记录」设置里填了保留天数后，超过天数的截图会按
``DropRecord_BackUpMethod`` 归置：直接删除、拷贝备份或压缩备份
（备份落在各来源目录下的 ``bak/``，实现见 ``module.base.archive``）；
填 0 表示不按天数清理。删除是不可逆操作，所以只处理文件名符合本模块
命名规则的图片，``screenshots/item_templates`` 里用户自己命名的模板
文件不会被误删，``bak/`` 里的备份也不会被重复处理。
"""

import os
import re
import time

from module.base import archive
from module.logger import logger

# 两次实际清理之间的最小间隔（秒）。掉落记录提交非常频繁（每场战斗一次），
# 扫目录的成本没必要每次都付。
CLEANUP_INTERVAL = 3600

# 备份目录名，落在各来源目录下（与日志轮转的 bak 约定一致）
BAK_FOLDER = 'bak'

# 委托收益截图目录，与 Commission._save_commission_reward_screenshots 保持一致
COMMISSION_REWARD_FOLDER = os.path.join('.', 'log', 'commission_rewards')

# 掉落截图文件名：13 位毫秒时间戳，可带 info 后缀
# （``AzurStats.commit()`` 生成的 ``{now}.png`` / ``{now}_{info}.png``）
DROP_IMAGE_PATTERN = re.compile(r'^\d{13}(_.+)?\.png$')

_LAST_CLEANUP = 0.0


def drop_screenshot_retention_days(config):
    """读取掉落截图保留天数。

    配置值不可解析时按 0（不清理）处理：删除是不可逆操作，
    配置异常时宁可什么都不删。

    Args:
        config: 当前运行实例的 AzurLaneConfig。

    Returns:
        int: 保留天数，0 表示不按天数清理。
    """
    return archive.read_days(config, 'DropRecord_RetentionDays', default=0)


def _collect_expired(folder, deadline, now, pattern=None):
    """收集文件夹下的过期截图，按所在目录分组。

    ``bak`` 目录不参与扫描：拷贝备份会保留原文件的修改时间，
    只看时间会把备份当成过期内容重复处理甚至删掉。

    Args:
        folder (str): 待扫描目录，不存在时返回空。
        deadline (float): 保留时长（秒），文件年龄超过它即视为过期。
        now (float): 当前时间戳。
        pattern (re.Pattern): 文件名过滤器，None 表示所有 .png 都算。

    Returns:
        dict[str, list[str]]: 所在目录 → 过期文件路径列表。
    """
    groups = {}
    if not os.path.isdir(folder):
        return groups

    for path, dirs, names in os.walk(folder):
        # topdown 时裁剪 dirs 才能真正跳过整个 bak 子树
        dirs[:] = [d for d in dirs if d != BAK_FOLDER]
        expired = []
        for name in names:
            if not name.endswith('.png'):
                continue
            if pattern is not None and not pattern.match(name):
                continue
            file = os.path.join(path, name)
            try:
                if now - os.path.getmtime(file) < deadline:
                    continue
            except OSError:
                continue
            expired.append(file)
        if expired:
            groups[path] = expired
    return groups


def _remove_empty_folders(folder):
    """移除清空后的空目录，保留来源根目录与 ``bak``。"""
    for path, _, _ in os.walk(folder, topdown=False):
        if path == folder or os.path.basename(os.path.normpath(path)) == BAK_FOLDER:
            continue
        try:
            os.rmdir(path)
        except OSError:
            # 还有文件（或权限不足）时留着，下次清理再试
            pass


def _expire_folder(folder, deadline, now, method, zip_method, name,
                   pattern=None, prefix=''):
    """按配置清理一个来源目录，返回处理的文件数。

    Args:
        folder (str): 来源目录。
        deadline (float): 保留时长（秒），文件年龄超过它即过期。
        now (float): 当前时间戳。
        method (str): delete / zip / copy。
        zip_method (str): bz2 / gzip / xz / zip。
        name (str): 分组目录名为空时的备用来源标识。
        pattern (re.Pattern): 文件名过滤器。
        prefix (str): 来源标识前缀，用于区分同级的多个来源。

    Returns:
        int: 处理的文件数。
    """
    groups = _collect_expired(folder, deadline, now, pattern)
    if not groups:
        return 0

    bak_folder = os.path.join(folder, BAK_FOLDER)
    handled = 0
    for parent, paths in sorted(groups.items()):
        source = os.path.basename(os.path.normpath(parent)) or name
        handled += archive.expire(
            paths, bak_folder, method, zip_method, f'{prefix}{source}')
    # 只有真的处理过才扫空目录，省掉每小时一次的无谓遍历
    _remove_empty_folders(folder)
    return handled


def cleanup_drop_screenshots(config, retention_days):
    """按保留天数清理掉落截图与委托收益截图。

    只清理当前实例自己的委托收益截图目录，其它实例由各自的
    配置实例负责（各实例的保留天数可能不同）。

    Args:
        config: 当前运行实例的 AzurLaneConfig。
        retention_days (int): 保留天数，小于等于 0 表示不清理。

    Returns:
        int: 处理的文件数。
    """
    if retention_days <= 0:
        return 0

    method = archive.read_method(config, 'DropRecord_BackUpMethod', default='zip')
    zip_method = archive.read_zip_method(config, 'DropRecord_ZipMethod', default='zip')

    now = time.time()
    deadline = retention_days * 86400
    handled = _expire_folder(
        str(config.DropRecord_SaveFolder), deadline, now,
        method, zip_method, name='screenshots', pattern=DROP_IMAGE_PATTERN)

    instance = getattr(config, 'config_name', None)
    if instance:
        handled += _expire_folder(
            os.path.join(COMMISSION_REWARD_FOLDER, str(instance)), deadline, now,
            method, zip_method, name=str(instance), prefix=f'{instance}_')

    if handled:
        logger.info(
            f'[掉落记录] 已处理 {handled} 张超过 {retention_days} 天的截图'
            f'（{method}），备份目录 {BAK_FOLDER}/')
    return handled


def cleanup_drop_screenshots_if_due(config):
    """按配置清理过期掉落截图，带节流（每小时最多真正清理一次）。

    由 ``AzurStats.new()`` 调用：掉落记录提交在战斗中很频繁，
    但清理没必要跟着那么勤。

    Args:
        config: 当前运行实例的 AzurLaneConfig。

    Returns:
        int: 本次实际处理的文件数；未到清理时间或保留天数为 0 时返回 0。
    """
    global _LAST_CLEANUP

    days = drop_screenshot_retention_days(config)
    if days <= 0:
        return 0

    now = time.time()
    if now - _LAST_CLEANUP < CLEANUP_INTERVAL:
        return 0
    _LAST_CLEANUP = now

    return cleanup_drop_screenshots(config, days)
