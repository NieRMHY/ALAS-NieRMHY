"""从任务已有画面旁路采集奖励，防止同一弹窗的重读和重点击重复入账。"""
import hashlib
from functools import lru_cache

from module.statistics import resource_flow
from module.logger import logger


@lru_cache(maxsize=1)
def reward_parser():
    from module.statistics.get_items import GetItemsStatistics
    from module.statistics.item import ItemGrid
    parser = GetItemsStatistics()
    parser.grid = ItemGrid(None, {}, template_area=(40, 21, 89, 70), amount_area=(50, 72, 94, 94))
    for relative in ('assets/stats_basic', 'assets/stats/commission_items',
                     'assets/stats/research_items', 'assets/stats/opsi_reward_items'):
        folder = resource_flow.ROOT / relative
        if folder.is_dir():
            parser.load_template_folder(str(folder))
    return parser


@lru_cache(maxsize=1)
def opsi_parser():
    from module.azur_stats.scene.operation_siren import SceneOperationSiren
    return SceneOperationSiren()


class RewardTracker:
    def __init__(self, config):
        self.config = config
        self.fingerprint = None
        self.stable = 0
        self.closed = 0
        self.layouts = set()

    def frame(self, image, *, clicked=False):
        if image is None:
            return
        from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
        from module.handler.assets import INFO_BAR_1
        from module.commission.assets import EXP_INFO_S_REWARD
        from module.os_handler.assets import AUTO_SEARCH_REWARD
        layout = None
        try:
            state = resource_flow.session_for(self.config)
            opsi = state['task'].startswith('Opsi')
            summary = opsi and AUTO_SEARCH_REWARD.match_template_color(image, offset=(50, 50))
            layout = 'summary' if summary else next((index for index, button in enumerate(
                (GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3))
                if button.match_template_color(image, offset=(5, 0))), None)
            if layout is None:
                self.closed += 1
                # 委托经验结算正向标记下一组奖励；快速领取可能只经过这一帧。
                next_commission = state['task'] == 'Commission' and EXP_INFO_S_REWARD.match_template_color(image, offset=(20, 20))
                if self.closed >= 2 or next_commission:
                    self.layouts.clear()
                    self.fingerprint, self.stable = None, 0
                return
            self.closed = 0
            if layout in self.layouts or INFO_BAR_1.appear_on(image):
                return
            fingerprint = hashlib.sha256(image[210:610, 300:1030].tobytes()).digest()
            self.stable = self.stable + 1 if fingerprint == self.fingerprint else 1
            self.fingerprint = fingerprint
            if not clicked and self.stable < 2:
                return
            if opsi:
                parser = opsi_parser()
                items = parser.parse_auto_search_reward(image) if summary else parser.parse_get_items(image)
            else:
                items = reward_parser().stats_get_items(image, amount_trim=True)
            changes = {}
            for item in items:
                if item.is_known_item() and isinstance(item.amount, int) and item.amount > 0:
                    key = resource_flow.canonical(item.name)
                    changes[key] = changes.get(key, 0) + int(item.amount)
            # 清油观察或恢复时遇到遗留奖励，不能将上一任务的收入认领到当前操作。
            task = 'Unattributed' if state['task'] in ('OilControl', 'Restart', 'Start') else None
            if resource_flow.record(self.config, changes, '奖励领取', evidence='recognition', task=task):
                for key, amount in changes.items():
                    state['rewards'][key] = state['rewards'].get(key, 0) + amount
            self.layouts.add(layout)
        except Exception as error:
            # 旁路统计的故障不能改变现有领取、卡死检测和恢复流程。
            logger.warning(f'[资源管理] 奖励解析失败：{type(error).__name__}')
            if layout is not None:
                self.layouts.add(layout)


def receipt_totals(config):
    state = resource_flow.session_for(config)
    return dict(state['rewards']) if state else {}


def record_purchase(config, item, quantity=1, receipts=None):
    """仅在已确认购买结果后调用，价格与数量缺失时不推测支出。"""
    cost = getattr(item, 'cost', None)
    price = getattr(item, 'price', None)
    if not isinstance(cost, str) or type(price) is not int or price <= 0 or type(quantity) is not int or quantity <= 0:
        return False
    changes = {resource_flow.canonical(cost): -price * quantity}
    amount = getattr(item, 'amount', None)
    if item.is_known_item() and type(amount) is int and amount > 0:
        name = resource_flow.canonical(item.name)
        recognized = max(0, receipt_totals(config).get(name, 0) - (receipts or {}).get(name, 0))
        changes[name] = changes.get(name, 0) + max(0, amount * quantity - recognized)
    return resource_flow.record(config, changes, f'购买 {item.name} × {quantity}')


def record_research_cost(config, project):
    """已启动的科研项目按现有项目目录中的明确消耗记账，未知用量不填零。"""
    changes = {}
    for item in getattr(project, 'data', {}).get('input', []):
        name = {'Coins': 'Coin', 'Cubes': 'Cube', 'Wisdom Cube': 'Cube',
                'Cognitive Chips': 'Chip'}.get(item.get('name'))
        amount = item.get('amount')
        if name and type(amount) is int and amount > 0:
            changes[name] = changes.get(name, 0) - amount
    return resource_flow.record(config, changes, f'启动科研 {project.name}')


def observe_campaign_end(config, device):
    """在已返回的选图页核对末轮收支，不导航或改变战役停止条件。

    Pages:
        in: page_campaign / page_event / page_sp
        out: 原页面
    """
    if resource_flow.session_for(config) is None:
        return
    runtime = config.__dict__.get('_scheduler_runtime')
    stop = runtime.script.stop_event if runtime is not None else None
    if stop is not None and stop.is_set():
        return
    import re
    from module.campaign.campaign_status import CampaignStatus, OCR_PT
    from module.campaign.assets import OCR_COIN, OCR_OIL
    from module.scheduler.resources import stable_read
    from module.log_res import LogRes
    from module.ui.page import page_campaign, page_event, page_sp
    ui = CampaignStatus(config, device)
    pages = (page_campaign, page_event, page_sp)
    visible = lambda: any(ui.ui_page_appear(page) for page in pages)
    if not visible():
        return
    def read():
        row = {}
        for name, button, color in (('Oil', OCR_OIL, (247, 247, 247)),
                                    ('Coin', OCR_COIN, (239, 239, 239))):
            value = ui._get_num(button, f'RESOURCE_END_{name}', color, require_valid=True)
            if type(value) is int and value >= 0 and (name != 'Oil' or value <= 25000):
                row[name] = value
        if ui.ui_page_appear(page_event) or ui.ui_page_appear(page_sp):
            text = OCR_PT.ocr(device.image).strip()
            if re.fullmatch(r'X?\d+', text):
                row['Pt'] = int(text.lstrip('X'))
        return row or None
    row = stable_read(ui, visible, read)
    if row:
        log = LogRes(config)
        for name, value in row.items():
            log.record(name, value, source='campaign_end')
        config.save()
