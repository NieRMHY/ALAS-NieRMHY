# 商店系统（shop / shop_event）

> 各类游戏商店的自动化购买：常规商店（通用/功勋/舰队/核心/勋章/代币）的货架识别与按优先级购买、活动商店的 PT/URpt 货币规划。

## 1. 模块概述

商店系统由两个协作子模块构成：

- `module/shop`：常规商店框架与六个具体商店（通用、功勋、舰队、核心、勋章、代币/白票）。它们共享「识别货架 → 过滤排序 → 逐个购买」的流程，差异只在网格布局、货币类型和购买弹窗形态，因此以 `ShopBase` + `ShopClerk` 抽象公共流程，每个商店一个子类只覆盖差异点。
- `module/shop_event`：活动商店。其货架随活动动态变化（无固定模板网格）、货币是活动点数 pt/URpt 且存在「UR 舰船用 URpt、URpt 用 pt 兑换」的换算链，购买策略（保船、保留点数、活动结束前清货架）与常规商店完全不同，故独立成模块。

在系统中，调度器 `alas.py` 的 `ShopFrequent`/`ShopOnce`/`EventShop` 任务分别进入 `RewardShop.run_frequent()`、`RewardShop.run_once()` 和 `EventShop.run()`；大世界白票商店（`OpsiVoucher`）与档案任务（`OpsiArchive`）直接实例化 `VoucherShop`。大世界港口/明石商店（`module/os_shop`）与私人休息室商店（`module/private_quarters`）是独立模块，复用常规商店的基类与界面模式。

## 2. 模块职责

### 负责

- 常规商店的货架物品识别（模板匹配 + 价格/成本 OCR）、售罄检测、遮挡弹窗处理。
- 商品过滤：`>` 分隔的优先级字符串（`Filter` 正则三级匹配 group/sub_genre/tier），以及模板无法覆盖的自定义商品判定（装备外观箱、未获得舰船）。
- 购买执行：选择式（装备箱/教材/图纸的选择网格）与数量式（数量输入框）两条确认路径，含库存 OCR 与防超买。
- 货币余额 OCR 并同步至 Dashboard（`LogRes`）。
- 商店刷新、金币溢出购买猫箱、活动商店 URpt 规划与多标签页遍历。

### 不负责

- 大世界港口商店与明石商店的识别购买（`module/os_shop`），由其自身任务控制器负责。
- 私人休息室商店（`module/private_quarters`，复用本系统模式但独立实现）。
- 页面跳转图谱与导航路径（`module/ui`），本模块只调用 `ui_ensure()`/`ui_goto()`。
- 过滤字符串的配置定义、迁移与生成（`module/config`）。

## 3. 模块位置

```
module/shop/
├── base.py                 # ShopBase：物品识别/过滤/选品框架；ShopItemGrid(_250814)、FILTER 正则
├── clerk.py                # ShopClerk：购买执行器（选择式/数量式）、StockCounter 库存 OCR、shop_buy 主循环
├── shop_status.py          # ShopStatus：各商店货币 OCR 并同步 LogRes
├── ui.py                   # ShopUI：标签切换（Switch）、刷新、ui_goto_shop 导航
├── shop_reward.py          # RewardShop：调度各商店的任务入口（run_frequent/run_once）
├── shop_general.py         # GeneralShop_250814：通用商店（金币+钻石）
├── shop_guild.py           # GuildShop_250814：舰队商店（舰队币）
├── shop_medal.py           # MedalShop2_250814：勋章商店（动态网格+滚动翻页）
├── shop_merit.py           # MeritShop_250814：功勋商店（未获得舰船识别）
├── shop_core.py            # CoreShop_250814：核心数据商店
├── shop_voucher.py         # VoucherShop：大世界白票商店（被 os 任务复用）
├── shop_select_globals.py  # 选择弹窗网格与 SELECT_ITEM_INFO_MAP（book/box/retrofit/plate/pr/dr）
└── shop_reward.py          # 见上，RewardShop

module/shop_event/
├── shop_event.py           # EventShop：活动商店控制器（URpt 规划、过滤）
├── clerk.py                # EventShopClerk：动态货架检测、商品定位与购买执行
├── item.py                 # EventShopItem/Grid：库存计数 OCR、按价格推断商品身份
├── selector.py             # 活动商店 FILTER 正则与预设过滤器
└── ui.py                   # EventShopUI：多标签导航、截止时间 OCR、PT/URpt 读取

```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `RewardShop.run_frequent()` | `ShopFrequent` 任务：仅通用商店，`task_delay(server_update=True)` 后结束 |
| `RewardShop.run_once()` | `ShopOnce` 任务：依次功勋 → 舰队 → 核心（月度页）→ 勋章商店 |
| `EventShop.run()` | `EventShop` 任务：遍历所有活动商店标签页执行购买 |
| `VoucherShop.run()` / `run_once()` | `OpsiVoucher` 任务购买白票商品；`OpsiArchive` 用 `run_once()` 单买一个日志档案 |
| `ShopBase.shop_get_item_to_buy(items)` | 选品决策入口：过滤器，集成测试的主要接触点 |

