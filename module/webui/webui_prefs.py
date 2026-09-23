# -*- coding: utf-8 -*-
"""WebUI 界面偏好持久化。

用于记住纯界面状态（如概览页右栏展示日志还是统计），
与实例配置解耦：存 ``config/webui_prefs.json``，不污染 ``argument.yaml`` 的配置 schema。

对应的浏览器端缓存键见 :data:`LOCALSTORAGE_KEYS`，由前端 ``localStorage`` 镜像一份，
使服务端文件缺失（如手动清理）时仍能回退到用户上次的选择。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from module.logger import logger

PANEL_LOG = 'log'
PANEL_STAT = 'stat'
PANEL_CHOICES = (PANEL_LOG, PANEL_STAT)
PANEL_DEFAULT = PANEL_STAT

LOCALSTORAGE_KEYS = {
    'overview_panel': 'alas_overview_panel',
}

# 自定义背景图网址上限。这些值会被当作图片地址加载，
# 加上限与长度上限，避免脏数据把页面拖垮。
BACKGROUND_URL_MAX = 20
BACKGROUND_URL_LENGTH = 2048

# 本地背景图目录（项目根下的 bg/），与网址并存时优先
BACKGROUND_DIR_NAME = 'bg'
BACKGROUND_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PREFS_FILE = _PROJECT_ROOT / 'config' / 'webui_prefs.json'


def resolve_panel(stored: Any, cached: Any) -> str:
    """按「服务端偏好 > 浏览器缓存 > 默认」解析概览页右栏面板。

    任何非 ``"log"`` / ``"stat"`` 的值（脏数据、``None``、非字符串）都不生效，
    直接落回默认值，避免异常取值把界面卡在空白状态。

    Args:
        stored: 服务端偏好值。
        cached: 浏览器 ``localStorage`` 镜像值。

    Returns:
        ``"log"`` 或 ``"stat"``。
    """
    for candidate in (stored, cached):
        if isinstance(candidate, str) and candidate in PANEL_CHOICES:
            return candidate
    return PANEL_DEFAULT


def _read_prefs() -> dict:
    try:
        with open(_PREFS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning(f'[WebUI-偏好] 读取 {_PREFS_FILE} 失败: {e}')
        return {}


def get_pref(key: str, default: Any = None) -> Any:
    """读取一个界面偏好；文件缺失或损坏时返回 ``default``。"""
    return _read_prefs().get(key, default)


def set_pref(key: str, value: Any) -> bool:
    """写入一个界面偏好，保留其余键。

    Returns:
        是否写入成功。失败只告警不抛出——界面偏好不该影响主流程。
    """
    data = _read_prefs()
    data[key] = value
    try:
        _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PREFS_FILE.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(_PREFS_FILE)
        return True
    except OSError as e:
        logger.warning(f'[WebUI-偏好] 写入 {_PREFS_FILE} 失败: {e}')
        return False


def get_overview_panel(cached: Optional[str] = None) -> str:
    """解析概览页右栏面板。``cached`` 为浏览器 ``localStorage`` 镜像值。"""
    return resolve_panel(get_pref('overview_panel'), cached)


def set_overview_panel(panel: str) -> bool:
    """记住概览页右栏面板选择。非法值拒绝写入。"""
    if panel not in PANEL_CHOICES:
        return False
    return set_pref('overview_panel', panel)


def normalize_background_urls(value: Any) -> list:
    """把用户填的网址整理成干净列表。

    容忍常见输入瑕疵：空行、首尾空白、误加的引号或逗号。
    只保留 ``http://`` / ``https://`` 开头且长度合理的项，
    其余丢弃——这些值会被当作加载地址用，不能放行脏数据。

    Args:
        value: 原始值（列表、或换行/逗号分隔的字符串）。

    Returns:
        去重后的网址列表，最多 :data:`BACKGROUND_URL_MAX` 条。
    """
    if isinstance(value, str):
        raw = value.replace(',', '\n').splitlines()
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        return []

    out = []
    for item in raw:
        if not isinstance(item, str):
            continue
        url = item.strip().strip('"\'').strip()
        if not url or len(url) > BACKGROUND_URL_LENGTH:
            continue
        if not url.startswith(('http://', 'https://')):
            continue
        if url not in out:
            out.append(url)
        if len(out) >= BACKGROUND_URL_MAX:
            break
    return out


def get_background_urls() -> list:
    """读取自定义背景图网址列表；缺失或损坏时返回空列表。"""
    return normalize_background_urls(get_pref('background_urls'))


def set_background_urls(urls: Any) -> bool:
    """记住自定义背景图网址列表，写入前先做校验整理。"""
    return set_pref('background_urls', normalize_background_urls(urls))
