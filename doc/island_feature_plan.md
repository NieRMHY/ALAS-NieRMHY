# 岛屿功能扩展设计文档

> 本文档记录岛屿模块新增功能的详细设计方案。

---

## 实现进度

- [ ] **功能1**: 矿山/森林按库存阈值执行 — 检测仓库数量，低于阈值才安排生产
- [ ] **功能2**: 每日订单功能 — 自动接取和完成每日订单
- [ ] **功能3**: 货运委托功能 — 集成已有运输系统
- [ ] **功能4**: 每周珍珠售卖 — 按配置日自动全量卖出珍珠
- [ ] **功能5**: 经营模块智能分波 — 分两波 + 季节限定检测替换 + 加成商品检测替换
- [ ] **功能6**: 自动采集角色体力检测 — 体力 < 100 自动换人
- [ ] **功能7**: 摸猫/JUU速运任务 — 每日互动任务
- [ ] **功能8**: 自动清空开发季商店 — 花光开发季 PT 买空商店
- [ ] **功能9**: 给三个小人打招呼 — NPC 互动
- [ ] 配置系统：更新 [`argument.yaml`](module/config/argument/argument.yaml) 和 [`task.yaml`](module/config/argument/task.yaml)
- [ ] i18n：更新翻译文件

---

## 目录

