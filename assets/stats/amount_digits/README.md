# 掉落数量数字模板

`popup.png` 用于原生 96px 物品格的数量区，包含普通和科研图纸粗体字形；`reward.png` 用于自律寻敌原生 64px 物品格。模板来自 1280×720 游戏截图的数量切片，只包含数字笔画。

每格为 24×24，列号依次对应数字 0～9，每行是一组可选变体；空白格忽略。字形按原始宽高比居中，白底黑字。读取与匹配实现见 `module/statistics/amount_digits.py`。

新增变体需核对原始截图中的完整数量和字形，不能将旧 OCR 输出直接当作标注。保留原生数量切片到 `tests/fixtures/statistics_amounts/`，在 `cases.json` 填写人工核验的数量，并运行 `tests.test_statistics_amount_digits`。运行时不自动学习或写入模板；匹配不确定时使用现有 OCR 后端。
