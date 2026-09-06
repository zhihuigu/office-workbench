#!/usr/bin/env python3
"""Deterministic CASE registry and generated workbench views.

CASE.md files are the only authoritative task records. 工作看板.md and INDEX/
are disposable views and can always be rebuilt from CASE files.
"""

from __future__ import annotations

import argparse
import functools
import contextlib
import io
import os
from contextlib import nullcontext
import hashlib
import json
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import safety
import retrieval


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ACTIVE_STATUSES = {
    "drafting", "awaiting_user", "submitted", "waiting_external",
    "revision_required", "final_confirmed",
}
ALL_STATUSES = ACTIVE_STATUSES | {"archived"}
WAITING_STATUSES = {"submitted", "waiting_external"}
ACTION_STATUSES = {"drafting", "awaiting_user", "revision_required"}
UPDATE_STATUSES = ACTION_STATUSES | WAITING_STATUSES
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
STATUS_LABELS = {
    "drafting": "制作中", "awaiting_user": "待用户确认",
    "submitted": "已提交待审核", "waiting_external": "等待他人/材料",
    "revision_required": "需修改", "final_confirmed": "终版已确认待闭环",
    "archived": "已归档",
}
DATE_FIELDS = {
    "created", "due", "next_action_due", "final_confirmed_at",
    "completed", "archived",
}
FIELD_ORDER = [
    "schema_version", "case_id", "title", "series_id", "series", "period",
    "created", "due", "next_action_due", "status", "priority", "source",
    "source_refs", "related_cases", "previous_case_id", "current_version",
    "submitted_version", "final_version", "final_path", "final_sha256",
    "waiting_for", "next_action", "final_confirmed_at",
    "final_confirmation_note", "completed", "archived", "reopened_from",
]
REQUIRED_FIELDS = {
    "schema_version", "case_id", "title", "created", "status", "priority",
    "source", "next_action",
}
CASE_ID_PATTERN = re.compile(r"^CASE-\d{8}-[0-9A-F]{32}$")
SERIES_ID_PATTERN = re.compile(r"^SERIES-\d{8}-[0-9A-F]{32}$")
DASHBOARD_NAME = "工作看板.md"
UPDATE_FIELDS = (
    "status", "priority", "due", "next_action_due", "waiting_for",
    "next_action", "current_version", "submitted_version",
)


class CaseError(safety.SafetyError):
    """A user-correctable CASE or command error."""


@dataclass
class CaseRecord:
    path: Path
    data: dict[str, Any]
    body: str
    root: Path
    loaded_sha256: str

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def area(self) -> str:
        try:
            return self.path.relative_to(self.root).parts[0].upper()
        except (ValueError, IndexError):
            return "UNKNOWN"

    @property
    def relative_path(self) -> str:
        try:
            return self.path.relative_to(self.root).as_posix()
        except ValueError:
            return self.path.as_posix()


def default_root() -> Path:
    raise CaseError('必须显式指定已初始化的私人工作目录；请使用该目录的 office.py')


def normalize_root(value: str | Path | None) -> Path:
    supplied = Path(value) if value else default_root()
    if supplied.is_symlink() or (hasattr(supplied, 'is_junction') and supplied.is_junction()):
        raise CaseError('root 不允许链接')
    for parent in (supplied.absolute(), *supplied.absolute().parents):
        if parent.is_symlink() or parent.is_junction():
            raise CaseError('root 的父路径不允许链接')
    root = supplied.resolve()
    marker = safety.bounded(root, root / '.office-workbench.json')
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('format') != 1:
        raise CaseError('未初始化的私人工作目录；禁止直接操作代码目录或其他工作台')
    if not root.is_dir() or not (root / 'ACTIVE').is_dir() or not (root / 'ARCHIVE').is_dir():
        raise CaseError(f'无效工作台 root（必须已有 ACTIVE/ARCHIVE）：{root}')
    for area in ('ACTIVE','ARCHIVE'):
        safety.bounded(root, root / area)
    return root


def case_scope(root, path, areas=('ACTIVE','ARCHIVE')):
    root = normalize_root(root)
    allowed = tuple(areas)
    if not allowed or any(a not in ('ACTIVE','ARCHIVE') for a in allowed):
        raise CaseError('非法 AREA')
    path = safety.bounded(root, path)
    rel = path.relative_to(root)
    if len(rel.parts) < 3 or rel.parts[0] not in allowed or rel.name != 'CASE.md':
        raise CaseError(f'CASE 路径不在允许 AREA {allowed}：{path}')
    return path


def mutation(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        first = args[0]
        root = first.root if isinstance(first, CaseRecord) else first
        root = normalize_root(root)
        if kwargs.get('preview', False):
            return function(*args, **kwargs)
        with safety.transaction(root):
            return function(*args, **kwargs)
    return wrapped


def preview_result(args, record=None, *, before=None, moves=None, fields=None):
    result = {'dry_run':True, 'case_path':record.relative_path if record else None,
              'current_status':before.data.get('status') if before else None,
              'target_status':record.data.get('status') if record else None,
              'changed_fields':fields or (sorted(k for k,v in record.data.items() if before is None or before.data.get(k) != v) if record else []),
              'moves':moves or [], 'refresh_views':args.command != 'series-new',
              'risks':[], 'validation':{'errors':[], 'warnings':[]}}
    if record:
        result['case_id'] = record.data.get('case_id')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise CaseError(f"非法引号字符串：{value}") from exc
    if value.startswith(('"', "'")) and not value.endswith(value[0]):
        raise CaseError(f"未闭合的字符串：{value}")
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "~"}:
        return ""
    return value


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str, str]:
    return parse_frontmatter_bytes(path.read_bytes(), path)


def parse_frontmatter_bytes(raw_bytes, path):
    text = raw_bytes.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CaseError(f"缺少 YAML 头：{path}")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise CaseError(f"YAML 头未闭合：{path}") from exc
    data: dict[str, Any] = {}
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise CaseError(f"无法解析 {path}:{number}：{line}")
        key, raw = line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise CaseError(f"非法字段名 {path}:{number}：{key}")
        if key in data:
            raise CaseError(f"重复 frontmatter 字段：{path}:{number}: {key}")
        data[key] = parse_scalar(raw)
    body = "\n".join(lines[end + 1:]).rstrip() + "\n"
    return data, body, hashlib.sha256(raw_bytes).hexdigest()


def parse_case(path: Path, root: Path) -> CaseRecord:
    path = case_scope(root,path)
    data, body, digest = parse_frontmatter(path)
    return CaseRecord(path=path, data=data, body=body, root=root, loaded_sha256=digest)


def serialize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def serialize_field(key: str, value: Any) -> str:
    if key in DATE_FIELDS:
        text = str(value or "").strip()
        if not text:
            return ""
        if iso_date(text) is not None:
            return text[:10]
    return serialize_scalar(value)


def assert_case_unchanged(record: CaseRecord) -> None:
    if not record.path.is_file():
        raise CaseError(f"CASE 已被移动或删除，拒绝覆盖：{record.path}")
    current = hashlib.sha256(record.path.read_bytes()).hexdigest()
    if current != record.loaded_sha256:
        raise CaseError(
            "当前事项状态似乎已被其他会话更新；请重新读取最新 CASE，核对冲突后再修改："
            f"{record.relative_path}"
        )


