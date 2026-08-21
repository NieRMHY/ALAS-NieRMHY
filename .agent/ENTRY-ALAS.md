---
description:
alwaysApply: true
---

# alas.py 入口文件深度分析

## 1. 文件基础信息

| 项目 | 内容 |
|---|---|
| 文件路径 | `alas.py` |
| 总行数 | 1568 行 |
| 文件类型 | Python 脚本（主入口 + 核心调度器类） |
| 许可证 | GPL-3.0 |
| 修改注释 | 基于原版增加了自动尝试重启调度器的功能（rev: auto_restart, Last Updated: 2025-09-01） |
| 最后分析 | 2026-08-14（dev 分支，commit f992af6c0） |

### 导入依赖

| 模块来源 | 具体导入 | 用途 |
|---|---|---|
| 标准库 | `json`, `os`, `re`, `shutil`, `threading`, `time` 及 `from datetime import datetime, timedelta` | 文件操作、正则、线程、时间（`subprocess`/`tempfile` 在方法内按需导入，非顶层） |
| 第三方 | `inflection` | 驼峰/下划线命名转换（任务名 -> 方法名） |
| 第三方 | `cached_property` | 惰性属性缓存 |
| 项目内部 | `module.base.decorator.del_cached_property` | 清除缓存属性 |
| 项目内部 | `module.base.api_client.ApiClient` | Bug 日志上报 |
| 项目内部 | `module.base.ssh.clear_ssh_host_key` | 远程 SSH 执行前清除已知主机密钥 |
| 项目内部 | `module.config.config.AzurLaneConfig, TaskEnd` | 配置系统 |
| 项目内部 | `module.config.deep.deep_get, deep_set` | 嵌套字典操作 |
| 项目内部 | `module.config.time_source.now as current_time` | 统一时间源 |
| 项目内部 | `module.config.utils` | `DEFAULT_CONFIG_NAME`、`ensure_time`、`filepath_i18n`、`get_server_last_update`、`get_server_next_update`、`read_file` |
| 项目内部 | `module.exception.*` | 全部自定义异常类（通配符导入） |
| 项目内部 | `module.logger.logger` | 日志系统 |
| 项目内部 | `module.notify.handle_notify, notify_webui` | 推送通知 |

---

## 2. 模块级全局变量与函数

### 2.1 `_i18n_task_names` 缓存 (L31)

```python
_i18n_task_names = None
```

全局模块级缓存，用于存储 i18n 任务名称映射字典。首次调用 `_get_task_display_name()` 时从文件加载并缓存。

### 2.2 `_get_task_display_name(task_command)` (L32-L57)

```python
def _get_task_display_name(task_command):
    """从 i18n 获取任务的本地化显示名，找不到则返回英文名"""
```

- **功能**: 根据任务命令名获取本地化显示名称
- **参数**: `task_command` (str) - 任务命令名（如 `'Research'`）
- **返回**: `str` - 本地化名称或原始命令名
- **执行流程**:
  1. 首次调用时，从 `config/deploy.yaml` 读取语言设置（默认 `zh-CN`）
  2. 加载对应的 i18n JSON 文件，提取 `Task` 节点下的 `name` 字段
  3. 构建 `{command: display_name}` 映射并缓存到 `_i18n_task_names`
  4. 后续调用直接查缓存
- **设计模式**: 模块级单例缓存模式
- **容错**: 所有异常均被静默捕获，失败时返回原始命令名

### 2.3 重启敏感任务机制（原 `RESTART_SENSITIVE_TASKS` 常量已删除）

> **注意**：旧版本中 `RESTART_SENSITIVE_TASKS = ['Commission', 'Research']` 常量已被移除。

当前实现改为动态判断：`Error_StrictRestart`（默认关闭，`config/template.json`）启用时，结合 `{task}.Scheduler.Sensitive` 配置项决定是否触发严格重启行为。敏感任务出错时直接停止（`exit(1)`），不做任何重启。代码中有两处判断：

- `run()` 内每个异常分支都会先调用 `_check_sensitive_exit()`（alas.py L233-L271）：通过 `inflection.camelize(command)` 还原任务名，读取 `{task}.Scheduler.Sensitive`，为真时记录错误现场、推送 onepush + webui 通知并 `exit(1)`；
- `loop()` 的失败计数检查（alas.py L1431-L1455）：`Error_StrictRestart && 连续失败 >= 1 && {task}.Scheduler.Sensitive` 时上报 bug 日志（`ApiClient.submit_bug_log`）并退出。

`config/template.json` 中默认 `Sensitive: true` 的任务为 `OpsiCrossMonth`、`OpsiAbyssal`、`OpsiObscure`（原 `['Commission', 'Research']` 已不适用）。

---

## 3. `AzurLaneAutoScript` 类分析 (L62-L1564)

### 3.1 类定义与类属性

```python
class AzurLaneAutoScript:
    stop_event: threading.Event = None
```

