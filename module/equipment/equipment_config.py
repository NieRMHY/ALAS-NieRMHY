"""演习与 META 作战共用的战前、战后装备方案。"""

import yaml

from module.base.decorator import cached_property
from module.equipment.assets import (
    FLEET_POSITION_DOWN, FLEET_POSITION_FLAGSHIP, FLEET_POSITION_HEAD,
    FLEET_POSITION_MIDDLE, FLEET_POSITION_TAIL, FLEET_POSITION_UP, FLEET_REORGANIZE, FLEET_SAVE,
)
from module.equipment.equipment import Equipment
from module.exception import GameStuckError, RequestHumanTakeover
from module.logger import logger

POSITION_BUTTON = {
    'flagship': FLEET_POSITION_FLAGSHIP,
    'up': FLEET_POSITION_UP,
    'down': FLEET_POSITION_DOWN,
    'head': FLEET_POSITION_HEAD,
    'middle': FLEET_POSITION_MIDDLE,
    'tail': FLEET_POSITION_TAIL,
}


class EquipmentConfigHandler(Equipment):
    """按舰船站位应用方案，保留通用装备码接口的备份及交接语义。"""

    def ensure_reorganize(self):
        """进入整编并确认保存按钮出现。

        Pages:
            in: BATTLE_PREPARATION
            out: FLEET_SAVE
        """
        for _ in self.loop(timeout=10):
            if self.appear(FLEET_SAVE):
                return
            if self.appear_then_click(FLEET_REORGANIZE, interval=2):
                continue
        raise GameStuckError('无法确保进入整编界面')

    def ensure_save(self):
        """保存整编并确认已返回战斗准备页。

        Pages:
            in: FLEET_SAVE
            out: BATTLE_PREPARATION
        """
        for _ in self.loop(timeout=10):
            if self.appear(FLEET_REORGANIZE):
                return
            if self.appear_then_click(FLEET_SAVE, interval=2):
                continue
        raise GameStuckError('无法保存编队')

    @cached_property
    def equipment_config(self):
        """在任何卸装操作前校验整份方案，省略的站位及阶段视为空值。"""
        config = {}
        try:
            data = yaml.safe_load(self.config.Equipment_Config)
            if data is None:
                return config
            if not isinstance(data, dict) or data.keys() - POSITION_BUTTON.keys():
                raise ValueError('配置必须为有效舰船站位的映射')
            for position in POSITION_BUTTON:
                if position not in data:
                    continue
                values = data[position]
                if not isinstance(values, dict) or values.keys() - {'before', 'after'}:
                    raise ValueError(f'{position} 必须包含 before/after 装备码配置')
                codes = {}
                for phase in ('before', 'after'):
                    code = values.get(phase)
                    if code is not None:
                        if not isinstance(code, str):
                            raise TypeError(f'{position}.{phase} 装备码必须为字符串或空值')
                        code = code.strip()
                        if code and not self._is_equipment_code(code):
                            raise ValueError(f'{position}.{phase} 装备码格式无效')
                    codes[phase] = code or None
                if codes['before']:
                    config[position] = codes

        except (yaml.YAMLError, AttributeError, TypeError, ValueError, KeyError, IndexError) as exc:
            # 战后方案也必须预检，避免先卸装再发现无法恢复。
            raise RequestHumanTakeover(f'装备码配置格式错误：{exc}') from exc

        return config

    @cached_property
    def equipment_config_enabled(self):
        return bool(getattr(self.config, 'Equipment_Enable', False) and self.equipment_config)

    @property
    def equipment_handle_before_flag(self):
        return getattr(self, '_equipment_handle_before_flag', False)

    def _equipment_config_clear(self):
        """清空当前站位，不覆盖通用 code_clear(name) 的备份接口。"""
        if not self.equipment_code_supported():
            return False
        self._code_enter()
        return self._code_apply(code=None)

    def _equipment_config_apply(self, code):
        """应用已校验的站位方案，不占用通用 code_apply(name) 接口。"""
        if not self.equipment_code_supported():
            return False
        if not self._is_equipment_code(code):
            logger.warning("没有可用装备码，跳过装备应用")
            return False
        self._code_enter()
        return self._code_apply(code=code)

    def equipment_clear(self):
        for position in self.equipment_config:
            logger.attr('卸装站位', position)
            self.equip_enter(POSITION_BUTTON[position])
            if not self._equipment_config_clear():
                return False
            self.ui_back(FLEET_SAVE)
        return True

    def equipment_handle_before(self):
        """首次出击前换装；需要清空时，先卸下所有目标舰船再依次装备。

        Pages:
            in: BATTLE_PREPARATION
            out: BATTLE_PREPARATION
        """
        if not self.equipment_config_enabled or self.equipment_handle_before_flag:
            return
        if not self.equipment_code_supported():
            raise RequestHumanTakeover('当前控制方式不支持装备码换装')

        logger.hr('战前装备配置', level=2)
        self.ensure_reorganize()

        if self.config.Equipment_ClearBeforeApply:
            if not self.equipment_clear():
                raise RequestHumanTakeover('清空装备失败')

        for position, value in self.equipment_config.items():
            logger.attr('战前换装站位', position)
            self.equip_enter(POSITION_BUTTON[position])
            if not self._equipment_config_apply(value['before']):
                raise RequestHumanTakeover('应用装备失败')
            self.ui_back(FLEET_SAVE)

        self.ensure_save()

        self._equipment_handle_before_flag = True

    def equipment_handle_after(self):
        """恢复战后方案，确认保存成功后才清除待恢复标志。

        Pages:
            in: BATTLE_PREPARATION
            out: BATTLE_PREPARATION
        """
        if not self.equipment_config_enabled or not self.equipment_handle_before_flag:
            return
        if not self.equipment_code_supported():
            raise RequestHumanTakeover('当前控制方式不支持装备码换装')

        logger.hr('战后装备配置', level=2)
        self.ensure_reorganize()

        if self.config.Equipment_ClearBeforeApply:
            if not self.equipment_clear():
                raise RequestHumanTakeover('清空装备失败')

        for position, value in self.equipment_config.items():
            logger.attr('战后换装站位', position)
            code = value['after']
            if not code:
                if not self.config.Equipment_ClearBeforeApply:
                    self.equip_enter(POSITION_BUTTON[position])
                    if not self._equipment_config_clear():
                        raise RequestHumanTakeover('清空装备失败')
                    self.ui_back(FLEET_SAVE)

                continue

            self.equip_enter(POSITION_BUTTON[position])
            if not self._equipment_config_apply(code):
                raise RequestHumanTakeover('应用装备失败')
            self.ui_back(FLEET_SAVE)

        self.ensure_save()
        self._equipment_handle_before_flag = False
