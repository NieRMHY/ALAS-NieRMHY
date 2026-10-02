"""离线验证同步工作流的全量检出和推送重试，不连接 GitCode。"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class TestGitCodeSync(unittest.TestCase):
    def test_checkout_and_push_retry(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/sync2.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['repo-sync']['steps']
        self.assertEqual(0, steps[0]['with']['fetch-depth'])
        push = next(step['run'] for step in steps if step.get('name') == 'sync')
        bash = str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Git/bin/bash.exe') if os.name == 'nt' else shutil.which('bash')
        if not bash or not Path(bash).exists():
            self.skipTest('环境未提供 Bash')
        stub = '''
set -e
git() {
    if [[ "$*" == *" push "* ]]; then
        printf '%s\\n' "$*" >> push.log
        local count
        count="$(wc -l < push.log)"
        if [ "$count" -le "$FAILURES" ]; then
            return 128
        fi
    fi
    return 0
}
sleep() { :; }
'''
        for failures, expected_status, expected_attempts in ((2, 0, 3), (5, 128, 5)):
            with self.subTest(failures=failures), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [bash, '-c', stub + push], cwd=directory, capture_output=True,
                    env={**os.environ, 'FAILURES': str(failures), 'GITCODE_USER': 'test',
                         'GITCODE_TOKEN': 'test-token', 'REPO_NAME': 'test', 'GITHUB_REF_NAME': 'dev'},
                )
                self.assertEqual(expected_status, result.returncode, result.stderr.decode(errors='replace'))
                attempts = (Path(directory) / 'push.log').read_text().splitlines()
                self.assertEqual(expected_attempts, len(attempts))
                for attempt in attempts:
                    self.assertIn('http.userAgent=Mozilla/5.0', attempt)
                    self.assertIn('HEAD:refs/heads/dev', attempt)


if __name__ == '__main__':
    unittest.main()