def render_case(record):
    ordered = [key for key in FIELD_ORDER if key in record.data]
    ordered.extend(sorted(key for key in record.data if key not in FIELD_ORDER))
    header = ['---'] + [f'{key}: {serialize_field(key, record.data[key])}' for key in ordered] + ['---']
    return ('\n'.join(header) + '\n\n' + record.body.lstrip('\n')).encode('utf-8')


def validate_transition(old, new, operation='update'):
    a, b = old.data.get('status'), new.data.get('status')
    if operation == 'update':
        allowed = {status:set(UPDATE_STATUSES) for status in UPDATE_STATUSES}
        allowed['final_confirmed'] = {'final_confirmed'}
        allowed['archived'] = {'archived'}
        if b not in allowed.get(a, set()):
            raise CaseError(f'非法状态转换：{a} → {b}；Final/归档必须使用专用流程')
        protected = ('case_id','final_version','final_path','final_sha256','final_confirmed_at',
                     'final_confirmation_note','completed','archived')
        if any(old.data.get(k) != new.data.get(k) for k in protected):
            raise CaseError('普通写入不得改变永久 ID、Final 或归档字段')
        if a == 'archived' and (old.data != new.data or old.body != new.body):
            raise CaseError('归档 CASE 仅允许 reopen 专用关联流程修改')
    elif operation == 'confirm-final':
        if a not in ACTIVE_STATUSES or b != 'final_confirmed':
            raise CaseError('非法 Final 转换')
    elif operation == 'archive':
        if a not in ACTIVE_STATUSES or b != 'archived':
            raise CaseError('非法归档转换')
    elif operation == 'reopen':
        if a != 'archived' or b != 'archived':
            raise CaseError('reopen 只能从 ARCHIVE 建立后续事项')
        if any(old.data.get(k) != new.data.get(k) for k in old.data if k != 'related_cases'):
            raise CaseError('reopen 必须保留旧 CASE 状态、Final、完成日期')
    else:
        raise CaseError('未知写入操作')


def preflight(record, old=None, operation='update', artifact_dir=None):
    case_scope(record.root, record.path)
    errors, warnings = validate_record(record, artifact_dir=artifact_dir, strict=True)
    peers = scan_cases(record.root)
    same = [r for r in peers if r.data.get('case_id') == record.data.get('case_id') and r.path != (old.path if old else record.path)]
    if same:
        errors.append('CASE ID 重复，拒绝写入')
    previous = str(record.data.get('previous_case_id','')).strip()
    if previous and not any(r.data.get('case_id') == previous for r in peers):
        errors.append('previous_case_id 找不到对应 CASE')
    if old:
        old_errors, _ = validate_record(old, strict=False)
        errors.extend(old_errors)
        validate_transition(old,record,operation)
    if errors:
        raise CaseError('写入前校验失败：' + '；'.join(errors))
    return warnings


def write_case(record, *, operation='update', previous=None):
    # Lock then re-read, validate the full proposed record, and compare again before replacing.
    with safety.transaction(record.root), safety.file_lock(record.root, 'case:' + str(record.data.get('case_id'))):
        assert_case_unchanged(record)
        old = previous or parse_case(case_scope(record.root,record.path),record.root)
        preflight(record,old,operation)
        data = render_case(record)
        parse_frontmatter_bytes(data,record.path)
        assert_case_unchanged(record)
        safety.atomic_write(record.root,record.path,data)
        record.loaded_sha256 = hashlib.sha256(data).hexdigest()

def scan_cases(root: Path, areas: Iterable[str] = ('ACTIVE','ARCHIVE')) -> list[CaseRecord]:
    class Records(list):
        pass
    records = Records()
    records.errors = []
    root = normalize_root(root)
    areas = tuple(areas)
    if any(a not in ('ACTIVE','ARCHIVE') for a in areas):
        raise CaseError('非法 AREA')
    for area in areas:
        for directory, dirs, files in os.walk(root / area, followlinks=False):
            # Never descend artifact trees or linked folders while looking for CASE identities.
            dirs[:] = [d for d in dirs if d not in ('sources','work','deliverables')]
            for d in list(dirs):
                child = Path(directory) / d
                if child.is_symlink() or (hasattr(child,'is_junction') and child.is_junction()):
                    records.errors.append(f'控制目录含链接，已隔离：{child.relative_to(root)}')
                    dirs.remove(d)
            if 'CASE.md' in files:
                path = Path(directory) / 'CASE.md'
                try:
                    records.append(parse_case(case_scope(root,path,areas),root))
                except (safety.SafetyError,OSError,UnicodeError,ValueError) as exc:
                    records.errors.append(str(exc))
    records.sort(key=lambda r:r.relative_path)
    if records.errors:
        for error in records.errors:
            print('ERROR (isolated): ' + error,file=sys.stderr)
    return records


def healthy_cases(root):
    records = scan_cases(root)
    ids = {}
    for record in records:
        ids.setdefault(record.data.get('case_id'), []).append(record)
    healthy = []
    for record in records:
        errors, _ = validate_record(record)
        if len(ids[record.data.get('case_id')]) > 1:
            errors.append(f'CASE ID 重复，已隔离：{record.relative_path}')
        if errors:
            records.errors.extend(errors)
            for error in errors:
                print('ERROR (isolated): ' + error,file=sys.stderr)
        else:
            healthy.append(record)
    records[:] = healthy
    return records

def iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def safe_name(value: str, fallback: str = "事项") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or fallback


def ensure_inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    base = parent.resolve()
    if resolved != base and base not in resolved.parents:
        raise CaseError(f"路径越出事项目录：{path}")
    return resolved


def resolve_case(root: Path, value: str, areas: Iterable[str] = ('ACTIVE','ARCHIVE')) -> CaseRecord:
    root = normalize_root(root)
    candidate = Path(value)
    # Relative paths are always relative to the chosen root, never the caller's cwd.
    path = candidate if candidate.is_absolute() else root / candidate
    if path.exists() or candidate.is_absolute() or '/' in value or '\\' in value or '..' in candidate.parts:
        if path.is_dir():
            path /= 'CASE.md'
        record = parse_case(case_scope(root,path,areas),root)
        duplicates = [r for r in scan_cases(root) if r.data.get('case_id') == record.data.get('case_id')]
        if len(duplicates) > 1:
            raise CaseError('CASE ID 重复，拒绝通过路径绕过')
        return record
    matches = [r for r in scan_cases(root,areas) if str(r.data.get('case_id','')) == value]
    if not matches:
        raise CaseError(f'找不到 CASE：{value}')
    if len(matches) != 1:
        raise CaseError(f'CASE ID 重复：{value}')
    return matches[0]

