#!/usr/bin/env python3
"""Install and maintain separate, private, file-based office workspaces. No network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')
REPO = Path(__file__).resolve().parent
MARKER = '.office-workbench.json'
DOCS = ('quickstart.md', 'daily-use.md', 'files-and-history.md', 'maintenance.md',
        'privacy.md', 'integrations.md', 'commands.md', 'architecture.md')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plain_path(value):
    supplied = Path(value).absolute()
    if '..' in supplied.parts:
        raise ValueError('请使用不含 .. 的明确路径')
    for p in (supplied, *supplied.parents):
        if p.is_symlink() or p.is_junction():
            raise ValueError('不接受软链接或 junction：' + str(p))
    return supplied.resolve()


def separate(path, other):
    if path == other or path.is_relative_to(other) or other.is_relative_to(path):
        raise ValueError('目录必须彼此独立，不能相同或嵌套')


def outside_repo(path):
    separate(path, REPO)
    for p in (path, *path.parents):
        if (p/'.git').exists():
            raise ValueError('私人工作目录不能位于 Git 仓库内')


def new_destination(value, other=None):
    path = plain_path(value)
    outside_repo(path)
    if other is not None:
        separate(path, other)
    if path.exists():
        raise ValueError('目标必须不存在；不会合并、清空或覆盖现有目录')
    if not path.parent.is_dir():
        raise ValueError('请先建立目标的父目录，再初始化其下的新目录')
    for p in path.parents:
        if (p/MARKER).exists() or (p/'ACTIVE').exists() or (p/'ARCHIVE').exists():
            raise ValueError('目标不能嵌入已有工作台')
    return path


def payload():
    files = {}
    for name in ('caseboard.py', 'safety.py', 'retrieval.py'):
        files[name] = (REPO/'engine'/name).read_bytes()
    for name in ('CASE.md', 'SERIES.md', 'KNOWLEDGE.md'):
        files['templates/'+name] = (REPO/'templates'/name).read_bytes()
    for name in DOCS:
        files['docs/'+name] = (REPO/'docs'/name).read_bytes()
    version = (REPO/'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9A-Za-z.-]+',version):
        raise ValueError('VERSION 格式无效')
    hashes = {p:digest(data) for p,data in files.items()}
    release = version + '-' + digest(json.dumps(hashes,sort_keys=True).encode())[:16]
    return files, {'format':1, 'version':version, 'release':release, 'files':hashes}


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def install_payload(root, files, state):
    release = root/'.office-system/releases'/state['release']
    release.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        write_new(release/name, data)


def encode(state):
    return (json.dumps(state,ensure_ascii=False,indent=2)+'\n').encode('utf-8')


def check_workspace(value):
    root = plain_path(value)
    outside_repo(root)
    if not root.is_dir() or not (root/MARKER).is_file():
        raise ValueError('不是本项目初始化的私人目录；不会自动迁移其他工作台')
    for command in ('version', 'validate'):
        result = subprocess.run([sys.executable,'-I','-B',str(root/'office.py'),command],
                                capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            raise ValueError('工作目录检查未通过：\n'+result.stdout+result.stderr)
    return root


def init(args):
    destination = new_destination(args.workspace)
    files, state = payload()
    if args.dry_run:
        return {'dry_run':True, 'destination':str(destination), 'version':state['version'],
                'global_config_changes':False, 'login_required_by_script':False}
    # Build in a fresh sibling; a failed build is retained for inspection, never merged.
    staging = destination.with_name('.'+destination.name+'.init-'+uuid.uuid4().hex)
    staging.mkdir()
    install_payload(staging, files, state)
    for name in ('office.py','AGENTS.md','LOCAL.md','START-HERE.md','private.gitignore'):
        target = '.gitignore' if name == 'private.gitignore' else name
        write_new(staging/target,(REPO/'templates'/name).read_bytes())
    write_new(staging/MARKER,encode(state))
    for name in ('ACTIVE','ARCHIVE','INBOX','SERIES','KNOWLEDGE/CANDIDATES',
                 'KNOWLEDGE/APPROVED','INDEX','DERIVED'):
        (staging/name).mkdir(parents=True,exist_ok=True)
    check_workspace(staging)
    result = subprocess.run([sys.executable,'-I','-B',str(staging/'office.py'),'refresh'],
                            capture_output=True,text=True,encoding='utf-8')
    if result.returncode:
        raise ValueError('初始化刷新失败，保留临时目录：'+str(staging)+'\n'+result.stderr)
    if destination.exists():
        raise ValueError('目标被其他进程建立；保留临时目录：'+str(staging))
    staging.rename(destination)
    return {'workspace':str(destination),'version':state['version'],'next':'在 Codex 打开此私人目录，读取 START-HERE.md'}


def tree_hashes(root, skip_lock_files=False):
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise ValueError('快照根目录无效或为链接')
    result = {}
    def fail(exc):
        raise exc
    for folder, dirs, files in os.walk(root,followlinks=False,onerror=fail):
        for name in dirs + files:
            p = Path(folder)/name
            if p.is_symlink() or p.is_junction():
                raise ValueError('备份树含链接，先将材料独立复制入目录：'+str(p))
        for name in files:
            p = Path(folder)/name
            if skip_lock_files and p.parent == root/'.caseboard/locks':
                continue
            if p.stat().st_nlink > 1:
                raise ValueError('备份树含硬链接，先独立复制：'+str(p))
            result[p.relative_to(root).as_posix()] = digest(p.read_bytes())
    return result


def directory_names(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_dir())


def load_safety(root):
    state = json.loads((root/MARKER).read_text(encoding='utf-8'))
    runtime = root/'.office-system/releases'/state['release']
    sys.path.insert(0,str(runtime))
    import safety
    return safety


def backup(args):
    root = check_workspace(args.workspace)
    destination = new_destination(args.destination, root)
    safe = load_safety(root)
    safe.ensure_no_pending(root)
    if args.dry_run:
        return {'dry_run':True,'files':len(tree_hashes(root)),'destination':str(destination),
                'contains_private_data':True,'encrypted':False}
    with safe.file_lock(root,'workspace-writer'):
        safe.ensure_no_pending(root)
        before = tree_hashes(root,skip_lock_files=True)
        directories = directory_names(root)
        staging = destination.with_name('.'+destination.name+'.backup-'+uuid.uuid4().hex)
        staging.mkdir()
        (staging/'workspace').mkdir()
        for name in directories:
            (staging/'workspace'/name).mkdir(parents=True,exist_ok=True)
        for name in before:
            # Recheck each source path before reading; this is not an adversarial filesystem sandbox.
            source = plain_path(root/name)
            if not source.is_relative_to(root):
                raise ValueError('备份源越界')
            write_new(staging/'workspace'/name,source.read_bytes())
        if tree_hashes(root,skip_lock_files=True) != before or tree_hashes(staging/'workspace') != before or directory_names(root) != directories:
            raise ValueError('复制期间文件变化；保留临时备份，请停止其他写入后重试')
        write_new(staging/'backup-manifest.json',encode({'format':1,'files':before,'directories':directories}))
        if destination.exists():
            raise ValueError('备份目标已出现，拒绝覆盖')
        staging.rename(destination)
    return {'backup':str(destination),'verified_files':len(before),'encrypted':False}


def restore(args):
    source = plain_path(args.backup)
    outside_repo(source)
    destination = new_destination(args.workspace,source)
    manifest_path = plain_path(source/'backup-manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != 1:
        raise ValueError('未知备份格式')
    copied = plain_path(source/'workspace')
    before = tree_hashes(copied)
    directories = directory_names(copied)
    if before != manifest['files'] or directories != manifest['directories']:
        raise ValueError('备份完整性校验失败，不能恢复')
    if args.dry_run:
        return {'dry_run':True,'verified_files':len(before),'destination':str(destination)}
    staging = destination.with_name('.'+destination.name+'.restore-'+uuid.uuid4().hex)
    staging.mkdir()
    for name in directories:
        (staging/name).mkdir(parents=True,exist_ok=True)
    for name in before:
        write_new(staging/name,plain_path(copied/name).read_bytes())
    if tree_hashes(staging) != before or tree_hashes(copied) != before or directory_names(staging) != directories or directory_names(copied) != directories:
        raise ValueError('恢复期间文件变化，保留临时目录')
    check_workspace(staging)
    if destination.exists():
        raise ValueError('恢复目标已出现，拒绝覆盖')
    staging.rename(destination)
    return {'workspace':str(destination),'verified_files':len(before)}


def upgrade(args):
    root = check_workspace(args.workspace)
    if (root/'office.py').read_bytes() != (REPO/'templates/office.py').read_bytes():
        raise ValueError('启动器不同；本版不自动替换，请保留原目录并按手册处理兼容性')
    files, state = payload()
    old = json.loads((root/MARKER).read_text(encoding='utf-8'))
    safe = load_safety(root)
    safe.ensure_no_pending(root)
    if args.dry_run:
        return {'dry_run':True,'from':old['release'],'to':state['release'],
                'case_changes':False,'root_AGENTS_changes':False,'backup_required':'请先执行 backup'}
    with safe.file_lock(root,'workspace-writer'):
        safe.ensure_no_pending(root)
        if json.loads((root/MARKER).read_text(encoding='utf-8')) != old:
            raise ValueError('升级期间版本标记变化，请重读')
        if state['release'] == old['release']:
            return {'unchanged':True,'release':old['release']}
        target = root/'.office-system/releases'/state['release']
        if target.exists():
            if tree_hashes(target) != state['files']:
                raise ValueError('目标版本目录已存在但不一致；保留现场，不覆盖')
        else:
            install_payload(root,files,state)
        result = subprocess.run([sys.executable,'-I','-B',str(target/'caseboard.py'),'--root',str(root),'validate'],
                                capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            raise ValueError('候选引擎校验失败，原版本仍生效：'+result.stdout+result.stderr)
        # Runtime switch is atomic; retain the old marker and release for inspection.
        history = root/'.office-system/history'/(uuid.uuid4().hex+'.json')
        safe.bounded(root,history)
        write_new(history,encode(old))
        safe.raw_atomic_write(root/MARKER,encode(state))
    return {'upgraded':True,'from':old['release'],'to':state['release'],
            'next':'运行 office.py doctor；升级不修改 CASE、根目录 AGENTS.md 或 LOCAL.md'}


def main():
    if sys.version_info < (3,12):
        raise ValueError('需要 Python 3.12 或更高版本')
    parser = argparse.ArgumentParser(description='Office Workbench：独立私人目录的安装与维护；不访问网络')
    sub = parser.add_subparsers(dest='command',required=True)
    for name, function in (('init',init),('backup',backup),('restore',restore),('upgrade',upgrade)):
        p = sub.add_parser(name)
        p.add_argument('--workspace',required=True)
        p.add_argument('--dry-run',action='store_true')
        if name == 'backup': p.add_argument('--destination',required=True)
        if name == 'restore': p.add_argument('--backup',required=True)
        p.set_defaults(function=function)
    args = parser.parse_args()
    print(json.dumps(args.function(args),ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        raise SystemExit(2)
