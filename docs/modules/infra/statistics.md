# 统计与数据提交（module/statistics、module/azur_stats、module/log_res）

> 把游戏运行期产生的掉落、战斗、资源与委托数据落成本地统计库，供 WebUI 统计页、LLM 日报与遥测提交消费。

## 1. 模块概述

AzurPilot 在执行任务时天然经过大量战斗结算与资源画面。这些画面里藏着用户关心的数字：打到了什么掉落、练级效率多少、行动力循环是否为正、委托攒了多少钻石。`module/statistics` 及其两个伴生目录就是把这些瞬时画面沉淀为可查数据的统计层。

这一层由四条相对独立的链路组成：

- **掉落统计链路**：战斗结算截图经 `AzurStats` 保存或解析入库。实时侧（`azurstats.py`）在战斗结束的上下文里收集截图；离线侧（`drop_statistics.py`）对历史截图文件夹做批量模板匹配与 OCR，导出 CSV。大世界掉落（除侵蚀1练级外）在「保存」与「上传」两个档位都会解析入库，`opsi_drop_stats.py` 把它们按窗口聚合成「大世界掉落」页的金菜与彩图纸收益。
- **CL1 统计链路**：`Cl1Database` 按「实例 × 月份」记录大世界侵蚀 1（CL1）与耄耋相接的战斗、明石、行动力等指标；`Cl1DataSubmitter` 把当月汇总匿名化后提交到官方遥测端点。
- **日报链路**：`DailySummaryStore` 持续采集任务运行与侵蚀 1 战斗事件，`DailySummaryService` 在触发窗口聚合事实、调用 LLM 生成文案并经 OnePush 推送。
- **仓库快照链路**：独立 `StorageStatistics` 任务进入普通仓库材料页，两次完整扫描一致后，把指定物品数量原子保存到 `config/storage_statistics.db`。统计页面只读最近快照及成功扫描的历史趋势，刷新不启动游戏扫描。

`module/azur_stats/` 是掉落解析的场景层（原远程 AzurStats 上传的遗留名），复用 `module/statistics` 的物品识别原语；`module/log_res/` 则是资源变动的写入口，游戏代码通过属性赋值声明「资源变了」，由它决定写配置还是写快照库。

被动采集的统计不得影响游戏调度：落库失败不应中断正在进行的游戏业务。独立仓库统计则把完整性作为任务成功条件，识别或写入失败时保留旧快照、设置失败间隔并返回任务失败，不为此重启游戏。

## 2. 模块职责

### 仓库统计任务

入口为 `alas.py::storage_statistics()` → `module/storage/statistics.py`，默认关闭；可从统计页「仓库」分类手动运行，也可启用原生定时任务。任务复用 `StorageUI` 导航到材料页，不打开物品或消耗材料。

`statistics_recognition.py` 从完整方框动态定位物品，结合图标模板相似度、次优差距和稀有度底色确认身份，不读取物品名称文字。数量在图标右下角逐位匹配，并先核对全部首末位、字高、基线与间距；残缺首位不能被当成噪声删除。只有几何完整但二值字形匹配失败时，才使用 `amount_glyphs.py` 的原生灰度模板补充：以基线锚定 24×20 画布，保留抗锯齿，不随滚动后的二值包围盒变化缩放。灰度均方误差必须小于 0.006，与次优数字的差距必须大于 0.006；粘连字形仍使用已有的有界拆分，不强取灰度候选。灰度仍不确定时才尝试有限二值阈值，至少两个合格读数一致且无冲突才接受，不改变通用数字匹配门槛。

仓库专用模板位于 `assets/stats/storage_items/amount_digits.png` 和 `amount_glyphs.png`。灰度模板由 `uv run -m dev_tools.storage_amount_templates` 从人工核对的 125 个滚动数量切片与 25 个原始目录样本生成，覆盖金材料等不同原生字形。只合成横纵各四种有限采样相位，不使用 OCR 输出作标签；独立失败帧不参与生成。模板及生成机制不影响科研或大世界数字识别。

仓库目录只登记实际物品的同一身份变体，不能直接沿用共享掉落模板的别名。`PlateGeneralT4_2.png` 的 ALL 图案是定向部件 T4（Lua 30114/30900，使用后选择一类部件），与通用部件 T4（17004）不同，因此不作为仓库通用部件模板；未使用的定向道具参与未知格重叠，不折算或合并数量。

每一页稳定复读后，用唯一重叠行拼接，未知物品也参与重叠核对。已知格已经通过图标模板、次优差距和完整数量确认，按相同身份与数量核对，不再让虹彩、闪光或采样差异导致整格像素比较推翻结果；没有读出数量的已知格不能通过。未知格先匹配 RGB，再在核对稀有度底色后匹配灰度、平滑结构及去除低频背景的主体结构，四种比较均保持 0.985 门槛。主体分支以 3×3 与 31×31 灰度高斯滤波的有符号浮点差分消除虹彩渐变，保留蓝图主体和数量边缘，不能只比共同边框或把负边缘截成零。成功拼接后，重叠行更新为刚通过核对的图像，避免后续页一直比较更早的虹彩或采样相位；歧义、数量变化和未出现新行的失败路径不改已读行。首末端额外拖过边界并确认滚动条端点，半格留给下一页。到达底部才结束，再从顶部扫描一次。两次物品行和数量全部一致后，`storage_snapshot.save_snapshot()` 在单个 SQLite 事务中提交。

未运行显示「未扫描」，完整扫描未发现的目标显示未知数量，均不能推断为零。扫描或落库失败不会覆盖旧快照；数据库按实例隔离并纳入备份。目录版本包括清单、图标和数量字形，资源变化后旧快照会提示重新运行。

未知格另尝试严格读取完整数量，仅保存在 `comparison_amount` 供翻页核对，不赋予物品身份或计入清单。两格已确认数量不同立即拒绝；数量无法确认时仍可使用上述 0.985 图像分支，但不能使用强虹彩补充。只有两格完整数量独立确认一致后，补充分支才比较去背景主体：7×7 与 31×31 高斯差分，主体区 `(12, 12, 116, 100)` 排除共同边框和数量，允许 3px 对齐且相似度须达到 0.97。同数量的不同头像仍须拒绝，不能只凭数量认为是同一格。

中途在列表内精确拖动一行（178px），释放前停住手指，滚动条只用于端点与稳定性判断。不能按滑块长度推算翻页距离或追赶旧目标百分比：真实滑块长度会变化，快速滑动还有惯性，二次拖动可能越过重叠行。不支持拖拽的控制后端使用慢速滑动，禁止触发设备层「滑动后点击」的拖拽回退。

