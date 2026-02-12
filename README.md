**| [English](README_en.md) | 简体中文 | [日本語](README_jp.md) |**

# AzurLaneAutoScript

我们屁眼通红(Python)真的太有实力了

## 添加了

1. 智能调度
2. 解除大世界限制
3. 如果使用 docker 部署 默认 webui 密码为 123456

## 感谢某不知名 AI IDE 的支持（

请加 QQ 群 1077880342

# 智能调度系统完整逻辑流程图

## 系统概述

智能调度系统(OpsiScheduling)是AzurLaneAutoScript中用于协调大世界任务的核心调度器，负责在侵蚀1练级(OpsiHazard1Leveling)和黄币补充任务(OpsiMeowfficerFarming、OpsiObscure、OpsiAbyssal、OpsiStronghold)之间智能切换。

---

## 核心配置项

### OpsiScheduling 配置

| 配置项                                             | 说明                               | 默认值                  |
| -------------------------------------------------- | ---------------------------------- | ----------------------- |
| `Scheduler.Enable`                                 | 智能调度总开关                     | false                   |
| `OperationCoinsPreserve`                           | 侵蚀1黄币保留值(覆盖原配置)        | 0 (使用原配置)          |
| `ActionPointPreserve`                              | 行动力保留值(覆盖所有任务)         | 0 (使用原配置)          |
| `ActionPointNotifyLevels`                          | 行动力阈值通知列表                 | "500, 1000, 2000, 3000" |
| `OperationCoinsReturnThreshold`                    | 黄币返回阈值                       | null (等于CL1保留值)    |
| `OperationCoinsReturnThresholdApplyToAllCoinTasks` | 黄币阈值是否适用于所有黄币补充任务 | true                    |
| `EnableMeowfficerFarming`                          | 启用短猫相接                       | true                    |
| `EnableObscure`                                    | 启用隐秘海域                       | false                   |
| `EnableAbyssal`                                    | 启用深渊海域                       | false                   |
| `EnableStronghold`                                 | 启用塞壬要塞                       | false                   |

---

## 完整逻辑流程图

```mermaid
flowchart TD
    Start([用户启动OpsiScheduling任务]) --> CheckEnabled{智能调度<br/>是否启用?}

    CheckEnabled -->|否| End1([跳过执行])
    CheckEnabled -->|是| GetResources[获取当前资源状态]

    GetResources --> GetYellowCoins[读取当前黄币数量]
    GetYellowCoins --> GetActionPoint[进入行动力界面<br/>读取总行动力]
    GetActionPoint --> GetCL1Preserve[获取CL1黄币保留值<br/>优先使用智能调度配置]

    GetCL1Preserve --> CheckYellowCoins{黄币 < 保留值?}

    CheckYellowCoins -->|否| YellowCoinsEnough[黄币充足]
    CheckYellowCoins -->|是| YellowCoinsLow[黄币不足]

    %% 黄币充足分支
    YellowCoinsEnough --> GetMinAPReserve[获取CL1最低行动力保留值]
    GetMinAPReserve --> CheckMinAP{行动力 < 最低保留?}

    CheckMinAP -->|是| NotifyAPLow[推送通知:<br/>行动力低于最低保留]
    CheckMinAP -->|否| ExecuteCL1[执行侵蚀1练级]

    NotifyAPLow --> DelayScheduling1[延迟智能调度1小时]
    DelayScheduling1 --> End2([任务停止])

    ExecuteCL1 --> DisableAllCoinTasks[禁用所有黄币补充任务]
    DisableAllCoinTasks --> CallCL1[调用OpsiHazard1Leveling]
    CallCL1 --> End3([任务停止])

    %% 黄币不足分支
    YellowCoinsLow --> GetMeowAPPreserve[获取短猫行动力保留值<br/>优先使用智能调度配置]
    GetMeowAPPreserve --> CheckMeowAP{行动力 < 短猫保留值?}

    CheckMeowAP -->|是| NotifyBothLow[推送通知:<br/>黄币与行动力双重不足]
    CheckMeowAP -->|否| GetEnabledTasks[获取智能调度中<br/>启用的黄币补充任务]

    NotifyBothLow --> DelayScheduling2[延迟智能调度1小时]
    DelayScheduling2 --> End4([任务停止])

    GetEnabledTasks --> CheckTasksEmpty{启用的任务<br/>列表为空?}

    CheckTasksEmpty -->|是| DefaultMeow[默认启用短猫相接]
    CheckTasksEmpty -->|否| CheckTasksEnabled[检查各任务调度器状态]

    DefaultMeow --> CheckTasksEnabled

    CheckTasksEnabled --> AutoEnableTasks[自动启用未启用的任务]
    AutoEnableTasks --> NotifySwitchToCoin[推送通知:<br/>切换至黄币补充任务]
    NotifySwitchToCoin --> CallCoinTasks[调用所有可用的<br/>黄币补充任务]
    CallCoinTasks --> CheckCoolingDown{有冷却任务?}

    CheckCoolingDown -->|是| DelayToCD[延迟智能调度<br/>到冷却任务之后]
    CheckCoolingDown -->|否| End5([任务停止])

    DelayToCD --> End6([任务停止])

    style Start fill:#e1f5e1
    style End1 fill:#ffe1e1
    style End2 fill:#ffe1e1
    style End3 fill:#ffe1e1
    style End4 fill:#ffe1e1
    style End5 fill:#ffe1e1
    style End6 fill:#ffe1e1
```