1. [功能1: 矿山/森林按库存阈值执行](#功能1-矿山森林按库存阈值执行)
2. [功能2: 每日订单功能](#功能2-每日订单功能)
3. [功能3: 货运委托功能](#功能3-货运委托功能)
4. [功能4: 每周珍珠售卖](#功能4-每周珍珠售卖)
5. [功能5: 经营模块智能分波](#功能5-经营模块智能分波)
6. [功能6: 自动采集角色体力检测换人](#功能6-自动采集角色体力检测换人)
7. [功能7: 摸猫/JUU速运任务](#功能7-摸猫juu速运任务)
8. [功能8: 自动清空开发季商店](#功能8-自动清空开发季商店)
9. [功能9: 给三个小人打招呼](#功能9-给三个小人打招呼)
10. [任务调度与 TODO 列表集成](#任务调度与-todo-列表集成)
11. [配置变更总览](#配置变更总览)

---

## 功能1: 矿山/森林按库存阈值执行

### 目标

当前 [`IslandMineForest.run()`](module/island/island_mine_forest.py:46) 根据固定槽位配置（Mining1~4、Felling1~4）决定哪些岗位运行，不考虑库存数量。
改为先检查仓库库存，低于阈值才安排生产。

### 设计方案

修改文件: [`module/island/island_mine_forest.py`](module/island/island_mine_forest.py)

#### 新增配置项

```yaml
IslandMine:
  MinCopper: 0
  MinAluminium: 0
  MinIron: 0
  MinSulphur: 0
  MinSilver: 0
IslandForest:
  MinElegant: 0
  MinPractical: 0
  MinSelected: 0
```

#### 核心逻辑

```python
def check_inventory_and_prepare(self):
    self.warehouse_filter('mine')
    image = self.device.screenshot()
    needs = []
    for product_name, (_, _, _) in self.PRODUCT_CONFIGS.items():
        if product_name in ['Elegant', 'Practical', 'Selected', 'Natural']:
            continue
        min_key = f'Min{product_name}'
        threshold = getattr(self.config, f'IslandMine_{min_key}', 0)
        count = self.ocr_item_quantity(image, TEMPLATE_MINE_PRODUCTS[product_name])
        if count < threshold:
            needs.append(product_name)

    self.warehouse_filter('forest')
    image = self.device.screenshot()
    for product_name in ['Elegant', 'Practical', 'Selected', 'Natural']:
        # 同理
        ...
    return needs

def run(self):
    needs = self.check_inventory_and_prepare()
    for post_id, product_config, time_var_name in all_configs:
        if product_config is not None and product_config in needs:
            self.run_single_post(post_id, product_config, time_var_name)
```

---

## 功能2: 每日订单功能

### 目标

岛屿系统中存在"每日订单"功能（在管理页面 → 采集页签旁的"订单"页签），玩家可以接取每日订单，完成后获得奖励。

### 设计方案

**新文件**: [`module/island/island_daily_order.py`](module/island/island_daily_order.py)

```python
class IslandDailyOrder(Island):
    def run(self):
        """进入订单页签 → 领取已完成奖励 → 检测可用订单 → 自动接取"""
```

#### 流程

```
run()
  ├── goto_management()
  ├── switch_to_order_tab()
  ├── claim_completed_orders()
  ├── detect_available_orders()   # OCR 需求物品 + 匹配仓库库存
  ├── accept_best_orders()
  └── set_next_run_time()
```

#### 配置项

```yaml
IslandDailyOrder:
  Enabled: true
  AutoAccept: true
  MaxOrders: 3
```

---

## 功能3: 货运委托功能

### 目标

货运委托（运输系统）已在 [`transport.py`](module/island/transport.py) 中有完整实现。将其集成到统一调度中，增加自动刷新未满委托的开关。

### 现有功能

| 方法 | 功能 |
|------|------|
| [`IslandTransportRun.island_transport_run()`](module/island/transport.py:400) | 完整执行运输流程 |
| [`transport_receive()`](module/island/transport.py:280) | 领取已完成委托 |
| [`transport_detect()`](module/island/transport.py:249) | 检测委托状态 |
| [`transport_refresh()`](module/island/transport.py:334) | 刷新委托 |
| [`transport_start()`](module/island/transport.py:364) | 开始委托 |

#### 配置项

```yaml
IslandTransport:
  Enabled: true
  AutoRefresh: true
  SubmitCopper: true
  SubmitAluminium: true
  # ... 其他物品
```

---

## 功能4: 每周珍珠售卖

### 目标

每周一（或配置的某天）自动进入珍珠商店，将库存中的珍珠全部卖出。

### 设计方案

**新文件**: [`module/island/island_pearl_sell.py`](module/island/island_pearl_sell.py)

```python
class IslandPearlSell(Island):
    def run(self):
        """检查售卖日 → 导航到珍珠商店 → 全量卖出 → 设置下周运行"""
```

#### 流程

```
run()
  ├── if today != config.sell_day: skip
  ├── navigate_to_island_shop()
  ├── switch_to_pearl_tab()
  ├── detect_pearl_count()
  ├── if count > 0: click_sell_all() → confirm_sell()
  └── schedule_next_week()
```

#### 配置项

```yaml
IslandPearlSell:
  Enabled: false
  SellDay:
    value: monday
    option: [monday..sunday]
  SellTime: "09:00"
```

---

## 功能5: 经营模块智能分波

### 目标

对现有 [`IslandBusiness`](module/island/island_business.py:39) 进行三项增强：

1. **分两波经营**：5 个商店分成两波
2. **季节限定检测替换**：季节限定餐品 < 7 则替换为备用菜品
3. **加成商品检测替换**：检测当天有加成的商品，**从下往上替换**

### 设计方案

修改文件: [`module/island/island_business.py`](module/island/island_business.py)

#### 5.1 分两波经营

```python
WAVE_CONFIG = {
    'wave1': {'shops': ['有鱼餐馆', '白熊饮品', '啾啾简餐'], 'time': "08:00"},
    'wave2': {'shops': ['乌鱼烤肉', '啾咖啡'],                'time': "14:00"},
}
```

```yaml
IslandBusiness:
  WaveEnabled: true
  Wave1Time: "08:00"
  Wave2Time: "14:00"
```

#### 5.2 季节限定检测替换

经营前检查季节限定餐品库存，数量 < SeasonalThreshold 则替换。

```python
def check_seasonal_dish_quantity(self, shop_name):
    replacement_plan = []
    seasonal_items = self._get_seasonal_items_for_shop(shop_name)
    for product in self.active_products.get(shop_name, []):
        if product['name'] in seasonal_items:
            count = self._check_product_quantity(product['name'])
            if count < 7:  # SeasonalThreshold
                fallback = self._get_fallback_product(shop_name, product['name'])
                if fallback:
                    replacement_plan.append((product, fallback))
    return replacement_plan
```

```yaml
IslandBusinessShop1:
  SeasonalFallback1: hearty_meal
  SeasonalFallback2: fo_tiao
```

#### 5.3 加成商品检测替换（从下往上）

进入商店后检测加成商品，满足条件则从最后一个槽位往上替换。

```python
def check_boosted_products(self, shop_name):
    boosted_products = self._detect_boosted(shop_name)
    if not boosted_products:
        return
    current_products = self.active_products.get(shop_name, [])
    for product in reversed(current_products):  # 从下往上
        for boosted in boosted_products:
            if boosted['name'] != product['name'] and self._check_boost_condition(boosted):
                self._replace_product(shop_name, product, boosted)
                break
```

```yaml
IslandBusiness:
  BoostedReplace: true
  BoostThreshold: 1.2
  BoostReplaceDirection: bottom_up
```

---

## 功能6: 自动采集角色体力检测换人

### 目标

在 [`IslandDailyGather`](module/island/island_daily_gather.py:14) 选择采集角色时，检测体力低于 100 则跳过换人。

### 设计方案

修改文件: [`module/island/island_daily_gather.py`](module/island/island_daily_gather.py)

#### 核心逻辑

```python
def _select_characters_with_stamina_check(self):
    for slot_idx in range(3):
        best_char = None  # (button, stamina)
        for attempt in range(max_swipes):
            self.device.screenshot()
            for char_button in self._get_visible_characters():
                stamina = self._ocr_stamina(char_button)
                if stamina >= 100:
                    self.device.click(char_button)
                    self.device.click(SELECT_UI_CONFIRM)
                    return
                if best_char is None or stamina > best_char[1]:
                    best_char = (char_button, stamina)
            self._swipe_down()
        if best_char:
            self.device.click(best_char[0])
            self.device.click(SELECT_UI_CONFIRM)

def _ocr_stamina(self, char_button):
    stamina_area = (
        char_button.area[0] + 80, char_button.area[1] + 5,
        char_button.area[0] + 120, char_button.area[1] + 25)
    ocr = Digit(Button(area=stamina_area, ...), letter=(255,255,255), threshold=200)
    return int(ocr.ocr(self.device.image) or 0)
```

#### 配置项

```yaml
IslandDailyGather:
  StaminaThreshold: 100
  StaminaCheckEnabled: true
```

---

## 功能7: 摸猫/JUU速运任务

### 目标

每日在岛屿上执行两个小互动：摸猫（点击猫获得奖励）、JUU速运（领取/提交速运任务）。

### 设计方案

**新文件**: [`module/island/island_daily_interact.py`](module/island/island_daily_interact.py)

```python
class IslandDailyInteract(Island):
    def run(self):
        self.goto_island()
        self.pet_cat()
        self.juu_express()

    def pet_cat(self):
        """模板匹配检测猫 → 点击 → 抚摸 → 关闭奖励"""

    def juu_express(self):
        """寻找速运点 → 领取奖励 → 接受速运"""
```

#### 配置项

```yaml
IslandDailyInteract:
  PetCat: true
  JuuExpress: true
```

---

## 功能8: 自动清空开发季商店

### 目标

开发季活动期间，自动进入开发季商店，用金币买空商店中有价值的物品（如"开发核心""繁荣之基""发展支柱"等）。

### 设计方案

**新文件**: [`module/island/island_dev_shop.py`](module/island/island_dev_shop.py)

#### 核心类: `IslandDevShop`

```python
class IslandDevShop(Island):
    """自动清空开发季商店"""

    # 购买优先级：稀有物品优先
    PURCHASE_PRIORITY = [
        'development_core',      # 开发核心（高价值）
        'prosperity_foundation', # 繁荣之基
        'development_pillar',    # 发展支柱
        # ... 其他物品按价值降序
    ]

    def run(self):
        """检查金币 → 进入开发季商店 → 按优先级购买 → 花光金币"""
```

#### 流程

```
run()
  ├── goto_island_shop()
  ├── switch_to_dev_shop_tab()         # 切换到开发季商店页签
  ├── detect_gold()                    # OCR 当前持有金币数量
  ├── if gold == 0: return             # 没钱就跳过
  │
  ├── scan_shop_items()                # 扫描商店中所有可购买物品
  │     ├── 模板匹配识别物品图标
  │     └── OCR 物品价格（金币数）
  │
  ├── generate_purchase_plan()         # 按优先级生成购买计划
  │     ├── 优先购买稀有物品（开发核心等）
  │     ├── 剩余金币购买常规资源
  │     └── 金币不够买高优物品时跳过
  │
  └── execute_purchase_plan()          # 执行购买
        ├── click_item()
        ├── confirm_purchase()
        └── repeat until gold runs out
```

#### 金币检测

```python
def detect_gold(self):
    """OCR 检测当前持有金币数量（在商店页面顶部显示）"""
    ocr = Digit(OCR_GOLD, letter=(255, 255, 255), threshold=200)
    return ocr.ocr(self.device.image)
```

#### 购买优先级配置

```yaml
IslandDevShop:
  Enabled: true                # 启用自动清空
  ReserveGold: 0               # 保留金币数量（不花光）
```

#### 物品识别

- 使用模板匹配识别开发季商店中的各个物品
- 物品图标需要从游戏中截图后通过 [`button_extract.py`](dev_tools/button_extract.py) 提取

#### 配置项

```yaml
IslandDevShop:
  Enabled: true
  ReserveGold: 0
```

---

## 功能9: 给三个小人打招呼

### 目标

岛屿场景中出现的三个可互动 NPC 小人，点击打招呼获得友好度或小奖励。

### 设计方案

在 [`module/island/island_daily_interact.py`](module/island/island_daily_interact.py) 中扩展。

```python
def greet_npcs(self):
    NPC_TEMPLATES = [TEMPLATE_NPC_1, TEMPLATE_NPC_2, TEMPLATE_NPC_3]
    for template in NPC_TEMPLATES:
        if self.appear(template):
            self.device.click(template)
            # 处理打招呼弹窗 → 关闭
```

#### 配置项

```yaml
IslandDailyInteract:
  GreetNpcs: true
  GreetNpcCount: 3
```

---

## 任务调度与 TODO 列表集成

### 概述

所有功能由 `IslandPlan` 任务统一调度，内部维护 TODO 列表按优先级依次执行各模块。TODO 列表本身不是独立功能，而是各功能模块的统一调度机制。

### 核心调度类

**新文件**: [`module/island/island_todo.py`](module/island/island_todo.py)

```python
class IslandTodo(Island):
    PRIORITY_MAP = {
        'receive_transport':    10,   # 收取货运委托
        'daily_order':          20,   # 每日订单
        'pearl_selling':        30,   # 每周珍珠
        'pet_cat':              35,   # 摸猫
        'juu_express':          36,   # JUU速运
        'greet':                37,   # 打招呼
        'farm':                 40,   # 农场
        'mine_forest':          50,   # 矿山/森林
        'ranch':                60,   # 牧场
        'fishery':              61,   # 渔场
        'business_wave1':       70,   # 经营第一波
        'business_wave2':       71,   # 经营第二波
        'dev_shop':             75,   # 开发季商店
        'manufacture':          80,   # 制造
        'daily_gather':         100,  # 每日采集
        'air_drop':             110,  # 空投
        'season_task':          120,  # 季节任务
        'transport_start':      130,  # 开始货运委托
    }
```

### 执行流程

```
IslandTodo.run()
  ├── generate_todo_list()       # 根据配置和状态生成 TODO
  │     ├── check_transport_receive()
  │     ├── check_daily_order()
  │     ├── check_pearl_selling()
  │     ├── check_pet_cat()
  │     ├── check_juu_express()
  │     ├── check_greet()
  │     ├── check_dev_shop()         # 检查是否有开发季 PT
  │     ├── check_farm_needs()
  │     ├── check_mine_forest_needs()
  │     ├── check_business_wave1()
  │     ├── check_business_wave2()
  │     └── ...
  │
  ├── sort_todo_list()           # 按优先级排序
  │
  └── execute_todo_list()        # 依次执行
        ├── run_single_task(item)
        └── handle_error()
```

### 配置项

```yaml
IslandPlan:
  Season:
    value: spring
    option: [spring, summer, autumn, winter]
  EnabledModules:
    value: []
    option: [Farm, Rancher, MineForest, Business, DevShop, ...]
```

### 与现有任务调度的关系

当前的 [`task.yaml`](module/config/argument/task.yaml:362) 中 `Island` 组有多个独立任务。新增 `IslandPlan` 任务后，用户可以选择使用统一的 `IslandPlan` 任务替代多个独立任务。

### 优先级调度

```
高优先级（立即执行）：
  收取货运委托 → 10
  每日订单 → 20
  每周珍珠 → 30
  摸猫/速运 → 35-36

中优先级（定期执行）：
  打招呼 → 37
  农场/矿山/牧场 → 40-61
  经营第一波 → 70
  经营第二波 → 71
  开发季商店 → 75
  制造 → 80

低优先级（确保每日执行）：
  每日采集 → 100
  空投 → 110
  季节任务 → 120
  货运开始 → 130
```

---

## 配置变更总览

### [`argument.yaml`](module/config/argument/argument.yaml) 新增配置

```yaml
IslandPlan:
  Season:
    value: spring
    option: [spring, summer, autumn, winter]
  EnabledModules:
    value: []
    option: [Farm, Rancher, MineForest, Business, Restaurant, Teahouse,
             Grill, JuuEatery, JuuCoffee, DailyGather, AirDrop, Transport,
             DailyOrder, PearlSell, DailyInteract, DevShop, SeasonTask, Manufacture]

IslandMine:
  MinCopper: 0
  MinAluminium: 0
  MinIron: 0
  MinSulphur: 0
  MinSilver: 0

IslandForest:
  MinElegant: 0
  MinPractical: 0
  MinSelected: 0
  MinNatural: 0

IslandBusiness:
  WaveEnabled: true
  Wave1Time: "08:00"
  Wave2Time: "14:00"
  SeasonalReplaceEnabled: true
  SeasonalThreshold: 7
  BoostedReplace: true
  BoostThreshold: 1.2
  BoostReplaceDirection: bottom_up

IslandBusinessShop1:
  SeasonalFallback1: hearty_meal
  SeasonalFallback2: fo_tiao

IslandDailyGather:
  StaminaThreshold: 100
  StaminaCheckEnabled: true

IslandDailyOrder:
  Enabled: true
  AutoAccept: true
  MaxOrders: 3

IslandPearlSell:
  Enabled: false
  SellDay:
    value: monday
    option: [monday..sunday]
  SellTime: "09:00"

IslandDevShop:
  Enabled: true
  ReservePT: 0

IslandDailyInteract:
  PetCat: true
  JuuExpress: true
  GreetNpcs: true
  GreetNpcCount: 3
```

### [`task.yaml`](module/config/argument/task.yaml) 修改

```yaml
Island:
  tasks:
    IslandPlan:
      - Scheduler
      - IslandPlan
      - IslandDailyOrder
      - IslandPearlSell
      - IslandDailyInteract
      - IslandDevShop
    # ... 保留现有独立任务
```

---

## 文件结构变化

```
module/island/
├── island.py                    # 已有
├── island_todo.py               # 新增 - 统一调度器
├── island_daily_order.py        # 新增 - 每日订单
├── island_pearl_sell.py         # 新增 - 珍珠售卖
├── island_dev_shop.py           # 新增 - 开发季商店清空
├── island_daily_interact.py     # 新增 - 摸猫/速运/打招呼
├── island_mine_forest.py        # 修改 - 库存检测
├── island_business.py           # 修改 - 分波 + 替换
├── island_daily_gather.py       # 修改 - 体力检测
├── transport.py                 # 已有
├── assets.py                    # 已有
```

---

## i18n 新增 Key

```json
{
  "Island.IslandPlan.EnabledModules": "启用模块",
  "Island.IslandMine.MinCopper": "铜矿最低库存",
  "Island.IslandMine.MinAluminium": "铝矿最低库存",
  "Island.IslandMine.MinIron": "铁矿最低库存",
  "Island.IslandMine.MinSulphur": "硫磺最低库存",
  "Island.IslandMine.MinSilver": "银矿最低库存",
  "Island.IslandForest.MinElegant": "优雅木材最低库存",
  "Island.IslandForest.MinPractical": "实用木材最低库存",
  "Island.IslandForest.MinSelected": "精选木材最低库存",
  "Island.IslandForest.MinNatural": "自然木材最低库存",
  "Island.IslandBusiness.WaveEnabled": "启用分波经营",
  "Island.IslandBusiness.SeasonalReplaceEnabled": "季节限定替换",
  "Island.IslandBusiness.SeasonalThreshold": "季节限定替换阈值",
  "Island.IslandBusiness.BoostedReplace": "加成商品替换",
  "Island.IslandBusiness.BoostThreshold": "加成倍率阈值",
  "Island.IslandBusinessShop1.SeasonalFallback1": "季节限定备用菜品1",
  "Island.IslandDailyGather.StaminaThreshold": "体力阈值",
  "Island.IslandDailyGather.StaminaCheckEnabled": "启用体力检测",
  "Island.IslandDailyOrder.Enabled": "启用每日订单",
  "Island.IslandPearlSell.Enabled": "启用珍珠售卖",
  "Island.IslandPearlSell.SellDay": "售卖日",
  "Island.IslandDevShop.Enabled": "启用开发季商店清空",
  "Island.IslandDevShop.ReservePT": "保留PT数量",
  "Island.IslandDailyInteract.PetCat": "摸猫",
  "Island.IslandDailyInteract.JuuExpress": "JUU速运",
  "Island.IslandDailyInteract.GreetNpcs": "打招呼"
}
```

---

## 实现优先级

| 优先级 | 功能 | 工作量 |
|--------|------|--------|
| P0 | 矿山/森林库存阈值 | 小 |
| P0 | 经营模块智能分波 + 季节替换 | 中 |
| P1 | 经营模块加成商品替换 | 中（需截图） |
| P1 | 货运委托集成 | 小 |
| P1 | 每日订单 | 中 |
| P1 | 自动采集体力检测 | 小 |
| P2 | 珍珠售卖 | 小 |
| P2 | 开发季商店清空 | 中（需截图） |
| P2 | 摸猫/JUU速运 | 中（需截图） |
| P3 | 打招呼 | 中（需截图） |

> **注意**: 摸猫、JUU速运、打招呼、加成商品检测、开发季商店等功能需要游戏内截图资源，需先通过 `dev_tools/button_extract.py` 提取按钮定义。
