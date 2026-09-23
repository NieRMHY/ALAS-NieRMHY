# 编码规范与设计模式

> AzurPilot 游戏交互代码的统一编码规范：状态循环、异常层次、死循环检测、日志与命名的约定及其背后的设计原理。

## 1. 本文定位

本文是全项目游戏模块的规范性参考，回答「写一个新游戏功能时应该遵循什么模式、为什么是这个模式」。仓库根目录的 `AGENTS.md` 是当前权威约束（含「游戏交互约束」「配置与生成文件」两节硬规则），本文负责细化它并解释设计原因，两者冲突时以 AGENTS.md 为准；`.cursor/rules/develop-rules.mdc` 是历史规范文档，其中个别参数（如死循环超时秒数）已与当前代码不一致，一律以源码为准。

这些规范不是风格偏好，而是由运行场景决定的：AzurPilot 按 7×24 小时无人值守设计，任何一段交互代码都可能在凌晨三点无人盯着时卡死、被游戏弹窗打断、或跑在性能很差的机器上。理解这一点后，下文的每条规则都是它的推论。

各模块的具体实现分析见 [目录与任务映射](directory-map.md)；本文只讲横切的模式与契约。

## 2. 状态循环：唯一的游戏交互模式

### 2.1 为什么禁止「点击-等待」

```python
# 禁止：点击-等待模式
self.click(ENTER)
self.device.sleep(2)
self.click(START)
```

这类代码假设「点击后 2 秒画面必然就绪」，而真实环境里加载速度受模拟器性能、网络、游戏活动影响波动极大。等待短了点空、等待长了浪费时间，且任何一步失败后没有重试，错误会级联到后续每一步。

全项目统一使用「截图 → 识别 → 操作」状态循环，它同时解决三个问题：

- **高低配兼容**。循环节奏由截图速度自然调节，快机器每轮约 0.35 秒，慢机器每轮更久但行为正确。配套的 `Timer` 是双重计时器（时间 + 访问次数双阈值），在截图极慢的设备上靠访问次数兜底，不会因单张截图耗时而漏判。
- **点击失败自动重试**。点击后如果画面没变（网络延迟、弹窗抢焦点），下一轮循环会再次识别到同一按钮并再次点击，无需显式重试逻辑。
- **按当前状态选择操作**。每个分支描述「看到什么就做什么」，不依赖固定等待时间推断下一画面。分支顺序仍表示处理优先级：多个条件同时成立时，先命中且执行 `continue` 的分支会跳过后续检测，因此需合理安排退出条件、弹窗处理和普通操作，避免后面的分支长期得不到执行。

### 2.2 标准模板

```python
def some_function(self, skip_first_screenshot=True):
    while True:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        # 退出：纯检测，不设 interval
        if self.appear(END_CONDITION):
            break

        # 操作：设 interval 防连击
        if self.appear_then_click(BUTTON_A, interval=2):
            continue

        # 意外状态：统一弹窗处理
        if self.handle_popup_confirm():
            continue
```

要点：

- `skip_first_screenshot=True` 复用调用方已有的截图（调用者通常刚截完图并在其中识别到了入口），省掉一次约 350ms 的重复截图。只有「没有可用截图」时才传 `False`。
- 退出条件用 `appear()` 且**不设 `interval`**：退出检测必须每轮真实执行。`interval` 的实现是在间隔期内直接返回 `False`（跳过检测），用在退出条件上会无谓延迟退出，甚至让画面已就绪的循环空转。
- 操作分支用 `appear_then_click(..., interval=2)`，`interval` 一般取 2–5 秒，作用是防止连击（点击成功后该按钮在 interval 内不再触发）。
- 点击后立即 `continue` 获取新截图，不做任何等待——画面是否变化由下一轮识别判断，而不是由猜的时间决定。

### 2.3 错误模式清单

