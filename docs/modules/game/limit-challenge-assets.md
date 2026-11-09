# 限界挑战识别素材

素材目录 `assets/cn/limit_challenge/` 仅放图像，避免按钮生成器把文档当作识别资源。

素材及识别回归来自用户提供的六张国服 1280×720 截图，原图保存在 `tests/fixtures/limit_challenge/`。普通 Button 通过 `dev_tools.button_region_editor.process_button_image()` 保留指定区域、将外部置黑；Template 通过 `process_template_image()` 裁剪。定义由 `uv run -m dev_tools.button_extract` 生成，不手写 `assets.py`。

| 素材 | 原图 | 保留范围 (x1, y1, x2, y2) |
| --- | --- | --- |
| `ui/CAMPAIGN_MENU_GOTO_LIMIT_CHALLENGE` | `menu.png` | `(525, 599, 626, 626)` |
| `ui/CAMPAIGN_MENU_GOTO_LIMIT_CHALLENGE.BUTTON` | `menu.png` | `(497, 588, 627, 636)` |
| `ui/LIMIT_CHALLENGE_CHECK` | `easy.png` | `(120, 14, 235, 43)` |
| `CHALLENGE_START` | `easy.png` | `(1037, 632, 1209, 678)` |
| `CHALLENGE_PREPARATION` | `preparation.png` | `(1057, 559, 1134, 592)` |
| `CHALLENGE_PREPARATION.BUTTON` | `preparation.png` | `(1048, 557, 1238, 609)` |
| `SURFACE_FLEET` | `preparation.png` | `(33, 615, 114, 641)` |
| `LEVEL_1` | `easy.png` | `(27, 420, 244, 480)` |
| `LEVEL_2` | `easy.png` | `(27, 520, 244, 580)` |
| `LEVEL_3` | `easy.png` | `(27, 620, 244, 680)` |
| `TEMPLATE_LEVEL_SELECTED` | `easy.png` | `(30, 438, 52, 461)` |
| `TEMPLATE_LEVEL_LOCKED` | `easy.png` | `(73, 542, 227, 571)` |

`LEVEL_*` 只定义行区域与点击范围，不把窥探文字搬成其他难度的识别模板。共用选中菱形已在 `easy.png`、`normal.png`、`hard.png` 三档真实选中图中核对，不需要新增重复模板。左侧识别缺失时按持久化通关数继续，在挑战页直接点击开始；仍不点击明确锁定的难度。编队名称是玩家可改字段，不用作页面识别。

补充回归图 `normal.png` 为审视选中页，`hard.png` 为洞察选中页，`rewards.png` 为通关后获得道具页。奖励图可由现有 `GET_ITEMS_1` 识别，且不能命中挑战页退出条件；回放覆盖关闭奖励后自动选中审视／洞察并进入编队的顺序。道具图不作为通关次数或胜利评价的判据。不同月份主题与完整实机三关流程仍需相应材料验证。
