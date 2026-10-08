# 仓库统计识别资源

`catalog.json` 是统计目标清单。目标来自用户的红框标注，模板只取未经标注的 1280×720 国服截图。清单内 `reference` 只描述离线测试来源；运行时按完整方框定位网格，不使用这些物品坐标。

25 种目标中，22 种复用已有 `assets/stats/` 物品模板；`SecretDesignPlanT4.png`、`SecretDesignPlanT5.png`、`CognitiveChipsII.png` 从原始截图裁出。稀有度底色来自原始仓库截图，避免已有奖励模板的背景差异，以及 SSR/UR 纸张图形相似导致串品。

`amount_digits.png` 是仓库数量字体的 24×24 字形图集，每列对应 0–9，每行保留一种原始字形变体。数量保留原始分辨率，另核对末位位置、字高、基线和间距，残缺首位或连通图标不作为噪声删除。字形不确定时拒绝提交，不回退猜数或记零。

`partial_rows.png` 保留上下半行的真实截图，完整行的心智单元为 32791、心智单元II 为 1204。这两个已核对数量补充了原生数字边缘变体，匹配误差与次优差距门槛保持不变；截断行仍交给滚动后再读，不从残缺数字训练模板。

离线截图与期望值位于 `tests/fixtures/storage_statistics/`。在仓库根目录执行：

```powershell
uv run python -m unittest tests.test_storage_statistics
```

当前资源只经过国服截图验证，其他服务器在进入仓库前报错并保留旧快照。