---

## 侵蚀1练级任务逻辑

```mermaid
flowchart TD
    CL1Start([OpsiHazard1Leveling开始]) --> CL1CheckSmart{智能调度<br/>是否启用?}

    CL1CheckSmart -->|否| CL1Traditional[传统模式:<br/>黄币不足时延迟任务]
    CL1CheckSmart -->|是| CL1GetYellow[获取当前黄币数量]

    CL1GetYellow --> CL1GetPreserve[获取黄币保留值<br/>优先使用智能调度配置]
    CL1GetPreserve --> CL1CheckYellow{黄币 < 保留值?}

    CL1CheckYellow -->|否| CL1Continue[继续执行侵蚀1]
    CL1CheckYellow -->|是| CL1GetAP[获取当前行动力]

    CL1GetAP --> CL1GetMeowAP[获取短猫行动力保留值<br/>优先使用智能调度配置]
    CL1GetMeowAP --> CL1CheckAP{行动力 < 短猫保留值?}

    CL1CheckAP -->|是| CL1NotifyBoth[推送通知:<br/>黄币与行动力双重不足]
    CL1CheckAP -->|否| CL1GetEnabledTasks[获取智能调度中<br/>启用的黄币补充任务]

    CL1NotifyBoth --> CL1Delay1[延迟侵蚀1任务1小时]
    CL1Delay1 --> CL1End1([任务停止])

    CL1GetEnabledTasks --> CL1AutoEnable[自动启用未启用的任务]
    CL1AutoEnable --> CL1NotifySwitch[推送通知:<br/>切换至黄币补充任务]
    CL1NotifySwitch --> CL1CallCoin[调用所有可用的<br/>黄币补充任务]
    CL1CallCoin --> CL1CheckCD{有冷却任务?}

    CL1CheckCD -->|是| CL1DelayToCD[延迟侵蚀1到冷却任务之后]
    CL1CheckCD -->|否| CL1End2([任务停止])

    CL1DelayToCD --> CL1End3([任务停止])

    %% 继续执行侵蚀1的流程
    CL1Continue --> CL1SetAP[设置行动力<br/>预设为120点]
    CL1SetAP --> CL1NotifyAPThreshold[检查并推送<br/>行动力阈值通知]
    CL1NotifyAPThreshold --> CL1CheckMinAP{行动力 < 最低保留?}

    CL1CheckMinAP -->|是| CL1NotifyAPLow[推送通知:<br/>行动力低于最低保留]
    CL1CheckMinAP -->|否| CL1Execute[执行战略搜索]

    CL1NotifyAPLow --> CL1Delay2[延迟侵蚀1任务1小时]
    CL1Delay2 --> CL1End4([任务停止])

    CL1Execute --> CL1Rescan1[第一次重扫:<br/>战略搜索后完整镜头重扫]
    CL1Rescan1 --> CL1CheckFixedPatrol{启用舰队<br/>强制移动?}

    CL1CheckFixedPatrol -->|是且无事件| CL1FixedPatrol[执行定点巡逻扫描]
    CL1CheckFixedPatrol -->|否| CL1HandleAfter[处理战后事件]

    CL1FixedPatrol --> CL1Rescan2[第二次重扫:<br/>舰队移动后再次重扫]
    CL1Rescan2 --> CL1HandleAfter

    CL1HandleAfter --> CL1SubmitData[提交CL1数据到遥测]
    CL1SubmitData --> CL1CheckSwitch[检查任务切换]
    CL1CheckSwitch --> CL1Loop([循环继续])

    CL1Traditional --> CL1TraditionalDelay[延迟到服务器刷新]
    CL1TraditionalDelay --> CL1End5([任务停止])

    style CL1Start fill:#e1f5e1
    style CL1End1 fill:#ffe1e1
    style CL1End2 fill:#ffe1e1
    style CL1End3 fill:#ffe1e1
    style CL1End4 fill:#ffe1e1
    style CL1End5 fill:#ffe1e1
    style CL1Loop fill:#e1e1ff
```

