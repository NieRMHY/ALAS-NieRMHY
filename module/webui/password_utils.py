"""WebUI 密码策略的纯标准库实现。

WebUI 与独立运行的 MCP 服务共用同一套密码规则（同一个 `--key` /
`deploy.yaml Password`）。这里刻意只依赖标准库，不经过
``module.webui.app_dependencies``——后者会连带加载 pywebio 与
``module.ocr.rpc``，而独立 MCP 进程只需要一个密码策略，不该吃下整条
WebUI/OCR 依赖链。
"""

import os
import string
from secrets import SystemRandom, choice

#: 自动生成密码的落盘文件（相对工作目录）
WEBUI_AUTO_PASSWORD_FILE = "password.txt"


def is_demo_mode():
    """
    判断是否处于演示环境。

    Returns:
        bool: True 表示 DEMO=1。
    """
    return os.environ.get("DEMO") == "1"


def is_public_webui_host(host):
    """
    判断监听地址是否对所有网络接口开放。

    Args:
        host (str): 监听地址。

    Returns:
        bool: True 表示允许所有设备访问。
    """
    host = str(host or "").strip().lower()
    return host in ("0.0.0.0", "::", "[::]")


def is_webui_password_set(password):
    """
    判断密码是否有效设置。

    Args:
        password: 密码配置。

    Returns:
        bool: True 表示密码包含非空白字符。
    """
    return bool(str(password or "").strip())


def generate_webui_password(length=32):
    """
    生成包含大小写字母和数字的随机密码。

    Args:
        length (int): 密码长度。

    Returns:
        str: 随机密码。
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


def ensure_password_for_host(key, host, demo=False):
    """
    监听公网且未设置密码时生成随机密码并写入 ``password.txt``。

    只负责生成与落盘；是否把密码回写部署配置、如何记录日志由调用方决定，
    这样 WebUI 与独立 MCP 能共享同一份密码策略。

    Args:
        key: 已有的密码，可能为 None。
        host (str): 监听地址。
        demo (bool): 是否处于演示环境，演示环境不生成密码。

    Returns:
        str | None: 有效密码，未设置且无需生成时原样返回 key。

    Raises:
        Exception: 生成或写入失败时向上抛出，由调用方记录。
    """
    if demo or not is_public_webui_host(host) or is_webui_password_set(key):
        return key

    password = generate_webui_password()
    from deploy.atomic import atomic_write

    atomic_write(WEBUI_AUTO_PASSWORD_FILE, f"{password}\n")
    return password
