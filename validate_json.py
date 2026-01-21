import json
import os

i18n_dir = 'module/config/i18n'
for filename in os.listdir(i18n_dir):
    if filename.endswith('.json'):
        filepath = os.path.join(i18n_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                json.load(f)
            print(f"{filename}: OK")
        except json.JSONDecodeError as e:
            print(f"{filename}: ERROR - {e}")
