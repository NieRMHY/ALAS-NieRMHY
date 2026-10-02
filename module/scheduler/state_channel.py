"""worker 调度状态专用队列，读取端不触碰设备。"""
import copy
import queue

_output = None
_run_id = None


def initialize(output, run_id):
    global _output, _run_id
    _output, _run_id = output, run_id


def publish(state):
    if _output is None:
        return
    message = {'runId': _run_id, 'state': copy.deepcopy(state)}
    try:
        _output.put_nowait(message)
    except queue.Full:
        try:
            _output.get_nowait()
            _output.put_nowait(message)
        except (queue.Empty, queue.Full, EOFError, OSError):
            pass
    except (EOFError, OSError):
        # WebUI 退出后游戏 worker 仍可完成当前任务。
        pass