- **类型注解**: `stop_event` 是类级别的 `threading.Event`，用于从外部（如 GUI 进程）通知调度器停止
- **设计**: 类属性默认为 `None`，由 GUI 层在创建实例时注入

### 3.2 `__init__(self, config_name=DEFAULT_CONFIG_NAME)` (L65-L78)

```python
def __init__(self, config_name=DEFAULT_CONFIG_NAME):
```

- **参数**: `config_name` (str) - 配置实例名称，默认取 `module.config.utils.DEFAULT_CONFIG_NAME`（即 `'alas'`）
- **初始化状态**:
  - `self.config_name` - 配置实例名
  - `self.is_first_task` (bool) - 标记是否为首次任务（用于跳过启动时的 Restart）
  - `self.failure_record` (dict) - 任务失败计数器 `{task_name: failure_count}`
  - `self.consecutive_game_stuck` (int) - 连续游戏卡死次数
  - `self.consecutive_adb_offline` (int) - 连续 ADB 离线次数
  - `self.script_error_count` (int) - `ScriptError` 连续计数，达到 3 次后退出（代码 bug 重试无意义）
  - `self.last_emulator_restart_time` (float) - 上次计划重启模拟器的时间戳（`time.monotonic()`）

---

### 3.3 惰性缓存属性

三个缓存属性初始化失败时均通过 `logger.error_context` 记录错误并 `exit(1)` 终止（`RequestHumanTakeover` 同样终止）；`device`/`checker` 在方法内惰性导入，避免启动时就建立设备连接。

#### `config` (L172-L192)

```python
@cached_property
def config(self):
    config = AzurLaneConfig(config_name=self.config_name)
    return config
```

- **类型**: `AzurLaneConfig`
- **惰性加载**: 首次访问时从 `config/{config_name}.json` 加载配置
- **错误处理**: `RequestHumanTakeover` 致命退出，其他异常记录后退出

#### `device` (L195-L216)

```python
@cached_property
def device(self):
    from module.device.device import Device
    device = Device(config=self.config)
    return device
```

- **类型**: `Device`（多重继承：`Screenshot + Control + AppControl + Input`）
- **惰性导入**: 内部导入避免启动时就连接设备
- **依赖**: 需要 `self.config` 先初始化

#### `checker` (L219-L231)

```python
@cached_property
def checker(self):
    from module.server_checker import ServerChecker
    checker = ServerChecker(server=self.config.Emulator_ServerName)
    return checker
```

- **类型**: `ServerChecker`
- **功能**: 游戏服务器可用性检查器，调用外部 API 检测服务器状态

---

### 3.4 核心方法 `run(self, command, skip_first_screenshot=False)` (L273-L561)

```python
def run(self, command, skip_first_screenshot=False):
```

**这是整个调度器的任务执行核心方法。**

- **参数**:
  - `command` (str) - 任务方法名（下划线格式，如 `'research'`；由 `loop()` 通过 `inflection.underscore(task)` 转换）
  - `skip_first_screenshot` (bool) - 是否跳过首次截图
- **返回值**:
  - `True` - 任务成功完成
  - `False` - 任务失败且不可恢复（计入失败限制）
  - `'recoverable'` - 任务失败但可恢复（不计入失败限制）

**执行流程**:
1. 截图（除非 `skip_first_screenshot=True`）
2. 通过 `self.__getattribute__(command)()` 动态调用对应任务方法
3. 根据异常类型进行分级错误处理（每个分支先调用 `_check_sensitive_exit()` 判断是否为敏感任务）

**异常处理矩阵**（当前版本调度器"永不主动退出"，绝大多数错误都转为 `'recoverable'` 自动恢复）：

| 异常类型 | 处理策略 | 返回值 | 是否通知 | 是否重启 |
|---|---|---|---|---|
| `TaskEnd` | 正常结束 | `True` | 否 | 否 |
| `GameNotRunningError` | 注入 Restart 任务自动恢复 | `'recoverable'` | 是 (onepush + webui) | 游戏重启 |
| `GameStuckError` / `GameTooManyClickError` | 保存日志；`Error_GameStuckRestart` 启用时按 `Error_GameStuckThreshold` 计数，达到阈值重启模拟器；否则重启游戏 | `'recoverable'` | 是 | 游戏/模拟器重启 |
| `GameBugError` | 重启游戏修复客户端 bug | `'recoverable'` | 是 | 游戏重启 |
| `GamePageUnknownError` | 检查服务器状态；可用则重启游戏，不可用则等待服务器恢复 | `'recoverable'` / `False` | 是 | 视情况 |
| `ScriptError` | 连续 3 次后 `exit(1)`（代码 bug 重试无意义），否则重启恢复 | `'recoverable'` / `exit(1)` | 是 | 重启游戏 |
| `EmulatorNotRunningError` | 始终尝试重启模拟器（失败也不退出） | `'recoverable'` | 是 | 模拟器重启 |
| `RequestHumanTakeover` | 尝试通过重启模拟器自动恢复（不再直接终止） | `'recoverable'` | 是 | 模拟器重启 |
| `AutoSearchSetError` | 重启游戏恢复 | `'recoverable'` | 是 | 游戏重启 |
| 其他 `Exception` | 尝试重启模拟器恢复 | `'recoverable'` | 是 | 模拟器重启 |

