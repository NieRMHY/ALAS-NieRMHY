# AzurPilot 日志设计语言规范 (Log Design Language, LDL)

> 适用于 AzurPilot / Alas 自动化框架的全项目标准化日志体系、通信协议与 WebUI 解析渲染规范。
> 版本：2.0.0 | 状态：正式实现 (Implemented) | 日期：2026-09-27

---

## 1. 概述与设计背景

### 1.1 现状与痛点分析

当前 AzurPilot 的日志系统基于 Python 标准库 `logging` 与 `rich` 库构建。运行架构中，子进程通过 `RichRenderableHandler` 将 Rich 渲染对象发送至多进程队列，主进程再经由 `Console(width=160, color_system=None)` 渲染成宽度为 160 列的无颜色纯文本，最终通过 WebSocket 推送至 WebUI。

这种架构存在四个核心痛点：

1. **信息黑盒化与格式退化（Format Degradation）**：
   后端原本具备高度结构化的数据（如 `logger.hr(title, level)`、`logger.attr(name, val)`、Rich 表格、异常上下文 `error_context`、海图坐标阵列等），但在流向 WebUI 时被强行压平为 160 宽度的 ASCII 文本（包含填充空格与框线字符），丢失了原始数据类型与语义元数据。

2. **前端逆向解析的脆弱性（Fragile Regex Scraping）**：
   前端 WebUI 必须依赖脆弱的正规表达式（`LOG_LINE_RE`、`RULE_RE`、`PURE_RULE_RE`、`CENTER_TITLE_RE`、`tokenRegex` 等）去“逆向猜测”日志的类型。当日志正文中出现关键字（如包含 "INFO" 或 "WARNING"）、或者时间格式变化时，容易出现级别猜错、标题行误判为普通文本等缺陷。

3. **多行与排版错乱灾难（Multiline / Wrap Collision）**：
   在 WebUI 布局中，160 字符宽度的异常堆栈（Traceback）、ASCII 表格和海图网格，在面对弹性容器或移动端屏幕（约 800px 宽）时，若使用 `white-space: pre-wrap; word-break: break-all` 会导致框线碎片化错位；若使用 `white-space: pre` 则普通文本无法自适应折行。

4. **缺乏现代 WebUI 富交互能力（Lack of Rich UI Capabilities）**：
   纯文本日志使得前端无法提供折叠/展开异常堆栈、原生数据表格排序、海图交互式网格高亮、操作流水时间线审计（Timeline / Breadcrumbs）、任务大纲快速跳转（Table of Contents）等功能。

### 1.2 LDL 设计目标

- **语义先于排版（Semantics First, Presentation Decoupled）**：日志首先描述“发生了什么业务事件、携带什么结构化数据”，而不是硬编码“在哪里留几个空格、画哪种边框字符”。排版呈现由终端、文件和 WebUI 各自独立实现。
- **全项目场景覆盖（Comprehensive Domain Coverage）**：统一覆盖调度、设备、视觉识别、UI导航、战役、战斗、海图、大世界、日常管理及异常诊断等全部 10 大核心子系统。
- **标准化数据模型（Standardized Schema & Protocol）**：建立统一类型契约（Discriminated Union），提供严格的 JSON Schema 与 TypeScript/Python 双端类型定义。
- **WebUI 极简解析与富交互呈现（Zero-Guessing Parsing & Rich UI）**：前端无需通过复杂正则猜测类型，直接依据数据驱动渲染原生组件；内置虚拟滚动、任务大纲、可折叠堆栈与数据表格。
- **渐进增强与 100% 向后兼容（Backward Compatibility & Progressive Enhancement）**：无缝兼容项目中既有的 3000+ 处 `logger.info` 扁平文本调用，支持双模共存与平滑过渡。

---

## 2. LDL 核心分层架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Layer 1: 业务生产者层 (Domain Producers)               │
│  alas.py / device / ocr / combat / map / opsi / meowfficer / exception  │
│  API: logger.info() / logger.hr() / logger.attr() / logger.emit_event()│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ LogEvent / LogEntry
┌───────────────────────────────────▼────────────────────────────────────┐
│                   Layer 2: 规范模型层 (Standardized Schema)             │
│        Base Envelope: id, ts, level, category, task, instance, kind    │
│        Payloads: text | rule | kv | action | map | table | error | tb  │
└───────────────────┬───────────────────────────────┬────────────────────┘
                    │                               │
┌───────────────────▼───────────────┐   ┌───────────▼────────────────────┐
│ Layer 3A: 进程内/本地格式化       │   │ Layer 3B: 远程传输与管道       │
│  - Rich Console Formatter (控制台) │   │  - Multiprocessing Queue 队列  │
│  - TimedRotating Formatter (文件) │   │  - WebSocket 广播 (/api/v1/ws) │
└───────────────────────────────────┘   └───────────┬────────────────────┘
                                                    │ JSON Stream
                                        ┌───────────▼────────────────────┐
                                        │ Layer 4: WebUI 表现层 (React)  │
                                        │  - Virtual Scroll Container    │
                                        │  - Component Library (10 Kinds)│
                                        │  - Outline / Filters / Search  │
                                        └────────────────────────────────┘
```

---

## 3. 标准化数据模型 (Schema Specification)

### 3.1 顶层信封（Base Log Envelope）

每个日志条目在进入传输层与 WebUI 时，均具备统一的标准信封结构：

```typescript
export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface BaseLogEntry {
  /** 单调递增的唯一全局游标 ID，客户端据此进行增量拉取、去重与追踪 */
  id: number;
  /** 事件生成时间，毫秒级 Unix 时间戳 (1727400000000) */
  ts: number;
  /** 明确的日志严重等级，前端和网关无需反查文本内容 */
  level: LogLevel;
  /** 领域/子系统分类标识符 */
  category: LogCategory;
  /** 当前所属的实例名称，如 'alas'、'demo-main' */
  instance: string;
  /** 当前正在执行的任务名称，如 'Commission'、'Main'、'OpsiAshBeacon'，无任务时为 null */
  task?: string | null;
  /** 表现类型指示符 (Discriminated Union Tag) */
  kind: LogKind;
  /** 经典纯文本回退（控制台/文件渲染的纯文本，保证降级兼容与一键复制） */
  rawText: string;
}
```

### 3.2 子系统分类词典（LogCategory）

```typescript
export type LogCategory =
  | 'system'     // 框架启动、更新、配置、进程生命周期
  | 'scheduler'  // 调度器、任务队列、排队与延迟
  | 'device'     // 模拟器、ADB、投屏截屏、触控输入
  | 'vision'     // 图像模板匹配、颜色比对、边缘检测
  | 'ocr'        // OCR 字符识别与结果判定
  | 'ui'         // UI 页面导航、弹窗拦截、页面前后置确认
  | 'campaign'   // 战役选关、进图、出击策略
  | 'combat'     // 战斗循环、结算、自律状态、阵容与掉落
  | 'map'        // 海图识别、坐标系、路径规划、迷宫与机关
  | 'opsi'       // 大型作战（大世界）、行动力、区域移动、信标
  | 'game'       // 日常维护、委托、科研、指挥喵、商店、退役
  | 'diagnostics'; // 错误诊断、崩溃现场、LLM 分析
