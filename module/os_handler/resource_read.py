"""在固定截图上后台识别货币；游戏操作和结果验收留在主线程。"""

from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from module.ocr.ocr import ocr_batch


class CoinReplenishRequired(Exception):
    """已确认黄币不足，需要返回调度决策而非恢复设备。"""


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='OpsiResourceOcr')


@dataclass(frozen=True)
class CoinReading:
    identity: tuple
    observed_at: datetime
    yellow: int
    valid: bool
    ap: int | None = None
    ap_epoch: int = 0
    ap_spent: int = 0
    sampled_at: float = 0


def read_coins(image, readers, identity, observed_at, ap_epoch=0, ap_spent=0, sampled_at=0):
    # Digit.last_valid 与按钮偏移是可变状态，后台不能复用前台识别器对象。
    readers = [copy(reader) for reader in readers]
    for reader in readers:
        reader.buttons = tuple(reader.buttons[0])
    values = ocr_batch(image, readers, show_log=False)
    # 地图只显示黄币；商店紫币区域在地图上是舰队信息，不能参与确认或写库。
    yellow = values[0]
    valid = yellow >= 0 and bool(getattr(readers[0], 'last_valid', False))
    ap = (int(values[1]) if len(values) == 2 and bool(getattr(readers[1], 'last_valid', False))
          and 0 <= values[1] <= 600 else None)
    return CoinReading(identity, observed_at, int(yellow), valid,
                       ap, ap_epoch, ap_spent, sampled_at)


class BackgroundCoinRead:
    """每个运行器最多一个待识别帧；连续两张地图截图同值才接受。"""

    def __init__(self):
        self.future = None
        self.candidate = None
        self.accepted = None
        self.frame = None
        self.last_result = None
        self.wanted = True
        self.not_before = 0

    def invalidate(self):
        """画面变化或同步确认后丢弃旧观察，保留在途任务以限制队列长度。"""
        self.not_before = monotonic()
        self.candidate = self.accepted = self.last_result = None
        self.wanted = True

    def request(self):
        """每轮只采集一次稳定观察，避免高频地图帧堆积持久化队列。"""
        if not self.wanted:
            self.candidate = None
        self.wanted = True

    def poll(self, identity):
        if self.future is None or not self.future.done():
            return None
        future, self.future = self.future, None
        result = future.result()
        current = result.identity == identity and result.sampled_at >= self.not_before
        self.last_result = result if current else None
        if not result.valid or not current:
            self.candidate = None
            return None
        previous, self.candidate = self.candidate, result
        if (previous is None or previous.identity != identity
                or previous.yellow != result.yellow):
            return None
        self.accepted = result
        self.wanted = False
        return result

    def submit(self, image, readers, identity, *, ap_epoch=0, ap_spent=0):
        if self.future is not None or image is self.frame or (not self.wanted and len(readers) < 2):
            return
        # 保持原图引用以防对象 ID 被重复利用；后台只使用私有副本。
        self.frame = image
        readers = [copy(reader) for reader in readers]
        for reader in readers:
            reader.buttons = tuple(reader.buttons[0])
        self.future = _executor.submit(read_coins, image.copy(), readers, identity, datetime.now(),
                                       ap_epoch, ap_spent, monotonic())