**关键设计点**:
- `'recoverable'` 返回值不计入失败次数限制，这是可恢复错误的核心机制
- `GameStuckError` 和 `GameTooManyClickError` 有专门的连续卡死计数器（`consecutive_game_stuck`），达到 `Error_GameStuckThreshold`（默认 3）时尝试重启模拟器而非仅重启游戏
- `RequestHumanTakeover` 由"直接退出"改为"重启模拟器自动恢复"，符合调度器永不主动退出的整体策略
- 敏感任务（`Sensitive=True`）在任一分支都会被 `_check_sensitive_exit()` 拦截并直接 `exit(1)`
- 所有错误处理路径都包含 `handle_notify`（onepush 推送）和 `notify_webui`（WebUI 通知）双重通知

---

### 3.5 `_try_restart_emulator(self)` (L80-L139)

```python
def _try_restart_emulator(self):
```

- **功能**: 尝试重启模拟器，**永不放弃，一直重试**
- **前置条件**: 无（不再受 `Error_AdbOfflineRestart` 开关限制，超过阈值仅增加等待间隔）
- **返回**: `bool` - 重启成功返回 `True`；失败返回 `False`（调度器会继续尝试）
- **执行流程**:
  1. 递增 `consecutive_adb_offline` 计数器，输出 `连续次数/Error_AdbOfflineThreshold`
  2. 超过阈值 `Error_AdbOfflineThreshold`（默认 3）时不放弃，仅增加等待间隔 `min(300, 30 * (次数 - 阈值 + 1))` 秒后继续重试
  3. 优先复用已缓存的 `self.device` 对象（含 `emulator_instance` 缓存）
  4. 若 device 缓存不存在，根据平台回退创建 `PlatformWindows` 或 `PlatformMac`
  5. 调用 `device.emulator_stop()` -> sleep(5) -> `device.emulator_start()`
  6. 成功后 `del_cached_property(self, 'device')` 强制重建连接，并重置 `consecutive_adb_offline`
  7. 失败时通过 `logger.exception_context` 记录原因并返回 `False`
- **平台适配**: 区分 `sys.platform == 'darwin'` (macOS) 和其他平台 (Windows)
- **关联方法**: `_start_emulator_after_long_wait()` (L141-L169) 是省资源模式（长时间等待关闭模拟器后）的显式启动恢复路径，同样不受开关与次数限制

---

### 3.6 `keep_last_errlog(self, folder_path, n=30)` (L563-L579)

```python
def keep_last_errlog(self, folder_path, n: int = 30):
```

- **功能**: 保留错误日志目录中最后 n 个子文件夹，删除旧的
- **参数**: `folder_path` (str) - 目录路径, `n` (int) - 保留数量（默认 30，对应 `Error_SaveErrorCount`）
- **行为**: `n <= 0` 时不执行任何操作

### 3.7 `save_error_log(self)` (L581-L640)

```python
def save_error_log(self):
```

- **功能**: 保存错误现场（截图 + 日志）到 `./log/error/<config-name>/<timestamp>/`，同时触发 LLM 错误分析
- **执行流程**:
  1. **LLM 分析优先**: 如果启用了 `Error_LlmAnalysis` 且 `sys.exc_info()` 存在异常，先调用 `module.llm.analyze_exception()` 进行 AI 错误分析（避免后续保存截图时二次崩溃导致分析未执行）
  2. **截图保存**: `Error_SaveError` 启用时，从 `device.screenshot_deque` 获取最近截图（仅当 device 已初始化），进行敏感信息遮罩后保存
  3. **日志保存**: 读取日志文件，提取最后一个 `═` 分隔线之后的内容，进行敏感信息遮罩后保存为 `log.txt`
  4. **清理旧日志**: 调用 `keep_last_errlog()` 按 `Error_SaveErrorCount`（默认 30）限制日志数量

**安全性**: 使用 `handle_sensitive_image` 和 `handle_sensitive_logs` 处理敏感信息

---

### 3.8 基础任务方法 (L642-L706)

#### `restart()` (L642-L647)
```python
def restart(self):
    if self.delay_due_restart():
        return
    LoginHandler(self.config, device=self.device).app_restart()
    self.delay_next_restart()
```
重启游戏应用：先检查每日重启是否命中服务器刷新整点（`delay_due_restart()`，命中则按 `Restart_RandomDelay` 随机延后），再执行 `app_restart()`，最后用 `delay_next_restart()` 安排下一次重启时间。