页面识别失败会记录具体物品或网格原因，并在同一个截图状态循环内围绕失败位置上下微调，最多四次；已读页面未出现新行时继续向下移动一行，每次仍须稳定复读并与已读行唯一重叠。读取窗口使用 `Timer(20, count=2)`，避免慢截图被四十次访问条件拖长；每次实际微调后重置窗口，第四次恢复也必须读取后续画面再判失败。操作间隔按每个截图帧累计，避免慢速稳定复读后首次拼接失败时，恢复计数才刚开始而窗口已经到期。首末端先移开再回到原端点，不能通过跳过首尾行完成扫描。只有页面成功稳定复读并拼接后才清除连续操作记录，失败重试仍受防连点和次数限制；页签短暂无法确认时只等待新截图，不立即把数量识别失败误报为离开仓库。

`storage_snapshot.get_storage_timeline()` 在只读连接中用单条 SQL 查询成功扫描历史，按实例、完成时间窗口与条数过滤。仓库分类复用资源趋势的指标选择、折线/K 线、采样粒度、缩放、起止时间、原始记录与导出，支持最近 1/7/30/90/365 天。图表仅使用已确认数量，不补零或在区间边缘补造点；最新清单仍展示最近完整扫描。没有历史扫描时不会创建数据库。

当前模板仅经过国服 1280×720 截图验证。离线验证入口为 `tests/test_storage_statistics.py`、`tests/test_storage_amount_glyphs.py`、`tests/test_storage_statistics_recovery.py` 和 `tests/test_storage_overlap_history.py`，覆盖仓库完整性、独立原生失败帧及采样相位、受限恢复窗口和连续三页的重叠参考图。合成相位与离线回放不能代替整仓实机验收；真实验证需指定实例与任务范围，并使用设备内置原生截图。

### 负责

- 战斗/搜索结算截图的保存（`DropRecord_SaveFolder`）与本地解析入库（SQLite `config/azurstats_local.db`）
- 物品识别原语：`Item`/`ItemGrid`/`AmountOcr`（模板匹配 + 带上限验证的数量 OCR）——商店、委托、仓库等模块都复用这一层
- CL1 月度统计库（`config/cl1_data.db`）的读写与旧数据迁移
- 侵蚀 1 遥测提交（`Cl1DataSubmitter` → `ApiClient`）
- 日报运行时事件采集、周期去重、LLM 文案生成与推送
- 资源快照记录（`resource_stats`）与资源变动入口（`LogRes`）
- 掉落截图按保留天数清理，过期后删除或备份到 `bak/`（`drop_cleanup`）
- 大世界运行期统计事件的统一落库入口（`opsi_runtime`）
- 大世界统计数据的本地存储与旧加密数据的一次性解密（`opsi_secure`）
- 离线批量掉落分析工具（`DropStatistics`，独立运行）

### 不负责

- 掉落截图的实时采集时机——由战斗/地图流程决定（`drop.handle_add()`），统计层只被动接收
- WebUI 的图表渲染与 API 编排——`module/api/statistics_service.py` 只是聚合查询本层导出的函数
- 推送通道实现——OnePush 由 `module/notify` 承担，日报只调用 `handle_notify()`
- 经验表数据本身——`LIST_SHIP_EXP` 来自 `module/os/ship_exp_data.py`
- 设备识别——`get_device_id()` 属于 `module/base/device_id.py`

## 3. 模块位置

```
module/statistics/
├── azurstats.py              # AzurStats：掉落记录提交、指挥喵 farming 汇总
├── cl1_database.py           # Cl1Database：月度统计库（单例 db）
├── cl1_data_submitter.py     # CL1 遥测提交器
├── daily_summary.py          # DailySummaryService：日报触发与生成
├── daily_summary_store.py    # DailySummaryStore：日报事件库
├── daily_summary_text.py     # 日报 system prompt
├── commission_income_stats.py# 委托收益聚合（day/week/month/interval）
├── research_drop.py          # 科研掉落解析（队列页角标读期数 + 收获帧识别）
├── research_stats.py         # 科研掉落聚合（按期 / 心智物资两种口径）
├── resource_stats.py         # resource_snapshots 快照与区间摘要
├── storage_snapshot.py       # 独立仓库扫描的完整快照与只读查询
├── ship_exp_stats.py         # ShipExpStats：战斗计时与经验效率
├── opsi_month.py             # OpsiMonthStats：月度大世界汇总与时间线
├── opsi_runtime.py           # 大世界运行期事件 → 落库的集中入口
├── opsi_drop_stats.py        # 大世界掉落聚合（部件、图纸、材料、计划及突破部件）
├── opsi_secure.py            # 大世界统计载荷的明文编解码与旧加密数据自动解密
├── drop_statistics.py        # 离线批量掉落分析（可独立运行）
├── drop_cleanup.py           # 掉落截图保留天数清理与备份
├── get_items.py / item.py / battle_status.py / campaign_bonus.py
│                             # 物品/敌人识别器（被 azur_stats 与离线分析复用）
├── amount_digits.py          # 原生数量字形匹配与有界粘连拆分
├── utils.py                  # pack/unpack、ImageError、load_folder
└── assets.py                 # 识别资源（button_extract 生成，勿手改）

module/azur_stats/
├── scene/base.py             # SceneBase：加载截图、parse_scene 骨架
├── scene/operation_siren.py  # SceneOperationSiren：大世界完整场景解析
├── image/base.py             # ImageBase：classify_server 多服务器识别
├── image/get_items.py        # 战斗结算「获得道具」识别（AutoSearchAmount 数量 OCR 也在这里）
├── image/auto_search_reward.py # 自律寻敌奖励页识别（AutoSearchItemGrid）；AutoSearchAmount 从本模块导入
├── image/opsi_reward.py / opsi_zone.py # 大世界奖励/区域识别
└── assets.py                 # 识别资源（生成文件）

module/log_res/
└── log_res.py                # LogRes：Dashboard 资源赋值入口
```

模板资源：`assets/stats_basic/`（基础物品模板，掉落统计启动时复制到用户目录）、`assets/stats/`（opsi_items、opsi_reward_items 等场景模板）。

**两个模板集不能互相顶替**：`opsi_reward_items`（自律寻敌结算页）与 `opsi_items`（获得道具页）里的图标缩放不同。`SceneOperationSiren.ITEM_TEMPLATE_FOLDER` 用的是 `opsi_items`；舰载机部件 T4 的原生弹窗变体为 `PlatePlaneT4_2.png`，通用部件、军用电子元件和彩色原型部件也有原生弹窗模板。通用装备研发图纸 `GearDesignPlanT4/T5` 与舰炮、鱼雷、防空炮、舰载机专用图纸是不同物品，名称按 Lua 物品定义确认，不能合并。