```

### 3.3 核心 Kind 载荷规范 (Discriminated Payloads)

LDL 定义了 10 类标准化条目，覆盖整个框架中的一切业务场景：

#### 1. `text` (标准文本行)
适用于普通文本输出，携带可选的词法 Token 数组，WebUI 可直接按 Token 着色，避免运行昂贵的前端正则。

```typescript
export interface TextToken {
  type: 'plain' | 'bool' | 'path' | 'time' | 'tag' | 'brace' | 'num';
  value: string;
}

export interface TextLogEntry extends BaseLogEntry {
  kind: 'text';
  payload: {
    message: string;
    tokens?: TextToken[];
  };
}
```

#### 2. `rule` (分节标题与阶段锚点)
对应现有的 `logger.hr(title, level)` 与 `logger.rule()`。不仅用于视觉分割，同时是构建 WebUI **任务导航大纲树（TOC）** 的核心数据来源。

```typescript
export interface RuleLogEntry extends BaseLogEntry {
  kind: 'rule';
  payload: {
    title: string;
    /**
     * 深度等级：
     * 0: 系统级大标题（如调度器启动、进程生命周期）
     * 1: 顶级任务（如 COMMISSION、MAIN、RESEARCH）
     * 2: 子阶段（如 SUB_STAGE、COMBAT、FLEET_PREPARATION）
     * 3: 步骤小节（如 <<< 查找所有舰队 >>>）
     */
    depth: 0 | 1 | 2 | 3;
    style: 'double' | 'single' | 'banner' | 'tag';
  };
}
```

#### 3. `key_value` (属性键值与状态徽章)
对应现有的 `logger.attr(name, text)` 与 `logger.attr_align()`。前端按原生 Key-Value 徽章或属性列表自适应渲染，彻底解决空格对齐被字体破坏的问题。

```typescript
export interface KeyValueLogEntry extends BaseLogEntry {
  kind: 'key_value';
  payload: {
    key: string;
    value: string | number | boolean | null;
    unit?: string;
    tag?: string; // 前置标签，例如 '[心情-保底]'
    status?: 'default' | 'success' | 'warning' | 'error' | 'info';
  };
}
```

#### 4. `action` (设备与识别流水)
记录自动化框架每一次关键动作（点击按钮、滑动屏幕、截屏耗时、OCR 耗时），用于执行链审计与性能回溯。

```typescript
export interface ActionLogEntry extends BaseLogEntry {
  kind: 'action';
  payload: {
    actionType: 'click' | 'swipe' | 'screenshot' | 'ocr' | 'appear' | 'ensure';
    target: string; // 目标按钮/区域名称，如 'FLEET_PREPARATION'、'BATTLE_STATUS_S'
    coords?: [number, number] | [number, number, number, number]; // [x, y] 或 [x1, y1, x2, y2]
    costMs?: number; // 操作或识别耗时（毫秒）
    confidence?: number; // 匹配或 OCR 置信度 (0.00 ~ 1.00)
    result: boolean | string;
    previewUrl?: string; // 可选的关联局部截图或调试图预览
  };
}
```

#### 5. `map_grid` (海图网格与战略视野)
彻底解决 `[地图-显示]` 中 15 行空格对齐的 ASCII 字符在 WebUI 上乱码、错位的问题。直接以结构化矩阵承载，前端可渲染为紧凑的可视化棋盘或交互式网格。

```typescript
export interface GridCell {
  coord: string; // 逻辑坐标，如 'C4'
  x: number;
  y: number;
  rawStr: string; // 原始符号，如 'FL'、'E1'、'MY'、'=='
  isFleet?: boolean;
  fleetId?: number; // 1, 2 或 3(潜艇)
  isEnemy?: boolean;
  enemyScale?: number; // 敌舰规模 1~3
  isBoss?: boolean;
  isMystery?: boolean;
  isMechanism?: boolean;
  isWalkable?: boolean;
}

export interface MapGridLogEntry extends BaseLogEntry {
  kind: 'map_grid';
  payload: {
    shape: [number, number]; // [宽, 高]，如 [8, 8]
    camera: [number, number]; // 摄像机全局坐标
    round: number;
    cells: GridCell[];
    fleets: Record<string, string>; // {"fleet_1": "B3", "fleet_2": "C4", "submarine": "D5"}
    selectedRoute?: string[]; // 当前规划路径 ['B3', 'B4', 'C4']
  };
}
```

#### 6. `table` (原生数据表格)
对应现有的指挥喵评分报告（Meowfficer Score）、性能跑分（Benchmark）、资源结算报表等。前端使用原生 HTML Table / CSS Grid 渲染，支持列排序与单元格选中复制。

```typescript
export interface TableColumn {
  key: string;
  label: string;
  align?: 'left' | 'center' | 'right';
  width?: string | number;
}

export interface TableLogEntry extends BaseLogEntry {
  kind: 'table';
  payload: {
    title?: string;
    columns: TableColumn[];
    rows: Array<Record<string, string | number | boolean | null>>;
  };
}
```

#### 7. `error_context` (统一错误与自愈指南)
对应现有的 `logger.error_context()`。结构化清晰呈现标题、根因、业务影响与操作建议，让非技术用户无需翻看堆栈即知如何处理。

```typescript
export interface ErrorContextLogEntry extends BaseLogEntry {
  kind: 'error_context';
  payload: {
    title: string;
    reason: string;
    impact: string;
    action: string;
    exceptionType?: string;
    exceptionMessage?: string;
    sensitiveTask?: boolean; // 是否触发敏感任务停机保护
    recoverable?: boolean;   // 是否为自动重启可恢复错误
  };
}
```

#### 8. `traceback` (结构化异常堆栈)
解决 150 列宽的 Rich 异常框线被打散的核心方案。将堆栈分解为标准调用帧（Stack Frames）与局部变量（Locals），WebUI 提供可折叠展开、源码行高亮、复制完整调用链的能力。

```typescript
export interface StackFrame {
  file: string;
  line: number;
  func: string;
  codeSnippet?: string;
  isFaultLine?: boolean;
  locals?: Record<string, string>;
}