延迟控制方法（每日重启随机延后机制，读取 `Restart_RandomDelay` 与 `Scheduler_ServerUpdate`）：
- `restart_random_delay_minutes()` (L649-L660) - 获取每日重启的随机延后分钟数
- `delay_due_restart()` (L662-L683) - 把排在服务器刷新整点的重启改排到随机延后时间
- `delay_next_restart()` (L685-L691) - 将下一次每日重启延后到服务器刷新后的随机时间

#### `start()` (L693-L695)
启动游戏应用（`LoginHandler.app_start()`，含登录等待处理）。

#### `goto_main()` (L697-L706)
导航到游戏主页面。如果应用已运行则直接 `UI.ui_goto_main()`，否则先启动应用再导航。

---

### 3.9 游戏任务方法 (L708-L1104)

`AzurLaneAutoScript` 类中共 **112 个方法**（`^    def ` 统计），其中 **93 个游戏任务方法**（L708-L1104，`research` → `emulator_manager`）由 `run()` 动态分发，另有 6 个基础任务方法（见 3.8）。每个方法遵循统一模式：

```python
def task_name(self):
    from module.xxx.xxx import TaskClass
    TaskClass(config=self.config, device=self.device).run()
```

**任务分类与模块映射**:

| 类别 | 方法名 | 处理器模块 | 说明 |
|---|---|---|---|
| **科研** | `research` | `module.research.research.RewardResearch` | 科研项目 |
| **委托** | `commission` | `module.commission.commission.RewardCommission` | 委托收发 |
| **战术** | `tactical` | `module.tactical.tactical_class.RewardTacticalClass` | 战术学院 |
| **宿舍** | `dorm` | `module.dorm.dorm.RewardDorm` | 宿舍管理 |
| **指挥喵** | `meowfficer` | `module.meowfficer.meowfficer.RewardMeowfficer` | 指挥喵 |
| **大舰队** | `guild` | `module.guild.guild_reward.RewardGuild` | 大舰队 |
| **奖励** | `reward` | `module.reward.reward.Reward` | 奖励收取 |
| **觉醒** | `awaken` | `module.awaken.awaken.Awaken` | 觉醒系统 |
| **商店** | `shop_frequent` / `shop_once` | `module.shop.shop_reward.RewardShop` | 商店（频繁/一次性） |
| **活动商店** | `event_shop` | `module.shop_event.shop_event.EventShop` | 活动商店 |
| **船坞** | `shipyard` | `module.shipyard.shipyard_reward.RewardShipyard` | 船坞 |
| **建造** | `gacha` | `module.gacha.gacha_reward.RewardGacha` | 建造系统 |
| **免费福利** | `freebies` | `module.freebies.freebies.Freebies` | 免费福利 |
| **小游戏** | `minigame` | `module.minigame.minigame.Minigame` | 小游戏 |
| **私人休息室** | `private_quarters` | `module.private_quarters.private_quarters.PrivateQuarters` | 私人休息室 |
| **岛屿** | `island` + `island_*` (17个) | `module.island.*` | 岛屿系统及子任务（农场/牧场/渔业/烧烤/茶室/餐厅/咖啡/制造/运输/商业/日常订单/日常互动/珍珠出售等） |
| **每日** | `daily` | `module.daily.daily.Daily` | 每日任务 |
| **困难** | `hard` | `module.hard.hard.CampaignHard` | 困难模式 |
| **演习** | `exercise` | `module.exercise.exercise.Exercise` | 演习 PvP |
| **SOS** | `sos` | `module.sos.sos.CampaignSos` | SOS 任务 |
| **作战档案** | `war_archives` | `module.war_archives.war_archives.CampaignWarArchives` | 作战档案 |
| **突袭** | `raid_daily` / `raid` / `raid_scuttle` | `module.raid.*` | 突袭任务 |
| **活动** | `event_a/b/c/d/sp` | `module.event.campaign_abcd/sp` | 活动战役 (A-D, SP) |
| **护航** | `maritime_escort` | `module.event.maritime_escort.MaritimeEscort` | 海上护航 |
| **大世界** | `opsi_*` (17个) | 见下 | 大世界各种任务（探索/商店/行动力/深渊/强敌/档案/信标/余烬等） |
| **大世界信标/余烬** | `opsi_ash_assist` / `opsi_ash_beacon` | `module.os_ash.meta.AshBeaconAssist` / `OpsiAshBeacon` | 余烬信标支援 / 信标激活 |
| **主线** | `main/main2/main3` | `module.campaign.run.CampaignRun` | 主线战役（3个槽位） |
| **活动战役** | `event/event2/event3` | `module.campaign.run.CampaignRun` | 活动战役（3个槽位） |
| **联动** | `coalition/coalition_sp/coalition_scuttle` | `module.coalition.*` | 联动活动 |
| **医院** | `hospital/hospital_event` | `module.event_hospital.*` | 医院活动 |
| **守护** | `daemon/opsi_daemon` | `module.daemon.*` | 守护模式 |
| **剧情** | `event_story` | `module.eventstory.eventstory.EventStory` | 活动剧情 |
| **拆箱** | `box_disassemble` | `module.storage.box_disassemble.StorageBox` | 箱子拆解 |
| **自动配装** | `auto_equip` | `module.auto_equip.auto_equip.AutoEquip` | 自动配装 |
| **特殊** | `azur_lane_uncensored` | `module.daemon.uncensored.AzurLaneUncensored` | 去遮罩 |
| **测试** | `benchmark/ocr_benchmark` | `module.daemon.*` | 性能基准测试 |
| **舰队扫描** | `fleet_scan` | `module.retire.fleet_management.FleetManagement` | 舰队扫描 |
| **管理** | `game_manager/emulator_manager` | `module.daemon.game_manager/手动SSH` | 游戏/模拟器管理 |