大世界掉落页固定展示部件 T4、舰炮/鱼雷/防空炮/舰载机研发图纸 SSR/UR 型、通用装备研发图纸 UR 型，以及特种钢材、军工级电子元件、HBX炸药、氟橡胶、超导铜、钛合金、机密/绝密实验计划和特装型突破部件。范围在 `opsi_drop_stats.py`，名称和稀有度在 `assets/stats/opsi_item_names.json`；这些物品进入收益、明细、记录和总计，仍受实例、时间与任务筛选。已入库的物品直接纳入查询，不重写数据库；尚未识别的数字编号不会自动改名。

实验计划模板统一按图标稀有度命名：紫色 T3、金色 T4、彩色 T5，与英文物品名称中的 T1/T2/T3 不同。获得道具页原来的 `OrdnanceTestingReportT1/T2` 模板改为 `T3/T4`，历史金计划 `OrdnanceTestingReportT2` 在展示时归入 T4，避免分成两行。两类奖励页都按底色排除错误等级的图纸、实验计划和突破部件；两种布局仅对纸类同级候选放宽匹配阈值，突破部件保持原阈值，并接收第三种 Boss 奖励布局。

新增模板来源记录在 `assets/stats/opsi_template_sources.json`。机密计划与突破部件的弹窗模板来自 `screenshots/opsi_abyssal/1790326881455.png` 和 `screenshots/opsi_month_boss/1790872111832.png` 的原始 1280×720 帧。绝密计划未在本地掉落截图及归档中找到，暂复用已有 1280×720 仓库原图中的模板并归一为 96×96；它的真实结算识别仍待获得样本后验证，不能把仓库参考图验证当作实机掉落验证。

**保留完整数量，再排除图标干扰**：科研、委托与大世界弹窗的默认数量区为 `(50, 72, 94, 94)`；大世界图纸/实验计划为 `(50, 76, 94, 94)`，作战补给凭证为 `(28, 72, 94, 94)`。自律寻敌原生 64px 格使用 `(15, 49, 63, 63)`，容纳五位凭证数量。数字由 `amount_digits.py` 按字高、基线、间距和模板逐位匹配，既保留重复数字与首尾位，也排除纸角、齿轮等残影；匹配不确定时才使用配置中的 OCR 后端。普通战斗的 `GetItemsStatistics` 默认数量区保持原值，科研通过实例属性覆盖。

**大世界的稀有度与单格上限**：白纸图标先根据金/彩/紫底色限定等级，再匹配图案；降低到 0.6 的阈值只适用于纸类候选，其他物品保持原阈值。`SceneOperationSiren` 在两种布局中均将彩色装备研发图纸和原型部件的单格数量限制为 2，多格、多帧仍按真实数量累加。特装原型是另一种物品，不能套用此上限。数量无法确认只跳过该格，保留同页其他有效物品。

**复用解析器时保留已知物品身份**：`ItemGrid` 先在达到阈值的已知模板中选择最佳匹配；只有没有合格的已知候选时，才查询数字编号的临时未知模板。前一张动画画面生成的未知模板即使与当前像素更接近，也不能覆盖已确认的物品名。

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `ModuleBase.stat`（`module/base/base.py` 的 cached_property） | 游戏任务获得 `AzurStats` 实例的唯一途径；`stat.new(genre, method=...)` 开启一次掉落记录 |
| `AzurStats.new()` → `DropImage` | 上下文管理器：战斗流程内 `drop.add()`/`drop.handle_add()` 收集截图，退出时自动 `commit()` |
| `Cl1Database.db`（模块级单例） | 各任务写入月度统计；同步方法 + `async_*` 系列（走 `async_executor`） |
| `opsi_runtime.record_*` / `start_/finish_battle_timer` | 大世界任务上报战斗、明石、吊机等事件的规范入口，避免任务代码直接写库 |
| `LogRes(config).<Res> = value` | 资源变动的声明式入口：写 `Dashboard.<Res>` 配置 + 触发资源快照 |
| `alas.py _start_daily_summary_scheduler` | 日报独立检查线程（启用时随调度器启动） |
| `statistics.report` / `statistics.refreshLoot` / `statistics.resources`（API 方法） | WebUI 统计页读取本层数据 |
| `python -m module.statistics.drop_statistics` | 离线批量掉落分析脚本 |

## 5. 核心组件

### 掉落识别（module/statistics）

| 组件 | 职责 |
| --- | --- |
| `Item` | 单个物品：模板匹配名 + 数量。名称 setter 自动剥离数字后缀（`Javelin_2` → `Javelin`）；`__eq__`/`__hash__` 基于名称，支撑两页掉落的去重合并 |
| `ItemGrid` | 物品网格：按 ButtonGrid 定位槽位，模板匹配（优先命中频率高的模板，未命中自动建数字编号新模板）+ 数量/价格 OCR + 标签颜色识别 |
| `AmountOcr` | 场景可启用逐位字形匹配和严格上限；模板不确定时回退 OCR 与碎片过滤。科研、委托、大世界超限仍无法确认时返回 0，不截断猜值；未启用的旧调用方保留原行为 |
| `DigitTemplates` | 匹配 `assets/stats/amount_digits/` 的原生普通/粗体数字模板，有界拆分粘连字形；候选接近或相似度不足时返回 `None` |
| `GetItemsStatistics` / `CampaignBonusStatistics` / `BattleStatusStatistics` | 三个离线统计器：获得物品页（1/2/3 行网格自动判断奇偶布局）、战役加成弹窗（金币数量校验截图有效性）、敌方舰队名 OCR |
| `DropStatistics` | 离线批量处理器：两步工作流（`extract_template` 提模板 → 手动重命名 → `extract_drop` 导出 CSV） |

### 实时掉落记录（azurstats.py）

