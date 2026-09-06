#!/usr/bin/env python3
"""Strict, no-history, allowlist-only candidate inspection and deterministic packing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile

sys.dont_write_bytecode = True
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]

# Heuristic checks are defense in depth; they do not replace a human content review.
PATTERNS = {
    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'service_secret': r'(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',
    'bearer_value': r'(?i)bearer\s+[A-Za-z0-9_.-]{20,}',
    'personal_mail': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    'home_path': r'(?i)(?:[A-Z]:[\\/]+Users[\\/]+[^\s"\'<>]+|/home/[a-z0-9_-]+/|/Users/[a-z0-9_-]+/)',
    'literal_case_identity': r'\b(?:CASE|SERIES)-\d{8}-[0-9A-Fa-f]{32}\b',
}


def check():
    allow = [line.strip() for line in (ROOT/'PUBLIC_FILES.txt').read_text(encoding='utf-8').splitlines()
             if line.strip() and not line.startswith('#')]
    if len(allow) != len(set(allow)):
        raise ValueError('白名单有重复文件')
    for path in allow:
        if path.startswith('/') or '\\' in path or ':' in path or any(p in ('','.','..') for p in path.split('/')):
            raise ValueError('白名单路径无效')
    actual = []
    allowed_dirs = {parent.as_posix() for name in allow for parent in Path(name).parents if parent != Path('.')}
    def fail(exc): raise exc
    for folder,dirs,files in os.walk(ROOT,followlinks=False,onerror=fail):
        for name in dirs + files:
            p = Path(folder)/name
            if p.is_symlink() or p.is_junction():
                raise ValueError('拒绝链接：'+p.relative_to(ROOT).as_posix())
        for name in dirs:
            if (Path(folder)/name).relative_to(ROOT).as_posix() not in allowed_dirs:
                raise ValueError('非白名单目录；请另建干净候选，不自动清理')
        if '.git' in dirs or '.git' in files:
            raise ValueError('候选必须没有 Git 元数据和历史；另建干净导出目录')
        for name in files:
            p=Path(folder)/name
            if p.stat().st_nlink > 1:
                raise ValueError('拒绝硬链接：'+p.relative_to(ROOT).as_posix())
            actual.append(p.relative_to(ROOT).as_posix())
    if set(actual) != set(allow):
        raise ValueError(json.dumps({'unexpected':sorted(set(actual)-set(allow)),
                                     'missing':sorted(set(allow)-set(actual))},ensure_ascii=False))
    hashes = {}
    for relative in sorted(allow):
        data=(ROOT/relative).read_bytes()
        if len(data)>250000 or b'\x00' in data:
            raise ValueError('非预期大文件或二进制：'+relative)
        text=data.decode('utf-8')
        for label,pattern in PATTERNS.items():
            if re.search(pattern,text):
                raise ValueError('内容检查命中 '+label+'：'+relative+'；不输出潜在秘密原文')
        hashes[relative]=hashlib.sha256(data).hexdigest()
    return hashes


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check')
    pack=sub.add_parser('pack')
    pack.add_argument('--output',required=True)
    args=parser.parse_args()
    hashes=check()
    result={'checked_files':len(hashes),'unexpected_files':0,'heuristic_findings':0,
            'git_history_included':False,'license_adopted':(ROOT/'LICENSE').is_file(),
            'human_review_required':True}
    if args.command == 'pack':
        raw=Path(args.output).absolute()
        for p in (raw,*raw.parents):
            if p.is_symlink() or p.is_junction(): raise ValueError('输出不能包含链接')
        output=raw.resolve()
        if output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
            raise ValueError('输出必须为源码目录外、父目录已存在、文件不存在的新路径')
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in sorted(hashes):
                data=(ROOT/relative).read_bytes()
                if hashlib.sha256(data).hexdigest()!=hashes[relative]:
                    raise ValueError('打包时源文件变化；保留候选供检查')
                info=zipfile.ZipInfo('office-workbench/'+relative,date_time=(2000,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                info.create_system=3
                info.external_attr=0o100644 << 16
                archive.writestr(info,data)
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None: raise ValueError('ZIP 校验失败')
            for relative,expected in hashes.items():
                if hashlib.sha256(archive.read('office-workbench/'+relative)).hexdigest()!=expected:
                    raise ValueError('ZIP 内容校验失败')
        result.update(output=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError,ValueError,UnicodeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