## 5. 核心组件

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `ShopBase` | shop/base.py | 货架识别循环 `shop_get_items`、选品 `shop_get_item_to_buy` |
| `ShopItemGrid_250814` | shop/base.py | 网格识别，为每个物品附加 group/sub_genre/tier 三属性；`ShopItem_250814` 按像素亮度判定售罄 |
| `FILTER` | shop/base.py | `Filter` 实例；正则捕获 group/sub_genre/tier 三级，如 `PlateGeneralT3`、`BookRedT3` |
| `ShopClerk` | shop/clerk.py | 购买执行：选择式 `shop_buy_select_execute`、数量式 `shop_buy_amount_execute`、主循环 `shop_buy` |
| `ShopStatus` | shop/shop_status.py | 各货币 OCR（`status_get_*`），读数同步写入 LogRes 仪表盘 |
| `ShopUI` | shop/ui.py | 250814 版顶部导航（通用/月度）与 9 个分类标签的 `Switch`；`shop_refresh()` |
| `RewardShop` | shop/shop_reward.py | 按配置 `*Shop_Enable` 调度各商店实例 |
| `EventShop` | shop_event/shop_event.py | 活动商店全流程：URpt 规划、未获取物品、过滤 |

过滤器与 `module/base/filter.py` 的关系：`Filter` 是通用的「`>` 优先级串 + 正则捕获组」引擎；商店侧只提供 `FILTER_REGEX` 与属性名 `('group', 'sub_genre', 'tier')`。`ShopItemGrid.predict` 用同一正则从模板名解析出三属性挂到物品上，`FILTER.apply(items, self.shop_check_item)` 按配置顺序输出排序后的可购列表。书籍类商品的色/级误识别由 `Book` 类二次模板匹配修正。

## 6. 工作流程

```mermaid
flowchart TD
    A[RewardShop.run_once / run_frequent] --> B[ui_goto_shop 进入军需商店]
    B --> C[shop_nav / shop_tab 切换标签]
    C --> D{该商店 Enable?}
    D -->|否| Z[跳过]
    D -->|是| E[商店子类 run]
    E --> F{filter 非空?}
    F -->|否| Z
    F --> G[shop_buy 主循环 最多 12 轮]
    G --> H[shop_get_items 截图循环识别货架]
    H --> I[shop_currency OCR 余额]
    I --> J{余额 > 0?}
    J -->|否| Z
    J --> K[shop_get_item_to_buy 选品]
    K --> L{有可购物品?}
    L -->|否| G2[购买完成]
    L -->|是| M[shop_buy_execute 状态循环<br/>点击商品 → 确认/数量/选择弹窗 → 关闭遮挡]
    M --> G
    G2 --> P{可刷新?}
    P -->|是| G
    P -->|否| Z
```

每轮 `shop_buy` 先检查外观箱、未获得舰船等特殊商品，再按 `FILTER` 优先级与实际余额选品；刷新和购买数量采用官源规则。

活动商店先扫描全部货架，再处理 UR 舰与 URpt、为未获得物品保留 PT，最后按过滤器购买普通商品。活动是否结束以商店截止日期剩余不足 7 天判断。

基础识别和购买流程采用官源。AzurPilot 保留普通商店独立开关、金币阈值及溢出买猫箱、仪表盘资源记录；大世界保留行动力专购、黄币完成状态与行动力统计。行动力专购不能更新普通黄币完成状态，也不能以其他未解锁商品判断失败。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| `alas.py`（ShopFrequent/ShopOnce/EventShop 任务） | 调用 `RewardShop` 与 `EventShop` |
| `module/os/tasks/voucher.py`、`archive.py` | 导航到白票兑换界面后调用 `VoucherShop.run()/run_once()` |

### 下游

| 模块 | 用途 |
| --- | --- |
| `module/base` | `Filter`、`ButtonGrid`、`cached_property`/`Config`、`Timer` |
| `module/statistics/item.py` | `Item`/`ItemGrid` 物品识别基类 |
| `module/ocr` | 价格、库存（X/Y）、货币余额等数字识别 |
| `module/ui` | 页面导航、`Navbar`、`Scroll`、`Switch` |
| `module/retire` | `Retirement.handle_retirement()` 处理购买触发的退役弹窗 |
| `module/tactical` | `Book` 类修正技能书颜色/等级识别 |
| `module/log_res` | 货币余额上报仪表盘 |
| `module/meowfficer` | 金币溢出时跳转指挥喵购买猫箱 |
| `module/config/redirect_utils/shop_filter.py` | 白票过滤器禁用词重定向（`voucher_redirect`） |

