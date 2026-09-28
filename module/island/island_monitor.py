"""
岛屿经济监控器（Add by MHY, 岛屿经济闭环）

持续聚合 ALAS 日志中的岛屿信息到 CSV/JSON，供错峰销售分析：
- 各店铺每次生产的商品与数量（已安排生产: xxx xN）
- 仓库库存快照（xx: 数量）
- 经营轮转（上架/经营中/剩余时间/领取奖励）
- 商品售出与收益（经营结算相关行）

设计为独立脚本（不碰游戏、不碰调度器），从 log/*.txt 提取，
可 cron 定时跑或手动跑，输出到 log/island_monitor/。
"""
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

# 项目根 = module/island/ 上两级；log 目录在项目根下
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(_PROJECT_ROOT, 'log')
OUT_DIR = os.path.join(LOG_DIR, 'island_monitor')

# 日志行模式
PAT_TIME = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
PAT_PRODUCED = re.compile(r'已安排生产：(.+?) x(\d+)')
PAT_STOCK = re.compile(r'^\s*(\S+?): (\d+)$')
PAT_BIZ_LISTING = re.compile(r'\[岛屿-AutoProfit\] (\S+) 上架: \[(.*?)\]')
PAT_BIZ_STATE = re.compile(r'\[岛屿-经营\] 视野中可见的批次商店: \[(.*?)\]')
PAT_BIZ_REMAIN = re.compile(r'经营剩余 ([\d:]+)，延时')
PAT_DELAY = re.compile(r'延迟任务 `(Island\w+)` 到 ([\d\- :]+)')
PAT_SHOP_DELAY = re.compile(r'\[岛屿-经营\] (\S+): (蓝色可经营|黄色可领取|经营中|不可经营)')
PAT_REFILL = re.compile(r'触发经营后餐馆补充任务')


