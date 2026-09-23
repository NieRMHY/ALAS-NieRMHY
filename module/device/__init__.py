"""设备包初始化：在第三方设备依赖加载前安装 pkg_resources 兼容层。

adbutils / uiautomator2 的部分导入路径仍依赖 pkg_resources，而 Python 3.14
环境不再保证它随 setuptools 可用。项目已经提供轻量兼容实现；在包初始化
阶段加载，可确保直接导入任意 module.device.* 子模块时也先注册该兼容层。
"""

from module.device.pkg_resources import get_distribution

# 导入 module.device.pkg_resources 会把兼容实现注册为顶层 pkg_resources。
# 保留显式引用，也与 Device 主入口原有的防导入优化写法保持一致。
_ = get_distribution
