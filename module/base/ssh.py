"""SSH 客户端公共工具。"""

from pathlib import Path
from subprocess import DEVNULL, PIPE, run

from module.logger import logger


def _get_known_hosts_files(ssh_executable: str, host: str, port: int) -> list[Path]:
    """查询指定 SSH 可执行文件对目标主机实际使用的主机指纹文件。

    Args:
        ssh_executable (str): SSH 可执行文件路径或命令名称。
        host (str): 目标主机名或 IP。
        port (int): 目标端口。

    Returns:
        list[Path]: 对应已知主机文件路径列表。
    """
    try:
        result = run(
            [ssh_executable, "-G", "-p", str(port), host],
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            check=False,
            text=True,
        )
    except FileNotFoundError:
        logger.warning(f"找不到 SSH 可执行文件，无法查询主机指纹路径：{ssh_executable}")
        return []

    if result.returncode:
        logger.warning(f"查询 SSH 主机指纹路径失败：{result.stderr.strip()}")
        return []

    files = []
    for line in result.stdout.splitlines():
        name, _, value = line.partition(" ")
        if name != "userknownhostsfile":
            continue
        for path in value.split():
            if path.lower() in ("none", "nul", "/dev/null"):
                continue
            file = Path(path).expanduser()
            if file not in files:
                files.append(file)
    return files


def clear_ssh_host_key(host: str, port: int, ssh_executable: str = "ssh") -> bool:
    """仅删除本次连接目标在 SSH 实际使用的主机指纹文件中的记录。

    Args:
        host (str): 目标主机名或 IP。
        port (int): 目标端口。
        ssh_executable (str): SSH 可执行文件命令。默认为 "ssh"。

    Returns:
        bool: 是否成功执行了指纹清理。
    """
    host = str(host or "").rsplit("@", 1)[-1].strip("[]")
    if not host:
        return False

    try:
        port = int(port)
    except (TypeError, ValueError):
        logger.warning(f"SSH 端口无效，跳过清理主机指纹：{host}:{port}")
        return False

    targets = [f"[{host}]:{port}"]
    if port == 22:
        targets.insert(0, host)

    known_hosts_files = _get_known_hosts_files(ssh_executable, host, port)
    if not known_hosts_files:
        return False

    removed = False
    for known_hosts in known_hosts_files:
        if not known_hosts.is_file():
            continue
        for target in targets:
            try:
                result = run(
                    ["ssh-keygen", "-R", target, "-f", str(known_hosts)],
                    stdin=DEVNULL,
                    stdout=PIPE,
                    stderr=PIPE,
                    check=False,
                    text=True,
                )
            except FileNotFoundError:
                logger.warning(f"找不到 ssh-keygen，无法清理 SSH 主机指纹：{target}")
                return removed

            if result.returncode == 0:
                logger.info(f"已清理 SSH 主机指纹：{target}（{known_hosts}）")
                removed = True
            elif result.returncode != 1:
                logger.warning(f"清理 SSH 主机指纹失败：{target}，{result.stderr.strip()}")

    return removed