def normalize_title(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def find_duplicate_candidates(
    root: Path, *, title: str, series_id: str = "", series: str = "", period: str = ""
) -> list[tuple[float, CaseRecord]]:
    wanted = normalize_title(title)
    candidates: list[tuple[float, CaseRecord]] = []
    for record in scan_cases(root, ("ACTIVE",)):
        existing_period = str(record.data.get("period", "")).strip()
        existing_series_id = str(record.data.get("series_id", "")).strip()
        existing_series = str(record.data.get("series", "")).strip().casefold()
        same_series_identity = bool(
            (series_id and series_id == existing_series_id)
            or (series and series.casefold() == existing_series)
        )
        if period and existing_period and period != existing_period and same_series_identity:
            continue
        existing = normalize_title(str(record.data.get("title", "")))
        if not wanted or not existing:
            continue
        same_period = bool(period and existing_period and period == existing_period)
        same_series = same_series_identity
        if same_period and same_series:
            score = 1.0
        elif wanted == existing:
            score = 1.0
        elif min(len(wanted), len(existing)) >= 4 and (wanted in existing or existing in wanted):
            score = 0.9
        else:
            score = SequenceMatcher(None, wanted, existing).ratio()
        if score >= 0.72:
            candidates.append((score, record))
    candidates.sort(key=lambda pair: (pair[0], str(pair[1].data.get("created", ""))), reverse=True)
    return candidates


def render_template(path: Path, values: dict[str, str]) -> str:
    if not path.exists():
        raise CaseError(f"缺少模板：{path}")
    rendered = path.read_text(encoding="utf-8")
    for key, value in values.items():
        escaped = json.dumps(str(value), ensure_ascii=False)[1:-1]
        rendered = rendered.replace("{{" + key + "}}", escaped)
    leftovers = sorted(set(re.findall(r"\{\{([A-Za-z0-9_]+)\}\}", rendered)))
    if leftovers:
        raise CaseError(f"模板仍有未赋值字段：{', '.join(leftovers)}")
    return rendered


def new_case_id(root: Path, created: str) -> str:
    existing = {str(record.data.get("case_id", "")) for record in scan_cases(root)}
    while True:
        value = f"CASE-{created.replace('-', '')}-{uuid.uuid4().hex.upper()}"
        if value not in existing:
            return value


@mutation
def create_case(
    root: Path, *, title: str, created: str, due: str, next_action_due: str,
    source: str, series: str, period: str, priority: str, next_action: str,
    series_id: str = "", previous_case_id: str = "", reopened_from: str = "",
    allow_related_new: bool = False, preview: bool = False,
) -> CaseRecord:
    for label, raw in (("created", created), ("due", due), ("next_action_due", next_action_due)):
        if raw and iso_date(raw) is None:
            raise CaseError(f"{label} 不是 YYYY-MM-DD 日期：{raw}")
    if priority not in PRIORITY_RANK:
        raise CaseError(f"priority 必须是 {', '.join(PRIORITY_RANK)}")
    if series_id and not SERIES_ID_PATTERN.fullmatch(series_id):
        raise CaseError(f"series_id 格式无效：{series_id}")
    duplicates = find_duplicate_candidates(
        root, title=title, series_id=series_id, series=series, period=period
    )
    if duplicates and not allow_related_new:
        details = "；".join(
            f"{record.data.get('title')}（{record.data.get('case_id')}，{record.relative_path}）"
            for _, record in duplicates[:5]
        )
        raise CaseError(
            "ACTIVE 中存在高度相关且未闭环的 CASE，拒绝重复创建："
            f"{details}。请先读取并判断是否继续原 CASE；确认是独立事项后才使用 --allow-related-new。"
        )
    case_id = new_case_id(root, created)
    folder = root / "ACTIVE" / f"{created}_{safe_name(title)}"
    if folder.exists():
        folder = root / "ACTIVE" / f"{created}_{safe_name(title)}_{case_id[-8:]}"
    values = {
        "case_id": case_id, "title": title, "series_id": series_id,
        "series": series, "period": period, "created": created, "due": due,
        "next_action_due": next_action_due, "status": "drafting",
        "priority": priority, "source": source,
        "previous_case_id": previous_case_id, "next_action": next_action,
        "reopened_from": reopened_from,
    }
    rendered = render_template(Path(__file__).resolve().parent / "templates" / "CASE.md", values)
    path = case_scope(root, folder / 'CASE.md', ('ACTIVE',))
    data, body, digest = parse_frontmatter_bytes(rendered.encode('utf-8'), path)
    record = CaseRecord(path,data,body,root,digest)
    preflight(record)
    if not preview:
        safety.mkdir(root,folder)
        for name in ('sources','work','deliverables'):
            safety.mkdir(root,folder / name)
        safety.atomic_write(root,path,rendered.encode('utf-8'))
        safety.fault('new_after_case')
    return record


@mutation
def create_series(
    root: Path, *, title: str, cadence: str, description: str, skill: str,
    created: str, preview: bool = False,
) -> tuple[str, Path]:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',created) or iso_date(created) is None:
        raise CaseError(f"created 不是 YYYY-MM-DD 日期：{created}")
    base = root / "SERIES"
    paths = sorted(base.rglob("SERIES.md")) if base.exists() else []
    for path in paths:
        data, _, _ = parse_frontmatter(path)
        if normalize_title(str(data.get("title", ""))) == normalize_title(title):
            raise CaseError(f"系列已存在：{data.get('series_id')}（{path.relative_to(root)}）")
    series_id = f"SERIES-{created.replace('-', '')}-{uuid.uuid4().hex.upper()}"
    folder = base / safe_name(title, "系列")
    if folder.exists():
        raise CaseError(f"系列目录已存在：{folder}")
    rendered = render_template(
        Path(__file__).resolve().parent / "templates" / "SERIES.md",
        {"series_id": series_id, "title": title, "cadence": cadence,
         "description": description, "skill": skill, "created": created},
    )
    path = safety.bounded(root,folder / 'SERIES.md')
    parsed, _, _ = parse_frontmatter_bytes(rendered.encode('utf-8'),path)
    if not str(parsed.get('title','')).strip() or not str(parsed.get('cadence','')).strip():
        raise CaseError('系列 title/cadence 不能为空')
    if not preview:
        safety.mkdir(root,folder)
        safety.atomic_write(root,path,rendered.encode('utf-8'))
    return series_id, path


def case_sort_key(record: CaseRecord) -> tuple[Any, ...]:
    due = iso_date(record.data.get("due")) or date.max
    priority = PRIORITY_RANK.get(str(record.data.get("priority", "normal")), 9)
    return due, priority, str(record.data.get("title", ""))


def case_view(record: CaseRecord) -> dict[str, Any]:
    data = record.data
    return {
        "case_id": str(data.get("case_id", "")),
        "title": str(data.get("title", "")),
        "series_id": str(data.get("series_id", "")),
        "series": str(data.get("series", "")),
        "period": str(data.get("period", "")),
        "status": str(data.get("status", "")),
        "priority": str(data.get("priority", "normal")),
        "created": str(data.get("created", "")),
        "due": str(data.get("due", "")),
        "next_action_due": str(data.get("next_action_due", "")),
        "waiting_for": str(data.get("waiting_for", "")),
        "next_action": str(data.get("next_action", "")),
        "current_version": str(data.get("current_version", "")),
        "submitted_version": str(data.get("submitted_version", "")),
        "final_version": str(data.get("final_version", "")),
        "final_path": str(data.get("final_path", "")),
        "final_sha256": str(data.get("final_sha256", "")),
        "completed": str(data.get("completed", "")),
        "area": record.area,
        "case_path": record.relative_path,
    }


def dashboard_data(root: Path, target: date, days: int, recent_days: int) -> dict[str, Any]:
    all_cases = healthy_cases(root)
    active = [r for r in all_cases if r.area == "ACTIVE"]
    active.sort(key=case_sort_key)
    today_action: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    window_end = target + timedelta(days=max(days, 1) - 1)
    for record in active:
        status = str(record.data.get("status", ""))
        due = iso_date(record.data.get("due"))
        action_due = iso_date(record.data.get("next_action_due")) or due
        view = case_view(record)
        if status in WAITING_STATUSES:
            waiting.append(view)
        elif status in ACTION_STATUSES and (action_due is None or action_due <= target):
            today_action.append(view)
        if due and target < due <= window_end and status not in WAITING_STATUSES:
            upcoming.append(view)
        if due and due < target and status != "final_confirmed":
            risks.append(view)
    recent_start = target - timedelta(days=max(recent_days, 1) - 1)
    for record in all_cases:
        completed = iso_date(record.data.get("completed"))
        if completed and recent_start <= completed <= target:
            recent.append(case_view(record))
    recent.sort(key=lambda item: (item.get("completed", ""), item.get("title", "")), reverse=True)
    return {
        "errors":all_cases.errors, "as_of": target.isoformat(), "window_days": days,
        "today_action": today_action, "upcoming": upcoming, "waiting": waiting,
        "risks": risks, "all_active": [case_view(record) for record in active],
        "recent_completed": recent,
    }


def markdown_link(label: str, target: str) -> str:
    safe_label = label.replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}](<{target}>)"