**注意**: `main/main2/main3`、`event/event2/event3`、`c72_mystery_farming`、`c122_medium_leveling`、`c124_large_leveling` 均调用 `module.campaign.run.CampaignRun.run()`，通过配置（`Campaign_Name`/`Campaign_Event`/`Campaign_Mode`）区分具体战役；`gems_farming`、`three_oil_low_cost` 调用 `module.campaign.gems_farming.GemsFarming.run()`；`ambush11` 调用 `module.campaign.ambush_1_1.Ambush11.run()`。

---

### 3.10 `emulator_manager()` (L1088-L1204) - 特殊方法

```python
def emulator_manager(self):
```

这是唯一一个不遵循统一模式的任务方法，直接在 `alas.py` 中实现了完整的 SSH 远程命令执行逻辑。

- **功能**: 通过 SSH 远程执行模拟器管理命令
- **配置来源**: 优先 `EmulatorInfo_*` 配置（`EmulatorInfo_EnableRemoteSSH` 等），回退到 `EmulatorManager.EmulatorManager.*`；主机或命令为空时跳过
- **SSH 参数**: `ssh -n -T -p <port> -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=10`
- **主机密钥**: 执行前调用 `module.base.ssh.clear_ssh_host_key()` 清除已知主机密钥记录
- **密钥处理**: 支持内联私钥（长度 > 50 时写入临时文件），Windows 上使用 `icacls /reset /inheritance:r /grant:r <USER>:F` 设置权限，其他平台 `chmod 0o600`
- **执行**: 使用 `subprocess.Popen`（Windows 上带 `CREATE_NO_WINDOW`），30 秒超时（超时 kill），分离的 stdout/stderr 收集线程（stderr 仅在失败时打印）
- **安全**: 临时密钥文件在 `finally` 块中清理（删除失败静默忽略）

---

### 3.11 `wait_until(self, future)` (L1206-L1232)

```python
def wait_until(self, future):
```

- **功能**: 阻塞等待直到指定时间到达，同时监控配置变更和停止事件
- **参数**: `future` (datetime) - 目标时间
- **返回**: `True` (正常等到), `False` (检测到配置变更，需要重新加载)
- **轮询间隔**: 5 秒
- **特性**:
  - 加 1 秒缓冲 (`future + timedelta(seconds=1)`)
  - 等待前调用 `config.start_watching()`（`module/config/watcher.py` 的 `ConfigWatcher`）记录基准修改时间
  - 每轮检查 `stop_event`，置位时记录"更新事件"并 `exit(0)` 退出
  - 每轮调用 `config.should_reload()` 检测配置文件修改，为真则返回 `False`

---

### 3.12 `get_next_task(self)` (L1234-L1322)

```python
def get_next_task(self):
```

- **功能**: 获取下一个待执行的任务
- **返回**: `str` - 任务命令名（如 `'Restart'`、`'Commission'`）
- **执行流程**:
  1. 调用 `config.get_next()` 获取优先级最高的任务（`module/config/config.py` 的 `get_next_task()` 按 `SCHEDULER_PRIORITY` 过滤排序）
  2. 绑定任务配置 (`config.bind(task)`)，非 `Alas` 任务时释放资源缓存 (`release_resources(next_task=task.command)`)
  3. 如果任务的 `next_run` 在未来，进入等待逻辑（置 `is_first_task = False`）
  4. **省资源长等待**: `Optimization_CloseEmulatorDuringLongWait` 且等待超过 3 小时、存在本地模拟器实例时，先关闭模拟器等待，恢复后由 `_start_emulator_after_long_wait()` 重新启动，非 `Restart` 任务则注入 `Restart`
  5. 等待期间根据 `Optimization_WhenTaskQueueEmpty` 设置执行不同策略：
     - `close_game` - 关闭游戏释放资源，等待后注入 `Restart`
     - `goto_main` - 导航到主页面，等待后继续
     - `stay_there` - 停留在当前页面，等待后继续
     - 其他无效值 - 记录警告并回退 `stay_there`
  6. 等待过程中持续监听配置变更（`wait_until()` 返回 `False` 时清除 config 缓存重新开始循环）
  7. 返回前设置 `AzurLaneConfig.is_hoarding_task = False`