export interface TracebackLogEntry extends BaseLogEntry {
  kind: 'traceback';
  payload: {
    excType: string;
    excValue: string;
    frames: StackFrame[];
    chainDepth?: number; // 异常链 (Exception Chaining) 深度
  };
}
```

#### 9. `llm_diagnosis` (AI 智能错误分析)
对应 `module/llm.py` 生成的错误原因分析与解决方案，独立卡片化展示，与常规堆栈区分。

```typescript
export interface LlmDiagnosisLogEntry extends BaseLogEntry {
  kind: 'llm_diagnosis';
  payload: {
    summary: string;
    probableCauses: string[];
    recommendedFixes: string[];
    confidence: number;
    cached: boolean;
  };
}
```

#### 10. `progress` (进度更新)
用于耗时循环、批次任务、下载更新或战斗轮次的即时进度。

```typescript
export interface ProgressLogEntry extends BaseLogEntry {
  kind: 'progress';
  payload: {
    label: string;
    current: number;
    total: number;
    percentage: number;
    etaSeconds?: number;
  };
}
```

---

## 4. 全项目子系统语义规范与日志词典 (Taxonomy & Lexicon)

为了确保各子系统输出风格一致，避免“有的写 `[设备-点击]`、有的写 `Click`、有的写 `Clicking button`”，特制定全项目标准词典：

### 4.1 子系统 Tag 命名与用词标准

| 子系统 | 标准 Tag 格式 | 推荐级别 | 经典输出示例 |
|---|---|---|---|
| 调度器 (alas) | `[调度-阶段]` / `[调度-任务]` | INFO | `[调度-任务] 派发 Commission，预计耗时 15m` |
| 进程控制 | `[进程-状态]` | INFO/WARN | `[进程-状态] worker alas (PID 12345) 已退出` |
| 设备/连接 | `[设备-连接]` / `[设备-截图]` | DEBUG/INFO | `[设备-截图] 完成首帧捕获，延迟 45ms` |
| 触控操作 | `[操作-点击]` / `[操作-滑动]` | INFO | `[操作-点击] 点击 FLEET_PREPARATION (640, 360)` |
| 图像识别 | `[识别-模板]` / `[识别-颜色]` | DEBUG/INFO | `[识别-模板] 匹配 BATTLE_STATUS_S，置信度 0.98` |
| 文字识别 | `[OCR-结果]` | DEBUG/INFO | `[OCR-结果] 识别 '出击' 置信度 0.99，耗时 12ms` |
| UI 导航 | `[UI-跳转]` / `[UI-弹窗]` | INFO/WARN | `[UI-弹窗] 拦截并确认 '通知: 委托已完成'` |
| 战役执行 | `[战役-进图]` / `[战役-撤退]` | INFO | `[战役-进图] 进入 12-4，模式: 普通，队伍: [1, 2]` |
| 战斗循环 | `[战斗-状态]` / `[战斗-结算]` | INFO | `[战斗-结算] 评级 S，获得经验 1200，掉落: 舰船*1` |
| 地图网格 | `[地图-移动]` / `[地图-寻路]` | INFO | `[地图-移动] 第一舰队 B3 -> C4，躲避路障` |
| 大世界核心 | `[大世界-移动]` / `[大世界-信标]` | INFO | `[大世界-信标] 开启 META 战斗，剩余挑战次数: 3` |
| 错误与诊断 | `[错误]` / `[诊断-AI]` | ERROR/CRIT | `[错误] 游戏状态无法推进，1 分钟内无有效操作` |

### 4.2 日志等级使用原则 (Level Governance)

1. **DEBUG**：高频低信息量数据，如单帧截屏延迟、每一轮模板无匹配结果、OCR 候选边界框。在生产环境默认过滤，仅在排查问题时开启。
2. **INFO**：系统主干状态流转。包括任务切换、页面跳转、点击按钮、战斗开始与结算、掉落汇总、海图移动。必须清晰可读。
3. **WARNING**：检测到非预期情况但框架具备自动恢复能力。例如：一次点击未响应正在重试、敌人移动导致需重新寻路、网络轻微波动、游戏未运行触发自动重启等。
4. **ERROR**：任务流程中断、非预期异常抛出、多次重试失败。必须携带 `error_context`，指明原因与建议。
5. **CRITICAL**：框架整体无法继续运行、敏感任务保护停机、配置/设备严重错误需要人工介入。必须触发高优先级推送通知与前端报警。

---

## 5. 特殊格式日志深度研究与组合解析架构 (Special Formats & Composite Parsing)

### 5.1 单行常规日志 vs 特殊格式日志的本质界限

在日常自动化运行中，项目日志存在两种根本不同的信息范式：

1. **常规单行信息（Atomic Single-line Log）**：
   - 特征：具备完全独立的时间与语义原子性。例如 `[操作-点击] 点击 FLEET_PREPARATION (640, 360)` 或 `[UI-跳转] 进入 page_campaign`。
   - 呈现诉求：WebUI 按普通文本行直接渲染（时间戳 + 级别徽章 + 分割线 + 消息正文）即可完全满足要求，简单高效。
2. **特殊格式日志（Composite & Structured Block Log）**：
   - 特征：在代码中虽然可能分散通过多行 `logger.info` 或多行字符串输出，但它们在**空间拓扑、视觉排版或业务逻辑上强相关，必须作为一个整体组合起来看**。
   - 呈现诉求：单行流水线渲染会将其彻底割裂打散。必须脱离单行孤立思维，通过**块级聚合（Block Aggregation）**与**专用组件卡片**进行整合呈现。

---

### 5.2 全项目特殊格式全景剖析

经全仓库代码扫描，AzurPilot 中存在的特殊格式输出可归纳为以下 8 类：

| 类型 | 典型来源 | 打印形式 | 业务本质与痛点 | 目标形态 |
|---|---|---|---|---|
| **海图矩阵块** | `map_base.py:478/717/725` | 连续 N+1 条 `logger.info` | **二维战局拓扑**。被时间戳打断、列头与数据行错位、容器折行散架 | `<LogMapBlock />` 紧凑网格卡片 |
| **连续对齐属性块** | `camera.py` / `combat.py` / `device.py` | 连续 3~10 条 `logger.attr_align` | **对象属性表**。22 字符空格在 Web 字体下错位，每行重复时间戳 | `<LogPropertyBlock />` 键值网格卡片 |
| **三行式顶层横幅** | `logger.hr(title, level=0)` | 连续 3 条 `logger.rule` | **系统级生命周期标记**。被拆为两条横线和一条居中字 | `<LogSystemBanner />` 状态横幅 |
| **任务双行标题** | `logger.hr(title, level=1/2)` | 1 条 Rule + 1 条同名 INFO | **任务/阶段大纲**。标题重复打印两次，存在视觉噪声 | `<LogStageHeader />` 大纲锚点标题 |
| **四段式错误上下文** | `logger.error_context` | 换行符 `\n` 连接的单条多行日志 | **结构化处置指南**。被当成长文本换行，建议不突出 | `<LogErrorCard />` 警示操作指南 |
| **富异常堆栈** | Python 未捕获异常 (Rich Traceback) | 150 列宽边框字符 + locals 框 | **深层调试栈**。在窄屏下被 `break-all` 撕裂为碎片 | `<LogTracebackViewer />` 折叠源码栈 |
| **富边框二维表格** | `benchmark.py` / `score_task.py` | Rich `Table` (Unicode 框线) | **多维量化报表**。字符边框折行错位，无法列排序与拷贝 | `<LogDataTable />` 原生滚动表格 |
| **LLM 智能分析报告** | `module/llm.py` | `[LLM]` 开始/结束内的多行 Markdown | **AI 故障诊断**。缺失 Markdown 语法渲染，排版粗糙 | `<LogAiSummaryCard />` 格式化分析卡片 |

---

### 5.3 海图识别的组合解析机制（核心专题）

海图识别是整个自动化决策的核心大脑，也是“代码是单行、实际必须组合起来看”的典型代表。

#### 5.3.1 现有代码与打印还原

在 `module/map/map_base.py` 中，海图网格打印代码如下：

```python
def show(self):
    # 第 1 行：列标头
    logger.info('[地图-显示] ' + ' '.join([' ' + chr(x + 64 + 1) for x in range(self.shape[0] + 1)]))
    # 第 2 ~ N+1 行：各行数据
    for y in range(self.shape[1] + 1):
        text = str(y + 1).rjust(2) + ' ' + ' '.join(
            [self[(x, y)].str if (x, y) in self else '  ' for x in range(self.shape[0] + 1)])
        logger.info(text)