def format_item(item: dict[str, Any]) -> str:
    status = STATUS_LABELS.get(item.get("status", ""), item.get("status") or "—")
    return (
        f"- {markdown_link(item['title'], item['case_path'])}（{item['case_id']}）"
        f"｜状态：{status}｜截止：{item.get('due') or '—'}"
        f"｜下一步：{item.get('next_action') or '—'}"
        f"｜等待：{item.get('waiting_for') or '—'}"
    )


def format_dashboard(board: dict[str, Any]) -> str:
    sections = [
        ("今天需要主动处理", "today_action"), ("即将到期", "upcoming"),
        ("等待他人", "waiting"), ("风险 / 逾期", "risks"),
        ("当前全部事项", "all_active"), ("最近完成", "recent_completed"),
    ]
    lines = [
        "# 工作看板", "",
        f"> 数据日期：{board['as_of']}。本文件由 CASE 自动生成，不是任务事实源；删除后可运行 `python office.py refresh` 重建。",
        "",
    ]
    for heading, key in sections:
        lines.extend([f"## {heading}", ""])
        items = board[key]
        if not items:
            lines.extend(["- 无", ""])
        else:
            lines.extend(format_item(item) for item in items)
            lines.append("")
    if board.get("errors"):
        lines.extend(["## 数据问题（已隔离，未修复）", ""])
        lines.extend("- " + error for error in board["errors"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@mutation
def refresh_dashboard(
    root: Path, target: date | None = None, days: int = 4, recent_days: int = 7,
) -> Path:
    board = dashboard_data(root, target or date.today(), days, recent_days)
    path = root / DASHBOARD_NAME
    safety.atomic_write(root,path,format_dashboard(board).encode("utf-8"))
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def final_fingerprint_status(record: CaseRecord) -> tuple[str, str]:
    final_path_value = str(record.data.get("final_path", "")).strip()
    expected = str(record.data.get("final_sha256", "")).strip().lower()
    if not final_path_value and not expected:
        return "not_recorded", ""
    if not final_path_value:
        return "missing_path", ""
    candidate = Path(final_path_value)
    if candidate.is_absolute():
        return "absolute_path", ""
    try:
        checked = ensure_inside(record.directory / candidate, record.directory)
    except CaseError:
        return "outside_case", ""
    if not checked.is_file():
        return "missing_file", ""
    try:
        actual = sha256_file(checked)
    except OSError:
        return "unreadable", ""
    if not expected:
        return "untracked", actual
    if actual.lower() != expected:
        return "mismatch", actual
    return "verified", actual


def trust_resolver(record):
    fingerprint, actual = final_fingerprint_status(record)
    confirmed = bool(record.data.get('status') in ('final_confirmed','archived')
                     and record.data.get('final_confirmed_at') and record.data.get('final_confirmation_note')
                     and record.data.get('final_version'))
    alerts = []
    if fingerprint == 'mismatch':
        alerts = ['FINAL_CHANGED','HASH_MISMATCH']
    elif fingerprint not in ('verified','not_recorded'):
        alerts = ['FINAL_UNVERIFIED',fingerprint.upper()]
    preferred, kind, rank = '', 'case_only', 0
    bad_final = None
    if record.data.get('final_path'):
        try:
            bad_final = ensure_inside(record.directory / str(record.data['final_path']),record.directory)
        except CaseError:
            pass
    for field, label, weight in [('submitted_version','submitted',40),('current_version','working',30)]:
        value = str(record.data.get(field,'')).strip()
        if not value or Path(value).is_absolute():
            continue
        try:
            candidate = ensure_inside(record.directory / value,record.directory)
            if not candidate.is_file():
                continue
            if fingerprint != 'not_recorded' and not (fingerprint == 'verified' and confirmed) and bad_final and (candidate == bad_final or (bad_final.exists() and os.path.samefile(candidate,bad_final))):
                continue
        except (CaseError,OSError):
            continue
        preferred,kind,rank = value,label,weight
        break
    if fingerprint == 'verified' and confirmed:
        preferred,kind,rank = str(record.data['final_path']),'confirmed_final',50
    credibility_value = 'final_changed' if fingerprint == 'mismatch' else kind
    if not confirmed and fingerprint == 'verified':
        alerts.append('FINAL_CONFIRMATION_MISSING')
    return {'credibility':credibility_value,'preferred_version':preferred,'preferred_kind':kind,
            'trust_rank':rank,'final_integrity':fingerprint,'alerts':alerts}


def credibility(record: CaseRecord) -> str:
    return trust_resolver(record)['credibility']

@mutation
def build_index(root: Path) -> tuple[Path, Path, int]:
    records = healthy_cases(root)
    records.sort(
        key=lambda record: (str(record.data.get("created", "")), str(record.data.get("case_id", ""))),
        reverse=True,
    )
    index_dir = root / "INDEX"
    safety.mkdir(root,index_dir)
    jsonl_path = index_dir / "cases.jsonl"
    md_path = index_dir / "cases.md"
    rows: list[dict[str, Any]] = []
    for record in records:
        row = case_view(record)
        row.update(trust_resolver(record))
        rows.append(row)
    safety.atomic_write(root,jsonl_path,"".join(json.dumps(row,ensure_ascii=False,sort_keys=True) + "\n" for row in rows).encode("utf-8"))
    lines = [
        "# 历史事项索引", "",
        "> 自动生成；CASE 才是事实源。运行 `caseboard.py index` 可重建。", "",
        "| 创建 | 事项 | 状态 | 系列/期次 | 可信版本 | CASE |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        series = " / ".join(value for value in (row["series"], row["period"]) if value) or "—"
        version = row["preferred_version"] or "—"
        if row["alerts"]:
            version = " / ".join(row["alerts"]) + " · " + version
        link = markdown_link("打开", "../" + row["case_path"])
        lines.append(
            f"| {row['created'] or '—'} | {row['title']} | {row['status']} | {series} | {version} | {link} |"
        )
    lines.extend(["", "## 数据问题"] + list(records.errors)) if records.errors else None
    safety.atomic_write(root,md_path,("\n".join(lines) + "\n").encode("utf-8"))
    return jsonl_path, md_path, len(rows)


@mutation
def refresh_views(root: Path) -> tuple[Path, Path, Path, int]:
    jsonl, md, count = build_index(root)
    dashboard = refresh_dashboard(root)
    return dashboard, jsonl, md, count


def series_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    base = root / "SERIES"
    if not base.exists():
        return ids
    for path in base.rglob("SERIES.md"):
        data, _, _ = parse_frontmatter(safety.bounded(root,path))
        value = str(data.get("series_id", "")).strip()
        if value:
            ids.add(value)
    return ids


def validate_record(record, *, artifact_dir=None, strict=False):
    data, label = record.data, record.relative_path
    errors, warnings = [], []
    missing = [k for k in REQUIRED_FIELDS if not str(data.get(k,'')).strip()]
    if missing:
        errors.append(f'{label}: 必填字段为空：{", ".join(missing)}')
    status = str(data.get('status',''))
    if status not in ALL_STATUSES:
        errors.append(f'{label}: 非法状态 {status}')
    if (record.area == 'ARCHIVE') != (status == 'archived'):
        errors.append(f'{label}: 状态与 AREA 不一致')
    if data.get('priority') not in PRIORITY_RANK:
        errors.append(f'{label}: priority 无效')
    if data.get('schema_version') != 2:
        warnings.append(f'{label}: 非当前 schema；不改写旧记录')
    if not CASE_ID_PATTERN.fullmatch(str(data.get('case_id',''))):
        warnings.append(f'{label}: 旧 ID 格式保留，不自动改写')
    for field in DATE_FIELDS:
        value = str(data.get(field,'')).strip()
        if value and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            errors.append(f'{label}: {field} 日期无效：{value}')
        elif value and iso_date(value) is None:
            errors.append(f'{label}: {field} 日期无效：{value}')
    final_path, final_version, final_sha = (str(data.get(k,'')).strip() for k in ('final_path','final_version','final_sha256'))
    if (final_path or final_version or final_sha) and status not in ('final_confirmed','archived'):
        errors.append(f'{label}: 未确认状态却填写 Final 字段')
    if bool(final_path) != bool(final_version) or (final_sha and not final_path):
        errors.append(f'{label}: Final 字段不完整')
    if final_path and not re.fullmatch('[0-9a-fA-F]{64}',final_sha):
        errors.append(f'{label}: Final SHA256 无效')
    if status == 'final_confirmed' and not final_path:
        errors.append(f'{label}: final_confirmed 缺少 Final')
    if final_path and not (data.get('final_confirmed_at') and data.get('final_confirmation_note')):
        errors.append(f'{label}: 缺少用户 Final 确认记录')
    directory = artifact_dir or record.directory
    for field in ('current_version','submitted_version','final_path'):
        value = str(data.get(field,'')).strip()
        if not value:
            continue
        if Path(value).is_absolute():
            (errors if strict or field == 'final_path' else warnings).append(f'{label}: {field} 必须使用事项内相对路径')
            continue
        try:
            candidate = ensure_inside(directory / value,directory)
            if not candidate.is_file():
                errors.append(f'{label}: {field} 指向的文件不存在：{value}')
        except CaseError as exc:
            errors.append(str(exc))
    if final_path:
        check_record = CaseRecord(directory / 'CASE.md',data,record.body,record.root,record.loaded_sha256)
        integrity, _ = final_fingerprint_status(check_record)
        if integrity == 'mismatch':
            warnings.append(f'{label}: FINAL_CHANGED / HASH_MISMATCH：Final 文件在确认后发生过修改')
    if status in WAITING_STATUSES and not str(data.get('waiting_for','')).strip():
        (errors if strict else warnings).append(f'{label}: 等待/已提交状态必须填写 waiting_for')
    linked = str(data.get('series_id','')).strip()
    if linked:
        try:
            if linked not in series_ids(record.root):
                errors.append(f'{label}: series_id 找不到对应 SERIES.md')
        except (safety.SafetyError,OSError,UnicodeError) as exc:
            errors.append(f'{label}: SERIES 无法校验：{exc}')
    return errors,warnings


def validate_cases(root: Path) -> tuple[list[str],list[str]]:
    records = scan_cases(root)
    errors, warnings = list(records.errors), []
    ids = {}
    for record in records:
        try:
            e,w = validate_record(record)
            errors.extend(e)
            warnings.extend(w)
        except (safety.SafetyError,OSError,UnicodeError,ValueError) as exc:
            errors.append(f'{record.relative_path}: {exc}')
        ids.setdefault(str(record.data.get('case_id','')),[]).append(record.relative_path)
    for key, paths in ids.items():
        if len(paths)>1:
            errors.append(f'CASE ID 重复 {key}: {paths}')
    try:
        series_ids(root)
    except (safety.SafetyError,OSError,UnicodeError) as exc:
        errors.append(str(exc))
    if safety.CURRENT.get() is None and safety.pending(root):
        errors.append('存在待恢复事务，先 check，再 repair --recover')
    return errors,warnings

def append_event(record: CaseRecord, line: str) -> None:
    heading = "## 重要决定与变更记录"
    if heading in record.body:
        before, after = record.body.split(heading, 1)
        record.body = before + heading + after.rstrip() + "\n" + line + "\n"
    else:
        record.body = record.body.rstrip() + f"\n\n{heading}\n\n{line}\n"


def validate_update_values(record: CaseRecord, changes: dict[str, str]) -> None:
    for field in ("due", "next_action_due"):
        value = changes.get(field)
        if value and iso_date(value) is None:
            raise CaseError(f"{field} 日期无效：{value}")
    for field in ("current_version", "submitted_version"):
        value = changes.get(field)
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            raise CaseError(f"{field} 必须是事项目录内的相对路径")
        checked = ensure_inside(record.directory / candidate, record.directory)
        if not checked.is_file():
            raise CaseError(f"{field} 指向的文件不存在：{value}")
    resulting_status = changes.get("status", str(record.data.get("status", "")))
    resulting_waiting_for = changes.get(
        "waiting_for", str(record.data.get("waiting_for", ""))
    ).strip()
    if resulting_status in WAITING_STATUSES and not resulting_waiting_for:
        raise CaseError("等待/已提交状态必须填写 waiting_for")


def cmd_update(args: argparse.Namespace) -> int:
    """Safely apply a partial structured update to the freshest ACTIVE CASE."""
    root = normalize_root(args.root)
    record = resolve_case(root, args.case, ("ACTIVE",))
    requested: dict[str, str] = {}
    for field in UPDATE_FIELDS:
        value = getattr(args, field)
        if value is not None:
            requested[field] = str(value).strip()
    if not requested:
        raise CaseError("至少传入一个需要修改的结构化字段")
    validate_update_values(record, requested)
    if requested.get("status") and requested["status"] not in UPDATE_STATUSES:
        raise CaseError("普通 update 不得伪造 Final 或归档状态")
    changes = {
        field: value
        for field, value in requested.items()
        if str(record.data.get(field, "")) != value
    }
    old = parse_case(record.path,root)
    if changes:
        record.data.update(changes)
        summary = "；".join(f"{field}={value or '（清空）'}" for field, value in changes.items())
        note = f" {args.note.strip()}" if args.note and args.note.strip() else ""
        append_event(
            record,
            f"- {date.today().isoformat()}：通过安全更新入口修改结构化字段：{summary}。{note}".rstrip(),
        )
    preflight(record,old)
    if getattr(args,"dry_run",False):
        return preview_result(args,record,before=old)
    if changes:
        write_case(record)
    errors, warnings = validate_cases(root)
    refresh_views(root)
    result = case_view(resolve_case(root, args.case, ("ACTIVE",)))
    result["changed_fields"] = sorted(changes)
    result["validation"] = {"errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def require_final_file(record: CaseRecord, final_path: str) -> tuple[str, Path]:
    normalized = Path(final_path).as_posix()
    candidate = Path(normalized)
    if candidate.is_absolute():
        raise CaseError("final_path 必须是事项目录内的相对路径")
    checked = ensure_inside(record.directory / candidate, record.directory)
    if not checked.is_file():
        raise CaseError(f"最终文件不存在：{normalized}")
    return normalized, checked


def cmd_new(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    created = args.created or date.today().isoformat()
    record = create_case(
        root, title=args.title, created=created, due=args.due or "",
        next_action_due=args.next_action_due or "", source=args.source,
        series_id=args.series_id or "", series=args.series or "",
        period=args.period or "", priority=args.priority,
        next_action=args.next_action, allow_related_new=args.allow_related_new,
        preview=getattr(args,"dry_run",False),
    )
    if getattr(args,"dry_run",False):
        return preview_result(args,record,moves=[{"create_directory":str(record.directory)}])
    refresh_views(root)
    print(json.dumps(case_view(record), ensure_ascii=False, indent=2))
    return 0


def cmd_series_new(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    created = args.created or date.today().isoformat()
    series_id, path = create_series(
        root, title=args.title, cadence=args.cadence,
        description=args.description, skill=args.skill, created=created, preview=getattr(args,"dry_run",False),
    )
    if getattr(args,"dry_run",False):
        return preview_result(args,moves=[{"create_directory":str(path.parent)}],fields=["series_id","title","cadence","description","skill"])
    print(json.dumps(
        {"series_id": series_id, "series_path": path.relative_to(root).as_posix()},
        ensure_ascii=False, indent=2,
    ))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    target = iso_date(args.date) if args.date else date.today()
    if target is None:
        raise CaseError(f"日期无效：{args.date}")
    board = dashboard_data(root, target, args.days, args.recent_days)
    if args.format == "json":
        print(json.dumps(board, ensure_ascii=False, indent=2))
    else:
        print(format_dashboard(board), end="")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    if getattr(args,"dry_run",False):
        errors,warnings=validate_cases(root)
        print(json.dumps({"dry_run":True,"files":[DASHBOARD_NAME,"INDEX/cases.jsonl","INDEX/cases.md"],"refresh_views":True,"errors":errors,"warnings":warnings},ensure_ascii=False,indent=2))
        return 1 if errors else 0
    dashboard, jsonl, md, count = refresh_views(root)
    print(f"已刷新 {dashboard}，并索引 {count} 个事项：{jsonl}；{md}")
    return 0


def cmd_index(args):
    return cmd_refresh(args)

def cmd_validate(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    errors, warnings = validate_cases(root)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"校验完成：{len(errors)} 个错误，{len(warnings)} 个警告。")
    return 1 if errors else 0


def cmd_confirm_final(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise CaseError("确认 Final 需要用户明确说明；核实后传 --confirm")
    if not args.confirmation_note.strip():
        raise CaseError("必须用 --confirmation-note 记录用户的明确确认")
    if not args.final_version.strip() or not args.final_path.strip():
        raise CaseError("确认 Final 必须同时提供 --final-version 与 --final-path")
    root = normalize_root(args.root)
    record = resolve_case(root, args.case, ("ACTIVE",))
    normalized, checked = require_final_file(record, args.final_path)
    confirmed = args.date or date.today().isoformat()
    if iso_date(confirmed) is None:
        raise CaseError(f"确认日期无效：{confirmed}")
    old = parse_case(record.path,root)
    record.data["status"] = "final_confirmed"
    record.data["final_version"] = args.final_version.strip()
    record.data["final_path"] = normalized
    record.data["final_sha256"] = sha256_file(checked)
    record.data["final_confirmed_at"] = confirmed
    record.data["final_confirmation_note"] = args.confirmation_note.strip()
    record.data["waiting_for"] = ""
    record.data["next_action"] = "等待确认是否正式闭环归档"
    append_event(
        record,
        f"- {confirmed}：用户确认 Final（{args.final_version.strip()}）；尚未归档。{args.confirmation_note.strip()}",
    )
    preflight(record,old,"confirm-final")
    if getattr(args,"dry_run",False):
        return preview_result(args,record,before=old)
    write_case(record,operation="confirm-final")
    safety.fault("confirm_after_case")
    refresh_views(root)
    print(json.dumps(case_view(record), ensure_ascii=False, indent=2))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    if not args.confirm:
        raise CaseError("归档需要用户明确确认；核实后传 --confirm")
    if not args.confirmation_note.strip():
        raise CaseError("必须用 --confirmation-note 记录用户的明确确认")
    root = normalize_root(args.root)
    record = resolve_case(root, args.case, ("ACTIVE",))
    supplied = bool(args.final_path.strip() or args.final_version.strip())
    if bool(args.final_path.strip()) != bool(args.final_version.strip()):
        raise CaseError("--final-version 与 --final-path 必须同时提供或同时省略")
    final_version = args.final_version.strip() or str(record.data.get("final_version", "")).strip()
    final_path = args.final_path.strip() or str(record.data.get("final_path", "")).strip()
    final_sha = ""
    if final_path:
        normalized, checked = require_final_file(record, final_path)
        final_path = normalized
        actual = sha256_file(checked)
        if not final_version:
            raise CaseError("存在 final_path 但缺少 final_version")
        if not supplied:
            expected = str(record.data.get("final_sha256", "")).strip().lower()
            if not expected or actual.lower() != expected:
                raise CaseError("Final 文件在确认后发生过修改，不能沿用旧确认归档；请重新判断版本关系并明确确认")
        final_sha = actual
    elif final_version:
        raise CaseError("存在 final_version 但缺少 final_path")
    closed = args.date or date.today().isoformat()
    if iso_date(closed) is None:
        raise CaseError(f"归档日期无效：{closed}")
    assert_case_unchanged(record)
    year = closed[:4]
    series = safe_name(str(record.data.get("series", "")), "独立事项")
    target = root / "ARCHIVE" / year / series / record.directory.name
    if target.exists():
        raise CaseError(f"归档目标已存在，拒绝覆盖：{target}")
    case_scope(root,target / "CASE.md",("ARCHIVE",))
    archived = CaseRecord(target / "CASE.md",dict(record.data),record.body,root,record.loaded_sha256)
    archived.data["status"] = "archived"
    archived.data["final_version"] = final_version
    archived.data["final_path"] = final_path
    archived.data["final_sha256"] = final_sha
    if supplied:
        archived.data["final_confirmed_at"] = closed
        archived.data["final_confirmation_note"] = args.confirmation_note.strip()
    elif final_path:
        # Closing the CASE does not replace the earlier Final confirmation.
        archived.data["final_confirmed_at"] = record.data.get("final_confirmed_at", "")
        archived.data["final_confirmation_note"] = record.data.get("final_confirmation_note", "")
    archived.data["completed"] = closed
    archived.data["archived"] = closed
    archived.data["waiting_for"] = ""
    archived.data["next_action"] = "已闭环归档"
    append_event(archived, f"- {closed}：用户确认最终完成并归档。{args.confirmation_note.strip()}")
    preflight(archived,record,'archive',artifact_dir=record.directory)
    if getattr(args,'dry_run',False):
        return preview_result(args,archived,before=record,moves=[{'from':str(record.directory),'to':str(target)}])
    with safety.file_lock(root,'case:' + str(record.data['case_id'])):
        assert_case_unchanged(record)
        safety.CURRENT.get().move(record.directory,target)
        safety.fault('archive_after_move')
        # preflight already validated old/source and full destination state before move.
        safety.atomic_write(root,archived.path,render_case(archived))
        safety.fault('archive_after_case')
        refresh_views(root)
        safety.fault('archive_after_views')
    print(json.dumps(case_view(archived), ensure_ascii=False, indent=2))
    return 0


def cmd_reopen(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    old = resolve_case(root, args.case,("ARCHIVE",))
    original = parse_case(old.path,root)
    preflight(old,original,"reopen")
    created = args.date or date.today().isoformat()
    title = args.title or f"{old.data.get('title', '历史事项')}（后续修改）"
    new = create_case(
        root, title=title, created=created, due=args.due or "",
        next_action_due=args.next_action_due or "",
        source=f"历史事项新要求：{args.reason}",
        series_id=str(old.data.get("series_id", "")),
        series=str(old.data.get("series", "")), period=args.period or "",
        priority=args.priority, next_action=args.next_action,
        previous_case_id=str(old.data.get("case_id", "")),
        reopened_from=old.relative_path, allow_related_new=True, preview=True,
    )
    old_related = str(old.data.get("related_cases", "")).strip()
    new_id = str(new.data.get("case_id", ""))
    old.data["related_cases"] = "; ".join(value for value in (old_related, new_id) if value)
    append_event(old, f"- {created}：收到后续要求“{args.reason}”，新建关联事项 {new_id}；旧 Final 保留不覆盖。")
    preflight(old,original,'reopen')
    if getattr(args,'dry_run',False):
        return preview_result(args,new,before=original,moves=[{'create_directory':str(new.directory)}],fields=['old.related_cases','old.body','new.CASE'])
    with safety.file_lock(root,'case:' + str(old.data['case_id'])):
        assert_case_unchanged(original)
        safety.mkdir(root,new.directory)
        for name in ('sources','work','deliverables'):
            safety.mkdir(root,new.directory / name)
        safety.atomic_write(root,new.path,render_case(new))
        safety.fault('reopen_after_new')
        write_case(old,operation='reopen')
        safety.fault('reopen_after_old')
        refresh_views(root)
        safety.fault('reopen_after_views')
    print(json.dumps(case_view(new), ensure_ascii=False, indent=2))
    return 0


def cmd_verify_final(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    record = resolve_case(root, args.case)
    status, actual = final_fingerprint_status(record)
    if status == "verified" and trust_resolver(record)["credibility"] == "confirmed_final":
        print(f"Final 指纹一致：{record.data.get('final_sha256')}（{record.data.get('final_path')}）")
        return 0
    if status == "mismatch":
        print(
            "WARNING: FINAL_CHANGED / HASH_MISMATCH：Final 文件在确认后发生过修改，需要重新判断版本关系。"
            f"\n登记：{record.data.get('final_sha256')}\n当前：{actual}"
        )
        return 1
    print(f"WARNING: 无法验证 Final：{status}")
    return 1


def search_case_matches(root: Path, query_value: str, limit: int = 20) -> list[dict[str, Any]]:
    """Legacy array API: incomplete diagnostics still use stderr; new consumers use json-v2."""
    result = retrieval.search(sys.modules[__name__], root, query=query_value, limit=limit)
    for issue in result['diagnostics']:
        if issue['severity'] == 'error':
            print('ERROR (isolated): ' + issue['reason'], file=sys.stderr)
    return result['items']


def cmd_search(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    structured = args.format == 'json-v2'
    filters = any((args.case_id, args.series_id, args.period, args.date))
    if not structured and (filters or args.purpose != 'inspect'):
        raise CaseError('结构化筛选和用途选择需要 --format json-v2；旧 json 保留数组契约')
    if structured:
        result = retrieval.search(sys.modules[__name__], root, query=args.query, limit=args.limit,
            case_id=args.case_id, series_id=args.series_id, period=args.period,
            date_value=args.date, date_field=args.date_field, purpose=args.purpose)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    matches = search_case_matches(root, args.query, args.limit)
    if args.format == 'json':
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0
    if not matches:
        print('本次未返回匹配 CASE；完整性请使用 search --format json-v2 查看。')
        return 0
    for view in matches:
        warning = ('\n  WARNING: ' + ' / '.join(view['alerts'])) if view['alerts'] else ''
        print(f"- [{view['credibility']}] {view['title']}（{view['case_id']}，{view['status']}）\n"
              f"  CASE: {view['case_path']}\n  默认参考（非用途选择）: {view['preferred_version'] or '无已登记版本'}{warning}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    text = retrieval.context(sys.modules[__name__], normalize_root(args.root), args.case,
        purpose=args.purpose, max_chars=args.max_chars, format_value=args.format)
    print(text, end='')
    return 0


def doctor_checks(root: Path) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []

    def add(status: str, name: str, detail: str) -> None:
        checks.append({"status": status, "name": name, "detail": detail})

    required = ("ACTIVE", "ARCHIVE", "SERIES", "KNOWLEDGE", "AGENTS.md", "office.py", ".office-workbench.json")
    for relative in required:
        target = safety.bounded(root, root / relative)
        add("PASS" if target.exists() else "FAIL", f"required:{relative}", str(target))
    for name in ("CASE.md", "SERIES.md", "KNOWLEDGE.md"):
        template = Path(__file__).resolve().parent / "templates" / name
        try:
            parse_frontmatter(template)
            add("PASS", "template:" + name, "frontmatter 可解析")
        except (CaseError, OSError) as exc:
            add("FAIL", "template:" + name, str(exc))
    errors, warnings = validate_cases(root)
    add("PASS" if not errors else "FAIL", "validate", f"{len(errors)} errors; {len(warnings)} warnings")
    views_missing_before = [
        relative for relative in ("工作看板.md", "INDEX/cases.jsonl", "INDEX/cases.md")
        if not (root / relative).is_file()
    ]
    if views_missing_before:
        add('WARN','generated views','缺少派生视图；显式 refresh/repair 才会重建：' + ', '.join(views_missing_before))
    else:
        add('PASS','generated views','派生文件存在；只读检查，不改写时间或内容')
    for journal in safety.pending(root):
        add('FAIL','pending transaction',str(journal) + '；显式 repair --recover')

    add("PASS", "core dependencies", "只需 Python 标准库；不读取全局配置，不检查账户或可选连接器")
    add("MANUAL", "AI Agent session", "请在私人目录开启会话，核实 Agent 已读取项目规则；此检查不证明登录、权限或模型理解")
    return checks


def cmd_doctor(args: argparse.Namespace) -> int:
    root = normalize_root(args.root)
    checks = doctor_checks(root)
    if args.format == "json":
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            print(f"{check['status']}: {check['name']} — {check['detail']}")
    return 1 if any(check["status"] == "FAIL" for check in checks) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="个人办公工作台 CASE 与看板工具")
    parser.add_argument("--root", help="已初始化的私人工作目录；必须显式传入")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="建立 ACTIVE 事项")
    new.add_argument("--title", required=True)
    new.add_argument("--created", help="建立日期 YYYY-MM-DD")
    new.add_argument("--due", default="")
    new.add_argument("--next-action-due", default="")
    new.add_argument("--source", required=True)
    new.add_argument("--series-id", default="")
    new.add_argument("--series", default="")
    new.add_argument("--period", default="")
    new.add_argument("--priority", choices=PRIORITY_RANK, default="normal")
    new.add_argument("--next-action", default="核实要求并开始办理")
    new.add_argument("--allow-related-new", action="store_true", help="已核实为独立事项后允许建立相似 CASE")
    new.set_defaults(func=cmd_new)

    series_new = sub.add_parser("series-new", help="建立不含本期实时状态的 SERIES.md")
    series_new.add_argument("--title", required=True)
    series_new.add_argument("--cadence", required=True)
    series_new.add_argument("--description", default="")
    series_new.add_argument("--skill", default="")
    series_new.add_argument("--created", help="建立日期 YYYY-MM-DD")
    series_new.set_defaults(func=cmd_series_new)

    dashboard = sub.add_parser("dashboard", help="即时输出工作看板")
    dashboard.add_argument("--date", help="看板日期 YYYY-MM-DD")
    dashboard.add_argument("--days", type=int, default=4, help="即将到期窗口天数")
    dashboard.add_argument("--recent-days", type=int, default=7)
    dashboard.add_argument("--format", choices=("markdown", "json"), default="markdown")
    dashboard.set_defaults(func=cmd_dashboard)

    refresh = sub.add_parser("refresh", help="从 CASE 重建根目录工作看板和 INDEX")
    refresh.set_defaults(func=cmd_refresh)

    index = sub.add_parser("index", help="重建历史索引并刷新工作看板")
    index.set_defaults(func=cmd_index)

    validate = sub.add_parser("validate", help="校验所有 CASE")
    validate.set_defaults(func=cmd_validate)

    doctor = sub.add_parser("doctor", aliases=["check"], help="检查工作台配置、生成视图和 AI Agent 集成静态条件")
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    doctor.set_defaults(func=cmd_doctor)

    update = sub.add_parser("update", help="安全地部分更新 ACTIVE CASE 的常用结构化字段")
    update.add_argument("--case", required=True, help="CASE ID 或路径")
    update.add_argument("--status", choices=sorted(UPDATE_STATUSES))
    update.add_argument("--priority", choices=PRIORITY_RANK)
    update.add_argument("--due")
    update.add_argument("--next-action-due")
    update.add_argument("--waiting-for")
    update.add_argument("--next-action")
    update.add_argument("--current-version")
    update.add_argument("--submitted-version")
    update.add_argument("--note", default="")
    update.set_defaults(func=cmd_update)

    confirm_final = sub.add_parser("confirm-final", help="在用户明确确认后登记 Final，但不归档")
    confirm_final.add_argument("--case", required=True, help="CASE ID 或路径")
    confirm_final.add_argument("--final-version", required=True, help="例如 V3")
    confirm_final.add_argument("--final-path", required=True, help="事项目录内相对路径")
    confirm_final.add_argument("--confirmation-note", required=True)
    confirm_final.add_argument("--date", help="Final 确认日期 YYYY-MM-DD")
    confirm_final.add_argument("--confirm", action="store_true")
    confirm_final.set_defaults(func=cmd_confirm_final)

    archive = sub.add_parser("archive", help="在用户明确确认闭环后归档事项")
    archive.add_argument("--case", required=True, help="CASE ID 或路径")
    archive.add_argument("--final-version", default="", help="例如 V3；与 --final-path 同时提供")
    archive.add_argument("--final-path", default="", help="事项目录内相对路径")
    archive.add_argument("--confirmation-note", required=True)
    archive.add_argument("--date", help="完成与归档日期 YYYY-MM-DD")
    archive.add_argument("--confirm", action="store_true")
    archive.set_defaults(func=cmd_archive)

    reopen = sub.add_parser("reopen", help="为历史事项建立关联后续 CASE")
    reopen.add_argument("--case", required=True, help="旧 CASE ID 或路径")
    reopen.add_argument("--reason", required=True)
    reopen.add_argument("--title")
    reopen.add_argument("--date", help="新事项建立日期 YYYY-MM-DD")
    reopen.add_argument("--due", default="")
    reopen.add_argument("--next-action-due", default="")
    reopen.add_argument("--period", default="")
    reopen.add_argument("--priority", choices=PRIORITY_RANK, default="normal")
    reopen.add_argument("--next-action", default="根据新增要求制作新版本")
    reopen.set_defaults(func=cmd_reopen)

    verify_final = sub.add_parser("verify-final", help="核对已确认 Final 的 SHA256")
    verify_final.add_argument("--case", required=True, help="CASE ID 或路径")
    verify_final.set_defaults(func=cmd_verify_final)

    search = sub.add_parser("search", help="检索 CASE 元数据、正文和可信版本导航")
    search.add_argument("--query", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--format", choices=("text", "json", "json-v2"), default="text")
    search.add_argument('--case-id', default='')
    search.add_argument('--series-id', default='')
    search.add_argument('--period', default='', help='period 字段严格相等，不从正文日期推断')
    search.add_argument('--date', default='', help='指定 date-field 字段严格等于 YYYY-MM-DD')
    search.add_argument('--date-field', choices=retrieval.DATE_FILTER_FIELDS, default='created')
    search.add_argument('--purpose', choices=retrieval.PURPOSES, default='inspect')
    search.set_defaults(func=cmd_search)
    context = sub.add_parser('context', help='已唯一定位 CASE 的只读上下文快照')
    context.add_argument('--case', required=True)
    context.add_argument('--purpose', choices=retrieval.PURPOSES, default='inspect')
    context.add_argument('--format', choices=('json','md'), default='json')
    context.add_argument('--max-chars', type=int, default=12000)
    context.add_argument('--save', help='显式保存简单文件名到私人工作目录内 DERIVED/task-context；拒绝覆盖')
    context.set_defaults(func=cmd_context)
    repair = sub.add_parser('repair',help='显式修复派生视图或恢复中断事务')
    repair.add_argument('--recover',action='store_true',help='恢复待处理事务，然后刷新视图')
    repair.set_defaults(func=cmd_repair)
    for command in (new,series_new,update,confirm_final,archive,reopen,refresh,index,repair):
        command.add_argument('--dry-run',action='store_true',help='只读预检和变更预览')
    return parser


def cmd_repair(args):
    root = normalize_root(args.root)
    if args.recover:
        if args.dry_run:
            print(json.dumps({'dry_run':True,'recovery':safety.recover(root,True),'refresh_views':True},ensure_ascii=False,indent=2))
            return 0
        safety.recover(root)
    return cmd_refresh(args)


def read_stamp(root):
    """Read only: detect a writer even if its journal appeared and disappeared."""
    folder = safety.bounded(root, root / '.caseboard' / 'transactions')
    return folder.stat().st_mtime_ns if folder.exists() else None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = normalize_root(args.root)
        writing = args.command in ('new','series-new','update','confirm-final','archive','reopen','refresh','index') and not getattr(args,'dry_run',False)
        if not writing and args.command not in ('repair','check','doctor','validate'):
            safety.ensure_no_pending(root)
        stamp = read_stamp(root)
        # Do not publish successful output until all writes and the commit complete.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with safety.transaction(root) if writing else nullcontext():
                code = int(args.func(args))
        if not writing and args.command not in ('repair','check','doctor','validate'):
            safety.ensure_no_pending(root)
            if stamp != read_stamp(root):
                raise CaseError('读取期间发生生命周期写入，结果已丢弃；请重新运行只读命令')
        if args.command == 'context' and args.save:
            retrieval.save_context(sys.modules[__name__], root, args.save, args.format, output.getvalue())
        print(output.getvalue(),end='')
        return code
    except (safety.SafetyError,OSError,UnicodeError,ValueError) as exc:
        if getattr(args,'dry_run',False):
            print(json.dumps({'dry_run':True,'case':getattr(args,'case',None),
                              'target_status':getattr(args,'status',None),'refresh_views':args.command != 'series-new',
                              'risks':[str(exc)],'validation':{'errors':[str(exc)],'warnings':[]}},ensure_ascii=False,indent=2))
        print(f'ERROR: {exc}',file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