**任务优先级**: 定义在 `module/config/config_manual.py` 的 `_DEFAULT_SCHEDULER_PRIORITY`（可由 `YukikazeTaskManager.TaskPriorityAdjustment` 覆盖，经 `SCHEDULER_PRIORITY` 属性合并），在 `module/config/config.py` 的 `get_next_task()` 中通过 `Filter` 应用。当前默认顺序（`>` 表示更高优先级）:

```text
Restart
> OpsiCrossMonth
> Commission > Tactical > Research
> Exercise
> Dorm > Meowfficer > Guild > Gacha
> Reward
> ShopFrequent > EventShop > ShopOnce > Shipyard > Freebies
> PrivateQuarters
> OpsiExplore
> Minigame > Awaken
> OpsiAshBeacon
> OpsiDaily > OpsiShop > OpsiVoucher
> OpsiScheduling
> OpsiAbyssal > OpsiStronghold > OpsiObscure > OpsiArchive
> Daily > Hard > OpsiAshBeacon > OpsiAshAssist > OpsiMonthBoss
> Sos > EventSp > EventA > EventB > EventC > EventD
> RaidDaily > CoalitionSp > WarArchives > MaritimeEscort
> IslandJuuEatery > IslandJuuCoffee > IslandGrill > IslandTeahouse > IslandRestaurant
> IslandFarm > IslandRancher > IslandMineForest > IslandDailyGather > IslandManufacture
> IslandAirDrop > IslandBusiness
> Event > Event2 > Event3 > Raid > Hospital > HospitalEvent > Coalition > CoalitionScuttle > RaidScuttle > Main > Main2 > Main3
> OpsiMeowfficerFarming
> GemsFarming
> Ambush11
> OpsiHazard1Leveling
> ThreeOilLowCost
```

---

### 3.13 `loop(self)` (L1324-L1564) - 主调度循环

```python
def loop(self):
```

**这是整个程序的主入口循环，实现了完整的任务调度、错误恢复和生命周期管理。**

- **功能**: 无限循环调度任务，处理错误，监控状态。**调度器永不主动退出**——所有未处理异常均通过指数退避重试恢复，唯一例外是 `ScriptError`（`run()` 内连续 3 次后退出）、敏感任务失败（`_check_sensitive_exit()` / `strict_restart` 判断）和 `stop_event` 更新信号
- **常量**:
  - `RESTART_DELAY = 20` - 重启等待基础秒数
  - `LONG_WAIT = 300` - 指数退避等待上限秒数
  - （原 `MAX_GLOBAL_FAILURES = 3` 常量已删除，连续全局失败只用于日志展示和退避策略，不再触发退出）

**执行流程**:

```
loop()
  ├── 设置文件日志 logger.set_file_logger(config_name)
  ├── 检查 OOBE (首次配置, is_oobe_needed() -> exit(1))
  ├── while True:
  │   ├── 检查 stop_event (GUI 更新信号 -> break)
  │   ├── checker.wait_until_available() (服务器维护检测)
  │   ├── 服务器恢复后 (is_recovered) -> 刷新配置并注入 Restart
  │   ├── 检查计划的模拟器重启 (EmulatorManagement_ScheduledEmulatorRestart + RestartIntervalHours)
  │   ├── get_next_task() 获取下一个任务
  │   ├── 初始化 device
  │   ├── 跳过首次 Restart 任务 (is_first_task)
  │   ├── 清除卡死/点击记录 (stuck_record_clear / click_record_clear)
  │   ├── run(inflection.underscore(task)) 执行任务
  │   ├── 每任务推送通知 (Scheduler_PushNotification)
  │   ├── 失败计数管理 (failure_record):
  │   │   ├── success=True -> 重置计数
  │   │   ├── success='recoverable' -> 不计入（也不重置）
  │   │   └── success=False -> 递增计数
  │   ├── strict_restart 判断: Error_StrictRestart && 失败>=1 && {task}.Scheduler.Sensitive
  │   │   └── 命中 -> 上报 bug 日志 (ApiClient.submit_bug_log) + exit(1)
  │   ├── 连续失败 >= 3 次（非敏感任务）-> 不退出，强制重启模拟器 + 注入 Restart，重置计数后继续
  │   ├── success=True -> 清除配置缓存, 重置全局计数, 继续下一个任务
  │   ├── success='recoverable' 或 Error_HandleError -> 刷新配置, 继续循环
  │   └── success=False -> 退出循环
  │
  └── except Exception (全局异常捕获, 永不退出):
      ├── 递增 consecutive_global_failures
      ├── LLM 错误分析 (Error_LlmAnalysis -> module.llm.analyze_exception)
      ├── 首次失败: save_error_log() + ApiClient.submit_bug_log()
      ├── 尝试重启模拟器 (_try_restart_emulator)
      ├── 注入 Restart 任务 + 重新加载配置
      └── 指数退避: min(300, 20 * 2^(连续失败-1)) 秒后重试
```