```

在真实运行时，它会输出类似如下连续的 8 条日志：

```text
INFO     14:24:31.851 │ [地图-显示]   A  B  C  D  E  F  G  H
INFO     14:24:31.852 │  1 ++ ++ ++ -- -- -- -- --
INFO     14:24:31.853 │  2 ++ ++ ++ -- 1M -- -- --
INFO     14:24:31.854 │  3 -- -- -- -- -- -- 2C --
INFO     14:24:31.855 │  4 -- FL -- -- -- ++ ++ ++
INFO     14:24:31.856 │  5 -- -- -- MY -- ++ ++ ++
INFO     14:24:31.857 │  6 -- -- -- -- -- -- -- BO
INFO     14:24:31.858 │  7 ++ ++ ++ -- -- -- -- --
```

#### 5.3.2 现有 WebUI 渲染的四大致命缺陷

1. **横向对齐完全失效（Offset Misalignment）**：
   - 列头行由于带有 `[地图-显示] `（占 13 个字符宽），导致 `A` 字母从第 15 列才开始。
   - 数据行则是 ` 1 ++ ++...`，数据从第 4 列开始。
   - 结果：**列名 A B C D 与下方的格子 `++`、`--`、`1M` 错开了整整 11 个字符宽度，完全对不齐**！
2. **时间戳严重割裂视觉（Visual Fragmentation）**：
   每一行都重复带有 `INFO 14:24:31.xxx │ `，占用了宝贵的横向视口空间，且把纵向连接的迷宫墙壁和水道切断。
3. **窄屏折行灾难（Wrapping Collapse）**：
   在手机端或展开侧边栏时（容器宽 < 900px），` 4 -- FL -- -- -- ++ ++ ++` 会在中间强行折成两行，整张战略地图彻底扭曲报废。
4. **2 字符缩写认知门槛（Cryptic Notation）**：
   新用户无法理解 `1M` 代表“大型主力舰队 (1★)”、`MY` 代表“神秘点”、`Fc` 代表“被塞壬捕获”。

#### 5.3.3 WebUI 流式块级聚合器 (Stream Aggregator)

为了在**不修改现有上万行游戏代码**的前提下彻底解决该问题，WebUI 日志摄入管道引入「流式块级聚合状态机」：

```typescript
// 聚合器状态机
interface MapAggregatorState {
  active: boolean;
  headerEntry: LogEntry | null;
  columns: string[];
  rows: Array<{ rowNum: number; cells: string[]; rawText: string }>;
}