| 错误写法 | 为什么错 | 正确做法 |
| --- | --- | --- |
| 循环内 `self.device.sleep(1)` | 盲等既不确认画面，也拖慢快机器；等待期间不截图，还削弱死循环检测的采样 | 删掉，交给下一轮循环截图 |
| `if not self.appear(A) and not self.appear(B): return` | 用负面条件控制流程：识别有误判率，「没识别到」可能是误判，导致提前退出或走错分支 | 用正面条件确认状态（识别到才动作）；误判时只是多等一轮，由死循环检测兜底 |
| `if self.appear_then_click(END): break` | 点击后画面立即变化，break 依据的操作已经发生，后续状态无人确认 | `if self.appear(END): break`，纯检测退出；点击交给操作分支的下一轮 |
| 给退出条件 `appear()` 加 `interval` | interval 会跳过检测，退出被人为延迟 | 退出检测不设 interval |
| 嵌套状态循环 | 内层循环独占控制流，外层的退出条件与弹窗处理在内层等待期间全部失效 | 把子循环的所有分支合并进父循环，一个函数一个循环 |
| 依赖固定 `sleep` 编排多步点击 | 同「点击-等待」模式 | 全部改写为状态循环分支 |

展平循环让退出条件和意外状态能在每张新截图上重新参与判断，适应「点击 A 后可能弹 B，B 后可能回 A」的变化；开发者仍需根据状态之间的重叠关系安排分支顺序。内层循环会暂时阻断外层检查，不能把它当作自动处理时序的机制。

## 3. handle_\*() 方法契约

`handle_*` 是全项目的命名约定（定义集中在 `module/handler`，见[处理器层](../handler.md)），契约只有两条：

- 只返回 `bool`。
- `True` 表示**方法内已对游戏进行了操作**，调用方的状态循环必须获取新截图（`continue`）；`False` 表示未操作，当前截图仍有效。

```python
while True:
    ...
    if self.handle_urgent_commission():   # 处理了弹窗，画面已变
        continue
    if self.handle_info_bar():            # 未出现信息栏，截图仍有效
        continue
```

部分功能将「是否需要执行」与「实际操作流程」分开，例如 `handle_fleet_repair()` 判断维修条件，再调用 `fleet_repair()`。这种拆分不保证操作方法不读配置，也不保证对象能直接离线实例化；是否需要配置、设备及其他状态，应检查具体方法和构造函数。离线测试的隔离方式见第 11 节。

## 4. 死循环检测：无人值守的安全网

状态循环「永远重试」的另一面是必须有人判定「永远重试 = 死循环」。这套检测在 `module/device/device.py` 的 `Device` 类中实现，参数如下（截至 2026-09，以源码为准）。

### 4.1 GameStuckError：无操作超时

- `stuck_timer = Timer(60, count=60)`：常规超时 60 秒，且需要约 60 次检测访问。
- `stuck_timer_long = Timer(195, count=195)`：长等待上限 195 秒。
- 判定逻辑：60 秒计时到达后，若当前等待的按钮属于长等待名单（`BATTLE_STATUS_S`、`PAUSE`、`LOGIN_CHECK`、`TEMPLATE_MANJUU`，即战斗结算与登录启动画面），宽限至 195 秒；否则立即判定卡死。
- 另有一条图像指纹检测：每次截图缩放到 16×16 取哈希，约 30 秒完全不变即判定卡死（游戏进程已退出时改抛 `GameNotRunningError`）。

工作机制：`appear()` 每次检测都会把按钮记入「等待中」集合；每次点击（`handle_control_check`）会清空该集合并重置计时器。因此「一直在检测某个按钮但从未点击成功」持续 60 秒（战斗/登录画面 195 秒）即触发异常。

`Timer` 的双重计数是低配兼容的关键：`reached()` 要求时间与访问次数**同时**达标。高配机器上 60 次访问远快于 60 秒，以时间为准；慢速设备上一张截图可能超过 1 秒，访问计数保证仍按「次数」判断，不会因截图慢而永不触发。