---

## 黄币补充任务逻辑(以短猫相接为例)

```mermaid
flowchart TD
    MeowStart([OpsiMeowfficerFarming开始]) --> MeowCheckCL1{启用了CL1?}

    MeowCheckCL1 -->|否| MeowExecute[执行短猫任务]
    MeowCheckCL1 -->|是| MeowGetThreshold[获取黄币返回阈值]

    MeowGetThreshold --> MeowCheckThresholdNull{阈值为null?}

    MeowCheckThresholdNull -->|是| MeowExecute
    MeowCheckThresholdNull -->|否| MeowCheckYellowStart{任务开始前:<br/>黄币 >= 返回阈值?}

    MeowCheckYellowStart -->|是| MeowReturnCL1Start[禁用所有黄币补充任务<br/>返回CL1]
    MeowCheckYellowStart -->|否| MeowExecute

    MeowReturnCL1Start --> MeowNotifyReturn1[推送通知:<br/>黄币充足切换回侵蚀1]
    MeowNotifyReturn1 --> MeowCallCL1_1[调用OpsiHazard1Leveling]
    MeowCallCL1_1 --> MeowEnd1([任务停止])

    %% 执行短猫任务
    MeowExecute --> MeowSetAP[设置行动力保留值<br/>优先使用智能调度配置]
    MeowSetAP --> MeowCheckAPFirst[首次检查行动力]
    MeowCheckAPFirst --> MeowNotifyAPThreshold[检查并推送<br/>行动力阈值通知]

    MeowNotifyAPThreshold --> MeowCheckSmart{智能调度<br/>是否启用?}

    MeowCheckSmart -->|否| MeowRun[执行短猫搜索]
    MeowCheckSmart -->|是| MeowGetAPPreserve[获取行动力保留值<br/>优先使用智能调度配置]

    MeowGetAPPreserve --> MeowCheckAPLow{行动力 < 保留值?}

    MeowCheckAPLow -->|否| MeowRun
    MeowCheckAPLow -->|是| MeowNotifyAPLow[推送通知:<br/>短猫行动力不足]

    MeowNotifyAPLow --> MeowDelay[延迟短猫1小时]
    MeowDelay --> MeowCheckCL1Enabled{启用了CL1?}

    MeowCheckCL1Enabled -->|是| MeowCallCL1_2[切换回OpsiHazard1Leveling]
    MeowCheckCL1Enabled -->|否| MeowEnd2([任务停止])

    MeowCallCL1_2 --> MeowEnd3([任务停止])

    %% 执行短猫搜索
    MeowRun --> MeowSearch[执行战略搜索]
    MeowSearch --> MeowRescan[重扫地图]
    MeowRescan --> MeowHandleAfter[处理战后事件]
    MeowHandleAfter --> MeowCheckSwitch[检查任务切换]

    MeowCheckSwitch --> MeowCheckYellowLoop{循环中:<br/>黄币 >= 返回阈值?}

    MeowCheckYellowLoop -->|是| MeowReturnCL1Loop[禁用所有黄币补充任务<br/>返回CL1]
    MeowCheckYellowLoop -->|否| MeowLoop([循环继续])

    MeowReturnCL1Loop --> MeowNotifyReturn2[推送通知:<br/>黄币充足切换回侵蚀1]
    MeowNotifyReturn2 --> MeowCallCL1_3[调用OpsiHazard1Leveling]
    MeowCallCL1_3 --> MeowEnd4([任务停止])

    style MeowStart fill:#e1f5e1
    style MeowEnd1 fill:#ffe1e1
    style MeowEnd2 fill:#ffe1e1
    style MeowEnd3 fill:#ffe1e1
    style MeowEnd4 fill:#ffe1e1
    style MeowLoop fill:#e1e1ff
```