export function aggregateLogEntries(entries: LogEntry[]): LogRenderItem[] {
  const result: LogRenderItem[] = [];
  let mapState: MapAggregatorState | null = null;

  for (const entry of entries) {
    const rawMsg = extractMessageText(entry.text);

    // 1. 检测海图列头起始: [地图-显示]   A  B  C ...
    const headerMatch = /^\[地图-显示\]\s+([A-Z](\s+[A-Z])*)$/.exec(rawMsg);
    if (headerMatch) {
      if (mapState) flushMap(result, mapState); // 闭合上一个未完成块
      mapState = {
        active: true,
        headerEntry: entry,
        columns: headerMatch[1].trim().split(/\s+/),
        rows: []
      };
      continue;
    }

    // 2. 检测海图数据行: 行号 + 双字符单元格列表 (如 " 1 ++ ++ -- 1M")
    if (mapState?.active) {
      const rowMatch = /^\s*(\d{1,2})\s+(([A-Za-z0-9_=+-]{2}\s*)+)$/.exec(rawMsg);
      if (rowMatch) {
        const rowNum = parseInt(rowMatch[1], 10);
        const cells = rowMatch[2].trim().split(/\s+/);
        mapState.rows.push({ rowNum, cells, rawText: rawMsg });
        continue;
      } else {
        // 遇到非海图行，海图块结束，输出合并卡片
        flushMap(result, mapState);
        mapState = null;
      }
    }

    // 3. 常规单行日志：直接原样输出
    result.push({ type: 'single', entry });
  }

  if (mapState) flushMap(result, mapState);
  return result;
}
```

#### 5.3.4 海图识别块组件 (`<LogMapBlock />`) 规范

聚合后的海图将被作为一个高内聚组件渲染：

1. **紧凑元数据头**：
   - 标题：`海图识别快照 (8×7) · 14:24:31`。
   - 右侧快捷操作：[查看原始文本]、[一键复制矩阵]、[折叠/展开]。
2. **消除偏移的绝对对齐网格**：
   - 剥离原有的 `[地图-显示]` 前缀，以纯 CSS Grid 或精确等宽 ASCII Table 呈现。
   - 顶部列头（A、B、C...）与下方格子精准垂直居中对齐。
3. **语义色彩高亮映射表**：

| 代码 | 语义释义 | WebUI 视觉呈现 |
|---|---|---|
| `FL` | 当前控制的第一舰队 | 亮蓝底色徽章 + 闪烁航向光标 |
| `Fl` | 第二舰队 | 青蓝底色徽章 |
| `ss` | 潜艇部队 | 靛蓝细边框徽章 |
| `BO` | 关卡 Boss 旗舰 | 金黄/深紫发光徽章 (`animate-pulse`) |
| `1M` / `2C` / `3E` | 敌舰（星级 + 舰种） | 橙红徽章（1星浅红、3星深红） |
| `MY` | 神秘问号点 / 物资 | 翠绿色徽章 |
| `AM` | 弹药补给点 | 明黄色弹药图标徽章 |
| `++` | 陆地与不可通行区域 | 哑光深灰底块 |
| `--` | 普通可航行海域 | 柔和海蓝色底点 |
| `==` | 已清除/安全格子 | 半透明浅灰符号 |
| `Fc` | 被塞壬捕获的舰队 | 危险红色警报边框 |

4. **交互式悬停 Tooltip**：
   鼠标悬停在格子上（如 `2C`），即时弹出浮层：“**坐标 F3：2★ 航母主力舰队（未清除）**”，彻底消除新用户的认知障碍。
5. **横向安全滚动保护**：
   网格容器使用 `.log-map-viewport { overflow-x: auto; white-space: pre; }`，在大图（如 15×12 的大型活动图）或窄屏下平滑横向拖拽，永不折行。

---

### 5.4 其他特殊格式的聚合与渲染标准

#### 1. 连续属性对齐块 (`<LogPropertyBlock />`)
- **识别规则**：连续 2 条及以上匹配 `^\s*([^:\n]{2,22}):\s*(.*)$` 且时间戳相差 < 200ms 的行。
- **渲染标准**：
  合并为一个原生 CSS Grid 卡片，Key 靠右、Value 靠左，支持布尔值/路径的原生着色，省略中间重复的时间戳。

#### 2. 三行式系统级横幅 (`<LogSystemBanner />`)
- **识别规则**：匹配三行组合 `[PURE_RULE(═)] -> [CENTER_TITLE] -> [PURE_RULE(═)]`。
- **渲染标准**：
  合并为一个沉浸式系统横幅组件，居中大字显示系统事件（如 `调度器启动`、`任务队列重置`），去除无意义的横线堆叠。

#### 3. 任务大纲双行去重 (`<LogStageHeader />`)
- **识别规则**：匹配 `[RULE(═ TITLE ═)] -> [INFO │ TITLE]` 的紧密相邻对。
- **渲染标准**：
  消除重复出现的下方 INFO 标题行；将第一条提取为具备大纲锚点的任务卡片头部。

#### 4. 四段式错误上下文 (`<LogErrorCard />`)
- **识别规则**：匹配首行 `[错误]` 并包含 `原因：`、`影响：`、`建议：` 的多行条目。
- **渲染标准**：
  渲染为危险色（Crimson）警示卡片，分为四行标签，建议部分高亮为绿/黄色操作指引，右上方提供「复制错误现场」按钮。

#### 5. 富异常堆栈 (`<LogTracebackViewer />`)
- **识别规则**：包含 `Traceback (most recent call last)` 的多行日志。
- **渲染标准**：
  默认收起为单行徽章 `[Traceback: ScriptEnd (2 栈帧) · 点击展开]`。展开后使用独立等宽水平滚动容器，高亮故障行（`❱`），局部变量框可独立折叠。

---

## 6. WebUI 解析与渲染规范

### 6.1 数据流与游标拉取契约

前端与后端的 WebSocket 日志通道遵循单向增量同步协议：

1. **拉取历史与握手**：
   - 客户端连接就绪后发送请求：`logs.get { instance: string, after: number, schemaVersion: '2.0' }`。
   - 服务端返回：`{ instance, cursor: number, reset: boolean, entries: LogEntry[] }`。
   - 若客户端未传 `schemaVersion: '2.0'`，服务端自动降级返回旧版文本条目。

2. **实时增量推送**：
   - 当后端生成新日志时，通过事件总线推送：`{ topic: 'logs', data: { instance, cursor, reset, entries: LogEntry[] } }`。
   - 若 `reset: true`，客户端清空本地日志缓冲区，全量替换为 `entries`；若 `reset: false`，客户端按 `id` 单调去重合并追加。
   - 客户端保留最大防爆上限（默认 1000 条），防止浏览器 DOM 数量溢出。

### 6.2 组件架构与布局规范

```
LogPanel (主容器，虚拟滚动，快捷键)
├── LogToolbar (工具栏：过滤等级、分类选择、搜索高亮、大纲抽屉开关、清屏、跟随)
├── LogOutlineDrawer (侧边大纲栏：提取 rule/hr 树，一键跳转到指定阶段)
└── VirtualScrollArea (虚拟列表容器，仅渲染视口可见条目)
    ├── [kind: 'text']           -> <LogTextLine /> (普通单行日志直接渲染)
    ├── [kind: 'rule']           -> <LogRuleHeader /> (注册大纲锚点)
    ├── [kind: 'key_value']      -> <LogKeyValueBadge />
    ├── [composite: 'property']  -> <LogPropertyBlock /> (连续属性合并卡片)
    ├── [composite: 'map']       -> <LogMapBlock /> (海图识别组合卡片，二维对齐网格)
    ├── [kind: 'action']         -> <LogActionChip /> (hover 展示详情卡片)
    ├── [kind: 'table']          -> <LogDataTable /> (水平自适应或独立横向滚动)
    ├── [kind: 'error_context']  -> <LogErrorCard /> (警示高亮，结构化建议)
    ├── [kind: 'traceback']      -> <LogTracebackViewer /> (默认折叠，源码高亮，复制)
    ├── [kind: 'llm_diagnosis']  -> <LogAiSummaryCard /> (AI 智能分析卡片)
    └── [kind: 'progress']       -> <LogProgressBar />
```

### 6.3 解决排版错乱的核心 CSS 规范

彻底废除对整个日志容器滥用 `white-space: pre-wrap; word-break: break-all;` 的旧做法：

1. **普通单行文本 (`.log-text-line`)**：
   采用 `white-space: pre-wrap; word-break: break-word;`，在保持连续空格的同时，按单词/汉字合理折行。
2. **结构化宽内容容器 (`.log-multiline-container` 与 `.log-map-viewport`)**：
   针对 `traceback`、`table`、`map_grid`、`map_block` 等固定字符对齐的内容，为其设置独立的局部横向滚动容器：
   ```css
   .log-multiline-container,
   .log-map-viewport {
     white-space: pre;
     word-break: normal;
     overflow-x: auto;
     overflow-y: hidden;
     max-width: 100%;
     scrollbar-width: thin;
   }
   ```
   **效果**：即使在手机屏或 800px 宽度下，异常堆栈框线、数据表格与海图网格依然完美对齐，用户可向右横向滑动浏览，绝不把框线打碎成碎片。

---

## 7. Python 端实现与双模降级设计

### 7.1 `LogEvent` 类与 Logger 增强

在 Python 后端新增 `module/logger/event.py`（逻辑解耦），并在 `module/logger.py` 中挂载增强 API：

```python
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import time

@dataclass
class LogEvent:
    id: int
    ts: int
    level: str
    category: str
    instance: str
    kind: str
    raw_text: str
    payload: Dict[str, Any]
    task: Optional[str] = None

    def to_dict(self):
        return asdict(self)
```

### 7.2 渐进增强与经典兼容 (Backward Compatibility)

项目中现存的上万行旧日志调用方式保持 **100% 兼容**，无需任何重构：

```python
# 1. 经典方式（零修改，自动封装为 kind='text'）
logger.info("普通任务执行中")
logger.warning("发现潜在异常")