已知会长时静止的场景（登录等待、猫扫描动画）用 `stuck_timeout_override()` 上下文管理器临时放宽阈值，而不是在业务代码里关掉检测或加 sleep。半自动与调试场景可用 `disable_stuck_detection()` 整体关闭。

### 4.2 GameTooManyClickError：连点异常

`click_record` 是容量 15 的双端队列，记录最近 15 次点击（含滑动）的按钮名。每次点击时检查：单一按钮 ≥12 次，或两个按钮各 ≥6 次，即抛出。它抓的是「点击在反复发生但画面不变」的另一类死循环——比如按钮点了没反应、或两个状态互相切换。

两个检测互为补充：`GameStuckError` 抓「什么都不做也过不去」，`GameTooManyClickError` 抓「一直做过不去」。

### 4.3 顶层恢复

这两个异常**只在调度器顶层捕获**（见[调度器](../entry/alas.md)）：保存错误现场后注入 `Restart` 任务重启游戏；启用 `Error_GameStuckRestart` 后，连续卡死达到阈值（`Error_GameStuckThreshold`，默认 3）则升级为重启模拟器。返回值标记为 `'recoverable'`，不计入任务失败次数——因为这类错误几乎总能靠重启恢复，7×24 运行不应为之退出。

开发者不需要在业务代码里捕获它们，也不应该捕获：吞掉这两个异常等于拆掉无人值守的安全网。

## 5. 异常层次与处理哲学

### 5.1 异常层次表

`module/exception.py` 定义了全部自定义异常，按语义分层（`HardNotSatisfied` 继承自 `RequestHumanTakeover`，其余均为 `Exception` 直接子类）：

| 层次 | 异常 | 含义 | 典型处理 |
| --- | --- | --- | --- |
| 正常结束 | `CampaignEnd` | 战役结束（回到关卡选择页），由关卡代码主动抛出 | 上层捕获，推进后续流程 |
| 正常结束 | `OilExhausted` / `OilMaxed` | 石油耗尽 / 石油满仓 | 结束当前出击任务 |
| 地图导航 | `MapDetectionError` | 透视网格识别失败（弹窗遮挡、画面异常） | 重试；连续失败上抛 |
| 地图导航 | `MapWalkError` | 舰队无法走到目标格 | 换路径或换目标重试 |
| 地图导航 | `MapEnemyMoved` | 敌人移动使路径失效 | 重新扫描、重新寻路 |
| 地图导航 | `CampaignNameError` | 配置的关卡名无法映射到地图文件 | 上抛为脚本错误 |
| 游戏状态 | `GameStuckError` | 无操作超时（见第 4 节） | 重启游戏，连续卡死重启模拟器 |
| 游戏状态 | `GameBugError` | 游戏客户端 bug | 重启游戏 |
| 游戏状态 | `GameTooManyClickError` | 连点异常（见第 4 节） | 同 `GameStuckError` |
| 连接/页面 | `GameNotRunningError` | 截图黑屏或游戏进程退出 | 注入 Restart 任务 |
| 连接/页面 | `GamePageUnknownError` | 任何已知页面都匹配不上 | 重启游戏；服务器维护时等待 |
| 连接/页面 | `EmulatorNotRunningError` | ADB 连不上且模拟器进程不存在 | 重启模拟器，永不退出 |
| 开发者 | `ScriptError` | 脚本逻辑错误（代码 bug） | 重试 3 次，仍失败则 `exit(1)` |
| 开发者 | `ScriptEnd` | 流程需正常中断（非错误，不计失败） | 调度层捕获，安排延迟或结束 |
| 不可恢复 | `RequestHumanTakeover` | 配置错误等自动化无法处理的问题 | 当前策略：也先尝试重启模拟器自动恢复 |
| 不可恢复 | `AutoSearchSetError` | 自动搜索设置失败 | 重启游戏恢复 |
| 并发保护 | `EmulatorOpBusy` | 已有模拟器启停操作在进行（非错误） | 调用方放弃本轮，等下一轮调度 |