---

## 其他黄币补充任务逻辑(隐秘海域/深渊海域)

```mermaid
flowchart TD
    ObscureStart([OpsiObscure/OpsiAbyssal开始]) --> ObscureCheckCL1{启用了CL1?}

    ObscureCheckCL1 -->|否| ObscureExecute[执行任务]
    ObscureCheckCL1 -->|是| ObscureGetThreshold[获取黄币返回阈值]

    ObscureGetThreshold --> ObscureCheckThresholdNull{阈值为null?}

    ObscureCheckThresholdNull -->|是| ObscureExecute
    ObscureCheckThresholdNull -->|否| ObscureCheckApplicable{当前任务在<br/>适用范围内?}

    ObscureCheckApplicable -->|否| ObscureExecute
    ObscureCheckApplicable -->|是| ObscureCheckYellowStart{任务开始前:<br/>黄币 >= 返回阈值?}

    ObscureCheckYellowStart -->|是| ObscureReturnCL1Start[禁用所有黄币补充任务<br/>返回CL1]
    ObscureCheckYellowStart -->|否| ObscureExecute

    ObscureReturnCL1Start --> ObscureNotifyReturn1[推送通知:<br/>黄币充足切换回侵蚀1]
    ObscureNotifyReturn1 --> ObscureCallCL1_1[调用OpsiHazard1Leveling]
    ObscureCallCL1_1 --> ObscureEnd1([任务停止])

    %% 执行任务
    ObscureExecute --> ObscureGetNext[获取下一个目标<br/>隐秘坐标/深渊记录器]
    ObscureGetNext --> ObscureCheckContent{有可执行内容?}

    ObscureCheckContent -->|否| ObscureNoContent[没有可执行内容]
    ObscureCheckContent -->|是| ObscureRun[执行自动搜索]

    ObscureNoContent --> ObscureCheckSmartNoContent{智能调度<br/>是否启用?}

    ObscureCheckSmartNoContent -->|否| ObscureTraditionalDelay[延迟到服务器刷新<br/>或2.5小时后]
    ObscureCheckSmartNoContent -->|是| ObscureCheckYellowNoContent{黄币 < CL1保留值?}

    ObscureTraditionalDelay --> ObscureEnd2([任务停止])

    ObscureCheckYellowNoContent -->|是| ObscureTryOther[尝试其他黄币补充任务]
    ObscureCheckYellowNoContent -->|否| ObscureDisableTask[禁用当前任务<br/>延迟到30天后]

    ObscureTryOther --> ObscureCheckOtherAvail{有其他可用任务?}

    ObscureCheckOtherAvail -->|是| ObscureCallOther[调用下一个黄币补充任务]
    ObscureCheckOtherAvail -->|否| ObscureCallCL1_2[返回OpsiHazard1Leveling]

    ObscureCallOther --> ObscureEnd3([任务停止])
    ObscureCallCL1_2 --> ObscureEnd4([任务停止])
    ObscureDisableTask --> ObscureEnd5([任务停止])

    %% 执行自动搜索
    ObscureRun --> ObscureSearch[执行自动搜索]
    ObscureSearch --> ObscureHandleAfter[处理战后事件]
    ObscureHandleAfter --> ObscureCheckSwitch[检查任务切换]

    ObscureCheckSwitch --> ObscureCheckYellowLoop{循环中:<br/>黄币 >= 返回阈值?}

    ObscureCheckYellowLoop -->|是| ObscureReturnCL1Loop[禁用所有黄币补充任务<br/>返回CL1]
    ObscureCheckYellowLoop -->|否| ObscureCheckForceRun{ForceRun<br/>是否启用?}

    ObscureReturnCL1Loop --> ObscureNotifyReturn2[推送通知:<br/>黄币充足切换回侵蚀1]
    ObscureNotifyReturn2 --> ObscureCallCL1_3[调用OpsiHazard1Leveling]
    ObscureCallCL1_3 --> ObscureEnd6([任务停止])

    ObscureCheckForceRun -->|是| ObscureLoop([循环继续])
    ObscureCheckForceRun -->|否| ObscureFinish[根据智能调度状态<br/>完成任务]

    ObscureFinish --> ObscureCheckSmartFinish{智能调度<br/>是否启用?}

    ObscureCheckSmartFinish -->|是| ObscureDisableFinish[禁用任务调度]
    ObscureCheckSmartFinish -->|否| ObscureDelayFinish[延迟到服务器刷新<br/>或2.5小时后]

    ObscureDisableFinish --> ObscureEnd7([任务停止])
    ObscureDelayFinish --> ObscureEnd8([任务停止])

    style ObscureStart fill:#e1f5e1
    style ObscureEnd1 fill:#ffe1e1
    style ObscureEnd2 fill:#ffe1e1
    style ObscureEnd3 fill:#ffe1e1
    style ObscureEnd4 fill:#ffe1e1
    style ObscureEnd5 fill:#ffe1e1
    style ObscureEnd6 fill:#ffe1e1
    style ObscureEnd7 fill:#ffe1e1
    style ObscureEnd8 fill:#ffe1e1
    style ObscureLoop fill:#e1e1ff
```

