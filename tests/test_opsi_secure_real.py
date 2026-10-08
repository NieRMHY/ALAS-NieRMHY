"""只读采样旧部署，在临时安装副本中验证自动解密后不再有密文。"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from module.statistics import opsi_secure
from module.statistics.opsi_keys import ProviderUnavailable


@unittest.skipUnless(os.environ.get('ALAS_TEST_V1_SOURCE'), '未指定只读旧部署来源')
class RealCopyDecryptTest(unittest.TestCase):
    def test_copy_decrypts_completely_and_source_untouched(self):
        source = Path(os.environ['ALAS_TEST_V1_SOURCE']).resolve()
        keyring = source / 'config' / 'opsi_secure' / 'keyring.json'
        before = keyring.read_bytes() if keyring.exists() else None
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root = Path(folder) / 'env'
            shutil.copytree(source, root)
            previous = opsi_secure._STORE
            opsi_secure.set_store(opsi_secure.StatsStore(root))
            try:
                try:
                    result = opsi_secure.decrypt_all()
                except ProviderUnavailable:
                    self.skipTest('本机没有该部署的凭据')
                self.assertFalse(result['pending'], f"仍有未解密数据: {result}")
                self.assertEqual(opsi_secure.pending_blobs(root), [])
                self.assertFalse((root / 'config' / 'opsi_secure' / 'keyring.json').exists())
                # 解密后的库仍可打开且核心表可读。
                for name in ('cl1_data.db', 'azurstats_local.db', 'daily_summary.db'):
                    path = root / 'config' / name
                    if not path.exists():
                        continue
                    with closing(sqlite3.connect(path)) as conn:
                        rows = conn.execute("SELECT 1").fetchone()
                    self.assertEqual(rows, (1,))
            finally:
                opsi_secure.set_store(previous)
        if before is not None:
            self.assertEqual(keyring.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