| 组件 | 字段/方法 | 说明 |
| --- | --- | --- |
| `DropImage` | `save` / `local` | 两个布尔决定退出时是否存图 / 是否解析入库；`__bool__` 为 False 时整个上下文零开销 |
| `DropImage` | `handle_add(main, before)` | 处理信息栏遮挡后等待 `WAIT_BEFORE_SAVING_SCREEN_SHOT` 秒再截图加入 |
| `AzurStats` | `commit(images, genre, save, local, combat_count)` | 垂直拼接截图，save 走后台线程，local 持 `_record_lock` 同步解析 |
| `AzurStats` | `LOCAL_DB = './config/azurstats_local.db'` | 掉落明细库（opsi_items 表，带 device_id/genre/hazard_level 维度） |
| `AzurStats` | `get_meowofficer_farming()` | 从明细库重算 6 侵蚀等级的「平均黄币/轮、平均金菜/轮……」写入 `log/azurstat_meowofficer_farming.csv`，WebUI「大世界掉落」页最下面的「短猫掉落收益」表直接读取 |
| `AzurStats` | `is_opsi_drop_genre()` | 判定某个 genre 是否要解析入库：大世界任务都算，唯侵蚀1练级除外（它的收益在「大世界总结」页看） |
| `AzurStats` | `load_opsi_drop_rows()` | 按实例/时间窗口/任务读明细，供 `opsi_drop_stats.collect()` 汇总；任务范围直接由上面那套常量生成 |

大世界采集必须把同一个 `DropImage` 传入自律守护的地图事件、`interrupt_auto_search(drop=...)` 和 `map_exit(drop=...)`。隐秘海域使用 `run_auto_search(exit_map=True)`，将退出时的奖励一起提交；深渊与月度 Boss 在 `boss_clear()` 内退出。`SceneOperationSiren` 接收三种获得道具布局；单帧出现信息栏遮挡等 `ImageError` 时只跳过该帧，保留同包其他奖励。海域 OCR 失败不丢物品，展示可根据独立任务确定来源类型，但不猜海域编号或侵蚀等级。

统计页仍按金菜（部件 T4）与彩图纸（研发图纸 T5，包括通用装备研发图纸）展示。独立或共用掉落开关的任务始终可筛选；任务次数取完整时间窗口，筛选仅影响收获明细。窗口内没有这两类物品的奖励不显示在掉落记录表。`/opsi-items/` 先查 `opsi_reward_items`，缺图时回退到 `opsi_items` 同名模板；`/research-items/` 先查 `research_items`，再查 `stats_basic`。图标回退只影响展示，不改变识别模板选择。

### 大世界统计存储（opsi_secure.py）

大世界统计自 2026-10 起不再加密：载荷以明文 JSON 存放在既有列位（`cl1_data.secure_json`、`opsi_items.secure_payload`、`resource_snapshots.opsi_payload`、`daily_summary_cl1_events.secure_payload` 存 JSON 文本，`daily_summary_periods.report_text` 存正文），日志文件为普通 JSON/CSV。公共字段列与路由元数据不变；WebUI 历史展示不受影响。

旧版加密数据（`OPSIV1.`/`OPSIV2.` 前缀）由启动钩子 `initialize()` 自动解密：有界等待，超时转后台；按描述文件恢复当时的本机凭据（安装目录被移动时按安装标识找回），逐库、逐文件、含备份归档一并转成明文，并移除加密时代的触发器与辅助表。只有确认本机不再有任何密文后才删除描述文件并撤销密钥；密钥暂不可用或个别行解不开时按原样保留，读取路径按行兼容解密，后续启动自动重试，绝不丢数据。

补救与回退：若某条旧载荷**确认本机无法解密**（密钥可用但记录解不开，或凭据干净的未命中，如跨机器迁移），对应写入不再被永久冻结——原载荷原样另存到 `config/opsi_secure/unreadable-<时间戳>.json` 旁路备份后，按现状继续写入；凭据服务报错的暂时性不可用仍保持原样等待重试，不会替换还能救回的数据。

资源趋势等只使用非大世界列的查询保留 `include_opsi=False` 优化，跳过载荷解析。解密失败的行在读取时表现为缺失（显示降级），写回路径保留原载荷而不是用空值覆盖。

### CL1 月度库（cl1_database.py）

`cl1_data` 表以 `(instance, month)` 为主键，`data_json` 存整月快照。快照内的关键字段：

| 字段 | 说明 |
| --- | --- |
| `battle_count` / `akashi_encounters` / `akashi_ap` | CL1 战斗次数、明石遭遇、明石购得行动力 |
| `ap_snapshots` / `asset` | 行动力快照；资产 = 总体力 × 56.67（CL5 效率）+ 黄币 |
| `yellow_coin_snapshots` / `coins_snapshots` | 凭证分时快照（后者上限 500 条） |
| `meow_battle_raw_count` / `meow_battle_count` | 耄耋真实战斗场次 / 有效轮数（侵蚀 2-3 每轮 2 场、4-6 每轮 3 场折算） |
| `meow_hazard_stats` | 按侵蚀等级拆分的桶（次数、耗时样本、明石） |
| `siren_research_devices` | 塞壬研究装置（吊机）计数，cl1 与 meow 分源 |
| `commission_income_entries` / `running_gem_commissions` | 委托收益明细（上限 5000）与运行中钻石委托（跨月合并） |
| `research_drop_entries` | 科研掉落明细：项目代号、期数、物品（上限 5000，imgid 去重） |

关键机制：`_stats_transaction()` 用 `BEGIN IMMEDIATE` 取写锁，跨线程/进程串行化整个「读-改-写」，避免并发覆盖；`save_stats` 只做整体替换，增量修改必须走事务内方法。旧版 device_id 派生密钥的历史行在读取时解码，并在下一次写入时就地转换为载荷列明文；`OPSIV1.`/`OPSIV2.` 遗留密文由启动时的一次性解密处理。

证券历史的旧数据来源由 `cl1_legacy.read_ap_snapshots()` 在只读连接中提供，复用 CL1 的旧密钥派生和 AES-GCM 解码格式，不创建、删除或改写统计库。原实例首次升级时仅导入上海时区当月 `ap_snapshots` 中带 `ap_total` 的实际记录，再与中央认证历史合并进入持久补传队列；上月及更早月份不读取，注册时间不作为截断条件。已开户账户同样补传，数量不设 2000 条上限。同毫秒冲突以中央来源为准。当月旧统计读取失败时保留原件与重试资格，状态消息说明原因，每五分钟重试，不回滚中央历史、不阻断注册、登录及新记录同步；中央来源或补传队列的认证失败仍停止同步。迁移完成状态由实例身份和补传检查点认证，重命名保留原统计来源，复制及重建实例不继承；完成后不再读取旧库修改。没有总量的 `ap` 只表示当前行动力，不能当作证券股价。

### 日报（daily_summary*.py）

