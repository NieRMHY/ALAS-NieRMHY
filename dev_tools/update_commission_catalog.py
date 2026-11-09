"""Reproduce the factual commission name catalog from a pinned source snapshot."""

import hashlib
import json
from pathlib import Path

import requests

COMMIT = 'b0c59f49dcca437ca956a33826330a06a4acb104'
SOURCE = f'https://raw.githubusercontent.com/Qian-YiChen/AzurPilotStatsWorker/{COMMIT}/worker/commission_names.json'
SHA256 = 'ce4552befd737d6c81ff59fdd133646b386e74ebc1cba55195248df83ebdcd0a'
TARGET = Path(__file__).resolve().parent.parent / 'assets/stats/commission_names.json'


def main():
    response = requests.get(SOURCE, timeout=30)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != SHA256:
        raise ValueError('Pinned commission catalog checksum mismatch')
    catalog = response.json()
    if catalog.get('schema_version') != 1 or len(catalog.get('entries', [])) != 107:
        raise ValueError('Unexpected commission catalog schema')
    catalog['sources']['client_import_sha256'] = SHA256
    catalog['sources']['client_import_url'] = SOURCE.replace('raw.githubusercontent.com/', 'github.com/').replace(
        f'/{COMMIT}/', f'/blob/{COMMIT}/')
    TARGET.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
