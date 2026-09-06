"""Single-host filesystem transactions; journals are recovery data, never CASE state."""
from __future__ import annotations

import base64
import contextvars
import functools
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class SafetyError(RuntimeError):
    pass


CURRENT = contextvars.ContextVar('caseboard_transaction', default=None)
HELD = threading.local()
LOCAL_LOCKS = {}
LOCAL_GUARD = threading.Lock()
LOCK_TIMEOUT = 10.0


def fault(point):
    """Patch only in synthetic tests. No production environment fault switches."""


def bounded(root, path):
    root, path = Path(root).resolve(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f'路径越界：{path}') from exc
    current = root
    for part in relative.parts:
        if part in ('..', '.'):
            raise SafetyError(f'路径越界：{path}')
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise SafetyError(f'控制路径不允许软链接或 junction：{current}')
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise SafetyError(f'路径越界：{path}')
    return resolved


def raw_atomic_write(path, data):
    """The temporary file is always on the destination volume."""
    path = Path(path)
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        fault('atomic_before_replace')
        os.replace(temp, path)
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def file_lock(root, name, timeout=None):
    """Stable OS lock inode; process exit releases it, old lock files are harmless."""
    timeout = LOCK_TIMEOUT if timeout is None else timeout
    root = Path(root).resolve()
    lockdir = bounded(root, root / '.caseboard' / 'locks')
    lockdir.mkdir(parents=True, exist_ok=True)
    path = bounded(root, lockdir / (hashlib.sha256(name.encode()).hexdigest() + '.lock'))
    key = str(path)
    held = getattr(HELD, 'keys', {})
    HELD.keys = held
    if key in held:
        yield
        return
    with LOCAL_GUARD:
        local = LOCAL_LOCKS.setdefault(key, threading.RLock())
    if not local.acquire(timeout=timeout):
        raise SafetyError(f'写锁超时：{name}')
    stream = None
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        stream = path.open('a+b')
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                held[key] = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise SafetyError(f'写锁超时：{name}；锁由运行中的进程持有，禁止删除锁文件')
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            held.pop(key, None)
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)
        if stream:
            stream.close()
        local.release()


def pending(root):
    folder = bounded(root, Path(root) / '.caseboard' / 'transactions')
    return sorted(folder.glob('*.json')) if folder.exists() else []


def ensure_no_pending(root):
    paths = pending(root)
    if paths:
        raise SafetyError('存在待恢复事务；请先 check，再显式 repair --recover（可先 --dry-run）：' + ', '.join(p.name for p in paths))