另有一个不在 `exception.py` 的 `TaskEnd`（定义于 `module/config/config.py`）：任务提前结束（如情绪不足需延迟），调度器视为正常完成。

### 5.2 处理哲学

- **异常只在顶层捕获。** 中间层只负责 `raise`，不 `try`。这样任何错误都带着完整调用栈到达统一处理点，避免「每层都处理一点、每层都吞一点」的模糊状态。业务代码唯一的例外是**可预期的流程异常**（见下节）。
- **捕获后归档错误现场。** `save_error_log()` 把最近截图（由 `Error_ScreenshotLength` 控制的截图队列）与日志写入 `./log/error/<配置名>/<时间戳>/`，并按 `Error_SaveErrorRetentionDays` 过期后删除或备份到 `bak/`。
- **归档前清洗用户信息。** 错误日志默认会被用户分享到社区，因此截图遮罩指挥官昵称与 UID（`assets/mask/` 遮罩模板），日志中的本机路径替换为 `C:\fakepath\AzurLaneAutoScript`。新增可能截到个人信息的识别功能时应检查是否需要补遮罩。
- **重启是万能恢复手段。** 调度器对几乎所有异常的最终答案都是「重启游戏 / 重启模拟器 / 注入 Restart 任务」，只有 `ScriptError` 连续 3 次（代码 bug，重试无意义）才退出。整体策略是调度器永不主动退出。

### 5.3 异常作为控制流

`CampaignEnd` 与 `ScriptEnd` 是刻意的控制流设计：关卡与战斗逻辑往往嵌套很深（战役 → 地图 → 战斗 → 结算），用异常把「结束信号」从最深处一次跳回任务层，避免每一层都传递返回值。`ScriptEnd` 表示「条件达成、正常中断当前任务」（情绪不足延迟、停止条件、退役策略），语义上不是错误；`CampaignEnd` 则是关卡代码的通用退出方式，如 `clear_boss()` 打完 BOSS 后 `raise CampaignEnd('BOSS Clear.')`。

写业务代码时的判断标准：**深层的流程终止用异常上抛，浅层的画面分支用状态循环**。不要在状态循环里 `try/except` 游戏异常。

## 6. 命名约定

### 6.1 几何与地图术语

这套词汇贯穿全部识别与地图代码，混用会造成隐蔽 bug（屏幕坐标与网格坐标数值范围完全不同）：

| 术语 | 类型 | 含义 |
| --- | --- | --- |
| `point` | tuple (x, y) | 屏幕上的一个点。原点左上，x 向右，y 向下 |
| `area` | tuple (x1, y1, x2, y2) | 屏幕矩形区域（左上角与右下角坐标） |
| `location` | tuple (x, y) | 海域网格坐标，(0, 0) 是海图左上角的 A1 |
| `node` | str，如 `"E3"` | 网格坐标的字符串形式 |

`node` 与 `location` 通过 `node2location()` / `location2node()` 互转。约定：**逻辑编写与日志用 `node`（人可读），运行时计算用 `location`**。日志里出现 `E3` 而不是 `(4, 2)`，是排错时能直接对照游戏画面的关键。

### 6.2 代码命名

- 变量、函数 `snake_case`；类 `PascalCase`；常量 `UPPER_SNAKE_CASE`。
- 识别资源常量全大写（`CANCEL`, `POPUP_CONFIRM`），模板资源以 `TEMPLATE_` 开头，二者由 `button_extract` 等工具生成或配套，命名需与素材语义一致。
- 布尔返回方法按前缀区分语义：`appear_*` 只检测、`handle_*` 检测并操作（见第 3 节）、`is_*` / `has_*` 表示状态判断。

