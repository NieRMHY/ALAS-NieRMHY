# 此文件专门用于统计分析大世界（Operation Siren）的月度练级效率与资源投入数据。
# 负责从加密 SQLite 数据库中读取统计数据，并具备计算概况与详细指标的功能。
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

from module.logger import logger
from module.statistics.cl1_database import db as cl1_db


class OpsiMonthStats:
    def __init__(self, instance_name: str | None = None) -> None:
        self._instance_name = instance_name or "default"
    
    def summary(self, year: int | None = None, month: int | None = None) -> Dict[str, Any]:
        now = datetime.now()
        if year is None:
            year = now.year
        if month is None:
            month = now.month
        key = f"{year:04d}-{month:02d}"

        # 从数据库读取数据
        data = cl1_db.get_stats(self._instance_name, key)
        
        total = int(data.get('battle_count', 0))
        akashi = int(data.get('akashi_encounters', 0))

        return {"month": key, "total_battles": total, "akashi_encounters": akashi, "raw": data}

    def get_detailed_summary(self, year: int | None = None, month: int | None = None) -> Dict[str, Any]:
        """
        获取详细的统计摘要,包含所有计算指标
        """
        now = datetime.now()
        if year is None:
            year = now.year
        if month is None:
            month = now.month
        key = f"{year:04d}-{month:02d}"

        # 从数据库读取数据
        data = cl1_db.get_stats(self._instance_name, key)
        
        # 基础数据
        battle_count = int(data.get('battle_count', 0))
        akashi_encounters = int(data.get('akashi_encounters', 0))
        akashi_ap = int(data.get('akashi_ap', 0))
        
        # 计算衍生指标
        battle_rounds = battle_count // 2
        sortie_cost = battle_rounds * 120
        
        akashi_probability = round(akashi_encounters / battle_count, 4) if battle_count > 0 else 0.0
        average_stamina = round(akashi_ap / akashi_encounters, 2) if akashi_encounters > 0 else 0.0
        
        return {
            "month": key,
            "battle_count": battle_count,
            "battle_rounds": battle_rounds,
            "sortie_cost": sortie_cost,
            "akashi_encounters": akashi_encounters,
            "akashi_probability": akashi_probability,
            "average_stamina": average_stamina,
            "net_stamina_gain": akashi_ap,
        }


_singleton: Dict[str, OpsiMonthStats] = {}


def get_opsi_stats(instance_name: str | None = None) -> OpsiMonthStats:
    global _singleton
    key = instance_name or "default"
    if key not in _singleton:
        _singleton[key] = OpsiMonthStats(instance_name=instance_name)
    return _singleton[key]


def compute_monthly_cl1_akashi_ap(year: int | None = None, month: int | None = None, campaign: str = "opsi_akashi", instance_name: str | None = None) -> int:
    """
    计算指定月份从明石商店购买的行动力总额
    """
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    key_prefix = f"{year:04d}-{month:02d}"

    instance_name = instance_name or "default"
    data = cl1_db.get_stats(instance_name, key_prefix)
    
    return int(data.get('akashi_ap', 0))


__all__ = ["get_opsi_stats", "OpsiMonthStats", "compute_monthly_cl1_akashi_ap"]