**关键设计**:

1. **双重错误恢复**: 单个任务的 `run()` 方法处理任务级异常，`loop()` 的 `try/except` 处理未预期的全局异常
2. **永不主动退出**: 全局异常不再因连续失败达到上限而退出，改为指数退避持续重试（上限 300 秒）
3. **敏感任务保护**: `Error_StrictRestart` + `{task}.Scheduler.Sensitive` 命中时立即退出，避免状态或数据损坏
4. **计划模拟器重启**: 在任务间检查是否需要定时重启模拟器（`EmulatorManagement_RestartIntervalHours`，默认 4 小时），不中断正在运行的任务
5. **服务器维护检测**: 通过 `ServerChecker` API 检测游戏服务器状态，恢复后刷新配置并重启游戏客户端
6. **配置热重载**: 通过 `del_cached_property(self, 'config')` 清除缓存，下次访问时重新加载
7. **LLM 错误分析**: 全局异常时第一时间调用 AI 分析崩溃原因

---

### 3.14 `__main__` 入口 (L1566-L1568)

```python
if __name__ == '__main__':
    alas = AzurLaneAutoScript()
    alas.loop()
```

默认创建 `'alas'` 配置实例并启动调度循环。

---

## 4. 数据结构分析

### 4.1 内部状态数据结构

```python
# 任务失败记录
failure_record: Dict[str, int] = {}
# 示例: {'Commission': 2, 'Research': 0}

# i18n 任务名缓存
_i18n_task_names: Dict[str, str] = {}
# 示例: {'Research': '科研', 'Commission': '委托'}
```

### 4.2 配置数据结构 (通过 `AzurLaneConfig` 访问)

```python
config.data: Dict[str, Dict]  # 原始 JSON 配置
# 结构: {TaskName: {Group: {Arg: Value}}}

config.modified: Dict[str, Any]  # 修改追踪
# 结构: {path: value} 如 {'Scheduler.NextRun': '2025-01-01 00:00:00'}
```

---

## 5. 模块内部调用关系

```
alas.py
  ├── AzurLaneConfig (module.config.config)
  │   ├── ConfigUpdater - 配置更新和模板合并
  │   ├── ManualConfig - 手动配置（含 _DEFAULT_SCHEDULER_PRIORITY 任务优先级）
  │   ├── GeneratedConfig - 自动生成的配置属性
  │   └── ConfigWatcher (module.config.watcher) - 文件变更监控
  │
  ├── Device (module.device.device) - 惰性加载
  │   ├── Screenshot - 截图捕获
  │   ├── Control - 设备控制
  │   ├── AppControl - 应用管理
  │   └── Input - 输入模拟
  │
  ├── ServerChecker (module.server_checker) - 惰性加载
  │
  ├── 93 个游戏任务处理器 + 6 个基础任务方法 (module.*.*) - 全部惰性导入
  │   └── 每个处理器继承 ModuleBase, 实现 run()
  │
  ├── LoginHandler (module.handler.login)
  │
  ├── clear_ssh_host_key (module.base.ssh) - emulator_manager 使用
  │
  ├── handle_notify / notify_webui (module.notify)
  │
  ├── ApiClient (module.base.api_client)
  │
  └── LLM 分析 (module.llm) - 可选 (Error_LlmAnalysis)
```

---

## 6. 设计模式与架构分析

### 6.1 设计模式

| 模式 | 应用位置 | 说明 |
|---|---|---|
| **命令模式** | `run(command)` + 93 个游戏任务方法 | 通过方法名动态分发任务 |
| **策略模式** | `get_next_task()` 中的 `Optimization_WhenTaskQueueEmpty` / `Optimization_CloseEmulatorDuringLongWait` | 空闲时不同行为策略 |
| **惰性初始化** | `config`, `device`, `checker` 的 `@cached_property` | 按需加载重资源 |
| **观察者模式** | `ConfigWatcher` + `stop_event` | 监听配置变更和停止信号 |
| **模板方法** | 所有任务方法遵循相同模式 | 统一的 `import -> 实例化 -> run()` |
| **装饰器模式** | `@cached_property`, `del_cached_property` | 属性缓存管理 |

### 6.2 架构风格

- **调度器架构**: 中心化的任务调度循环，基于优先级的任务选择
- **模块化**: 每个游戏功能独立为一个模块，通过统一接口集成
- **事件驱动**: 通过 `threading.Event` 实现进程间通信
- **防御式编程**: 多层异常处理，分级错误恢复

---

## 7. 性能分析

### 7.1 性能瓶颈

