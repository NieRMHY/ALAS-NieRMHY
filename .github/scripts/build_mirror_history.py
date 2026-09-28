"""从固定基线生成普通镜像仓库，不修改源分支。

保留基线及其到分支顶端之间的后代提交与合并关系，截断范围外的父链接。
文件树、作者、时间和提交正文保持原样。
重写后签名失效，因此移除提交签名及合并标签签名。镜像 SHA 与源仓库不同，
基线固定后同一源提交的镜像 SHA 稳定，后续同步可以快进。
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


MIRROR_BASELINE = json.loads(
    Path(__file__).with_name('mirror_history.json').read_text(encoding='utf-8')
)['baseline']


def git(*args, cwd=None, data=None):
    return subprocess.run(
        ['git', *args], cwd=cwd, input=data, stdout=subprocess.PIPE, check=True,
    ).stdout


def rewrite_commit(raw, mapping):
    """保留原始字节，只重写父链接并去除失效的签名头。"""
    headers, message = raw.split(b'\n\n', 1)
    result = []
    skip = False
    for line in headers.split(b'\n'):
        if line.startswith(b' '):
            if not skip:
                result.append(line)
            continue
        key = line.split(b' ', 1)[0]
        skip = key in (b'gpgsig', b'gpgsig-sha256', b'mergetag')
        if key == b'parent':
            parent = mapping.get(line.split(b' ', 1)[1].decode('ascii'))
            if parent:
                result.append(b'parent ' + parent.encode('ascii'))
        elif not skip:
            result.append(line)
    return b'\n'.join(result) + b'\n\n' + message


def retained_commits(baseline, fetch_branch=None):
    """浅克隆不足时按需加深，始终在同一个基线处截断。"""
    while True:
        reachable = set(git('rev-list', 'HEAD').decode().splitlines())
        before = git('rev-parse', '--git-path', 'shallow').decode().strip()
        boundaries = Path(before).read_bytes() if Path(before).exists() else b''
        shallow_tips = set(boundaries.decode().splitlines()) & reachable
        # 必须证明所有浅边界都已越过基线，避免侧支尚未读到基线时漏掉其后代。
        def ancestor(commit):
            result = subprocess.run(
                ['git', 'merge-base', '--is-ancestor', commit, baseline],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode not in (0, 1):
                raise RuntimeError('无法验证浅边界与固定基线的祖先关系')
            return result.returncode == 0

        if baseline in reachable and all(ancestor(commit) for commit in shallow_tips):
            descendants = git(
                'rev-list', '--ancestry-path', '--topo-order', '--reverse', f'{baseline}..HEAD',
            ).decode().splitlines()
            return [baseline, *descendants]
        shallow = git('rev-parse', '--is-shallow-repository').strip() == b'true'
        if not shallow or not fetch_branch:
            raise ValueError(f'当前历史未完整覆盖固定基线 {baseline}，停止同步')
        git('fetch', '--no-tags', '--deepen=300', 'origin', fetch_branch)
        if Path(before).exists() and Path(before).read_bytes() == boundaries:
            raise RuntimeError('浅克隆未能继续加深，停止同步')


def build_mirror(output, baseline=MIRROR_BASELINE, fetch_branch=None):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('输出目录必须不存在，避免覆盖已有仓库')
    source_tip = git('rev-parse', 'HEAD').decode().strip()
    commits = retained_commits(baseline, fetch_branch)
    mapping = {}
    for commit in commits:
        raw = git('cat-file', 'commit', commit)
        mapping[commit] = git(
            'hash-object', '-t', 'commit', '-w', '--stdin',
            data=rewrite_commit(raw, mapping),
        ).decode().strip()
    tip = mapping[source_tip]
    git('init', '--bare', str(output))
    # 只导出重写后的可达对象，输出仓库不带浅边界或源仓库的其他引用。
    with tempfile.TemporaryFile() as pack:
        subprocess.run(
            ['git', 'pack-objects', '--revs', '--stdout'],
            input=(tip + '\n').encode('ascii'), stdout=pack, check=True,
        )
        pack.seek(0)
        subprocess.run(
            ['git', 'index-pack', '--stdin'], cwd=output,
            stdin=pack, stdout=subprocess.DEVNULL, check=True,
        )
    git('update-ref', 'refs/heads/mirror', tip, cwd=output)
    git('symbolic-ref', 'HEAD', 'refs/heads/mirror', cwd=output)
    git('fsck', '--strict', '--no-reflogs', cwd=output)
    count = int(git('rev-list', '--count', 'HEAD', cwd=output))
    if count != len(commits):
        raise RuntimeError('镜像可达提交数量与保留范围不一致')
    print(f'镜像保留 {count} 个提交，固定基线 {baseline}')
    return tip


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--fetch-branch', help='浅克隆不足时从 origin 加深该分支')
    args = parser.parse_args()
    build_mirror(args.output, fetch_branch=args.fetch_branch)
