"""ADB Shell 警告信息过滤模块。

移除 VMOS、Waydroid 等环境 Shell 输出中的链接器与渲染器警告信息，
避免干扰后续数据解析（如 PNG 截图数据）。
"""

from typing import overload


@overload
def remove_shell_warning(s: bytes) -> bytes: ...


@overload
def remove_shell_warning(s: str) -> str: ...


def remove_shell_warning(s):
    """过滤 Shell 执行输出中的链接器等干扰警告信息。

    处理场景包括：
    1. VMOS shell 中的链接器警告（如 `WARNING: linker: [vdso]: unused DT entry...`）
    2. 多命令串联执行时重复出现的链接器警告

    Args:
        s (str | bytes): 原始 Shell 输出文本或字节串。

    Returns:
        str | bytes: 过滤警告后的输出内容。
    """
    if isinstance(s, bytes):
        while 1:
            if s.startswith(b'WARNING: linker:'):
                _, _, s = s.partition(b'\n')
            else:
                break
    elif isinstance(s, str):
        while 1:
            if s.startswith('WARNING: linker:'):
                _, _, s = s.partition('\n')
            else:
                break

    return s


@overload
def remove_screenshot_warning(s: bytes) -> bytes: ...


@overload
def remove_screenshot_warning(s: str) -> str: ...


def remove_screenshot_warning(s):
    """过滤截屏数据前附带的各种控制台警告前缀。

    处理场景包括：
    1. Waydroid screencap 着色器缓存创建失败提示
    2. 多屏幕设备 screencap 的 display id 缺失提示
    3. VMOS PRO 截图前缀未知头
    4. NAS 等轻量 Linux 运行 redroid 时的 AMD GPU 驱动警告

    Args:
        s (str | bytes): 原始截屏二进制或文本数据。

    Returns:
        str | bytes: 过滤掉警告头部的实际截屏数据。
    """
    if isinstance(s, bytes):
        if s.startswith(b'Failed to create'):
            _, _, s = s.partition(b'\n')
        if s.startswith(b'[Warning] Multiple displays'):
            _, _, s = s.partition(b'\n')
            if s.startswith(b'A display id') or s.startswith(b'A display ID'):
                _, _, s = s.partition(b'\n')
                if s.startswith(b'See "dumpsys'):
                    _, _, s = s.partition(b'\n')
        if s.startswith(b'long long=8'):
            _, _, s = s.partition(b'\n')
        if s.startswith(b'amdgpu:'):
            _, _, s = s.partition(b'\n')
            if s.startswith(b'If they do'):
                _, _, s = s.partition(b'\n')

    elif isinstance(s, str):
        if s.startswith('Failed to create'):
            _, _, s = s.partition('\n')
        if s.startswith('[Warning] Multiple displays'):
            _, _, s = s.partition('\n')
            if s.startswith('A display id') or s.startswith('A display ID'):
                _, _, s = s.partition('\n')
                if s.startswith('See "dumpsys'):
                    _, _, s = s.partition('\n')
        if s.startswith('long long=8'):
            _, _, s = s.partition('\n')
        if s.startswith('amdgpu:'):
            _, _, s = s.partition('\n')
            if s.startswith('If they do'):
                _, _, s = s.partition('\n')

    return s
