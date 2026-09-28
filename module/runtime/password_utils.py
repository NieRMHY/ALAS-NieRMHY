"""API 和独立 MCP 服务共用的密码策略，不依赖界面或 OCR。"""

import os
import string
from secrets import SystemRandom, choice
from urllib.parse import urlsplit

#: 自动生成密码的落盘文件（相对工作目录）
WEBUI_AUTO_PASSWORD_FILE = "password.txt"

#: 视为本机的地址
LOCAL_HOSTS = frozenset(("127.0.0.1", "::1", "localhost"))

#: 远程访问隧道转发请求时注入的标记头，命中即视为非本机连接
REMOTE_ACCESS_HEADER = "x-azurpilot-remote-access"


def is_demo_mode() -> bool:
    """判断是否处于演示环境。

    Returns:
        bool: 环境变量 DEMO 为 '1' 时返回 True，否则返回 False。
    """
    return os.environ.get("DEMO") == "1"


def is_public_webui_host(host: str) -> bool:
    """判断监听地址是否对所有网络接口开放。

    Args:
        host: 监听地址字符串。

    Returns:
        bool: 允许所有外部设备访问返回 True，否则返回 False。
    """
    host = str(host or "").strip().lower()
    return host in ("0.0.0.0", "::", "[::]")


def is_webui_password_set(password: str) -> bool:
    """判断密码是否有效设置。

    Args:
        password: 密码配置字符串。

    Returns:
        bool: 包含有效非空白字符返回 True，否则返回 False。
    """
    return bool(str(password or "").strip())


def generate_webui_password(length: int = 32) -> str:
    """生成包含大小写字母和数字的高强度随机密码。

    Args:
        length: 密码长度，默认为 32 位。

    Returns:
        str: 生成的随机密码字符串。
    """
    letters_upper = string.ascii_uppercase
    letters_lower = string.ascii_lowercase
    digits = string.digits
    alphabet = letters_upper + letters_lower + digits
    password = [
        choice(letters_upper),
        choice(letters_lower),
        choice(digits),
    ]
    password.extend(choice(alphabet) for _ in range(length - len(password)))
    SystemRandom().shuffle(password)
    return "".join(password)


def ensure_password_for_host(key: str | None, host: str, demo: bool = False) -> str | None:
    """监听公网且未设置密码时自动生成随机密码并写入文件。

    只负责生成与落盘；是否把密码回写部署配置、如何记录日志由调用方决定，
    这样 WebUI 与独立 MCP 能共享同一份密码策略。

    Args:
        key: 已有的密码配置，可能为 None。
        host: 监听地址字符串。
        demo: 是否处于演示环境，演示环境不生成密码。

    Returns:
        str | None: 有效密码；未设置且无需生成时原样返回 key。

    Raises:
        Exception: 密码生成或原子写入失败。
    """
    if demo or not is_public_webui_host(host) or is_webui_password_set(key):
        return key

    password = generate_webui_password()
    from deploy.atomic import atomic_write

    atomic_write(WEBUI_AUTO_PASSWORD_FILE, f"{password}\n")
    return password


def host_name(value: str) -> str:
    """从 Host 头、Origin 或来源地址中提取纯主机名。

    去掉协议、端口与 IPv6 方括号，统一转换为小写主机名，便于与 ``LOCAL_HOSTS`` 比较。

    Args:
        value: Host 头、Origin 头或来源地址，可能为空。

    Returns:
        str: 提取出的小写主机名；无法解析时返回空字符串。
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        return urlsplit(text).hostname or ""
    if text.startswith("["):
        return text[1:].split("]", maxsplit=1)[0]
    if text.count(":") > 1:
        # 裸 IPv6 地址：冒号是地址本身的一部分，不是端口分隔符
        return text
    return text.split(":", maxsplit=1)[0]


def is_local_client(client_host: str, header_host: str, origin: str = None, remote_access: str = None) -> bool:
    """判断连接是否来自本机直连访问。

    本机访问不需要密码。密码保护的是局域网与远程访问隧道的入口，而本机上的
    任何进程本来就能读到配置文件里的明文密码，要求本机用户输密码属于冗余操作。
    判定同时要求来源地址与 Host 头都是本机地址，并且 Origin 也指向本机，
    避免外部网页脚本借本机地址绕过登录。

    Args:
        client_host: 连接来源主机/IP 地址。
        header_host: 请求的 Host 头。
        origin: 可选的浏览器 Origin 头。
        remote_access: 可选的远程访问隧道标记头，非空表示请求经隧道转发。

    Returns:
        bool: 连接来自本机且未走隧道返回 True，否则返回 False。
    """
    if remote_access:
        return False
    if host_name(client_host) not in LOCAL_HOSTS:
        return False
    if host_name(header_host) not in LOCAL_HOSTS:
        return False
    if origin and host_name(origin) not in LOCAL_HOSTS:
        return False
    return True
