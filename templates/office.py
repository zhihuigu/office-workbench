#!/usr/bin/env python3
"""Private workspace entry point; independent of the source checkout and cwd."""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')


def main():
    if sys.version_info < (3, 12):
        raise ValueError('需要 Python 3.12 或更高版本；请先运行 python --version')
    root = Path(__file__).absolute().parent
    for parent in (root, *root.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('工作目录及父路径不能是链接或 junction')
    marker = root / '.office-workbench.json'
    if marker.is_symlink():
        raise ValueError('工作目录标记不能是链接')
    state = json.loads(marker.read_text(encoding='utf-8'))
    release = state.get('release', '')
    if state.get('format') != 1 or not re.fullmatch(r'[0-9A-Za-z._-]+', release):
        raise ValueError('工作目录标记格式无效')
    runtime = root / '.office-system' / 'releases' / release
    for path in (root/'.office-system', runtime.parent, runtime):
        if path.is_symlink() or path.is_junction():
            raise ValueError('运行时路径不能是链接')
    manifest = state['files']
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('运行时清单无效')
    for relative, expected in manifest.items():
        parts = relative.split('/')
        if any(p in ('', '.', '..') or ':' in p or '\\' in p for p in parts):
            raise ValueError('运行时清单路径无效')
        target = runtime
        for part in parts:
            target = target / part
            if target.is_symlink() or target.is_junction():
                raise ValueError('运行时文件路径不能是链接')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ValueError('运行时文件已变化：' + relative + '；先保留现场并恢复备份，禁止覆盖绕过')
    args = sys.argv[1:]
    if any(a == '--root' or a.startswith('--root=') for a in args):
        raise ValueError('office.py 固定管理自身所在目录，不接受 --root；请运行目标目录的 office.py')
    if args == ['version']:
        print(json.dumps({'version':state['version'], 'release':release, 'workspace':str(root)}, ensure_ascii=False))
        return 0
    if args == ['guide']:
        print((runtime/'docs/quickstart.md').read_text(encoding='utf-8'))
        print('\n完整手册目录：' + str(runtime/'docs'))
        return 0
    sys.path.insert(0, str(runtime))
    import caseboard
    return caseboard.main(['--root', str(root), *args])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
