"""
诊断并修复 CL1 战斗统计问题的脚本
该脚本用于检查和修复 cl1_monthly.json 文件的数据结构
"""
import json
from pathlib import Path
from datetime import datetime

# 定位项目根目录
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent

# 定位 cl1_monthly.json
cl1_dir = project_root / 'log' / 'cl1'
json_file = cl1_dir / 'cl1_monthly.json'

print(f"检查文件: {json_file}")

# 确保目录存在
cl1_dir.mkdir(parents=True, exist_ok=True)

# 读取现有数据
if json_file.exists():
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"\n当前数据内容:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"读取文件失败: {e}")
        data = {}
else:
    print("文件不存在，将创建新文件")
    data = {}

# 获取当前月份
now = datetime.now()
current_month = f"{now.year:04d}-{now.month:02d}"
akashi_key = f"{current_month}-akashi"

print(f"\n当前月份: {current_month}")
print(f"战斗场次键名: {current_month}")
print(f"明石遇见键名: {akashi_key}")

# 检查数据结构
battles = data.get(current_month, 0)
akashi = data.get(akashi_key, 0)

print(f"\n当前统计:")
print(f"  战斗场次: {battles}")
print(f"  遇见明石: {akashi}")

print(f"\n数据键列表:")
for key in sorted(data.keys()):
    print(f"  {key}: {data[key]}")

# 保存备份
if data:
    backup_file = json_file.with_suffix('.json.backup')
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n已保存备份至: {backup_file}")

print("\n诊断完成！")
print("\n如果战斗场次为 0 但明石次数不为 0，说明战斗统计逻辑没有被触发。")
print("请检查:")
print("1. 确认您运行的任务是 'OpsiHazard1Leveling'")
print("2. 确认任务调度器中此任务已启用")
print("3. 查看日志中是否有 'cl1_battle_count' 字样")