def parse_log_file(path):
    """解析单个日志文件，返回事件列表。"""
    events = []
    shop_name_map = {
        '豆腐': 'tofu', '肉末烧豆腐': 'tofu_meat', '蛋包饭': 'omurice',
        '白菜豆腐汤': 'cabbage_tofu', '蔬菜沙拉': 'salad', '炸鱼薯条': 'fish_chip',
        '洋葱蒸鱼': 'onion_fish', '佛跳墙': 'fo_tiao', '经典豆腐套餐': 'tofu_combo',
        '凉拌双笋': 'double_bamboo_shoots', '芦笋炒虾仁': 'asparagus_shrimp',
        '苋菜饭团': 'amaranth_rice_ball', '番茄炒蛋': 'tomato_egg',
        '松茸鸡汤': 'matsutake_chicken_soup', '柿子饼': 'persimmon_cake',
        '绵玉定食': 'hearty_meal',
        '苹果汁': 'apple_juice', '香蕉芒果汁': 'banana_mango', '蜂蜜柠檬水': 'honey_lemon',
        '草莓蜜沁': 'strawberry_lemon', '草莓蜂蜜冰沙': 'strawberry_honey',
        '薰衣草茶': 'lavender_tea', '花香果韵': 'floral_fruity',
        '缤纷果乐园': 'fruit_paradise', '阳光蜜水': 'sunny_honey', '西瓜汁': 'watermelon_juice',
        '菊花茶': 'chrysanthemum_tea', '胡萝卜秋梨汁': 'carrot_pear_juice',
        '迎春花茶': 'spring_flower_tea', '鲜榨菠萝汁': 'pineapple_juice',
        '黄瓜汁': 'cucumber_juice',
        '苹果派': 'apple_pie', '玉米杯': 'corn_cup', '香橙派': 'orange_pie',
        '香蕉可丽饼': 'banana_crepe', '果园二重奏': 'orchard_duo', '芒果糯米饭': 'rice_mango',
        '香甜组合': 'succulently_sweet', '莓果香橙甜点组': 'berry_orange',
        '草莓夏洛特': 'strawberry_charlotte', '海鲜饭': 'seafood_rice',
        '碳烤肉串': 'roasted_skewer', '禽肉土豆拼盘': 'chicken_potato',
        '胡萝卜厚蛋烧': 'carrot_omelette', '爆炒禽肉': 'stir_fried_chicken',
        '汉堡肉饭': 'steak_bowl', '柠檬虾': 'lemon_shrimp', '爆炒小龙虾': 'crayfish_stir_fry',
        '烤肉狂欢': 'carnival', '能量双拼套餐': 'double_energy',
        '欧姆蛋': 'omelette', '冰咖啡': 'iced_coffee', '芝士': 'cheese', '拿铁': 'latte',
        '柑橘咖啡': 'citrus_coffee', '草莓奶绿': 'strawberry_milkshake',
        '晨光活力组合': 'morning_light', '醒神套餐': 'wake_up_call',
        '果香双杯乐': 'fruity_fruitier',
    }
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for raw in f:
                tm = PAT_TIME.match(raw)
                if not tm:
                    continue
                ts = tm.group(1)
                if '已安排生产' in raw:
                    m = PAT_PRODUCED.search(raw)
                    if m:
                        events.append(('produce', ts, m.group(1), int(m.group(2))))
                elif '上架:' in raw:
                    # rich 折行：列表可能跨行，直接从整行抓全部 'name' 片段
                    items = re.findall(r"'(\w+)'", raw.split('上架:')[-1])
                    shop = re.search(r'\[岛屿-AutoProfit\] (\S+) 上架', raw)
                    if shop and items:
                        events.append(('listing', ts, shop.group(1), items))
                elif '视野中可见的批次商店' in raw:
                    m = PAT_BIZ_STATE.search(raw)
                    if m:
                        shops = re.findall(r"'(\S+?)\((\w+)\)'", m.group(1))
                        events.append(('shop_state', ts, '', shops))
                elif '经营剩余' in raw:
                    m = PAT_BIZ_REMAIN.search(raw)
                    if m:
                        events.append(('biz_remain', ts, m.group(1), ''))
                elif '延迟任务 `Island' in raw:
                    m = PAT_DELAY.search(raw)
                    if m:
                        events.append(('task_delay', ts, m.group(1), m.group(2)))
                elif '蓝色可经营' in raw or '黄色可领取' in raw:
                    m = PAT_SHOP_DELAY.search(raw)
                    if m:
                        events.append(('shop_action', ts, m.group(1), m.group(2)))
                elif '仓库库存' in raw and ':' in raw:
                    # 调试信息里的库存快照行（中文: 数字）
                    m = re.search(r'(\S+?): (\d+)', raw.split('仓库库存')[-1])
    except OSError:
        pass
    return events


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    all_events = []
    # 扫描今天的日志：优先 log/island_monitor/（拉取脚本落点），其次 log/ 根目录
    candidates = []
    for base in (OUT_DIR, LOG_DIR):
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if name.endswith('.txt') and today[:10] in name and name != 'runner.log':
                path = os.path.join(base, name)
                if path not in candidates:
                    candidates.append(path)
    if not candidates:
        # 用 log/ 里最近的 txt
        txts = [os.path.join(LOG_DIR, n) for n in os.listdir(LOG_DIR)
                if n.endswith('.txt') and os.path.isfile(os.path.join(LOG_DIR, n))]
        if txts:
            candidates = [max(txts, key=os.path.getmtime)]
    for path in candidates:
        all_events.extend(parse_log_file(path))

    # 聚合：按日汇总
    daily = defaultdict(lambda: {'produce': [], 'listing': [], 'shop_state': [], 'biz_remain': [],
                                 'task_delay': [], 'shop_action': []})
    for ev in all_events:
        kind, ts, a, b = ev
        day = ts[:10]
        daily[day][kind].append({'time': ts, 'detail': a, 'value': b})

    out_path = os.path.join(OUT_DIR, f'island_daily_{today}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dict(daily), f, ensure_ascii=False, indent=1)

    # 控制台摘要
    print(f'[island_monitor] 解析 {len(candidates)} 个日志, {len(all_events)} 条事件 -> {out_path}')
    for day, data in sorted(daily.items()):
        produce_cnt = len(data['produce'])
        listing_cnt = len(data['listing'])
        print(f'  {day}: 生产{produce_cnt}次 上架{listing_cnt}轮 '
              f'经营检测{len(data["biz_remain"])}次 延迟{len(data["task_delay"])}次')


if __name__ == '__main__':
    main()
