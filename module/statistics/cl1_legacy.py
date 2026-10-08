"""旧版 CL1 统计的解码与只读行动力历史来源，不创建或改写统计库。"""
import json
import sqlite3
from contextlib import closing

from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.KDF import PBKDF2


def derive_legacy_key(device_id):
    return PBKDF2(device_id.encode(), b'AlasCl1SecureStorage', dkLen=32, count=1000, hmac_hash_module=SHA256)


def decrypt_legacy_payload(blob, key):
    cipher = AES.new(key, AES.MODE_GCM, nonce=blob[:16])
    return json.loads(cipher.decrypt_and_verify(blob[32:], blob[16:32]).decode('utf-8'))


def read_ap_snapshots(path, instance, months):
    """只读取所属实例的完整月快照，兼容已迁移 JSON 和旧 AES-GCM 行。"""
    keys = None
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cl1_data'").fetchone():
            return
        columns = {row[1] for row in connection.execute('PRAGMA table_info(cl1_data)')}
        data_column = 'data_json' if 'data_json' in columns else 'NULL'
        blob_column = 'encrypted_blob' if 'encrypted_blob' in columns else 'NULL'
        placeholders = ','.join('?' for _ in months)
        rows = connection.execute(f'SELECT {data_column},{blob_column} FROM cl1_data WHERE instance=? AND month IN ({placeholders}) ORDER BY month',
                                  [instance, *months])
        for raw, blob in rows:
            try:
                data = json.loads(raw) if raw else None
            except (ValueError, TypeError):
                data = None
            if not isinstance(data, dict) and blob:
                if keys is None:
                    from module.base.device_id import get_device_id, get_old_device_id
                    ids = {get_device_id(), get_old_device_id()} - {None, ''}
                    keys = [derive_legacy_key(value) for value in ids]
                for key in keys:
                    try:
                        data = decrypt_legacy_payload(blob, key)
                    except (ValueError, TypeError, UnicodeError):
                        continue
                    if isinstance(data, dict):
                        break
            if not isinstance(data, dict):
                raise ValueError('旧统计密文无法解码' if blob else '旧统计 JSON 无法解析')
            if not isinstance(data.get('ap_snapshots', []), list):
                raise ValueError('旧统计行动力快照格式无效')
            yield from (row for row in data.get('ap_snapshots', []) if isinstance(row, dict))
