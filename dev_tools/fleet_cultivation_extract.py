"""Extract the small cultivation rule snapshot from a supplied CN ship_level.lua.

Usage: uv run python -m dev_tools.fleet_cultivation_extract /path/to/ship_level.lua
Source: https://github.com/AzurLaneTools/AzurLaneLuaScripts/blob/master/CN/sharecfg/ship_level.lua
No network or account data is used by the runtime calculator.
"""
import hashlib
import json
import re
import sys
from pathlib import Path


def extract(raw):
    levels, awaken = {}, {}
    for match in re.finditer(r'pg\.base\.ship_level\[(\d+)\] = \{(.*?)(?=\n\tpg\.base\.ship_level|\nend\)|\Z)', raw, re.S):
        level, body = int(match[1]), match[2]
        levels[str(level)] = {key: int(re.search(r'\b' + key + r' = (\d+)', body)[1]) for key in ('exp', 'exp_ur')}
        costs = {}
        for rarity, name in enumerate(('N', 'R', 'SR', 'SSR', 'UR'), 2):
            block = re.search(r'need_item_rarity' + str(rarity) + r' = (.*?)(?=\n\t\tneed_item_rarity|\Z)', body, re.S)[1]
            items = re.findall(r'\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}', block)
            if items:
                cost = {'gold': 0, 'mind': 0, 'mind2': 0}
                for kind, item, count in items:
                    key = {('1', '1'): 'gold', ('2', '15008'): 'mind', ('2', '15012'): 'mind2'}[(kind, item)]
                    cost[key] += int(count)
                costs[name] = cost
        if costs:
            awaken[str(level)] = costs
    assert set(levels) == {str(x) for x in range(1, 126)}
    assert set(awaken) == {'100', '105', '110', '115', '120'}
    return dict(source='https://github.com/AzurLaneTools/AzurLaneLuaScripts/blob/master/CN/sharecfg/ship_level.lua',
                source_sha256=hashlib.sha256(raw.encode()).hexdigest(), levels=levels, awaken=awaken)


if __name__ == '__main__':
    output = Path(__file__).parents[1] / 'assets/ship/cultivation.json'
    output.write_text(json.dumps(extract(Path(sys.argv[1]).read_text()), ensure_ascii=False, indent=2) + '\n')
