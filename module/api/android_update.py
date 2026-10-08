"""Android 宿主热更新服务：浅 git 更新源码 + 宿主发布的预构建前端。

恢复链全部复用内置更新器的文件协议（reloadalas / webui-dependency-sync-pending /
restart_event），实例的优雅停止、依赖同步与重启由父监督器接管；本服务只负责
"取代码 + 取匹配的 dist + 改写 BUILD_MANIFEST"这三件运行时做不到的事。

前端永不本地编译：应用前先探测宿主渠道（AZURPILOT_ANDROID_DIST_BASE）是否已
发布目标提交的 dist 资产，未发布则视作暂不可更新，从源头规避源码与 dist 失配
导致的启动崩溃（CI 未编译完 / 断网时保持旧版本，下次再试）。
"""
import json
import subprocess
import threading
import time
from pathlib import Path

from deploy.atomic import atomic_write
from deploy import frontend as frontend_deploy
from module.api.protocol import ApiError
from module.logger import logger

STATE_FILE = './config/android-update-state.json'
_LS_REMOTE_TTL = 60
_DIST_PROBE_TTL = 60


class AndroidUpdateService:
    """安卓宿主热更新控制器。

    Attributes:
        root: 代码仓库根目录路径。
        lock: 串行化 apply 的互斥锁。
        _ls_remote_cache: (时间戳, 上游提交哈希) 的短缓存。
        _dist_probe_cache: (时间戳, 是否存在 dist) 的短缓存。
    """

    def __init__(self, root=None, updater=None):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self._updater = updater
        self.lock = threading.Lock()
        self._ls_remote_cache = None
        self._dist_probe_cache = None

    @property
    def updater(self):
        """获取底层更新器单例（复用其 git 路径、UA、仓库与分支配置）。"""
        if self._updater is None:
            from module.runtime.updater import updater
            self._updater = updater
        return self._updater

    # ---------- 状态与探测 ----------

    def _read_state(self) -> dict:
        try:
            return json.loads((self.root / STATE_FILE).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def _write_state(self, state: dict) -> None:
        atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False) + '\n')

    def _git(self, *args, timeout=900):
        """以随机 UA 执行 git 命令，返回 (returncode, stdout, stderr)。"""
        command = [self.updater.git, '-c', f'http.userAgent={self.updater.git_user_agent()}', *args]
        try:
            result = subprocess.run(command, cwd=self.root, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, '', f'{type(exc).__name__}: {exc}'
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def upstream_head(self, force=False) -> str:
        """ls-remote 直取上游分支头（秒级，无需本地对象）；失败返回空串。"""
        cached = self._ls_remote_cache
        if not force and cached and time.monotonic() - cached[0] < _LS_REMOTE_TTL:
            return cached[1]
        code, out, _ = self._git('ls-remote', self.updater.Repository, self.updater.Branch, timeout=30)
        head = out.split()[0] if code == 0 and out else ''
        self._ls_remote_cache = (time.monotonic(), head)
        return head

    def dist_ready(self, commit, force=False) -> bool:
        """探测宿主渠道是否已发布该提交的预构建 dist（带短缓存）。"""
        cached = self._dist_probe_cache
        if not force and cached and cached[1] == commit and time.monotonic() - cached[0] < _DIST_PROBE_TTL:
            return cached[2]
        ready = frontend_deploy.android_dist_ready(commit, self.root)
        self._dist_probe_cache = (time.monotonic(), commit, ready)
        return ready

    def status(self) -> dict:
        """汇总热更状态，供宿主轮询。

        Returns:
            dict: 含当前/上游提交、是否可应用、忙闲、阶段与错误等。
        """
        manifest = frontend_deploy.android_manifest(self.root)
        commit = manifest.get('azurpilot_commit')
        state = self._read_state()
        running = state.get('phase') not in (None, 'done')
        base_ready = bool(frontend_deploy.android_dist_base())
        upstream = self.upstream_head() if base_ready else ''
        dist_ready = self.dist_ready(upstream) if upstream else False
        return {
            'enabled': base_ready,
            'localHead': commit,
            'upstreamHead': upstream or None,
            'available': bool(base_ready and upstream and commit and upstream != commit and dist_ready),
            'distReady': dist_ready,
            'busy': running,
            'phase': state.get('phase'),
            'target': state.get('target'),
            'error': state.get('error', ''),
            'updatedAt': state.get('updatedAt'),
        }

    # ---------- 更新事务 ----------

    def apply(self) -> dict:
        """启动后台热更新线程（先做全部前置探测，失败即拒绝）。"""
        if self.updater_state_locked():
            raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
        status = self.status()
        if not status['enabled']:
            raise ApiError('UPDATE_MANAGED_BY_ANDROID', '宿主未注入预构建前端下载地址')
        if status['busy']:
            raise ApiError('UPDATE_BUSY', '热更新正在进行中')
        if not status['upstreamHead']:
            raise ApiError('UPDATE_FAILED', '无法获取上游最新提交，请检查网络')
        if status['localHead'] and status['upstreamHead'] == status['localHead']:
            raise ApiError('UPDATE_UNAVAILABLE', '已是最新版本')
        if not status['distReady']:
            raise ApiError('UPDATE_UNAVAILABLE', '该版本的预构建前端尚未发布，请稍后再试')

        with self.lock:
            state = self._read_state()
            if state.get('phase') not in (None, 'done'):
                raise ApiError('UPDATE_BUSY', '热更新正在进行中')
            self._write_state({'phase': 'git', 'target': status['upstreamHead'],
                               'error': '', 'updatedAt': _now()})
            try:
                thread = threading.Thread(target=self._run, args=(status['upstreamHead'],), daemon=True)
                thread.start()
            except RuntimeError as exc:
                self._write_state({'phase': 'done', 'error': '无法启动更新任务', 'updatedAt': _now()})
                raise ApiError('UPDATE_FAILED', '无法启动更新任务，请重试') from exc
        return {'accepted': True, 'target': status['upstreamHead']}

    def updater_state_locked(self) -> bool:
        """内置更新器是否处于不可打扰的状态。"""
        from module.runtime.updater import updater
        return updater.state not in (0, 1, 'failed', 'finish')

    def _phase(self, phase: str) -> None:
        self._write_state({'phase': phase, 'target': self._current_target(),
                           'error': '', 'updatedAt': _now()})

    def _current_target(self):
        return self._read_state().get('target')

    def _git_shallow_reset(self, target: str) -> None:
        """浅拉上游分支并硬重置到目标提交；rootfs 出厂无 .git，首次自动初始化。"""
        logger.hr('[Android-热更] 浅拉源码')
        for lock_file in ('.git/index.lock', '.git/HEAD.lock'):
            path = self.root / lock_file
            if path.exists():
                path.unlink()
        if not (self.root / '.git').exists():
            code, _, err = self._git('init')
            if code:
                raise RuntimeError(f'git init 失败: {err}')
        code, _, err = self._git('remote', 'add', 'origin', self.updater.Repository)
        if code and 'already exists' not in err:
            code, _, err = self._git('remote', 'set-url', 'origin', self.updater.Repository)
        if code:
            raise RuntimeError(f'git remote 配置失败: {err}')
        code, _, err = self._git('fetch', '--depth', '1', '--progress', 'origin',
                                 self.updater.Branch, timeout=1800)
        if code:
            raise RuntimeError(f'git fetch 失败: {err[-400:]}')
        code, head, err = self._git('rev-parse', 'FETCH_HEAD')
        if code or not head:
            raise RuntimeError(f'git rev-parse 失败: {err}')
        if head != target:
            # 检查后上游又前进了：按确切提交补拉一次（GitHub/gitcode 均支持按哈希取包）
            code, _, err = self._git('fetch', '--depth', '1', 'origin', target, timeout=1800)
            if code:
                raise RuntimeError(f'上游已前进且按提交拉取失败: {err[-400:]}')
            head = target
        code, _, err = self._git('reset', '--hard', target)
        if code:
            raise RuntimeError(f'git reset 失败: {err[-400:]}')
        logger.info(f'[Android-热更] 源码已重置到 {target[:12]}')

    def _update_manifest(self, target: str) -> None:
        """热更成功后改写 BUILD_MANIFEST 的版本字段（rootfs_version 不动，
        宿主据此区分"仅源码热更"与"需要整包重部署的基础镜像变更"）。"""
        import hashlib
        import datetime

        manifest = frontend_deploy.android_manifest(self.root)
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        manifest['azurpilot_commit'] = target
        manifest['frontend_sha256'] = sha(self.root / 'frontend' / 'dist' / 'index.html')
        manifest['uv_lock_sha256'] = sha(self.root / 'uv.lock')
        manifest['built_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (self.root / 'BUILD_MANIFEST').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    def _run(self, target: str):
        """热更工作线程：恢复计划先行落盘，随后 git → dist → manifest → 重载。

        恢复协议与内置更新器一致：reloadalas 记录更新前运行中的实例，父监督器
        重启 WebUI 后由 startup() 自动拉起；依赖同步标记交父监督器在启动前完成。
        任一步失败都照常触发重载（源码已在失败点回滚），实例在旧版本上恢复。
        """
        from module.runtime.setting import State, mark_dependency_sync_pending
        from module.runtime.startup_memory import mark_update_restart

        instances = []
        try:
            from module.runtime.process_manager import ProcessManager
            instances = ProcessManager.running_instances()
            names = [alas.config_name + '\n' for alas in instances]
            # 恢复计划先落盘：一旦开始动源码，实例只能由父监督器在重启后恢复
            mark_dependency_sync_pending()
            atomic_write('./config/reloadalas', ''.join(names))

            old_commit = frontend_deploy.android_manifest(self.root).get('azurpilot_commit')
            self._phase('git')
            self._git_shallow_reset(target)
            self._phase('dist')
            try:
                frontend_deploy._android_fetch_dist(self.root / 'frontend', self.root)
            except Exception:
                # dist 拉取失败必须回滚源码：旧 dist 未动，回滚后指纹重新匹配
                if old_commit:
                    logger.warning('[Android-热更] dist 拉取失败，回滚源码到旧版本')
                    self._git('reset', '--hard', old_commit)
                raise
            self._phase('manifest')
            self._update_manifest(target)

            self._phase('reload')
            with State.restart_lock:
                if State._restart_requested:
                    raise RuntimeError('WebUI 已请求重启')
                if State.restart_event is None or State.dependency_sync_event is None:
                    raise RuntimeError('父监督器不可用，无法安全重启')
                State._restart_requested = True
                State.dependency_sync_event.set()
                from module.api.lifecycle import clearup
                clearup()
                mark_update_restart()
                State.restart_event.set()
            self._write_state({'phase': 'done', 'result': 'updated', 'target': target,
                               'error': '', 'updatedAt': _now()})
            logger.hr(f'[Android-热更] 完成，重载至 {target[:12]}')
        except Exception as exc:
            logger.exception('[Android-热更] 失败')
            self._write_state({'phase': 'done', 'result': 'failed', 'target': target,
                               'error': str(exc)[:300], 'updatedAt': _now()})
            # 与内置更新器的失败路径一致：照常触发重载，实例在旧代码上恢复
            try:
                with State.restart_lock:
                    if not State._restart_requested and State.restart_event is not None:
                        State._restart_requested = True
                        State.dependency_sync_event.set()
                        from module.api.lifecycle import clearup
                        clearup()
                        mark_update_restart()
                        State.restart_event.set()
            except Exception:
                logger.exception('[Android-热更] 失败后的重载也失败，实例保持停止')


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


android_update_service = AndroidUpdateService()
