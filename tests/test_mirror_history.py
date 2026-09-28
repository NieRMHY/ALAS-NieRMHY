"""固定基线镜像的隔离 Git 集成验证，不连接实际远端。"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/build_mirror_history.py'
spec = importlib.util.spec_from_file_location('build_mirror_history', SCRIPT)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


class TestMirrorHistory(unittest.TestCase):
    def test_shallow_merge_history_and_stable_incremental_push(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, shallow, destination = (root / name for name in ('source', 'shallow', 'remote.git'))

            def git(cwd, *args, data=None):
                return subprocess.run(
                    ['git', *args], cwd=cwd, input=data, check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                ).stdout

            git(root, 'init', str(source))
            # 用固定元数据创建历史，避免依赖本机身份和签名设置。
            stream = bytearray()
            for index in range(12):
                stream.extend(
                    f'commit refs/heads/master\nmark :{index + 1}\n'
                    f'committer 测试 <test@example.invalid> {1700000000 + index} +0800\n'
                    f'data {len(str(index))}\n{index}\n'.encode('utf-8')
                )
                if index:
                    stream.extend(f'from :{index}\n'.encode())
                else:
                    stream.extend(b'M 100644 inline file.txt\ndata 4\ntest\n')
                stream.extend(b'\n')
            git(source, 'fast-import', '--quiet', data=bytes(stream))
            baseline = git(source, 'rev-parse', 'master~4').decode().strip()
            # 额外的分支与合并让深度和可达提交数量不同。
            tree = git(source, 'rev-parse', 'master^{tree}').strip()
            side_parent = git(source, 'rev-parse', 'master~2').strip()
            side_raw = (
                b'tree ' + tree + b'\nparent ' + side_parent
                + b'\nauthor Test <test@example.invalid> 1700000600 +0800\n'
                b'committer Test <test@example.invalid> 1700000600 +0800\n\nside\n'
            )
            side = git(source, 'hash-object', '-t', 'commit', '-w', '--stdin', data=side_raw).strip()
            merge_raw = side_raw.replace(
                b'parent ' + side_parent,
                b'parent ' + git(source, 'rev-parse', 'master').strip() + b'\nparent ' + side,
            ).replace(b'\n\nside\n', b'\n\nmerge\n')
            tip = git(source, 'hash-object', '-t', 'commit', '-w', '--stdin', data=merge_raw).strip()
            git(source, 'update-ref', 'refs/heads/master', tip.decode())
            git(root, 'clone', '--bare', str(source), str(destination))
            git(root, 'clone', '--depth=2', '--branch=master', source.as_uri(), str(shallow))
            self.assertEqual(b'true', git(shallow, 'rev-parse', '--is-shallow-repository').strip())
            original_cwd = Path.cwd()
            try:
                os.chdir(shallow)
                with self.assertRaises(ValueError):
                    mirror.build_mirror(root / 'missing.git', baseline)
                first = mirror.build_mirror(root / 'first.git', baseline, 'master')
                repeated = mirror.build_mirror(root / 'repeated.git', baseline)
                self.assertEqual(first, repeated)
                self.assertEqual(tip, git(shallow, 'rev-parse', 'HEAD').strip())
                for name in ('first.git', 'repeated.git'):
                    output = root / name
                    self.assertEqual(b'7', git(output, 'rev-list', '--count', 'HEAD').strip())
                    self.assertEqual(2, len(git(output, 'show', '-s', '--format=%P', 'HEAD').split()))
                    self.assertEqual(b'false', git(output, 'rev-parse', '--is-shallow-repository').strip())
                    self.assertEqual(tree, git(output, 'rev-parse', 'HEAD^{tree}').strip())
                    git(output, 'fsck', '--strict')
                git(root / 'first.git', 'push', '--force', str(destination), 'HEAD:master')
                self.assertEqual(b'7', git(destination, 'rev-list', '--count', 'master').strip())
                next_raw = side_raw.replace(
                    b'parent ' + side_parent, b'parent ' + tip,
                )
                next_tip = git(shallow, 'hash-object', '-t', 'commit', '-w', '--stdin', data=next_raw).strip()
                git(shallow, 'update-ref', 'refs/heads/master', next_tip.decode())
                mirror.build_mirror(root / 'next.git', baseline)
                self.assertEqual(first, git(root / 'next.git', 'rev-parse', 'HEAD^').decode().strip())
                # 首次截断需要强推，此后无需强推即可快进。
                git(root / 'next.git', 'push', str(destination), 'HEAD:master')
                self.assertEqual(b'8', git(destination, 'rev-list', '--count', 'master').strip())
                git(destination, 'fsck', '--strict')
                with self.assertRaises(ValueError):
                    mirror.build_mirror(root / 'absent.git', '0' * 40)
            finally:
                os.chdir(original_cwd)

    def test_invalid_signatures_removed_and_message_preserved(self):
        raw = (
            b'tree abc\nparent old\nauthor A\ncommitter C\ngpgsig signature\n continuation\n'
            b'mergetag tag\n continuation\nencoding UTF-8\n\nmessage\n parent untouched\n'
        )
        self.assertEqual(
            b'tree abc\nparent new\nauthor A\ncommitter C\nencoding UTF-8\n\nmessage\n parent untouched\n',
            mirror.rewrite_commit(raw, {'old': 'new'}),
        )

if __name__ == '__main__':
    unittest.main()
