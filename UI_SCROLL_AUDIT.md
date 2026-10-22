# UI 页面逐屏滚动与全视口真实巡检审计报告 (UI_SCROLL_AUDIT.md)

**执行标准**：强制全页面滚动巡检与视觉修复协议<br>
**巡检工具**：Playwright Headless Chromium 真实浏览器自动化套件<br>
**执行日期**：2026-10-18<br>
**执行状态**：**PASS**（全部 6 个目标视口与交互验收项通过真实浏览器验证）

---

## 一、审计概述与核心问题根因分析

在本次巡检中，针对「AFA 远程配对功能优化（二维码替换粒子码）」及 WebUI 全局视口适配进行了深度巡检，发现并彻底修复了以下三个深层布局与交互问题：

1. **宽屏低高度视口（2016×766、1366×768）纵向单列挤压问题**：
   - **根因**：原布局采用单列居中自上而下堆叠（居中主提示 → 272px 二维码 → 配对码 → 按钮组 → 倒计时 → 设备列表），在 2016×766 等高度受限的宽屏窗口下，二维码卡片占用了过多纵向高度，导致配对码、复制按钮与设备列表完全掉入首屏折叠线以下，用户不滚动无法获取配对码。
   - **修复**：重构为响应式并排配对台（`.pairing-stage`），在桌面端（宽屏及横屏）采用双列并排流（左列 272×272 二维码卡片，右列配对引导、六位大字配对码徽标、复制按钮组与倒计时安全说明），纵向高度由 >600px 压缩至 ~290px。在 2016×766 首屏即可同时完整呈现二维码、六位配对码、复制按钮组与已授权设备列表头部。

2. **移动端与窄屏（≤950px）内部主滚动容器高度塌陷导致无法滚动问题**：
   - **根因**：材质主题（Apple HIG/Material）通过 `.app-shell:has(> .main-shell > .shell-frame > .topbar)` 设置了 `height: var(--viewport-height); overflow: hidden;`，并依赖 `.main-shell > main` 处理内部纵向滚动。但在 `@media (max-width: 950px)` 响应式规则中，外层 `.app-shell` 被切为 `display: block`，导致内部 `.main-shell` 失去网格/弹性高度继承约束（未声明 `height: 100%`），`main` 的内容高度直接撑开而无法产生可滚动计算，被外层 `overflow: hidden` 强制裁切。
   - **修复**：在 `apple.css` 中显式为 `.main-shell` 补全 `height: 100%`，确保在移动端与平板窄屏下，`main#main-content` 准确承载 `var(--viewport-height) - 56px` 的滚动视口，产生平滑、可滚动的物理滚动条。

3. **小屏移动端（360×640）设备卡片状态徽标文字竖排折行问题**：
   - **根因**：`.pairing-device-title-row` 在 360px 宽度下空间受限，未声明 `flex-wrap: wrap`，导致「已授权」徽标被挤压折行。
   - **修复**：声明 `.pairing-device-title-row { flex-wrap: wrap; }` 与 `.pairing-device-badge { white-space: nowrap; flex-shrink: 0; }`，确保在任何极窄屏幕下均平整单行展现。

---

## 二、全量视口实测数据与逐屏滚动记录

测试套件真实启动 Chromium 浏览器，对每个视口执行了：
1. 首屏渲染稳定校验与顶部截图
2. 内部滚动容器 DOM 盒模型与尺寸检测（`clientHeight`, `scrollHeight`, `maxScrollTop`）
3. 真实鼠标滚轮（`page.mouse.wheel`）每次按 75% 视口高度逐屏滚动
4. 页面最底部到达验证与全部已授权设备检查
5. 真实点击最底部设备条目的「移除配对」按钮并验证列表即时更新
6. 向上平滑回滚至顶部并验证无粘性错位与闪烁

### 1. 关键视口：2016 × 766 (Key Widescreen Viewport)

- **视口尺寸**：宽度 2016px，高度 766px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`732px`
- **容器实测 scrollHeight**：`1803px`
- **最大可滚动距离 (maxScrollTop)**：`1071px`
- **物理安全空隙 (Quiet Zone)**：PASS（四周 Padding 严格等于 32px，背景纯白 `#ffffff`，满足 ISO/IEC 18004 与 GB/T 18284 标准 $\ge 4\text{X}$）
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [2016x766-key-1-top.png](frontend/test-results/screens/2016x766-key-1-top.png)
  - `scroll-1` (scrollTop: 574px) -> [2016x766-key-2-scroll.png](frontend/test-results/screens/2016x766-key-2-scroll.png)
  - `scroll-2` (scrollTop: 1071px) -> [2016x766-key-3-scroll.png](frontend/test-results/screens/2016x766-key-3-scroll.png)
  - `bottom` (scrollTop: 1071px) -> [2016x766-key-bottom.png](frontend/test-results/screens/2016x766-key-bottom.png)
  - `backtop` (scrollTop: 0px) -> [2016x766-key-backtop.png](frontend/test-results/screens/2016x766-key-backtop.png)
  - `fullpage` 全景 -> [2016x766-key-fullpage.png](frontend/test-results/screens/2016x766-key-fullpage.png)
