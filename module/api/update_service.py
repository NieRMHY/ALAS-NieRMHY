"""全局更新接口：只读 Git 快照、分页历史与后台更新操作。"""
import subprocess
import threading
from threading import Thread
from pathlib import Path

from module.api.protocol import ApiError


class UpdateService:
    def __init__(self, root=None, updater=None):
        self.root = Path(root or Path(__file__).resolve().parents[2])
        self._updater = updater
        self.lock = threading.Lock()
        self.operation = None
        self.error = ''

    @property
    def updater(self):
        if self._updater is None:
            from module.runtime.updater import updater
            self._updater = updater
        return self._updater

    def git(self, *args, optional=False):
        """参数数组避免 shell 解释；错误只返回固定文案。"""
        try:
            result = subprocess.run([self.updater.git, *args], cwd=self.root, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApiError('UPDATE_FAILED', '无法读取 Git 仓库') from exc
        if result.returncode and not optional:
            raise ApiError('UPDATE_FAILED', '无法读取提交记录')
        return result.stdout.strip() if result.returncode == 0 else ''

    def heads(self):
        local = self.git('rev-parse', '--verify', 'HEAD', optional=True)
        upstream = self.git('rev-parse', '--verify', f'refs/remotes/origin/{self.updater.Branch}', optional=True)
        return local, upstream

    def status(self):
        local, upstream = self.heads()
        ahead = behind = 0
        if local and upstream:
            ahead, behind = map(int, self.git('rev-list', '--left-right', '--count', f'{local}...{upstream}').split())
        from module.runtime.setting import State
        state = self.updater.state
        busy = self.operation is not None or state not in (0, 1, 'failed', 'finish') or getattr(self.updater, '_force_update_checking', False)
        visible_state = {0: 'idle', 1: 'available'}.get(state, state)
        if self.operation == 'fetch' or self.operation == 'apply' and state in (0, 1, 'finish'):
            visible_state = self.operation
        return {'state': visible_state,
                'localHead': local or None, 'upstreamHead': upstream or None,
                'branch': self.updater.Branch, 'ahead': ahead, 'behind': behind,
                'available': behind > 0 or state == 1, 'busy': busy, 'error': self.error,
                'canApply': bool(local and upstream and behind and not ahead and not busy
                                 and State.restart_event is not None and State.dependency_sync_event is not None),
                'canCancel': state in ('start', 'wait')}

    def commits(self, offset=0, limit=50):
        """合并本地和上游可达历史，不截断总记录数，保留完整提交正文。"""
        local, upstream = self.heads()
        refs = list(dict.fromkeys(ref for ref in (local, upstream) if ref))
        entries = []
        if refs:
            raw = self.git('log', '--topo-order', f'--skip={offset}', f'--max-count={limit + 1}',
                           '--format=%H%x00%an%x00%aI%x00%B%x00', *refs, '--')
            fields = raw.split('\x00')
            for index in range(0, len(fields) - 3, 4):
                sha, author, date, message = fields[index:index + 4]
                entries.append({'sha': sha.strip(), 'author': author, 'date': date, 'message': message.strip()})
        total = int(self.git('rev-list', '--count', *refs, '--')) if refs else 0
        return {'entries': entries[:limit], 'total': total, 'hasMore': len(entries) > limit,
                'localHead': local or None, 'upstreamHead': upstream or None}

    def start(self, operation):
        """先保留操作槽，再启动线程，避免重复点击与跨连接重复更新。"""
        with self.lock:
            status = self.status()
            if status['busy']:
                raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
            if operation == 'apply' and not status['canApply']:
                raise ApiError('UPDATE_UNAVAILABLE', '当前版本或服务状态不支持更新')
            self.operation, self.error = operation, ''
            try:
                Thread(target=self._run, args=(operation,), daemon=True).start()
            except RuntimeError as exc:
                self.operation = None
                raise ApiError('UPDATE_FAILED', '无法启动更新任务，请重试') from exc
        return {'accepted': True}

    def _run(self, operation):
        owns_check = False
        try:
            if operation == 'fetch':
                # 和旧更新流程共用互斥锁；保留 checking 状态阻止定时检查插入。
                with self.updater._update_lock:
                    if self.updater.state not in (0, 1, 'failed', 'finish'):
                        raise ApiError('UPDATE_BUSY', '更新器正在处理其他操作')
                    self.updater.state = 'checking'
                    owns_check = True
                    self.updater._fetch_with_retry('origin', self.updater.Branch, max_retry=3, delay=1)
                    local, upstream = self.heads()
                    behind = int(self.git('rev-list', '--count', f'{local}..{upstream}')) if local and upstream else 0
                    self.updater.state = bool(behind)
            else:
                if self.updater.state == 'finish':
                    self.updater.state = 0
                if not self.updater.run_update():
                    raise ApiError('UPDATE_FAILED', '更新失败，请检查服务日志')
        except Exception:
            self.error = '获取更新失败，请检查网络或服务日志' if operation == 'fetch' else '更新失败，请检查服务日志'
            if owns_check:
                self.updater.state = 'failed'
        finally:
            with self.lock:
                self.operation = None

    def cancel(self):
        if self.updater.state not in ('start', 'wait'):
            raise ApiError('UPDATE_UNAVAILABLE', '当前更新阶段无法取消')
        self.updater.cancel()
        return {'accepted': True}


update_service = UpdateService()
