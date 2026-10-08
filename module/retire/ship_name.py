"""舰队扫描使用的舰娘名称纠错。"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from module.logger import logger


class ShipNameMatcher:
    """用舰船数据中的本服名称匹配船坞 OCR 结果。"""

    DATA_FILE = Path(__file__).parents[2] / "assets" / "ship" / "ship_names.json"

    def __init__(self, language: str) -> None:
        self.names = self._load_names(language)
        self.normalized_names: Dict[str, set[str]] = {}
        for name in self.names:
            self.normalized_names.setdefault(self._normalize(name), set()).add(name)

    @staticmethod
    def _normalize(name: str) -> str:
        """对舰船名称进行 NFKC 规范化并移除空白字符后转换为小写。

        Args:
            name (str): 待规范化的舰船名称。

        Returns:
            str: 规范化后的字符串。
        """
        return "".join(unicodedata.normalize("NFKC", name).split()).casefold()

    @classmethod
    @lru_cache(maxsize=4)
    def _load_names(cls, language: str) -> Tuple[str, ...]:
        """从舰船数据文件中加载指定语言的舰船名称集合。

        Args:
            language (str): 语言代码（如 'cn', 'jp', 'en', 'tw'）。

        Returns:
            Tuple[str, ...]: 排序后的舰船标准名称元组。
        """
        try:
            data = json.loads(cls.DATA_FILE.read_text(encoding="utf-8"))
            names = data.get(language) if isinstance(data, dict) else None
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise ValueError(f'缺少有效的 {language} 舰船名称名单')
        except (OSError, ValueError) as exc:
            logger.warning(f"[舰队扫描-OCR] 无法读取舰船名称数据: {exc}")
            return ()

        return tuple(sorted({name.strip() for name in names if name.strip()}))

    def exact(self, value: str):
        """只接受唯一的精确规范化匹配，不跨服回退或模糊猜名。"""
        raw = str(value).strip()
        if raw in self.names:
            return raw
        candidates = self.normalized_names.get(self._normalize(raw), set())
        return next(iter(candidates)) if len(candidates) == 1 else None

    def resolve(self, value: str) -> Tuple[str, str]:
        """返回名称与依据；省略号必须是游戏明确显示的尾部截断标记。"""
        raw = str(value).strip()
        if not raw:
            return raw, 'empty'
        if not self.names:
            return raw, 'missing_catalog'
        exact = self.exact(raw)
        if exact is not None:
            return exact, 'exact'
        match = re.search(r'(?:\.{2,}|…+|⋯+)$', raw)
        if match:
            prefix = self._normalize(raw[:match.start()])
            # 单字符截断无法提供足够身份信息。
            if len(prefix) >= 2:
                candidates = {name for key, names in self.normalized_names.items()
                              if key.startswith(prefix) for name in names}
                if len(candidates) == 1:
                    return next(iter(candidates)), 'prefix'
                if len(candidates) > 1:
                    return raw, 'ambiguous'
        return raw, 'unconfirmed'

    def correct(self, value: str) -> str:
        """仅接受精确匹配或唯一截断补全，否则保留 OCR 原文。

        Args:
            value (str): OCR 识别出的舰娘名称。

        Returns:
            str: 匹配到的标准舰娘名，若输入为空或无数据则返回去除首尾空格的原名称。
        """
        return self.resolve(value)[0]

    def retry_candidate(self, raw: str, retry: str):
        """彩色复识别须精确命中，且保留首轮可读前缀，不能换成另一个身份。"""
        candidate = self.exact(retry)
        if candidate is None:
            return None
        name, status = self.resolve(raw)
        if status in ('exact', 'prefix'):
            return candidate if candidate == name else None
        prefix = re.sub(r'(?:\.{2,}|…+|⋯+)$', '', str(raw).strip())
        if not prefix or self._normalize(candidate).startswith(self._normalize(prefix)):
            return candidate
        return None
