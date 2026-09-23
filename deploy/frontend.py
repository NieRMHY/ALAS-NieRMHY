"""构建本地 React 静态资源，取代旧桌面应用更新步骤。"""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def npm_command():
    """Windows 直接使用 Node 执行 npm，避免将批处理当作可执行文件。"""
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
    """使用内容摘要识别源码变化，避免 Git 检出时间导致重复构建。"""
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


def ensure_frontend(root=None):
    """缺少或过期时构建前端；已有对应版本的产物不要求安装 Node。"""
    from module.logger import logger
    directory = (Path(root) if root else Path(__file__).resolve().parents[1]) / 'frontend'
    marker = directory / 'dist/.source-fingerprint'
    fingerprint = source_fingerprint(directory)
    if (directory / 'dist/index.html').is_file() and marker.is_file() and marker.read_text().strip() == fingerprint:
        return
    command = npm_command()
    logger.info('正在构建 React 前端资源')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, 'CREATE_NO_WINDOW') else {}
    subprocess.run([*command, 'ci', '--no-audit', '--no-fund'], cwd=directory, check=True, timeout=600, **flags)
    subprocess.run([*command, 'run', 'build'], cwd=directory, check=True, timeout=180, **flags)
    marker.write_text(fingerprint + '\n', encoding='utf-8')


if __name__ == '__main__':
    ensure_frontend()
