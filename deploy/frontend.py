"""构建本地 React 静态资源，取代旧桌面应用更新步骤。"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def npm_command():
    """Windows 直接使用 Node 执行 npm，避免将批处理当作可执行文件。

    Returns:
        list[str]: 用于执行 npm 命令的可执行文件与参数列表。

    Raises:
        RuntimeError: 当缺少 Node.js 或未找到 npm-cli.js 时抛出。
    """
    npm = shutil.which('npm')
    if not npm:
        raise RuntimeError('前端需要构建，请安装 Node.js 22.12+，在 frontend 中运行 npm ci 和 npm run build')
    if os.name != 'nt':
        return [npm]
    node = shutil.which('node')
    candidates = [Path(npm).resolve().parent / 'node_modules/npm/bin/npm-cli.js']
    if node:
        candidates.append(Path(node).resolve().parent / 'node_modules/npm/bin/npm-cli.js')
    for cli in candidates:
        if node and cli.is_file():
            return [node, str(cli)]
    raise RuntimeError('未找到 npm-cli.js，请修复 Node.js 安装后重新启动')


def source_fingerprint(directory):
    """使用内容摘要识别源码变化，避免 Git 检出时间导致重复构建。

    Args:
        directory (Path): 前端工程目录路径。

    Returns:
        str: 前端源文件的 SHA-256 校验和。
    """
    paths = [directory / 'package.json', directory / 'package-lock.json', directory / 'index.html',
             directory / 'vite.config.ts', directory / 'tsconfig.json']
    paths.extend(sorted((directory / 'src').rglob('*')))
    paths.extend(sorted((directory / 'public').rglob('*')))
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _log_process_error(exc, stage='npm'):
    """记录子进程执行失败的输出，对文件占用等常见错误给予友好提示。"""
    from module.logger import logger
    detail = (getattr(exc, 'stderr', None) or getattr(exc, 'stdout', None) or '').strip()
    if detail:
        lines = [line for line in detail.splitlines() if line.strip()]
        summary = '\n'.join(lines[-15:]) if len(lines) > 15 else detail
        logger.warning(f'{stage} 错误输出:\n{summary}')
    retcode = getattr(exc, 'returncode', 0)
    if 'EPERM' in detail or 'EBUSY' in detail or retcode in (4294963248, -4048):
        logger.error('node_modules 中的文件被其他进程占用（如正在运行的 WebUI、Vite 或编辑器）。请先关闭占用进程后重新启动。')


def _install_dependencies(command, directory, flags):
    """优先使用镜像安装，失败或超时后仅用官方源重试一次。

    Args:
        command (list[str]): npm 命令的可执行文件与参数列表。
        directory (Path): 前端工程目录。
        flags (dict): 平台相关的子进程启动参数。

    Raises:
        subprocess.CalledProcessError: 两个源均安装失败时抛出最后一次异常。
        subprocess.TimeoutExpired: 官方源安装超时时抛出。
    """
    from module.logger import logger

    registries = ('https://registry.npmmirror.com', 'https://registry.npmjs.org')
    for index, registry in enumerate(registries):
        logger.info(f'使用 npm 源安装前端依赖: {registry}')
        try:
            subprocess.run(
                [*command, 'ci', '--no-audit', '--no-fund', f'--registry={registry}'],
                cwd=directory, check=True, timeout=600, capture_output=True, text=True,
                encoding='utf-8', errors='replace', **flags,
            )
            return
        except subprocess.CalledProcessError as exc:
            _log_process_error(exc, stage='npm ci')
            if index == len(registries) - 1:
                raise
            logger.warning(f'镜像源安装失败，切换至 npm 官方源重试: {exc}')
        except subprocess.TimeoutExpired:
            if index == len(registries) - 1:
                raise
            logger.warning('镜像源安装超时，切换至 npm 官方源重试')


def ensure_frontend(root=None):
    """缺少或过期时构建前端；已有对应版本的产物不要求安装 Node。

    Args:
        root (str | Path, optional): 项目根目录，默认为当前文件上两级目录。

    Raises:
        RuntimeError: 在 Android 环境缺少预构建产物时抛出。
        subprocess.CalledProcessError: 前端构建命令执行失败时抛出。
        subprocess.TimeoutExpired: 官方源安装或编译超时时抛出。
    """
    from module.logger import logger
    directory = (Path(root) if root else Path(__file__).resolve().parents[1]) / 'frontend'
    marker = directory / 'dist/.source-fingerprint'
    fingerprint = source_fingerprint(directory)
    if (directory / 'dist/index.html').is_file() and marker.is_file() and marker.read_text().strip() == fingerprint:
        return
    if os.environ.get('AZURPILOT_ANDROID') == '1':
        raise RuntimeError('Android 运行包缺少与源码匹配的预构建前端，请安装兼容的 APK')
    command = npm_command()
    logger.info('正在构建 React 前端资源')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
    _install_dependencies(command, directory, flags)
    try:
        subprocess.run(
            [*command, 'run', 'build'],
            cwd=directory, check=True, timeout=180, capture_output=True, text=True,
            encoding='utf-8', errors='replace', **flags,
        )
    except subprocess.CalledProcessError as exc:
        _log_process_error(exc, stage='前端构建')
        raise
    marker.write_text(fingerprint + '\n', encoding='utf-8')


if __name__ == '__main__':
    ensure_frontend()