---

## 行动力阈值通知逻辑

```mermaid
flowchart TD
    APStart([行动力设置完成]) --> APCheckSmart{智能调度<br/>是否启用?}

    APCheckSmart -->|否| APEnd1([跳过通知])
    APCheckSmart -->|是| APGetCurrent[获取当前行动力总量]

    APGetCurrent --> APGetLevels[解析配置的阈值列表<br/>如: 500,1000,2000,3000]
    APGetLevels --> APFindThreshold[从高到低遍历阈值<br/>找到第一个 <= 当前行动力的阈值]

    APFindThreshold --> APCheckFirst{是否首次调用?}

    APCheckFirst -->|是| APSaveThreshold[保存当前阈值<br/>不发送通知]
    APCheckFirst -->|否| APCheckChanged{阈值区间<br/>是否变化?}

    APSaveThreshold --> APEnd2([完成])

    APCheckChanged -->|否| APEnd3([无变化,不通知])
    APCheckChanged -->|是| APCheckDirection{当前阈值<br/>是否为null?}

    APCheckDirection -->|是| APBelowLowest[降到最低阈值以下]
    APCheckDirection -->|否| APCompare{当前阈值 ><br/>上次阈值?}

    APBelowLowest --> APNotifyBelow[推送通知:<br/>行动力降至X以下]
    APNotifyBelow --> APUpdateLast[更新上次通知的阈值]
    APUpdateLast --> APEnd4([完成])

    APCompare -->|大于| APRise[行动力增加]
    APCompare -->|小于| APFall[行动力减少]

    APRise --> APNotifyRise[推送通知:<br/>行动力升至X+]
    APFall --> APNotifyFall[推送通知:<br/>行动力降至X+]

    APNotifyRise --> APUpdateLast2[更新上次通知的阈值]
    APNotifyFall --> APUpdateLast2
    APUpdateLast2 --> APEnd5([完成])

    style APStart fill:#e1f5e1
    style APEnd1 fill:#ffe1e1
    style APEnd2 fill:#ffe1e1
    style APEnd3 fill:#ffe1e1
    style APEnd4 fill:#ffe1e1
    style APEnd5 fill:#ffe1e1
```