# 2. 现有增强辅助方法（自动封装为对应 kind，保留终端富文本输出）
logger.hr("COMMISSION", level=1)  # 自动生成 kind='rule', depth=1
logger.attr("战斗次数", "3/5")       # 自动生成 kind='key_value', key='战斗次数', value='3/5'
logger.error_context(              # 自动生成 kind='error_context'
    title="游戏卡住",
    reason="无操作",
    impact="重启",
    action="检查模拟器"
)

# 3. 新增高阶结构化 API（按需选用）
logger.action("click", target="BATTLE_START", coords=(640, 360), cost_ms=35)
logger.map_grid(shape=(8, 8), camera=(4, 4), round=1, cells=[...])
logger.table(title="跑分结果", columns=[...], rows=[...])
```

### 7.3 控制台与文件落盘的自适应呈现

- **终端控制台（Rich Console）**：当遇到结构化 `LogEvent` 时，富渲染器（Rich Formatter）根据 `kind` 转换成对应的 Rich 组件（`Rule`、`Table`、带配色的属性文本）。
- **文件落盘（RichTimedRotatingHandler）**：自动提取 `raw_text`，按格式 `YYYY-MM-DD HH:MM:SS.mmm | LEVEL | MESSAGE` 紧凑持久化，绝不在文本日志中混入不可见 JSON 碎片。
- **WebUI 通信层（RuntimeService）**：若客户端声明接收 v2 协议，则直接序列化 `LogEvent` 的字典对象；若客户端未声明，则仅取 `raw_text` 发送旧版文本。

---

## 8. 落地实施总结与交互标准 (Implementation & Acceptance Summary)

在前端 WebUI (`LogPanel.tsx` 与 `LogCardView.tsx`) 中，已全面完成卡片式聚合引擎的生产级实现与交付验收：

1. **流式块级聚合状态机 (`aggregateEntriesToCards`)**：
   - 实现了对 160 列无颜色终端日志流的高性能线性聚合（单趟扫描 $O(N)$）。
   - 涵盖 11 种标准化卡片形态：系统横幅 (`system_banner`)、任务阶段标题 (`stage_header`)、2.5D 海域透视拓扑 (`perspective`)、海域战术地图 (`map_grid`)、寻路移动代价热力图 (`cost_grid`)、局部/雷达扫描矩阵 (`matrix_grid`)、紧凑状态属性清单 (`property_sheet`)、原生数据表格 (`data_table`)、四段式错误上下文 (`error_context`)、AI 智能诊断报告 (`llm_report`) 及经典单行高亮 (`single`)。

2. **核心视觉约束与工业级质感**：
   - **零动效准则**：移除所有不必要的 CSS 动画、渐变过渡与悬停高亮效果，界面响应零延迟，维持工程级高信息密度。
   - **海域 2.5D 透视视口**：梯形视口采用物理前倾（近大远小，短顶宽底），缺失边界以鲜明红色虚线标注，闭合边界以翠绿实线标注。
   - **战术地图网格**：海域纯蓝基底，单元格间距无缝合并（`gap: 0; padding: 0; border: none;`），全面覆盖大世界图例（`ME`、`EX`、`SD`、`AR`、`PO`、`MI`、`AM`、`FL`、`BO` 等），剔除波浪图标干扰。
   - **寻路移动代价热力图**：9999 障碍物直接呈现为纯黑背景（`#000000`），起点 0 呈现为高亮翡翠绿，移动步数代价自适应多阶平滑热力色谱。
   - **紧凑原生数据表格**：消除全屏 100% 弹性拉伸与冗余留白，采用自适应紧凑排版（`width: fit-content; align-self: flex-start;`），支持 Unicode 全格式边框与经典 ASCII `+---+---+` 边框，数值列自动右对齐。
   - **结构化异常追踪**：默认直接展开堆栈，精准高亮 `▶` 故障代码行与局部变量表（locals），剔除无意义的帧号徽标。
   - **Markdown 智能诊断**：集成 `MarkdownView` 原生渲染器，支持 KaTeX 数学公式、Markdown 列表代码块与安全 HTML 清理。

3. **双模自由切换与多语言覆盖**：
   - 顶栏常驻卡片视图 (`<LayoutGrid />`) 与经典黑框终端 (`<Terminal />`) 切换按钮，偏好设置持久化至 `localStorage`（默认激活现代卡片模式）。
   - 全面支持 `zh-CN`、`zh-TW`、`en-US`、`ja-JP`、`zh-MIAO` 五种语言的无缝国际化切换。

---

## 9. 多主题系统适配规范 (Multi-Theme Synchronization)

LDL 卡片式日志系统已全面完成对 AzurPilot 全量 6 套主题（Classic Light、Classic Dark、Minimal、Extreme Compact、Legacy Light、Legacy Dark）的统一样式同步与设计契约绑定。通过解耦主题底层变量与表现层卡片组件，实现一套业务组件在不同主题风格下的无缝原生呈现。

### 9.1 全量主题适配原则 (Theme Adaptation Principles)

| 主题族类 | 包含主题 | 设计哲学与核心材质 | 几何形态与空间排版 | 视觉层级与对比度策略 |
|---|---|---|---|---|
| **Classic 材质主题** | `Classic Light`<br>`Classic Dark` | Apple 材质设计语言 (Apple Material Glass)，半透明毛玻璃底色 (`var(--theme-glass)`)，微发光内轮廓与高光边框 (`var(--theme-glass-edge)`) | 10px 控件圆角 / 12px 卡片圆角 (`--theme-radius-card: 12px`)，呼吸感内边距 | 浅色强调玻璃晶莹通透感；深色模式采用深黑高对比背景，增强文本与状态徽章辨识度，避免眩光 |
| **Minimal 简约主题** | `Minimal` | 现代平面工程风格，扁平无阴影 (`box-shadow: none`)，移除所有滤镜与模糊层 | 8px 平面几何圆角 (`--theme-radius-control: 8px`)，标准工作台间隙 | 卡片使用实色背景 (`var(--surface)`)，外层容器与卡片头部采用凹陷背景色 `var(--surface-muted)` 托衬卡片，边界纯净硬朗 |
| **Extreme 紧凑主题** | `Extreme Compact` | 极致信息密度与专业监控，最大化屏幕信息吞吐量，消除一切视觉留白 | 强制全量 **0px 零圆角** (`border-radius: 0 !important`)，超紧凑边距，容器内边距深度压缩 | 排版字号下探至 10px / 9px，行高高度收紧；滚动条压至 0 宽或外挂浮层轨道，保证日志横向空间最大化 |
| **Legacy MD3 主题** | `Legacy Light`<br>`Legacy Dark` | Material Design 3 经典规范，传承老版视觉记忆与纯色对比基调 | 12px 卡片圆角 / 8px 控件圆角 (`--theme-radius-control: 8px`) | 采用表面高度 (Surface Elevation) 体系，不透明实色对比结合细腻的浮层微阴影 (`0 1px 2px rgb(0 0 0 / .05)`)，经典靛紫沉稳基调 |