## 8. 数据流

```
设备截图
  → ShopItemGrid.predict（模板匹配 + OCR）
      → Item（name/cost/price + group/sub_genre/tier/售罄）
  → FILTER.apply + shop_check_item（余额）
  → shop_buy_execute 状态循环点击购买
  → ShopStatus OCR 余额 → LogRes 仪表盘 → config.update()
```

## 10. 配置

配置路径 `<Task>.<Group>.<Argument>`，代码经 `self.config.Group_Argument` 访问。商店相关任务分组（`task.yaml`）：`ShopFrequent`（GeneralShop）、`ShopOnce`（GuildShop/MedalShop2/MeritShop/CoreShop）、`EventShop`、`OpsiVoucher`/`OpsiShop`/`PrivateQuarters`。

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `GeneralShop.Enable / UseGems / Refresh / BuySkinBox / ConsumeCoins / OverflowCoins` | bool/int | false / 0 | 钻石购买、刷新、外观箱、金币阈值功能 |
| `GeneralShop.Filter` | string | BookRedT3 > ... > FoodT5 | 优先级串 |
| `GuildShop.Filter` 及 `BOX_T3/T4`、`BOOK_T2/T3`、`RETROFIT_T2/T3`、`PLATE_T2/T3/T4`、`PR1~3` | string/enum | 见 argument.yaml | 选择式商品的「买哪个」由这些键决定 |
| `MedalShop2.Enable/Filter` 及 `RETROFIT_T1~3`、`PLATE_T1~3` | 同上 | `DR > PR > ...` | 勋章商店选择配置 |
| `MeritShop.Enable/Refresh/BuyUnobtainedShip/Filter` | bool/string | false/Cube | 未获得舰船购买开关 |
| `CoreShop.Enable/Filter` | bool/string | true/Array | 核心数据商店 |
| `EventShop.UnlockSSRShip/BuyURShip/PresetFilter/CustomFilter` | bool/int/enum | true/2/all | UR 舰船购买数量、未获取 SSR、过滤器 |
| `OpsiVoucher.Filter` | string | LoggerAbyssal > ... | 经 `voucher_redirect` 重定向 |

关键关联：选择式购买（舰队/勋章商店的箱子、教材、图纸）的配置键由 `shop_get_choice` 动态拼接——`类名前缀（截取 "_" 之前）_GROUP大写_TIER大写`，如 `GuildShop_BOX_T4`、`MedalShop2_PLATE_T3`；PR 系列则按界面上检测到的 `SHOP_SELECT_PR1/2/3` 图标确定系列号后读 `GuildShop_PR2`。因此**类名与配置组名必须保持对应**。

手动配置 `SHOP_EXTRACT_TEMPLATE` 与 `EVENT_SHOP_IGNORE_DEADLINE` 位于 `config_manual.py`。

## 11. 异常与错误处理

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| `ScriptError` | 选择式商品配置键不存在、`SELECT_ITEM_INFO_MAP` 无该组、库存/数量 OCR 为 0 | 上抛终止任务，不静默重试 |
| `ItemNotFoundError`（活动商店） | 滚动位置上未找回目标商品 | `run()` 捕获后切换/刷新标签页重扫，最多 7 次 |
| `GameStuckError` | 活动商店加载超时 | 上抛，由调度器统一恢复 |
| 适配校验失败（价格伪造、超预算、超配额等） | 策略计划与真实上下文不符 | 同上，结构性失败，本轮跳过 |
| 物品加载超时 | 商店加载慢 | `shop_get_items` 超时后带当前结果继续，打 warning |

购买弹窗识别失败不会无限重试：`shop_buy` 以 12 轮为上限；余额耗尽（含策略货币投影）提前停止。

## 13. 缓存与持久化

- `cached_property` 缓存网格与物品网格对象；勋章/白票商店翻页、货架刷新后用 `del_cached_property` 强制重建（勋章商店网格随勋章图标位置变化，必须重算）。
- `ShopStatus` 每次读取货币即通过 `LogRes` 写入仪表盘并 `config.update()`。

## 14. 生命周期

调度器每轮任务创建新实例（如 `GeneralShop_250814(self.config, self.device)`），识别资源（模板、OCR 模型）由全局 Resource 注册表在任务切换时统一释放；商店自身无退出清理逻辑。活动商店在每个标签页开始时重置预留 PT，全部标签页结束后 `task_delay(server_update=True)`。