- **设备列表验证**：初始 5 台已授权设备全部完整渲染，成功点击末尾设备 #5 移除，设备数减少至 4 台。
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

### 2. 桌面常用视口：1920 × 1080 (FHD Desktop)

- **视口尺寸**：宽度 1920px，高度 1080px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`1046px`
- **容器实测 scrollHeight**：`1733px`
- **最大可滚动距离 (maxScrollTop)**：`687px`
- **物理安全空隙 (Quiet Zone)**：PASS（Padding 32px，背景 `#ffffff`）
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [1920x1080-desktop-1-top.png](frontend/test-results/screens/1920x1080-desktop-1-top.png)
  - `scroll-1` (scrollTop: 687px) -> [1920x1080-desktop-2-scroll.png](frontend/test-results/screens/1920x1080-desktop-2-scroll.png)
  - `bottom` (scrollTop: 687px) -> [1920x1080-desktop-bottom.png](frontend/test-results/screens/1920x1080-desktop-bottom.png)
  - `backtop` (scrollTop: 0px) -> [1920x1080-desktop-backtop.png](frontend/test-results/screens/1920x1080-desktop-backtop.png)
  - `fullpage` 全景 -> [1920x1080-desktop-fullpage.png](frontend/test-results/screens/1920x1080-desktop-fullpage.png)
- **设备列表验证**：配对台与前 4 项设备直接在首屏呈现，成功滚动到底部并移除末尾设备。
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

### 3. 笔记本视口：1366 × 768 (Standard Laptop)

- **视口尺寸**：宽度 1366px，高度 768px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`734px`
- **容器实测 scrollHeight**：`1731px`
- **最大可滚动距离 (maxScrollTop)**：`997px`
- **物理安全空隙 (Quiet Zone)**：PASS（Padding 32px，背景 `#ffffff`）
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [1366x768-laptop-1-top.png](frontend/test-results/screens/1366x768-laptop-1-top.png)
  - `scroll-1` (scrollTop: 576px) -> [1366x768-laptop-2-scroll.png](frontend/test-results/screens/1366x768-laptop-2-scroll.png)
  - `scroll-2` (scrollTop: 997px) -> [1366x768-laptop-3-scroll.png](frontend/test-results/screens/1366x768-laptop-3-scroll.png)
  - `bottom` (scrollTop: 997px) -> [1366x768-laptop-bottom.png](frontend/test-results/screens/1366x768-laptop-bottom.png)
  - `backtop` (scrollTop: 0px) -> [1366x768-laptop-backtop.png](frontend/test-results/screens/1366x768-laptop-backtop.png)
  - `fullpage` 全景 -> [1366x768-laptop-fullpage.png](frontend/test-results/screens/1366x768-laptop-fullpage.png)
- **设备列表验证**：滚动过程顺畅，底层所有设备条目及「WebUI 配置」面板均可正常访问与点击。
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

### 4. 平板纵向视口：768 × 1024 (Tablet Portrait)

- **视口尺寸**：宽度 768px，高度 1024px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`968px`
- **容器实测 scrollHeight**：`2249px`
- **最大可滚动距离 (maxScrollTop)**：`1281px`
- **响应式断点表现**：自适应切换为紧凑对称折行结构，二维码居中对齐，下方紧凑排列配对码与操作按钮。
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [768x1024-tablet-1-top.png](frontend/test-results/screens/768x1024-tablet-1-top.png)
  - `scroll-1` (scrollTop: 768px) -> [768x1024-tablet-2-scroll.png](frontend/test-results/screens/768x1024-tablet-2-scroll.png)
  - `scroll-2` (scrollTop: 1281px) -> [768x1024-tablet-3-scroll.png](frontend/test-results/screens/768x1024-tablet-3-scroll.png)
  - `bottom` (scrollTop: 1281px) -> [768x1024-tablet-bottom.png](frontend/test-results/screens/768x1024-tablet-bottom.png)
  - `backtop` (scrollTop: 0px) -> [768x1024-tablet-backtop.png](frontend/test-results/screens/768x1024-tablet-backtop.png)
  - `fullpage` 全景 -> [768x1024-tablet-fullpage.png](frontend/test-results/screens/768x1024-tablet-fullpage.png)
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

