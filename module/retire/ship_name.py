"""舰队扫描使用的舰娘名称纠错。"""

import json
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from module.logger import logger


class ShipNameMatcher:
    """用舰船数据中的本服名称匹配船坞 OCR 结果。"""

    DATA_FILE = Path(__file__).parents[2] / "assets" / "ship" / "ship_data.json"

    def __init__(self, language: str) -> None:
        self.names = self._load_names(language)
        self.normalized_names: Dict[str, str] = {}
        for name in self.names:
            self.normalized_names.setdefault(self._normalize(name), name)

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
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"[舰队扫描-OCR] 无法读取舰船名称数据: {exc}")
            return ()

        names = {
            entry.get("name", {}).get(language) or entry.get("name", {}).get("cn")
            for entry in data.values()
            if isinstance(entry, dict)
        }
        return tuple(sorted(name for name in names if isinstance(name, str) and name.strip()))

    def correct(self, value: str) -> str:
        """返回与 OCR 结果相似度最高的本服标准舰娘名。

        Args:
            value (str): OCR 识别出的舰娘名称。

        Returns:
            str: 匹配到的标准舰娘名，若输入为空或无数据则返回去除首尾空格的原名称。
        """
        raw = str(value).strip()
        if not raw or not self.normalized_names:
            return raw

        normalized = self._normalize(raw)
        exact = self.normalized_names.get(normalized)
        if exact:
            return exact

        _, best_name = max(
            (
                SequenceMatcher(None, normalized, candidate, autojunk=False).ratio(),
                name,
            )
            for candidate, name in self.normalized_names.items()
        )
        return best_name