| 组件 | 说明 |
| --- | --- |
| `DailySummaryService.check_due()` | 校验触发时间格式与服务器归属，计算最近一个服务器日窗口；错过宽限期（5 分钟）则 `mark_period_skipped` 防补发，到点则 `claim_period` 原子抢占后起后台线程 |
| `build_facts()` | 聚合任务运行、资源首末值、委托收益、侵蚀 1 事件四类事实；任何读取失败降级为 `data_quality.unavailable` 的明确缺失项，模型只拿可信数据 |
| `DailySummaryStore` | SQLite `config/daily_summary.db`；`busy_timeout=50ms`——写不进就放弃，宁可在日报里标「未采集」也不让调度等锁 |
| `daily_summary_periods` | 周期状态：`generating → sending → sent / failed(配置/LLM/推送/中断)`；`skipped` 表示已错过不补发 |
| `DAILY_SUMMARY_SYSTEM_PROMPT` | 猫娘角色设定 + 术语表，要求只使用 facts 中明确的数据 |

## 6. 工作流程

### 掉落记录链路（以一次大世界自动搜索为例）

```mermaid
flowchart LR
    A[战斗/搜索流程] -->|stat.new genre, method| B[DropImage 上下文]
    B -->|结算画面出现| C[drop.handle_add<br/>处理信息栏+截图]
    C --> B
    B -->|with 退出| D[AzurStats.commit]
    D -->|save=True| E[后台线程存图<br/>screenshots/&lt;genre&gt;/]
    D -->|local=True| F[SceneOperationSiren 解析]
    F --> G[opsi_items 明细入 SQLite]
    G --> H[get_meowofficer_farming 重算 CSV]
    G --> J[opsi_drop_stats.collect<br/>统计页「大世界掉落」]
    D --> I[cleanup_drop_screenshots_if_due<br/>节流 1 小时]
```

关键分叉在 `new()` 的 `method` 参数：配置值 `do_not` 产生空的 DropImage（零开销）；大世界掉落（`is_opsi_drop_genre()` 认可的任务，侵蚀1练级除外）的 `save` 与 `upload` **都会**解析入库，区别只在要不要把截图落盘——`upload` 这个名字是远程 AzurStats 时代的遗留，现在的「上传」就是「解析入本地库、不落盘」。解析中发现只有数字代号的未识别物品时，把结算截图画上红框另存到 `screenshots/unknown_items/`，供人工补模板。

### 日报流程

```mermaid
flowchart TD
    A[日报线程每秒检查] --> B{Enable?}
    B -->|否| A
    B -->|是| C[解析触发时间/服务器<br/>计算服务器日窗口]
    C --> D{在触发窗口内?}
    D -->|错过| E[mark_period_skipped<br/>本期不补发]
    D -->|到点| F[claim_period 原子抢占]
    F --> G[后台线程 build_facts<br/>聚合 automation/resources/commission/cl1]
    G --> H[OpenAI 兼容接口生成文案<br/>最多 3 次]
    H --> I[OnePush 推送<br/>最多 3 次]
    I --> J[(daily_summary_periods<br/>sent/failed)]
    J --> K[cleanup 清理 35 天前记录<br/>超 1 天的 generating/sending 标为 interrupted]
```

事实聚合的四个来源各自独立降级：任务运行摘要来自日报库自身（调度器在任务前后打点）、资源变化来自 `resource_stats` 的窗口首末快照、委托收益来自 `cl1_db` 的按月条目、侵蚀 1 事件来自 `record_cl1_battle_event` 逐场打点。LLM 配置不完整或 OnePush 无 provider 时直接置 `failed(error_kind='configuration')`，不调用模型。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| `module/base/base.py`（ModuleBase） | 持有 `stat`（AzurStats），战斗、委托、科研、喵箱、大世界各流程用 `stat.new()` 包住结算段 |
| `module/combat`、`module/os`、`module/os_combat`、`module/meowfficer`、`module/research` | 掉落记录的主要产生方；大世界战斗还调用 `opsi_runtime` 的计时器 |
| `module/commission` | 委托结算时调 `cl1_db.add_commission_income`（含钻石委托的事务内结算）与收益截图落盘 |
| `module/shop_status` / `os_status` / `campaign_status` 等 | 通过 `LogRes` 属性赋值上报资源变化 |
| `alas.py` | 日报调度线程 + 任务运行打点 |
| `module/api/statistics_service.py` / `runtime_service.py` | WebUI 统计页的聚合查询层 |

### 下游

| 模块 | 用途 |
| --- | --- |
| `module/ocr` | `AlOcr`/`Ocr`/`Digit` 数量与地名识别 |
| `module/os/globe_zone.ZoneManager` | OCR 地图名 → 标准区域（zone_id/hazard_level）映射 |
| `module/base/api_client.py` | CL1 遥测 POST（双端点故障转移，仅含哈希 device_id） |
| `module/base/async_executor` | 所有 `async_*` 统计写入的执行器 |
| `module/notify` | 日报与委托收益推送（`handle_notify`） |
| `openai` SDK | 日报文案生成（复用 Error 任务组的 LLM 配置） |

## 8. 数据流

```
战斗结算画面
  → DropImage.add()（截图缓存）
  → commit()：pack 成长图，文件名 = 13 位毫秒时间戳
      ├─ save → {DropRecord_SaveFolder}/{genre}/{ts}.png（后台线程）
      └─ local → SceneOperationSiren.parse_scene() → DataOpsiItems
              → opsi_items 表（azurstats_local.db）→ 重算 farming CSV
              └─ 统计页「大世界掉落」= opsi_drop_stats.collect()（指定部件、图纸、材料、计划及突破部件）
              └─ 有未识别物品 → unknown_items/ 红框标注图

任务事件（alas.py 打点）          → daily_summary_task_runs
侵蚀1战斗（ShipExpStats.on_battle_end）
  ├─ source=cl1 → ship_exp_data.json 日效率 + daily_summary_cl1_events
  └─ meow 来源只进 cl1_db 耙耋桶
资源 OCR（LogRes 赋值）
  ├─ Dashboard.<Res>.Value/Record → 配置文件（WebUI 仪表盘）
  └─ 全量快照 → resource_snapshots（azurstats_local.db）

查询侧：
  statistics.report → opsi_month / commission_income_stats / research_stats / ship_exp_stats
                    / azurstats / resource_stats → metrics + series + tables
  日报窗口 → 日报库 + resource_stats + cl1_db → facts JSON → LLM
```

## 9. 状态模型

日报周期是本层唯一显式的状态机（`daily_summary_periods.status`）：

```mermaid
stateDiagram-v2
    [*] --> generating: claim_period（INSERT OR IGNORE 抢占）
    generating --> sending: 文案生成成功
    generating --> failed: 配置缺失 / LLM 三次失败
    sending --> sent
    sending --> failed: 推送三次失败
    generating --> skipped: 错过触发窗口（mark_period_skipped）
    generating --> failed: 进程中断后 cleanup 补记
```

