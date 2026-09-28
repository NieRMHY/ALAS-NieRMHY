import unittest
from unittest.mock import Mock, patch

from gui import (
    EXIT_DEPENDENCY_SYNC_FAILURE,
    EXIT_FRONTEND_BUILD_FAILURE,
    EXIT_STARTUP_FAILURE,
    EXIT_WORKER_CLEANUP_FAILURE,
    run_webui_supervisor,
)


class TestSupervisorExitCode(unittest.TestCase):
    """启动失败必须以对应的具体非零退出码结束。"""

    def test_orphan_recovery_failure_returns_failure_code(self):
        with patch("gui._recover_orphaned_workers", return_value=False):
            self.assertEqual(run_webui_supervisor(), EXIT_WORKER_CLEANUP_FAILURE)

    def test_frontend_build_failure_returns_failure_code(self):
        with patch("gui._recover_orphaned_workers", return_value=True), patch(
            "gui._prepare_dependency_sync_before_webui_start",
            return_value=(True, None, None, None),
        ), patch("deploy.frontend.ensure_frontend", side_effect=RuntimeError("npm 不可用")):
            self.assertEqual(run_webui_supervisor(), EXIT_FRONTEND_BUILD_FAILURE)

    def test_dependency_sync_not_ready_returns_failure_code(self):
        with patch("gui._recover_orphaned_workers", return_value=True), patch(
            "gui._prepare_dependency_sync_before_webui_start",
            return_value=(False, None, None, None),
        ):
            self.assertEqual(run_webui_supervisor(), EXIT_DEPENDENCY_SYNC_FAILURE)

    def test_keyboard_interrupt_returns_success_code(self):
        process = Mock()
        process.pid = 4242
        with patch("gui._recover_orphaned_workers", return_value=True), patch(
            "gui._prepare_dependency_sync_before_webui_start",
            return_value=(True, None, None, None),
        ), patch("deploy.frontend.ensure_frontend"), patch(
            "gui.Process", return_value=process
        ), patch("gui._wait_for_webui_ready", side_effect=KeyboardInterrupt), patch(
            "gui._stop_webui_process_tree", return_value=True
        ):
            self.assertEqual(run_webui_supervisor(), 0)


if __name__ == "__main__":
    unittest.main()