## 7. 日志规范

全局 logger 实例在 `module/logger.py` 中以 monkey-patch 方式扩展（`logger.hr` / `logger.attr` / `logger.error_context` 等），整个框架共用这一个入口。

### 7.1 logger.hr() 分级

`hr(title, level)` 输出分节标题，`title` 会自动转为大写。四级含义：

| level | 形态 | 含义 |
| --- | --- | --- |
| 0 | 三行双线包夹 | 仅脚本启动时使用，每次运行最多一次 |
| 1 | `══` 双线 + 标题 | 开始执行某个任务（GUI 中的一个功能） |
| 2 | `──` 单线 + 标题 | 任务内的某个阶段开始 |
| 3 | `<<< TITLE >>>` | 阶段内的细分步骤 |

### 7.2 其他要点

- `logger.attr(name, text)` 打印识别到的属性，格式 `[name] text`，用于输出 OCR 结果、页面判定等关键状态；对齐场景用 `attr_align`。
- `logger.error_context(title, reason, impact, action)` / `exception_context()` 输出结构化错误信息（原因 / 影响 / 建议），用户可直接照「建议」操作；抛往顶层的异常在上层用它们记录，业务代码一般不需要。
- 日志是给人读的：强调是相对的，如果到处都是 `hr()` 和 `warning()`，等于没有强调任何东西。普通识别过程用 `logger.info`，真正的异常状态才用 `warning`。
- 格式统一为 `2026-09-21 08:35:59.460 | INFO | 消息`，由文件 handler 维护，不要在业务代码里自行拼时间戳或级别。

## 8. 注释规范

- docstring 用 Google 风格（`Args:` / `Returns:` / `Raises:`），内容使用简体中文；涉及界面进出的函数加 `Pages:` 标注，值为游戏页面或其识别按钮名：

  ```python
  """
  检查大舰队资金是否不足。

  Returns:
      bool: True 表示资金不足。

  Pages:
      in: GUILD_OPERATIONS_NEW
  """
  ```

- 注释解释**状态与原因**（为什么这样判断、这个状态意味着什么），不复述代码做了什么。不规定注释比例或函数行数——判断标准是「下一个人能否不看游戏画面就理解这段状态逻辑」。
- 代码标识符用英文；日志、注释、文档用简体中文。

## 9. 配置驱动的多实现分发

服务器差异、开关差异等「同名不同实现」的场景，用 `module/base/decorator.py` 的 `Config.when()` 装饰器分发，而不是在函数体内写 `if self.config.SERVER == 'en'`：

```python
@Config.when(SERVER='en')
def function(self):
    # 仅 EN 服务器执行
    ...

@Config.when(SERVER=None)
def function(self):
    # 其他服务器执行（None 是通配）
    ...
```

运行时按当前配置选第一个全部条件匹配的实现；没有任何匹配时打警告并回退到最后定义的版本。这样服务器差异被拆成平行的函数定义，新增一个服务器的适配不需要改动其他服务器的代码路径。

其他常用装饰器（`cached_property`、`del_cached_property`、`function_drop`、`run_once`）见[装饰器与工具函数](../base/decorator-utils.md)。

## 10. 性能事实与优化取向

与直觉相反，**编写业务代码时不需要特别注意 Python 性能**。运行时间的构成大致是：

- 超过 99% 的时间在等待模拟器截图，单张约 350ms；
- 常规图像识别处理约 2.5ms；
- 最重的操作（海图透视识别、OCR）也只约 100–180ms。

因此微优化 Python 循环没有意义；真正影响吞吐的只有两件事：**减少截图次数**（状态循环天然最优，因为只在必要时截图）和**减少重识别次数**（善用 `interval` 跳过未到期的检测、`cached_property` 缓存识别结果）。遇到性能问题时先检查「是不是多截了图 / 多识别了几次」，而不是优化像素处理代码。