| 状态 | 含义 |
| --- | --- |
| generating / sending | 生成中 / 推送中；进程意外退出后由 `cleanup()` 在次日改判 `failed(error_kind='interrupted')`，不补发 |
| sent / failed | 终态；`error_kind` 区分 configuration / llm / notify / internal / interrupted |
| skipped | 已错过窗口，防止进程恢复后补发旧日报 |

## 10. 配置

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `Alas.DailySummary.Enable` | checkbox | false | 日报开关；关闭时调度器不创建任何日报线程与存储 |
| `Alas.DailySummary.TriggerTime` | str | "20:00" | 触发时刻（服务器时区，24 小时制 HH:MM），由 `parse_daily_summary_trigger` 校验 |
| `Alas.DropRecord.SaveFolder` | str | ./screenshots | 掉落截图根目录（按 genre 分子目录） |
| `Alas.DropRecord.RetentionDays` | int | 0 | 截图保留天数，0 = 不清理 |
| `Alas.DropRecord.BackUpMethod` / `ZipMethod` | option | zip / zip | 过期截图的处理方式（delete / zip / copy）与压缩格式（bz2 / gzip / xz / zip）；备份落在各来源目录下的 `bak/` |
| `Alas.DropRecord.CombatRecord` / `ResearchRecord` / `CommissionRecord` | option | do_not | 各场景掉落记录方式（do_not / save / upload / save_and_upload） |
| `Alas.DropRecord.OpsiHazard1Leveling` / `OpsiMeowfficerFarming` / `OpsiDaily` / `OpsiObscure` / `OpsiAbyssal` / `OpsiStronghold` / `OpsiExplore` / `OpsiOther` | option | upload | 大世界掉落记录方式，按任务拆分（前七项依次为侵蚀1练级、耄耋相接、大世界每日、隐秘海域、深渊海域、塞壬要塞、每月开荒）：跨月每日跟大世界每日、档案坐标跟隐秘海域、月度Boss跟深渊海域共用开关，`OpsiOther` 兜底没列出的任务；运行期由 `opsi_drop_record(config)` 按 `config.task.command` 取用。除侵蚀1练级外，`save` / `upload` / `save_and_upload` 都会解析入库（区别只在要不要把截图落盘），侵蚀1练级只落盘截图、不入掉落统计 |
| `Alas.DropRecord.CommissionIncomeScreenshot` | option | save | 委托收益截图开关 |
| `Alas.DropRecord.ResearchRecord` | option | do_not | 科研掉落截图开关；`save` / `upload` / `save_and_upload` 都会统计（区别只在要不要把截图落盘） |
| `Alas.DropRecord.TelemetryReport` | bool | true | CL1 遥测提交开关（hazard_leveling 里检查） |
| `Alas.Error.LlmApiKey/LlmApiBase/LlmModel` | str | "" | 日报 LLM 配置（与错误上报共用） |
| `Alas.Error.OnePushConfig` | str | "" | 推送通道配置 |

关联关系：日报的 LLM 与推送配置刻意复用 `Error` 组，避免两套密钥；掉落记录各场景开关决定 `DropImage.save/local`。除侵蚀1练级外，大世界任务的 `save` / `upload` / `save_and_upload` 均本地解析，`do_not` 不统计。日报线程不持有完整配置对象——`alas.py` 只传 `SimpleNamespace` 快照并按配置文件 mtime 热读，避免与任务线程争用配置对象。

## 11. 异常与错误处理

| 异常/失败 | 原因 | 处理 |
| --- | --- | --- |
| `ImageError` 族（GetItemsInvalid、OpsiZoneInvalid…） | 截图不是预期结算页 / 信息栏遮挡 | `commit`/离线解析捕获后记 warning 跳过该截图，不影响战斗流程 |
| 掉落数量为 0 或仍超上限 | 数字不完整、图标残影或字形不确定 | 科研、委托、大世界按格记 warning 并跳过，保留同页其他掉落及原截图；不截断猜值 |
| SQLite 锁竞争 | WebUI 线程与调度线程并发写 | 日报库 `busy_timeout=50ms` 快速失败 + 内存暂存降级事件；CL1 库用 `BEGIN IMMEDIATE` 串行化 |
| 日报数据库写失败 | 磁盘/锁异常 | 记入 `daily_summary_collection_gaps`，该周期日报标「数据不完整」 |
| LLM 空响应 / 调用失败 | 网络、配额 | 最多 3 次重试，仍失败置 `failed(error_kind='llm')`，本期不发送 |
| OnePush 失败 | 配置错误、服务不可达 | 同一文案重发 3 次，仍失败置 `failed`，不重试整期 |
| 遥测提交失败 | 网络不通 | 仅 debug 日志，下个 10 分钟窗口再试 |

原则：**统计链路的异常一律不向游戏调度传播**。`record_task_start/finish`、资源快照、战斗计时等都有 try/except 包裹；只有 `Cl1Database.save_stats` 这类显式写接口会把异常传给调用方（由调用方决定回滚语义）。

## 12. 并发与线程模型

统计层被至少四类线程同时访问：游戏任务线程（同步写）、`async_executor` 工作线程（异步写）、日报后台线程（生成与推送）、WebUI 工作线程（查询）。

侵蚀1明石遭遇由 `opsi_runtime.record_cl1_akashi_encounter()` 提交到串行异步队列，并返回写入 Future，主游戏流程不做同步回读。`increment_akashi_encounter(instance, month=None)` 在事务提交后返回实际累计次数；传入事件发生月份避免跨月排队计入下个月。完成回调只在提交成功后打印累计次数，失败记录异常并保留事务回滚；进程正常退出沿用异步执行器的队列刷新。

耄耋相接同样通过 `record_meow_akashi_encounter()` 返回写入 Future。`increment_meow_akashi_encounter(instance, hazard_level, month=None)` 保留侵蚀等级分桶，提交后才返回该桶累计次数；月份在事件入队时固定，回调打印实际次数或记录写入异常。任务的 `_meow_record_akashi_if_solved()` 消费已解决的明石标记，避免后续轮次重复计数。该链路原本已异步，本次语义是确认实际落库，不增加游戏主线程等待。

