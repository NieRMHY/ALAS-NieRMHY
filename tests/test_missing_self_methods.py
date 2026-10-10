"""类内 self._xxx() 调用必须有定义（纯静态，不需要设备）。

Add by MHY, 2026-10-10：上游合并曾把 PQInteract._pq_target_appear 的定义弄丢，
调用点还在，宿舍计划 10-09 起每天 AttributeError、连续恢复 3 次后被延后。
只检查本分支重点维护的两个目录，避免误报整个框架的动态属性。
"""
import ast
import glob
import unittest

PACKAGES = ['module/private_quarters', 'module/island', 'module/island_season_plan']


def _collect(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    defined, called = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            defined.add(target.id)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self'
              and node.func.attr.startswith('_pq_')):
            called.setdefault(node.func.attr, node.lineno)
    return defined, called


class TestPrivateQuartersHelpersDefined(unittest.TestCase):
    def test_every_pq_helper_call_has_definition(self):
        defined, called = set(), {}
        for package in PACKAGES:
            for path in glob.glob(f'{package}/*.py'):
                d, c = _collect(path)
                defined |= d
                for name, line in c.items():
                    called.setdefault(name, f'{path}:{line}')
        missing = {name: where for name, where in called.items() if name not in defined}
        self.assertEqual(missing, {})


if __name__ == '__main__':
    unittest.main()