#### 1. Classic 材质主题（Light / Dark）
- **材质质感**：基于 Apple 毛玻璃材质，底层使用 `backdrop-filter: var(--theme-material-filter)` 与半透明背景 `var(--theme-glass)`。
- **边缘细节**：边框采用微发光边框 `var(--theme-glass-edge)` 与内发光阴影 `var(--theme-glass-shadow)`，卡片在暗色模式下能够清晰勾勒轮廓而不过分刺眼。
- **几何与空间**：采用 10px 控件与 12px 卡片圆角，视觉轻盈、富有空间纵深感。

#### 2. Minimal 简约主题
- **平面几何**：完全摒弃拟态与投影，全局 `--theme-shadow-*: none`，无任何毛玻璃或高光特效。
- **凹陷底色托衬**：为解决扁平化带来的视觉层级扁平问题，外层日志滚动视口与卡片头部均使用凹陷背景色 `var(--surface-muted)`，卡片主体采用纯白/纯黑 `var(--surface)`，通过冷暖明暗底色对比形成明确的几何卡片边界。
- **几何圆角**：统一为精致利落的 8px 平面圆角。

#### 3. Extreme 紧凑主题 (Extreme Compact)
- **极限吞吐量**：专为多实例监控与密集自动化排查设计，单位屏幕高度内容纳最多日志条目。
- **绝对零圆角**：强制覆盖所有卡片、徽标、视口边框圆角为 `0px`（`border-radius: 0`），消除圆角带来的边缘留白浪费。
- **压缩排版**：
  * 内边距压缩：卡片内边距从默认 10px~14px 缩减至 4px~6px。
  * 字体与行高：代码块、属性清单等下探至 10px 与 9px，行高压至 1.35~1.45。
  * 网格自适应：海图网格与热力图单元格无缝紧贴，剔除外围冗余 Margin。

#### 4. Legacy MD3 主题（Light / Dark）
- **规范继承**：严格复刻经典 Material Design 3 容器标准与色板规范。
- **微阴影与纯色对比**：不使用半透明毛玻璃，而是采用纯色表面（Light: `#ffffff`，Dark: `#1e1e1e`）与细腻的低扩散微阴影（`0 1px 2px rgb(0 0 0 / .05)`）营造层次感。
- **圆角规则**：遵循 MD3 Medium 规格（卡片 12px、内嵌控件与按钮 8px/20px）。

---

### 9.2 主题颜色契约变量继承机制 (Contract Tokens & Variable Inheritance)

为了实现 6 套主题的无缝切换与扩展，LDL 组件**严禁硬编码任何绝对颜色值**（如 `#ffffff`、`#000000`、`rgba(...)`），所有颜色、边框、阴影与字体必须严格通过 `--theme-*` 契约变量进行消费。

#### 9.2.1 核心契约变量映射表

```
┌────────────────────────────────────────────────────────┐
│             主题定制源 (theme.css / palettes.ts)         │
│  Classic Material / Minimal Palettes / Legacy CSS      │
└───────────────────────────┬────────────────────────────┘
                            │ 注入基础契约变量
┌───────────────────────────▼────────────────────────────┐
│                 全局设计契约层 (Design Tokens)           │
│   --theme-surface* / --theme-border / --theme-log-*    │
└───────────────────────────┬────────────────────────────┘
                            │ 驱动组件样式
┌───────────────────────────▼────────────────────────────┐
│              LDL 卡片渲染器 (LogCardView.tsx)           │
│  .log-card / .map-badge / .traceback-viewer / ...      │
└────────────────────────────────────────────────────────┘
```

| 契约变量族 | 变量名称 | 语义职责与 LDL 映射组件 |
|---|---|---|
| **表面与容器** | `--theme-surface` | 卡片核心背景色（`.log-card` 主体、展开面板、堆栈查看器） |
| | `--theme-surface-muted` | 凹陷背景色、卡片头部底色（`.card-header`、局部变量容器、空状态） |
| | `--theme-border` | 卡片边框、网格分割线、表格行列分隔线 |
| | `--theme-text` | 日志正文主色、卡片标题、属性值、代码字符 |
| | `--theme-muted` | 次级辅助文本、时间戳标签、属性键名、行号（Gutter） |
| | `--theme-accent` | 重点高亮色、主操作按钮、标题装饰条、寻路路径航向 |
| | `--theme-accent-soft` | 强调色浅色衬底、选区背景、当前高亮步骤背景 |
| **日志等级与状态** | `--theme-log-debug` | DEBUG 等级标记、调试性低优输出 |
| | `--theme-log-info` | INFO 等级标记、常规业务推进日志、普通链接 |
| | `--theme-log-warning` | WARNING 等级标记、非致命异常、重试警示、轻微滞后 |
| | `--theme-log-error` | ERROR 等级标记、故障中断、四段式错误卡片头部警报 |
| | `--theme-log-critical` | CRITICAL 等级标记、敏感任务熔断停机、框架崩溃 |
| **词法 Token 与数据** | `--theme-log-time` | 时间戳着色（HH:MM:SS.mmm）、耗时统计徽章 |
| | `--theme-log-true` | 布尔真值（True）、操作成功、闭合完整边界 |
| | `--theme-log-false` | 布尔假值（False）、操作失败、断裂缺失边界 |
| | `--theme-log-null` | 空值（None/Null）、未初始化状态 |
| | `--theme-log-path` | 文件路径、模块调用栈、资源标识符 |
| | `--theme-log-attr` | 属性名称键、OCR 识别置信度值、坐标标识 |
| | `--theme-log-search` | 日志全文检索与关键词过滤匹配高亮底色 |
| **字体契约** | `--theme-font-sans` | 卡片标题、说明文本、自愈指南动作建议 |
| | `--theme-font-mono` | ASCII 海图网格、移动代价热力图、等宽数据表格、Traceback 源码帧 |

#### 9.2.2 动态热重载与零代价重绘
当用户在 WebUI 切换主题、更换调色板（Palette）或切换深浅模式时：
1. 框架仅在根节点 `<html>` 或 `:root` 动态变更 `data-theme` 与 `data-color-mode` 属性，或通过内联样式批量刷新契约 CSS 变量；
2. 虚拟滚动列表内部的数百个日志卡片节点无需触发 React 虚拟 DOM 树重新挂载或全量重建；
3. 浏览器依据 CSS 自定义属性继承树完成原生硬件加速重绘（Repaint），重绘耗时低于 16ms，确保流畅不掉帧。

---

### 9.3 工业级性能与交互约束 (Zero-Hover & Zero-Motion Constraints)

作为面向 7×24 小时无人值守运行、每秒可能吞吐数十上百条事件的工业级自动化系统，LDL 日志界面必须保证极端严苛的性能基线与视觉抗疲劳要求。因此，**在全量 6 套主题中一律强制推行「零悬停特效、零过渡动效」的工业级硬约束**：