| 对象 | 保护方式 |
| --- | --- |
| `Cl1Database` | 每次读改写都在 `_stats_transaction()`（`BEGIN IMMEDIATE`）内完成，跨线程与跨进程串行化；不依赖调用方持锁。跨月结算在一个事务里同时写来源月与归档月 |
| `AzurStats` | `_record_lock` 串行化本地解析（解析是 CPU 密集的 OCR），`_local_lock` 串行化 SQLite 插入；save 单独开短命线程避免阻塞战斗 |
| `DailySummaryStore` | `RLock` + 每次操作新建短连接（`_ClosingConnection` 立即释放，防 Windows 文件锁残留）；采集失败先缓存内存、下次可写时补记 |
| `DailySummaryService` | `_lock` 保护 `_active/_processed_periods` 集合；周期幂等性主要靠数据库 `claim_period` 的 INSERT OR IGNORE，进程内集合只是去重快路径 |
| `resource_stats` / `_loot_lock` | 模块级锁串行化快照写入与 farming 重算 |
| 日报线程生命周期 | 由 `alas.py` 的调度器 loop 启停；`check_due` 里启动的生成线程是 daemon，异常全部隔离在 `_generate_and_send` 内 |

## 13. 缓存与持久化

| 存储 | 内容 | 写入时机 | 清理 |
| --- | --- | --- | --- |
| `config/azurstats_local.db` | `opsi_items` 掉落明细 + `resource_snapshots` 资源快照 | 每次 commit / LogRes 资源变化 | 不自动清理明细 |
| `config/opsi_secure/` | 旧加密环境的描述文件与凭据状态 | 仅历史版本产生 | 全部旧密文解密成功后自动移除 |
| `config/cl1_data.db` | CL1 月度统计（instance×month） | 各 `async_*` 方法即时写 | 快照列表内部截断（500/5000 条） |
| `config/storage_statistics.db` | 按实例保存完整仓库物品快照 | `StorageStatistics` 两次完整扫描一致后原子提交 | 保留已完成扫描 |
| `config/daily_summary.db` | 日报任务事件、周期状态、采集缺口 | 任务前后、战斗结束、日报流程 | `cleanup()` 保留 35 天 |
| `log/azurstat_meowofficer_farming.csv` | farming 汇总 | 每次本地解析成功后重算 | 覆写 |
| `log/cl1/<instance>/ship_exp_data.json` | 战斗耗时样本、每日经验、升级进度 | 每场战斗结束 | 样本 100 条 / 日统计 30 天 |
| `screenshots/<genre>/`、`log/commission_rewards/<instance>/<月份>/` | 掉落与委托截图 | commit / 委托结算 | `DropRecord_RetentionDays` 天数清理（节流 1 小时），过期后按 `DropRecord_BackUpMethod` 删除 / 拷贝备份 / 压缩备份到 `bak/` |

CL1 库的兼容性迁移是自动的：启动时把旧位置 `log/cl1/cl1_data.db` 移入 `config/`；旧 JSON 与 `.bak` 在原路径保存明文载荷。每日备份对四个数据库做普通 SQLite 复制，备份是可直接打开的明文库。

## 14. 生命周期

`Cl1Database.db`、日报 `DailySummaryStore`、遥测提交器 `_submitters` 都是进程级单例，随首次 import 惰性创建，无显式销毁。`AzurStats` 不是单例——每个 `ModuleBase` 持有自己的实例（只封装 config），共享的锁在类属性上。日报线程随调度器 `loop()` 启动、更新事件或进程退出时通过 `_stop_daily_summary_scheduler` 停止；日报关闭的实例从初始化起就不创建任何线程与数据库连接。

## 15. 扩展方式

新增一项月度统计（以「塞壬研究装置」为参照）：

1. 在 `cl1_database.py` 的 `_empty_data()` 加默认字段，新增 `add_xxx`/`get_xxx` 方法——读改写必须包在 `_stats_transaction()` 里，并按需提供 `async_` 包装。
2. 在 `opsi_runtime.py` 加运行期入口（或在对应任务里直接调用），任务代码只上报领域事件。
3. 在 `module/api/statistics_service.py` 的对应 category 里把指标加进 `report()` 输出；API 模型变更后运行 `uv run python -m dev_tools.export_api_schema`。
4. 需要进日报时，在 `DailySummaryService.build_facts()` 的 facts 里补字段并在 prompt 术语表加映射。

新增掉落识别模板：把结算截图交给 `DropStatistics.extract_template()` 提取，人工重命名后放回对应场景的模板目录；图纸、实验计划和突破部件的稀有度由 `AutoSearchItemGrid.match_candidates` 按底色限定，新等级需要同时补 `TIER_BY_COLOR` 可识别的底色。新增物品同时检查 `opsi_drop_stats.py`、名称表、静态图标及五种语言的 `stats.lootHint`；回归入口为 `tests.test_opsi_drop_stats`、`tests.test_opsi_item_recognition` 和前端「大世界掉落展示新增」模拟服务测试。

## 16. 修改注意事项

- **不要在任务代码里直接写 `cl1_db`**。大世界事件的落库口径（侵蚀等级折算、轮次闭合、来源判定）集中在 `opsi_runtime.py`，绕过它会产生口径分裂的统计。
- **正常代码升级不得清空统计**：新增保护字段、变更身份或格式必须先实现兼容迁移；未完成迁移或普通故障绝不能删除数据；唯一允许的自动删除是「旧密文已全部解密成功」后的描述文件清理。
- **`ItemGrid` 是被多处共享的单例状态**（`get_items.ITEM_GROUP` 是模块级实例）：`GetItemsStatistics`、`CampaignBonusStatistics`、`azur_stats.GetItems`、商店与仓库都改它的 `grids/item_class/similarity`。新增使用方时必须在使用前完整设置这些属性，如同 `_stats_get_items_load` 所做的那样，否则会带着上一场景的网格布局去匹配。数量侧同理：`amount_area` / `amount_area_rules` / `amount_ocr` / `amount_max` 都是按场景设置的，`azur_stats.GetItems` 会把前三个一起设好。
- **删除是不可逆的**：`drop_cleanup` 只处理文件名匹配 `^\d{13}(_.+)?\.png$` 的文件，配置异常时按 0 处理（不清理）；`bak/` 内的备份不参与扫描（拷贝备份保留原修改时间，只看时间会被反复处理），压缩或拷贝失败时保留原文件。改清理逻辑时保持这些保守默认。
- **日报的 `period_key` 含服务器与时区信息**，改动 `get_daily_summary_window` 的窗口语义会让已存在库里的 period_key 失配，导致重复推送。
- **数量识别先用真实切片回归**：`amount_digits` 的字形阈值、粘连拆分与 `remove_small_fragments` 的 OCR 兜底均需覆盖原生数字；不要把 OCR 旧输出作为真值，也不要凭删首位或末位修正超限值。回归包含重复数字、五位凭证、纸角和粗体图纸数字。
- **遥测提交只发聚合指标**（battle_count/明石次数 + MD5 前缀 instance_id），不要往 `calculate_metrics` 里加可识别个人的字段。
- `module/statistics/assets.py` 与 `module/azur_stats/assets.py` 是 `dev_tools.button_extract` 的生成物，改按钮资源后重新生成，不要手改。
- **科研的期数只能看队列页卡片的罗马数字角标**（`research_drop._read_series`，复用 `module/research/series.py` 的模板）。项目代号在每一期都存在、判不了期；掉落物也判不了——只有彩装备与舰船图纸绑期数，金装备各期混着出，项目还会「额外赠送」别期的图纸。
- **科研的列剖面只用于图纸的 OCR 兜底**：先匹配完整数量字形，图纸纸角粘连且完整匹配不确定时可核对最右单字；末位为 0 不返回单字数量，保留真实的 10。神经 OCR 兜底仅在上限 ≤10 时取最右数字簇，读空时提高阈值重读，仍超限则跳过本格。物资、心智单元不能按图纸切列，避免三位数丢失首位。
- **心智单元不属于任何一期**：它有自己的「心智/物资」视图，也不计入每期的总收益。两个视图**共用同一套版式**（收益卡片 + 收获明细 + 掉落记录，只是心智/物资不分期）。**金装备已不再统计**（2026-09-24 撤掉原「金装统计」视图：它各期混着出、不绑期数，图标又与彩装备相近，容易被认成彩装）。`research_stats.should_show()` 按 `scope` 分这两套口径。
- 科研模板的新增/重命名走 `dev_tools/research_template_extract.py`（从游戏 Lua 数据推导仓库命名，含底色变体与 `{namecode:XXX}` 占位符处理），不要手裁素材。
- **模板改名只改了模板，改不动库里已写入的记录**：记录里存的是模板文件名，显示时才按名称表翻译，所以旧记录会张冠李戴（实测把「四联装610mm鱼雷」显示成八期彩装、把九期彩装 Ta 152C 显示成四期天雷）。名字级的历史映射救不了——一个旧名可能同时盖住两件不同装备——只能用原截图重放：`dev_tools/research_drop_repair.py`（只覆盖 `items`，不动期数与项目代号，动库前先备份）。

