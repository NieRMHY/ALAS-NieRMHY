"""数据备份与归档模块。

提供数据库和用户配置的每日自动备份、压缩存档与历史备份过期清理功能。
"""

import json
import shutil
import sqlite3

from datetime import datetime, timedelta
from pathlib import Path

from module.logger import logger


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / 'config'
BACKUP_ROOT = ROOT_DIR / 'AzurPilot_Data_Backup'

BACKUP_KEEP_DAYS = 7

DATABASE_FILES = (
    'azurstats_local.db',
    'cl1_data.db',
)


def backup(enable=True, keep_days=BACKUP_KEEP_DAYS):
    """执行每日备份。

    备份数据库文件与用户配置文件，并清理超期备份。

    Args:
        enable (bool): 是否启用备份。关闭时直接返回，既不新建备份，
            也不清理历史备份，避免关掉开关后仍在动备份目录。
        keep_days (int): 历史备份保留天数，超过该天数的备份会被删除。
            小于 1 时按 1 天处理。
    """
    if not enable:
        logger.info('每日备份已关闭，跳过备份')
        return

    date = datetime.now().strftime('%Y-%m-%d')
    backup_dir = BACKUP_ROOT / date

    if backup_dir.exists():
        logger.info(f'今日备份已存在，跳过备份：{backup_dir}')
        return

    logger.info('开始执行每日备份')

    backup_dir.mkdir(parents=True, exist_ok=True)

    files = []

    files.extend(backup_database(backup_dir))
    files.extend(backup_config(backup_dir))

    create_backup_info(
        backup_dir=backup_dir,
        files=files,
    )

    clean_backup(keep_days=keep_days)

    logger.info(f'每日备份完成，共备份 {len(files)} 个文件')


def backup_database(backup_dir):
    """备份数据库文件。

    Args:
        backup_dir (Path): 备份目标目录。

    Returns:
        list[dict]: 成功备份的文件信息列表。
    """
    logger.info('开始备份数据库')

    files = []

    for name in DATABASE_FILES:
        source = CONFIG_DIR / name

        if not source.exists():
            logger.warning(f'未找到数据库文件，跳过备份：{source}')
            continue

        target = backup_dir / name

        try:
            sqlite_backup(
                source=source,
                target=target,
            )

            files.append({
                'name': name,
                'size': target.stat().st_size,
            })

            logger.info(f'数据库备份成功：{name}')
        except Exception as e:
            logger.warning(f'数据库备份失败：{name}，{e}')

    return files


def backup_config(backup_dir):
    """备份用户配置文件。

    包括 deploy.yaml 和除 template*.json 外的所有 json 配置文件。

    Args:
        backup_dir (Path): 备份目标目录。

    Returns:
        list[dict]: 成功备份的文件信息列表。
    """
    logger.info('开始备份用户配置')

    files = []
    scheduler = CONFIG_DIR / 'scheduler'
    if scheduler.exists():
        from module.scheduler.store import ProgramStore
        store = ProgramStore(CONFIG_DIR)
        for source in scheduler.glob('*.sqlite3'):
            relative = source.relative_to(CONFIG_DIR)
            target = backup_dir / relative
            try:
                store.backup(source.stem, target)
                files.append({'name': str(relative), 'size': target.stat().st_size})
            except Exception as exc:
                logger.warning(f'调度数据库备份失败：{source}，{exc}')

    deploy = CONFIG_DIR / 'deploy.yaml'

    if deploy.exists():
        target = backup_dir / deploy.name

        shutil.copy2(deploy, target)

        files.append({
            'name': deploy.name,
            'size': target.stat().st_size,
        })

        logger.info('用户配置备份成功：deploy.yaml')

    for file in CONFIG_DIR.glob('*.json'):
        if file.stem.startswith('template'):
            continue

        target = backup_dir / file.name

        try:
            shutil.copy2(file, target)

            files.append({
                'name': file.name,
                'size': target.stat().st_size,
            })

            logger.info(f'用户配置备份成功：{file.name}')
        except Exception as e:
            logger.warning(f'用户配置备份失败：{file.name}，{e}')

    return files

def sqlite_backup(source, target):
    """使用 SQLite 原生 backup() 接口备份数据库。

    Args:
        source (Path): 原数据库路径。
        target (Path): 备份数据库路径。
    """
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)

    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def create_backup_info(backup_dir, files):
    """创建备份信息元数据文件。

    Args:
        backup_dir (Path): 备份目录路径。
        files (list): 已备份文件信息列表。
    """
    info = {
        'backup_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'file_count': len(files),
        'files': files,
    }

    with open(backup_dir / 'backup_info.json', 'w', encoding='utf-8') as f:
        json.dump(
            info,
            f,
            indent=4,
            ensure_ascii=False,
        )


def clean_backup(keep_days=BACKUP_KEEP_DAYS):
    """清理超过保留天数的历史备份目录。

    Args:
        keep_days (int): 历史备份保留天数。小于 1 时按 1 天处理，
            避免把「只保留今天」误配成清空全部备份。
    """
    if not BACKUP_ROOT.exists():
        return

    keep_days = max(int(keep_days), 1)
    expire_date = datetime.now().date() - timedelta(days=keep_days)

    for folder in BACKUP_ROOT.iterdir():
        if not folder.is_dir():
            continue

        try:
            folder_date = datetime.strptime(folder.name, '%Y-%m-%d').date()
        except ValueError:
            continue

        if folder_date >= expire_date:
            continue

        try:
            shutil.rmtree(folder)
            logger.info(f'已删除过期备份：{folder.name}')
        except Exception as e:
            logger.warning(f'删除过期备份失败：{folder.name}，{e}')
