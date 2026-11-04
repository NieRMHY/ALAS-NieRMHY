"""Run all Python tests and frontend unit/build checks in an isolated writable environment."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-only', action='store_true')
    parser.add_argument('--last-failed', action='store_true')
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    run = root / 'log' / ('full-tests-' + uuid.uuid4().hex[:10])
    temporary = run / 'tmp'
    config = run / 'config'
    temporary.mkdir(parents=True)
    config.mkdir()
    env = {**os.environ, 'AZURPILOT_NTP_DISABLE': '1', 'PYTHONUTF8': '1',
           'PYTHONIOENCODING': 'utf-8', 'TEMP': str(temporary), 'TMP': str(temporary),
           'TMPDIR': str(temporary), 'SQLITE_TMPDIR': str(temporary),
           'AZURPILOT_CONFIG_DIR': str(config)}
    command = [sys.executable, '-m', 'pytest', 'tests', '-q', '--tb=short',
               '--basetemp=' + str(run / 'pytest'), '--junitxml=' + str(run / 'python.xml'),
               '--durations=15']
    if options.last_failed:
        command.append('--lf')
    checks = [('python', command, root)]
    if not options.python_only:
        npm = shutil.which('npm')
        if npm is None:
            raise RuntimeError('npm is required for frontend verification')
        checks.extend([('frontend-unit', [npm, 'test'], root / 'frontend'),
                       ('frontend-build', [npm, 'run', 'build'], root / 'frontend')])
    results = {}
    for name, command, directory in checks:
        with (run / (name + '.log')).open('w', encoding='utf-8') as output:
            result = subprocess.run(command, cwd=directory, env=env, stdout=output, stderr=output)
        results[name] = result.returncode
        print(f'{name}: {"PASS" if result.returncode == 0 else "FAIL"}; log: {run / (name + ".log")}', flush=True)
    (run / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return 1 if any(results.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