#### 1. 全主题一律禁用 Hover 特效 (Zero Hover Transformations)
- **绝对禁止项**：
  * 严禁在日志卡片上添加悬停位移（`translateY(-2px)`）、缩放（`transform: scale(1.01)`）或边框发光扩散（`box-shadow: 0 8px 24px ...`）。
  * 严禁海图网格单元格在鼠标掠过时触发上浮或背景爆亮效果。
  * 严禁属性表格行在 hover 时触发高对比度跳动。
- **工程约束依据**：
  * **防止图层重排与掉帧**：日志列表处于高速追加流中，频繁的 hover 复合图层提升会打断浏览器的合成器线程优化，造成虚拟滚动卡顿。
  * **保证文本选取精准度**：排查问题时，运维人员常需跨行划选日志文本、报错信息或网格坐标。卡片上浮或抖动会直接破坏操作系统的文本选择光标位置，导致复制错位。

#### 2. 全主题一律禁用过渡动效 (Zero Transitions & Zero Animation)
- **绝对禁止项**：
  * 卡片与子元素严禁配置 `transition: all 0.2s`、`transition: height` 等补间缓动。
  * 卡片折叠/展开、异常堆栈展开、查看原始文本等交互，一律采用**即时状态切换（0ms 响应）**，禁止风琴式伸缩滑行动画。
  * 新增日志卡片流式推入时，严禁使用淡入（Fade-in）、滑动切入（Slide-in）或尺寸伸展动画。
- **工程约束依据**：
  * **消除界面呈现延迟**：在排查严重故障时，运维人员需要第一眼看到完整调用栈与自愈建议，任何 200ms~300ms 的过度动画都是对排障效率的消耗。
  * **消除 CPU / GPU 冗余开销**：7×24 小时常驻运行中，后台多开实例的 WebUI 界面若持续计算 CSS 动效插值，会产生不必要的资源占用，违背低功耗自动化框架的设计初衷。

---

## 10. 高性能前端渲染与流式批处理架构 (High-Performance Virtualization & Stream Pipeline)

在高频日志推送或密集复杂卡片渲染场景下（如包含 ASCII 视锥图、代价热力图、大型数据表格与异常调用栈时），单纯的全量 DOM 渲染会导致数万个节点驻留内存，引发严重的重排（Reflow）阻塞与掉帧卡顿。为保证 60 FPS 的丝滑交互体验与低 CPU 占用，前端实现了全链路的高性能渲染架构：

### 10.1 视口虚拟化窗口裁剪与动态测高 (Virtual Windowing & Slicing)
- **零开销自适应阈值 (`VIRTUAL_THRESHOLD = 40`)**：
  * 当卡片总数 $\le 40$ 时，直接执行纯扁平渲染，完全避免虚拟窗口计算、滚动监听和占位计算的开销。
  * 当卡片总数 $> 40$ 时，自动无缝切换为虚拟视口裁剪模式。
- **动态预估与测量高度表 (Dynamic Height Cache)**：
  * 针对不同类型的卡片（如单行卡片、海图、透视梯形、热力图、表格、Traceback、LLM 报告等）设置不同的初始估算高度（42px ~ 420px），结合数据行数动态微调。
  * 真实渲染时通过组件回调动态更新实测高度，实现高度缓存自愈。
- **$O(\log N)$ 二分查找与过采样缓冲 (`OVERSCAN_BUFFER_PX = 800`)**：
  * 借助前缀高度累加表（Prefix Sum Offset），滚动时通过二分查找（`findVisibleRange`）在毫秒级时间内定位视口当前可见范围。
  * 上下各提供 800px 的过采样安全缓冲区，消除快速滚屏时的白屏走样感。
- **无感上下占位与平滑跟随 (Spacer & Auto-Follow Integration)**：
  * 容器首尾使用 `paddingTop` 与 `paddingBottom` 模拟全量列表高度，保持滚动条轨道比例与物理真实感。
  * 与 `LogPanel` 的 RAF 平滑跟随算法完美协同，即使在视口虚拟化动态剔除/挂载 DOM 节点的情况下，也能精准锚定最底端最新卡片，无任何跳动或抖动。

### 10.2 流式日志 RAF 微批处理缓冲队列 (RequestAnimationFrame Micro-batching)
- **高频推流冲突**：WebSocket 可能在 1 秒内触发 20~50 次日志事件推送。若每次推送都直接调用 `setEntries` 触发 React 调度与 Reconciliation，会形成渲染风暴。
- **微批队列设计 (`queueLogEvent` & `flushBuffer`)**：
  * 所有入站的 `logs` 事件先推入 `logBuffer` 缓冲队列中累积。
  * 利用 `requestAnimationFrame`（附带环境降级垫片 `safeRaf`）将渲染提交频率严格节流并与浏览器刷新率（~16.6ms / 60 FPS）硬同步。
  * 在导出日志（Download）或清空日志（Clear）时，主动执行同步 `flushBuffer`，防止流式缓冲区滞留数据丢失。

### 10.3 增量尾部聚合与不可变对象复用 (Incremental Tail Aggregation)
- **历史前缀复用 (`REUSE_TAIL_MARGIN = 4`)**：
  * 当新日志追加到末尾时，避免对前 $N$ 条历史日志做全量正则状态机重新扫描。
  * `aggregateEntriesToCards` 会比对已有日志切片引用，仅回溯未闭合的末尾 4 条记录进行增量解析，并将新卡片安全追加到历史不可变卡片列表末尾。
  * 该机制将流式追加卡片的时间复杂度从 $O(N)$ 降低为 $O(1)$，并最大程度维持卡片对象引用的唯一性（Referential Equality）。

### 10.4 词法分词 LRU 高速缓存 (Lexical Token Cache)
- **模块级预编译正则与分词池 (`TOKEN_CACHE_MAX = 2000`)**：
  * 静态预编译多合一 Token 正则表达式（`TOKEN_REGEX`），杜绝运行时重复动态编译正则。
  * 高频字符串分词结果缓存在模块级 `tokenCache`（LRU 策略，最大 2000 项），同一行或相似特征的日志直接复用预构建的 React 节点，减少垃圾回收（GC）频率。

### 10.5 精细化组件记忆化 (Component Memoization)
- **全量卡片封装 `React.memo`**：
  * 12 种不同卡片组件（`SingleLogLineCard`、`MapGridCard`、`PerspectiveCard`、`CostGridCard`、`MatrixGridCard`、`PropertySheetCard`、`DataTableCard`、`ErrorContextCard`、`TracebackCard`、`LlmReportCard`、`SystemBannerCard`、`StageHeaderCard`）均用 `memo` 严密包裹。
  * 自定义 Props 浅比对函数（`prev.card === next.card && prev.search === next.search`），确保当日志微批刷新追加新卡片时，视口内所有已有历史卡片节点跳过重渲染，DOM 更新操作量降至最低。


