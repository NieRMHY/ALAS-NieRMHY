"""requirements 依赖更新脚本（已废弃）。

项目已迁移至 uv 项目管理模式，不再维护 requirements*.txt。
请直接编辑 pyproject.toml 并使用 `uv lock` 刷新锁文件。
"""

raise SystemExit(
    "requirements*.txt are no longer used. "
    "Edit pyproject.toml and refresh uv.lock with `uv lock` instead."
)