---

## 黄币返回阈值计算逻辑

```mermaid
flowchart TD
    ThresholdStart([计算黄币返回阈值]) --> ThresholdCheckCL1{CL1是否启用?}

    ThresholdCheckCL1 -->|否| ThresholdReturn1([返回: null, null])
    ThresholdCheckCL1 -->|是| ThresholdCheckSmart{智能调度<br/>是否启用?}

    ThresholdCheckSmart -->|否| ThresholdGetOriginal[获取CL1原配置保留值]
    ThresholdCheckSmart -->|是| ThresholdCheckApplicable{当前任务在<br/>适用范围内?}

    ThresholdGetOriginal --> ThresholdReturn2([返回: null, CL1保留值<br/>禁用黄币检查])

    ThresholdCheckApplicable -->|否| ThresholdGetSmart1[获取智能调度CL1保留值]
    ThresholdCheckApplicable -->|是| ThresholdGetSmart2[获取智能调度CL1保留值]

    ThresholdGetSmart1 --> ThresholdReturn3([返回: null, CL1保留值<br/>禁用黄币检查])

    ThresholdGetSmart2 --> ThresholdGetConfig[读取OperationCoinsReturnThreshold配置]
    ThresholdGetConfig --> ThresholdCheckZero{配置值 == 0?}

    ThresholdCheckZero -->|是| ThresholdReturn4([返回: null, CL1保留值<br/>禁用黄币检查])
    ThresholdCheckZero -->|否| ThresholdCheckNull{配置值 == null?}

    ThresholdCheckNull -->|是| ThresholdUseDefault[使用默认值<br/>等于CL1保留值]
    ThresholdCheckNull -->|否| ThresholdUseConfig[使用配置值]

    ThresholdUseDefault --> ThresholdCalculate[计算最终阈值:<br/>CL1保留值 + 返回阈值]
    ThresholdUseConfig --> ThresholdCalculate

    ThresholdCalculate --> ThresholdReturn5([返回: 返回阈值, CL1保留值])

    style ThresholdStart fill:#e1f5e1
    style ThresholdReturn1 fill:#ffe1e1
    style ThresholdReturn2 fill:#ffe1e1
    style ThresholdReturn3 fill:#ffe1e1
    style ThresholdReturn4 fill:#ffe1e1
    style ThresholdReturn5 fill:#e1ffe1
```

---

## 任务优先级与执行顺序

### 黄币补充任务固定顺序

当需要尝试其他黄币补充任务时，按以下固定顺序:

1. **OpsiObscure** (隐秘海域)
2. **OpsiAbyssal** (深渊海域)
3. **OpsiStronghold** (塞壬要塞)
4. **OpsiMeowfficerFarming** (短猫相接)

### 任务切换规则

```mermaid
flowchart LR
    CL1[侵蚀1练级] -->|黄币不足| Coins[黄币补充任务]
    Coins -->|黄币充足| CL1
    Coins -->|无内容| NextCoin[下一个黄币补充任务]
    NextCoin -->|所有任务无内容| CL1
```

---

## 关键特性说明

### 1. 智能调度启用判定

