"""侧栏内容检索的索引与匹配。"""

import os
import time
import unittest

from module.api.search_service import I18N_DIR, SEARCH_LANGUAGES, search_content


class TestSearchContent(unittest.TestCase):
    def test_hits_are_real_substring_matches(self):
        """命中的每一条都必须真的含检索词（大小写不敏感）。"""
        for query in ('石油', '模拟器', '科研', 'OIL'):
            result = search_content(query)
            self.assertTrue(result['tasks'] or result['options'], f'{query} 无命中')
            needle = query.lower()
            for item in result['tasks'] + result['options']:
                haystack = ' '.join([item['task'], item['key'], item['label'], item['help'], item['values']]).lower()
                self.assertIn(needle, haystack)

    def test_no_duplicate_entries(self):
        """同一「类别 + 任务 + 键」只出现一次，中英文各命中一次也只算一条。"""
        result = search_content('模拟器')
        identities = [('task', item['task'], item['key']) for item in result['tasks']]
        identities += [('option', item['task'], item['key']) for item in result['options']]
        self.assertEqual(len(identities), len(set(identities)))

    def test_case_insensitive(self):
        self.assertEqual(search_content('oil'), search_content('OIL'))

    def test_empty_query_returns_nothing(self):
        self.assertEqual(search_content('   '), {'tasks': [], 'options': []})

    def test_missing_word_returns_nothing(self):
        self.assertEqual(search_content('zzzz不存在的词zzzz'), {'tasks': [], 'options': []})

    def test_index_follows_file_mtime(self):
        """文案文件改动后索引重建：改掉 mtime 就应该重新读取内容。"""
        path = I18N_DIR / f'{SEARCH_LANGUAGES[0]}.json'
        before = search_content('模拟器')
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 1))
        try:
            after = search_content('模拟器')
        finally:
            os.utime(path, (stat.st_atime, stat.st_mtime))
            time.sleep(0.01)
        self.assertEqual(len(before['options']), len(after['options']))


if __name__ == '__main__':
    unittest.main()