### 5. 现代手机视口：390 × 844 (Mobile Modern)

- **视口尺寸**：宽度 390px，高度 844px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`788px`
- **容器实测 scrollHeight**：`2411px`
- **最大可滚动距离 (maxScrollTop)**：`1623px`
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [390x844-mobile-1-top.png](frontend/test-results/screens/390x844-mobile-1-top.png)
  - `scroll-1` (scrollTop: 633px) -> [390x844-mobile-2-scroll.png](frontend/test-results/screens/390x844-mobile-2-scroll.png)
  - `scroll-2` (scrollTop: 1266px) -> [390x844-mobile-3-scroll.png](frontend/test-results/screens/390x844-mobile-3-scroll.png)
  - `scroll-3` (scrollTop: 1623px) -> [390x844-mobile-4-scroll.png](frontend/test-results/screens/390x844-mobile-4-scroll.png)
  - `bottom` (scrollTop: 1623px) -> [390x844-mobile-bottom.png](frontend/test-results/screens/390x844-mobile-bottom.png)
  - `backtop` (scrollTop: 0px) -> [390x844-mobile-backtop.png](frontend/test-results/screens/390x844-mobile-backtop.png)
  - `fullpage` 全景 -> [390x844-mobile-fullpage.png](frontend/test-results/screens/390x844-mobile-fullpage.png)
- **设备列表验证**：设备卡片排版紧凑适中，无水平滚动溢出，末尾设备条目成功操作并移除。
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

### 6. 小型手机视口：360 × 640 (Mobile Compact)

- **视口尺寸**：宽度 360px，高度 640px
- **主滚动容器**：`main#main-content`
- **容器实测 clientHeight**：`584px`
- **容器实测 scrollHeight**：`2508px`
- **最大可滚动距离 (maxScrollTop)**：`1924px`
- **逐屏滚动检查点**：
  - `top` (scrollTop: 0px) -> [360x640-small-mobile-1-top.png](frontend/test-results/screens/360x640-small-mobile-1-top.png)
  - `scroll-1` (scrollTop: 480px) -> [360x640-small-mobile-2-scroll.png](frontend/test-results/screens/360x640-small-mobile-2-scroll.png)
  - `scroll-2` (scrollTop: 960px) -> [360x640-small-mobile-3-scroll.png](frontend/test-results/screens/360x640-small-mobile-3-scroll.png)
  - `scroll-3` (scrollTop: 1440px) -> [360x640-small-mobile-4-scroll.png](frontend/test-results/screens/360x640-small-mobile-4-scroll.png)
  - `scroll-4` (scrollTop: 1920px) -> [360x640-small-mobile-5-scroll.png](frontend/test-results/screens/360x640-small-mobile-5-scroll.png)
  - `bottom` (scrollTop: 1924px) -> [360x640-small-mobile-bottom.png](frontend/test-results/screens/360x640-small-mobile-bottom.png)
  - `backtop` (scrollTop: 0px) -> [360x640-small-mobile-backtop.png](frontend/test-results/screens/360x640-small-mobile-backtop.png)
  - `fullpage` 全景 -> [360x640-small-mobile-fullpage.png](frontend/test-results/screens/360x640-small-mobile-fullpage.png)
- **设备列表验证**：在 360px 宽度极限条件下，设备名称与「已授权」标签保持水平平整对齐，移除配对按钮无遮挡且正常点击。
- **Bottom Reached**: YES | **All Content Accessible**: YES | **Clipping Detected**: NO | **Interaction Verified**: YES

---

## 三、检查项清单与验收判定

| 检查项 | 验证方式 | 判定 |
|---|---|---|
| **Quiet Zone 安全间距** | DOM 盒模型实测 padding=32px，纯白底色，内置 4 module SVG 边距 | **PASS** |
| **2016 × 766 关键视口完整性** | 并排双列配对台，二维码、配对码、操作按钮和首批设备均一屏可见 | **PASS** |
| **逐屏滚动（每次约 75%）** | 真实鼠标滚轮循环驱动，保存每个阶段截图 | **PASS** |
| **底部到达与操作性** | 到达最底部并成功对最后一条设备点击「移除配对」，列表即时同步 | **PASS** |
| **回滚稳定性** | 向上滚轮回滚至 scrollTop=0，无抖动、无粘性漂移、无残影 | **PASS** |
| **多设备支持（长列表）** | 实测 5 台设备并支持动态移除，无高度截断或滚动冲突 | **PASS** |
| **交互反馈** | 点击六位配对码复制、点击复制配对码按钮、点击复制链接按钮均提示成功 | **PASS** |
| **控制台异常** | 真实运行控制台零 error、零警告阻断 | **PASS** |

**最终判定：PASS**
