"""CI 导入冒烟测试：入口点导入与进程隔离守卫。

覆盖两类检查：

1. **入口点导入**：`alas` / `gui` / `mcp_server_sse` / `module.ocr.al_ocr`
   在独立子进程中必须可导入。入口点导入失败说明运行时代码损坏。

2. **进程隔离守卫**：WebUI 进程（挂载 mcp_server_sse 的进程）不得加载 OCR
   相关模块（`module.ocr.al_ocr` / `rapidocr`）。
   React API 与 OCR 分属不同进程，模型只在实际需要推理的工作进程中加载。
   旧的伪 PIL 注入已移除，本测试继续守护轻量服务进程的依赖边界。

所有检查都在子进程中执行，避免 import 副作用污染测试运行器本身。
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _run_py(code: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """在独立子进程中执行代码，隔离 import 副作用。"""
    env = {**os.environ, "AZURPILOT_NTP_DISABLE": "1", "PYTHONUTF8": "1"}
    return subprocess.run(
        [PYTHON, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        cwd=REPO_ROOT,
    )


class TestEntryPointImports(unittest.TestCase):
    """各入口点必须在独立进程内可导入。"""

    def _assert_import_ok(self, module: str):
        proc = _run_py(f"import {module}")
        self.assertEqual(
            proc.returncode, 0,
            f"模块 {module} 导入失败：{proc.stderr[-500:]}",
        )

    def test_alas_imports(self):
        self._assert_import_ok("alas")

    def test_gui_imports(self):
        self._assert_import_ok("gui")

    def test_mcp_server_sse_imports(self):
        self._assert_import_ok("mcp_server_sse")

    def test_al_ocr_imports_alone(self):
        # 单独导入 al_ocr 必须成功（真实损坏时会在此暴露）。
        self._assert_import_ok("module.ocr.al_ocr")


class TestProcessIsolation(unittest.TestCase):
    """WebUI/MCP 进程与 OCR 的进程隔离守卫。"""

    def test_mcp_server_sse_does_not_load_ocr(self):
        # 独立 MCP 只需要运行服务和认证，不应加载界面或 OCR 模型。
        code = (
            "import sys\n"
            "import mcp_server_sse\n"
            "assert 'pywebio' not in sys.modules, '不得加载已移除的界面依赖'\n"
            "assert 'module.ocr.al_ocr' not in sys.modules, 'OCR 不得加载进独立 MCP 进程'\n"
            "assert 'rapidocr' not in sys.modules, 'rapidocr 不得加载进独立 MCP 进程'\n"
        )
        proc = _run_py(code)
        self.assertEqual(
            proc.returncode, 0,
            f"独立 MCP 进程隔离被破坏：{proc.stderr[-500:]}",
        )

    def test_webui_app_does_not_load_ocr(self):
        # 创建完整 WebUI app（挂载 mcp_server_sse）后，
        # module.ocr.al_ocr / rapidocr 不得被加载进同一进程。
        code = (
            "import sys\n"
            "from module.api import app as webui_app\n"
            "application = webui_app.create_app(password='', manage_runtime=False)\n"
            "assert 'mcp_server_sse' in sys.modules, 'mcp_server_sse 应已加载'\n"
            "assert 'module.ocr.al_ocr' not in sys.modules, 'OCR 不得加载进 WebUI 进程'\n"
            "assert 'rapidocr' not in sys.modules, 'rapidocr 不得加载进 WebUI 进程'\n"
        )
        proc = _run_py(code)
        self.assertEqual(
            proc.returncode, 0,
            f"WebUI 进程隔离被破坏：{proc.stderr[-500:]}",
        )


if __name__ == "__main__":
    unittest.main()