## 17. 已知限制

- `AzurStats` 的远程上传路径已废弃；大世界 `upload` 表示本地解析、不保存截图，侵蚀1练级除外。
- `AzurStats.get_meow_loot_monthly_totals` / `get_meow_loot_available_months` 目前在仓库内没有调用方，属于预留接口。
- 委托收益条目没有「已检查但零结算」的心跳记录，日报侧只能把空列表标为 `available=False` 而非零收益（`commission_income_stats` 有注释说明）。
- 遥测域名 `ApiClient.PRIMARY_DOMAIN` 与 `FALLBACK_DOMAIN` 当前相同，故障转移实际未生效。
- farming CSV（`azurstat_meowofficer_farming.csv`）是全量重算而非增量，明细库很大时刷新会变慢。
- `drop_statistics.py` 离线分析依赖手动重命名模板与改脚本常量，没有命令行参数化。
- 科研模板库还缺 1~5 期几艘船的图纸（一期路易九世、三期柴郡、四期奥古斯特·冯·帕塞瓦尔与马可波罗、五期鲁普雷希特）：没有模板的掉落会在解析阶段被跳过，所以按期视图里看不到这几艘。

## 18. 示例

最小掉落记录路径（任务代码侧的全部参与方式）：

```python
# ModuleBase 子类里，用配置开关包住一次自动搜索
# 记录方式按当前任务取（opsi_drop_record），智能调度等代理执行时读到的是子任务的开关
with self.stat.new(
    genre=inflection.underscore(self.config.task.command),
    method=opsi_drop_record(self.config),
) as drop:
    combat = self.os_auto_search_run(drop)   # 结算画面出现时 drop.handle_add(main=self)
    drop.set_combat_count(combat)
```

写入一条月度统计（运行期入口模式）：

```python
# 任务代码只声明事件
record_siren_research_device(self)          # opsi_runtime 内部决定来源与等级并异步落库
```

## 19. 调试方法

- 日志前缀：`[统计-物品]`（识别修正）、`[统计-资源]`、`[统计-经验]`、`[统计-大世界]`（运行期事件）、`[统计-解密]`（旧加密数据自动解密）、`[日报]`（日报全链路）、`[掉落记录]`（清理）、`[基础-API]`（遥测提交）。`logger.attr('CL1单轮耗时', ...)` 等属性行适合 grep 单轮耗时。
- 本地调试服务：`ALAS_DEBUG_SERVER=1` 启动调度器后，`module/debug/commission_debug.py` 可以不开游戏注入伪造委托收益并触发推送，验证统计口径与推送链路。
- 测试：`tests/test_statistics_amount_digits.py` / `test_item_amount_area.py`（真实数量切片、严格上限、裁剪边界与单格失败保留其余物品）、`tests/test_statistics_transactions.py`（CL1 事务与并发）、`tests/test_daily_summary*.py`（日报窗口与聚合）、`tests/test_drop_cleanup.py`（清理与 `AzurStats.new` 节流）、`tests/test_archive.py`（删除/拷贝/压缩三种过期处理方式）、`tests/test_commission_settlement.py`、`tests/test_research_stats.py` / `test_research_drop.py` / `test_research_drop_repair.py`（科研口径、角标识别与记录订正）。
- 数据核查入口：直接用 sqlite3 打开 `config/cl1_data.db`（明文 JSON）、`config/azurstats_local.db`、`config/daily_summary.db`； farming 汇总看 `log/azurstat_meowofficer_farming.csv`。科研记录里出现「当前 `assets/stats/research_items/` 与名称表都没有的模板名」基本就是模板改名残留，用 `dev_tools/research_drop_repair.py` 拿原截图重放订正。
- 未识别物品：检查 `screenshots/unknown_items/` 下的红框标注图，补模板后重跑 `DropStatistics.extract_template`。

## 20. 相关模块

- [调度器（alas.py）](../entry/alas.md)——日报调度线程、任务运行打点的宿主
- [API 服务](../webui/api.md)——`statistics_service` 的 6 类报表与 `statistics.refreshLoot`
- [通知、LLM 与日志](notify-llm-logger.md)——`handle_notify` 推送通道与 LLM 配置复用
- [战斗系统](../combat.md)——`combat()` 是掉落截图最主要的产生方
- [大世界核心](../os/index.md)——CL1/耄耋相接任务与 `opsi_runtime` 事件的来源
- [委托系统](../game/commission.md)——委托收益识别、截图落盘与钻石委托结算的调用方
- [异步执行器与工具](../base/decorator-utils.md)——`async_executor` 的行为