## 11. 调试方法

离线测试优先直接调用接收图片的识别对象或纯函数。`ModuleBase` 子类以配置名正常构造时会加载配置并创建 `Device`，可能保存配置、连接 ADB 或尝试启动模拟器；随后设置 `image_file` 不能撤销这些初始化操作。需要测试实例方法时，使用隔离配置与假设备，并按被测方法补齐所需状态。

### 11.1 假截图调试 Button

使用已有的 1280×720 截图，直接调用按钮的模板匹配方法，不构造游戏模块或设备：

```python
import module.config.server as server
server.server = 'cn'

from module.base.utils import load_image
from module.sos.assets import SIGNAL_LIST_CHECK

image = load_image(r'./screenshots/sos_list.png')
print(SIGNAL_LIST_CHECK.match(image))
```

这里验证的是 `Button.match()` 的模板匹配结果，不包含 `ModuleBase.appear()` 的间隔控制等包装行为。`image_file` setter 本身只加载图片、设置非原生 720p 匹配标记并替换 `self.device.image`；它需要一个已准备好的设备对象，不能据此推断模块构造也是离线的。

### 11.2 批量调试识别函数

```python
from pathlib import Path
from types import SimpleNamespace
from module.handler.info_handler import InfoHandler

# 仅测试依赖 device.image 的旧版剧情选项检测，跳过配置和设备构造。
az = InfoHandler.__new__(InfoHandler)
az.device = SimpleNamespace(image=None)
for file in Path('./screenshots/case_folder').glob('*.png'):
    az.image_file = str(file)
    print(az._story_option_buttons())
```

此夹具只满足 `_story_option_buttons()` 及其裁剪路径的依赖，不能用于执行完整 handler、点击或导航流程。测试其他方法时先核对依赖；若方法会访问配置或设备控制能力，需另行提供相应的隔离夹具。

### 11.3 切换服务器离线调试

资源按服务器懒加载，因此**必须在导入任何游戏模块之前**设置全局服务器，且必须用 `import ... as` 保持对全局变量的引用：

```python
import module.config.server as server
server.server = 'en'

from module.ui.assets import MAIN_GOTO_REWARD  # 顺序不能反
```

### 11.4 海图识别调试

`dev_tools/grids_debug.py` 在框架外单独调用 `module/map_detection/view.py`：把截图路径与地图文件中的 `Config` 参数粘进去即可复现透视错误并可视化网格，是适配新海域时排查 `MapDetectionError` 的入口。

### 11.5 其他入口

- `dev_tools/button_extract.py`：修改按钮素材后重新生成 `assets.py`。
- `dev_tools/relative_record.py`：截取模板素材。
- `@function_drop(rate)` 装饰器可随机丢弃 `click()` 调用，模拟「点击失败」；离线验证时应作用于假设备，装饰真实设备不会阻止其余点击发送到模拟器。
- `disable_stuck_detection()` 关闭卡死检测，供半自动与调试使用。

工具清单见[目录与任务映射](directory-map.md)。

## 12. 相关模块

- [调度器（alas.py）](../entry/alas.md) — 异常顶层捕获与自动恢复策略的实现处
- [基础层 module/base](../base/index.md) — 状态循环原语 `appear` / `appear_then_click`、`Timer` 的实现处
- [装饰器与工具函数](../base/decorator-utils.md) — `Config.when` 等装饰器详情
- [设备层](../device.md) — 死循环检测与点击记录的实现处
- [UI 导航](../ui.md) — `Page` 页面图与 `ui_goto` 导航
- [处理器层](../handler.md) — `handle_*` 契约的定义处
- [OCR 系统](../ocr.md) — 识别类与 `Digit` / `Duration` 等变体
- [地图系统与检测](../map.md) — `location` / `node` 坐标体系的实现处
- [配置系统](../config.md) — `self.config.Group_Argument` 绑定机制