智能调度功能由 `OpsiScheduling.Scheduler.Enable` 控制，通过 [is_smart_scheduling_enabled(config)](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/smart_scheduling_utils.py#4-22) 函数统一判断。

### 2. 配置优先级

- **黄币保留值**: 智能调度配置 > CL1原配置
- **行动力保留值**: 智能调度配置 > 各任务原配置

### 3. 推送通知条件

所有推送通知需要同时满足:

1. 智能调度已启用
2. `OpsiGeneral.NotifyOpsiMail` 已启用
3. `Error.OnePushConfig` 已正确配置(provider不为null)

### 4. 任务完成策略

- **智能调度启用**: 禁用任务调度器，由智能调度统一管理
- **智能调度关闭**: 延迟到服务器刷新或指定时间后再运行

### 5. 黄币返回阈值适用范围

通过4个独立开关控制哪些黄币补充任务应用返回阈值:

- `EnableMeowfficerFarming`: 短猫相接(默认启用)
- `EnableObscure`: 隐秘海域(默认关闭)
- `EnableAbyssal`: 深渊海域(默认关闭)
- `EnableStronghold`: 塞壬要塞(默认关闭)

### 6. 行动力阈值通知机制

- 维护上次通知的阈值状态
- 仅在跨越阈值区间时发送通知
- 支持升至/降至两种方向的通知

---

## 核心类与方法

### OpsiScheduling 类

| 方法                                                                                                                                          | 说明                     |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| [run_smart_scheduling()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#533-612)           | 智能调度主入口           |
| [\_switch_to_coin_task()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#667-727)          | 切换到黄币补充任务       |
| [\_execute_hazard1_leveling()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#757-772)     | 执行侵蚀1练级            |
| [\_notify_coins_ap_insufficient()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#613-639) | 黄币与行动力双重不足通知 |
| [\_notify_ap_insufficient()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#640-666)       | 行动力不足通知           |
| [\_notify_switch_to_coin_task()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#728-756)   | 切换到黄币补充任务通知   |

### CoinTaskMixin 类

| 方法                                                                                                                                                           | 说明                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| [\_get_operation_coins_return_threshold()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#159-211)          | 计算黄币返回阈值              |
| [\_get_smart_scheduling_operation_coins_preserve()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#212-234) | 获取智能调度黄币保留值        |
| [\_get_smart_scheduling_action_point_preserve()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#235-251)    | 获取智能调度行动力保留值      |
| [\_check_yellow_coins_and_return_to_cl1()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#300-348)          | 检查黄币并返回CL1             |
| [\_disable_all_coin_tasks_and_return_to_cl1()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#351-360)      | 禁用所有黄币补充任务并返回CL1 |
| [\_try_other_coin_tasks()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#361-404)                          | 尝试其他黄币补充任务          |
| [\_finish_task_with_smart_scheduling()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#405-446)             | 根据智能调度状态完成任务      |
| [\_handle_no_content_and_try_other_tasks()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#447-518)         | 处理无内容情况并尝试其他任务  |
| [notify_push()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#80-127)                                      | 发送推送通知                  |

### OpsiHazard1Leveling 类

| 方法                                                                                                                                                       | 说明                     |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| [os_hazard1_leveling()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/hazard_leveling.py#141-423)                    | 侵蚀1练级主循环          |
| [check_and_notify_action_point_threshold()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/hazard_leveling.py#69-140) | 检查并推送行动力阈值通知 |
| [notify_push()](file:///c:/Users/Azur/Desktop/%E9%A1%B9%E7%9B%AE/AzurLaneAutoScript/module/os/tasks/scheduling.py#80-127)                                  | 发送推送通知             |

---

## 数据流向

```mermaid
flowchart LR
    Config[配置文件] --> Scheduler[OpsiScheduling]
    Scheduler --> CL1[OpsiHazard1Leveling]
    Scheduler --> Meow[OpsiMeowfficerFarming]
    Scheduler --> Obscure[OpsiObscure]
    Scheduler --> Abyssal[OpsiAbyssal]
    Scheduler --> Stronghold[OpsiStronghold]

    CL1 --> Scheduler
    Meow --> Scheduler
    Obscure --> Scheduler
    Abyssal --> Scheduler
    Stronghold --> Scheduler

    Scheduler --> Notify[推送通知系统]
    CL1 --> Notify
    Meow --> Notify
    Obscure --> Notify
    Abyssal --> Notify
```

---

## 总结

智能调度系统通过以下机制实现任务的智能协调:

1. **资源监控**: 实时监控黄币和行动力状态
2. **任务切换**: 根据资源状态在CL1和黄币补充任务间切换
3. **优先级管理**: 按固定顺序尝试黄币补充任务
4. **推送通知**: 关键状态变化时及时通知用户
5. **配置覆盖**: 智能调度配置优先于原任务配置
6. **灵活控制**: 支持启用/禁用特定黄币补充任务