class Transaction:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / '.caseboard' / 'transactions' / (uuid.uuid4().hex + '.json')
        self.entries = []
        self.phase = 'pending'

    def save(self):
        bounded(self.root, self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw_atomic_write(self.path, json.dumps({'version':1, 'root':str(self.root), 'phase':self.phase, 'entries':self.entries}, ensure_ascii=False).encode('utf-8'))

    def add(self, entry):
        self.entries.append(entry)
        self.save()  # write-ahead undo information must be durable first

    def mkdir(self, path):
        path = bounded(self.root, path)
        if path.is_dir():
            return
        if path.exists():
            raise SafetyError(f'目录目标已存在文件：{path}')
        self.mkdir(path.parent)
        self.add({'kind':'mkdir', 'path':str(path)})
        path.mkdir()
        fault('after_mkdir')

    def write(self, path, data):
        path = bounded(self.root, path)
        self.mkdir(path.parent)
        before = path.read_bytes() if path.exists() else None
        st = path.stat() if before is not None else None
        self.add({'kind':'write', 'path':str(path), 'before':None if before is None else base64.b64encode(before).decode(), 'before_mtime_ns':st.st_mtime_ns if st else None, 'after':hashlib.sha256(data).hexdigest()})
        raw_atomic_write(path, data)
        fault('after_write')

    def move(self, source, target):
        source, target = bounded(self.root, source), bounded(self.root, target)
        if target.exists() or not source.is_dir():
            raise SafetyError(f'移动源/目标异常：{source} → {target}')
        self.mkdir(target.parent)
        self.add({'kind':'move', 'source':str(source), 'target':str(target)})
        source.rename(target)  # never copy/delete fallback across volumes
        fault('after_move')

    def commit(self):
        if not self.entries:
            return
        fault('before_commit')
        self.phase = 'committed'
        self.save()
        # A leftover committed journal is harmless and can be explicitly cleaned.
        try:
            self.path.unlink()
        except OSError:
            pass

    def rollback(self):
        self.phase = 'pending'
        while self.entries:
            entry = self.entries[-1]
            kind = entry['kind']
            if kind == 'write':
                path = bounded(self.root, entry['path'])
                before = None if entry['before'] is None else base64.b64decode(entry['before'])
                current = path.read_bytes() if path.exists() else None
                if current != before:
                    if current is None or hashlib.sha256(current).hexdigest() != entry['after']:
                        raise SafetyError(f'恢复冲突，保留事务与现场，禁止覆盖外部修改：{path}')
                    if before is None:
                        path.unlink()
                    else:
                        raw_atomic_write(path, before)
                if before is not None and entry.get('before_mtime_ns') is not None:
                    os.utime(path,ns=(path.stat().st_atime_ns,entry['before_mtime_ns']))
            elif kind == 'move':
                source, target = bounded(self.root, entry['source']), bounded(self.root, entry['target'])
                if target.exists() and not source.exists():
                    target.rename(source)
                elif target.exists() or not source.exists():
                    raise SafetyError(f'恢复移动冲突：{source} / {target}')
            elif kind == 'mkdir':
                path = bounded(self.root, entry['path'])
                if path.exists():
                    path.rmdir()  # fails safely if someone added data; no recursive delete
            else:
                raise SafetyError(f'未知恢复操作：{kind}')
            self.entries.pop()
            self.save()  # makes interrupted rollback resumable and idempotent
        if self.path.exists():
            self.path.unlink()


@contextmanager
def transaction(root):
    existing = CURRENT.get()
    if existing is not None:
        if existing.root != Path(root).resolve():
            raise SafetyError('禁止跨 root 嵌套事务')
        yield existing
        return
    with file_lock(root, 'workspace-writer'):
        ensure_no_pending(root)
        tx = Transaction(root)
        token = CURRENT.set(tx)
        try:
            yield tx
            tx.commit()
        except BaseException as exc:
            try:
                tx.rollback()
            except BaseException as recovery:
                raise SafetyError(f'操作失败且自动恢复未完成：{exc}；{recovery}；保留恢复记录 {tx.path}') from exc
            raise
        finally:
            CURRENT.reset(token)


def atomic_write(root, path, data):
    with transaction(root) as tx:
        tx.write(path, data)


def mkdir(root, path):
    tx = CURRENT.get()
    if tx is None:
        raise SafetyError('mkdir requires transaction')
    tx.mkdir(path)


def recover(root, dry_run=False):
    if dry_run:
        return _recover_locked(root, True)
    with file_lock(root, 'workspace-writer'):
        return _recover_locked(root, False)


def _recover_locked(root, dry_run=False):
    plans = []
    for path in pending(root):
        obj = json.loads(path.read_text(encoding='utf-8'))
        if obj.get('version') != 1 or Path(obj.get('root', '')).resolve() != Path(root).resolve():
            raise SafetyError(f'恢复记录 root/version 无效：{path}')
        for entry in obj['entries']:
            for field in ('path', 'source', 'target'):
                if field in entry:
                    bounded(root, entry[field])
        plans.append({'journal':str(path), 'phase':obj['phase'], 'operations':obj['entries']})
    if dry_run:
        # Never expose prior CASE bodies in a preview.
        return [{'journal':p['journal'],'phase':p['phase'],'operations':[{k:v for k,v in e.items() if k != 'before'} for e in p['operations']]} for p in plans]
    with file_lock(root, 'workspace-writer'):
        for plan in plans:
            tx = Transaction(root)
            tx.path = Path(plan['journal'])
            tx.entries = plan['operations']
            if plan['phase'] == 'committed':
                tx.path.unlink()
            elif plan['phase'] == 'pending':
                tx.rollback()
            else:
                raise SafetyError('未知事务状态')
    return [{'journal':p['journal'],'recovered':True} for p in plans]
