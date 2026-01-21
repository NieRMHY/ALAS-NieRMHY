
import json

filename = 'module/config/i18n/zh-TW.json'

with open(filename, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
start = 4085
end = 4095

print(f"Showing lines {start+1} to {end}:")
for i in range(start, end):
    line = lines[i]
    print(f"{i+1}: {repr(line)}")
    # Print hex of line
    print(f"    Hex: {line.encode('utf-8').hex()}")

try:
    json.loads(content)
    print("JSON Valid")
except Exception as e:
    print(f"JSON Error: {e}")