| 位置 | 瓶颈 | 原因 | 优化建议 |
|---|---|---|---|
| `device.screenshot()` | 截图捕获 | ADB 传输延迟 ~350ms | 已使用 deque 缓存 |
| `run()` 中的任务执行 | 任务处理 | 图像匹配 + OCR | 模块级优化 |
| `wait_until()` | 空闲等待 | 5 秒轮询间隔 | 可接受 |
| `emulator_manager()` | SSH 命令 | 30 秒超时 | 已有超时控制 |

### 7.2 资源管理

- **截图缓存**: `device.screenshot_deque` 存储最近截图用于错误日志
- **资源释放**: `release_resources(next_task=task.command)` 在任务间释放非必要资源
- **缓存清除**: `del_cached_property()` 强制重新加载配置和设备连接

### 7.3 内存考虑

- `_i18n_task_names` 全局缓存仅在首次调用时加载一次
- 任务处理器通过惰性导入避免启动时加载所有模块
- 错误日志限制保留数量 (`Error_SaveErrorCount`)

---

## 8. 安全性分析

### 8.1 已实现的安全措施

| 措施 | 位置 | 说明 |
|---|---|---|
| 敏感信息遮罩 | `save_error_log()` | 使用 `handle_sensitive_image` 和 `handle_sensitive_logs` |
| SSH 密钥临时文件权限 | `emulator_manager()` | Windows: `icacls`, Unix: `chmod 0o600` |
| SSH 超时控制 | `emulator_manager()` | 30 秒超时 + BatchMode |
| SSH StrictHostKeyChecking | `emulator_manager()` | `=no` (接受所有主机密钥) |
| 错误日志数量限制 | `keep_last_errlog()` | 防止磁盘空间耗尽 |

### 8.2 潜在安全风险

| 风险 | 位置 | 严重程度 | 说明 |
|---|---|---|---|
| SSH 主机密钥未验证 | `emulator_manager()` L1122-L1125 | 中 | `StrictHostKeyChecking=no` 且将 known_hosts 指向 `/dev/null`，可能遭受 MITM 攻击 |
| 临时密钥文件残留 | `emulator_manager()` L1200-L1204 | 低 | `except: pass` 静默忽略删除失败 |
| 通配符异常导入 | L26 | 低 | `from module.exception import *` 可能引入意外名称 |
| LLM API 密钥暴露 | `save_error_log()` | 中 | 错误日志中可能包含 API 密钥 |

---

## 9. 代码质量评估

### 9.1 优点

1. **完善的错误恢复机制**: 分级异常处理，可恢复/不可恢复错误区分明确
2. **模块化设计**: 每个任务独立模块，通过惰性导入避免启动开销
3. **双重通知系统**: onepush + webui 确保用户不会错过重要事件
4. **配置热重载**: 通过 `ConfigWatcher` 实现无需重启的配置更新
5. **资源管理**: 任务间资源释放，空闲时多种策略
6. **LLM 集成**: AI 错误分析提高问题诊断效率

### 9.2 问题与不足

1. **`run()` 方法过长** (289 行, L273-L561): 异常处理逻辑可以提取为独立的错误处理策略类
2. **`loop()` 方法过长** (241 行, L1324-L1564): 全局异常处理和任务调度逻辑可分离
3. **通配符导入** (`from module.exception *`): 不利于代码分析和 IDE 支持
4. **硬编码字符串**: 日志消息中的 emoji 和口语化表达可能影响国际化
5. **`emulator_manager()` 内联**: SSH 逻辑直接嵌入任务方法，违反单一职责原则
6. **注释不一致**: 部分使用英文，部分使用中文
7. **类型注解不完整**: 大多数方法缺少返回值和参数类型注解

---

## 10. 潜在问题与改进建议

### 10.1 潜在 Bug

1. **`run()` 返回值类型不一致**: `True`/`False`/`'recoverable'` 混合，建议使用枚举
2. **`emulator_manager()` 中的 `subprocess.Popen`**: 未在 Windows 上正确处理信号传播
3. **`save_error_log()` 中的 `sys.exc_info()`**: 在异步上下文中可能返回 `(None, None, None)`
4. **`loop()` 中的 `del_cached_property(self, 'config')`**: 在某些异常路径下 config 可能未初始化

### 10.2 改进建议

1. **引入任务结果枚举**:
   ```python
   class TaskResult(Enum):
       SUCCESS = 'success'
       FAILURE = 'failure'
       RECOVERABLE = 'recoverable'
   ```

2. **提取错误处理器**:
   ```python
   class ErrorHandler:
       def handle_game_stuck(self, error): ...
       def handle_emulator_offline(self, error): ...
       def handle_game_bug(self, error): ...
   ```

3. **使用依赖注入**: 替代 `self.__getattribute__(command)()` 的动态分发

4. **添加类型注解**: 提高代码可维护性

5. **分离 SSH 逻辑**: 将 `emulator_manager()` 中的 SSH 代码移到 `module/device/platform/` 下

6. **使用结构化日志**: 替代当前的字符串格式化日志