## 15. 扩展方式

新增一个常规商店：

1. 在 `module/shop/` 新建子类继承 `ShopClerk`（需要导航/刷新则加 `ShopUI`），实现 `shop_filter`（读配置）、`shop_items()`、`shop_currency()`、`run()`；购买弹窗形态不同则重写 `shop_buy_handle` 与 `shop_interval_clear`。
2. 模板放入 `assets/shop/<name>/`，运行 `uv run -m dev_tools.button_extract` 核对 `assets.py`。
3. 在 `argument.yaml`/`task.yaml`/`default.yaml` 增加配置组（`Enable`、`Filter` 及选择项），运行 `uv run -m module.config.config_updater`。
4. 在 `shop_reward.py` 的 `run_frequent`/`run_once` 中按导航标签挂接。


## 16. 修改注意事项

- **类名日期后缀是配置契约**：`shop_get_choice` 用 `self.__class__.__name__.split("_")[0]` 拼配置键，重命名 `_250814` 类会直接破坏选择式购买。
- 勋章商店货架上价格为 5000 的商品表示**尚未加载完成**（`shop_has_loaded` 据此等待）；售罄商品会自动排到货架后方，`get_soldout_count` 非零即提前终止翻页。
- `FILTER_REGEX`（`module/shop/base.py`）与活动商店 `FILTER_REGEX`（`module/shop_event/selector.py`）是两套独立正则，新商品类型需分别维护。
- 服务器差异集中在 `shop_status.py`（OCR 字色）、`shop_voucher.py`（网格坐标）与 `shop_event/item.py`（计数器裁剪），改识别前先确认目标服务器。

## 17. 已知限制

- 通用商店货币识别存在历史 bug，`shop_currency` 中的复检循环目前实际只执行一次即退出（`currency_rechecked` 逻辑近似空转）。
- 网格识别依赖固定 5 列布局与 1280×720 截图；勋章/白票商店靠图标模板动态定行，图标缺失时退回硬编码布局并告警。
- 活动商店商品名主要靠价格+库存数推断（`correct_name_and_cost`），未识别商品会保存截图等待人工补模板，不会自动购买。

## 18. 示例

常驻商店过滤器示例：`BookRedT3 > Cube > FoodT6`，按顺序购买至库存耗尽或余额不足。活动商店仅使用商品优先级过滤器，不再支持数量后缀。

## 19. 调试方法

- 打开 `config_manual.py` 的 `SHOP_EXTRACT_TEMPLATE` 可将识别到的商品图存入对应 `assets/shop/*/` 模板目录，用于补模板。
- 日志关键字：`[商店-通用]`、`[商店-购买]`、`[商店-勋章]`、`[活动商店-...]`；`logger.attr('物品排序', ...)` 输出过滤器命中顺序。
- 离线识别验证：先用隔离配置和假设备准备商店实例，再调用 `shop_detect_items(image)`。传入图片不代表正常构造商店子类不会连接设备；该方法还依赖 `shop_items()` 和配置，启用 `SHOP_EXTRACT_TEMPLATE` 时会提取模板，纯识别测试应关闭此选项。
- `module/shop/shop_reward.py` 末尾有 `__main__` 直跑入口（连真实设备）。

## 20. 相关模块

- [基础层 module/base](../base/index.md) —— `Filter`、`ButtonGrid`、`cached_property` 等公共设施。
- [大世界辅助模块](../os/auxiliary.md) —— `os_shop` 港口/明石商店，拥有独立的过滤和购买流程。
- [日常维护模块合集](daily-maintenance.md) —— 商店任务在每日/每周任务流中的位置。
- [UI 导航](../ui.md) —— 页面图谱、`Switch`/`Navbar`/`Scroll` 组件。
- [OCR 系统](../ocr.md) —— 价格、库存与货币数字识别。

### 资源收支记录

普通、凭证与大世界商店在确认购买且返回商店后，按已识别单价和实际执行数量记录支出与已知商品数量；数量由购买界面处理器独立记录，不依赖已移除的商店脚本。同一次购买已由奖励画面入账的物品不重复累计，只有信息栏或普通确认弹窗时不判定成交。活动商店可靠 PT 读数在同次任务内的减少记作支出，不当成活动重置。未知价格或数量不补成零，完整数据语义见 [资源管理](../webui/resource-management.md)。

### 旧配置兼容

商店脚本和活动商店数量后缀已移除。`migrate_shop_options` 在运行器与 WebUI 读取旧配置时统一迁移：原先启用脚本的任务暂停；数量后缀移除并保留顺序，同时暂停活动商店。用户确认普通过滤器后可重新启用。迁移不修改输入，重复加载不会再次暂停已确认的新配置；模板生成不触发迁移。
