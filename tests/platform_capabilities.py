"""Probe OS test capabilities without changing developer-mode or administrator settings."""

import os
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def supports_symlinks():
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'target'
        target.touch()
        try:
            (Path(directory) / 'link').symlink_to(target)
        except OSError as error:
            if os.name == 'nt' and error.winerror == 1314:
                return False
            raise
    return True
