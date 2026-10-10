# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from routing_receipt import (
    ReceiptError,
    canonical_json,
    load_receipt_contract,
    posix_rel,
    request_sha256,
    sha256_file,
    validate_turn_dir,
)

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = ROOT / ".agent-project-control"
ACTIVITY_SCHEMA = 1
EXIT_INVALID = 2
EXIT_NOT_INITIALIZED = 3


class ActivityError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


def load_audit_contract() -> dict:
    contract = load_receipt_contract()
    audit = contract.get("audit")
    if not isinstance(audit, dict) or audit.get("schema") != ACTIVITY_SCHEMA:
        raise ActivityError("audit contract is missing or unsupported in routing.toml")
    for key in ("baseline_relpath", "events_relpath", "report_relpath"):
        value = audit.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ActivityError(f"audit.{key} is missing")
    return contract


def evidence_path(turn_dir: Path, relpath: str) -> Path:
    path = (turn_dir / relpath).resolve(strict=False)
    evidence = (turn_dir / "evidence").resolve()
    try:
        path.relative_to(evidence)
    except ValueError as exc:
        raise ActivityError(f"audit evidence path escapes current TR evidence/: {relpath}") from exc
    if path.parent != evidence:
        raise ActivityError(f"audit evidence file must live directly under current TR evidence/: {relpath}")
    return path


def audit_paths(turn_dir: Path, contract: dict) -> tuple[Path, Path, Path]:
    audit = contract["audit"]
    return (
        evidence_path(turn_dir, audit["baseline_relpath"]),
        evidence_path(turn_dir, audit["events_relpath"]),
        evidence_path(turn_dir, audit["report_relpath"]),
    )


def _run_git(*args: str, binary: bool = False) -> bytes | str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=not binary,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace") if binary else proc.stderr
        raise ActivityError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return proc.stdout


def _own_git() -> bool:
    try:
        probe=subprocess.run(['git','-C',str(ROOT),'rev-parse','--show-toplevel'],capture_output=True,text=True)
        return probe.returncode==0 and Path(probe.stdout.strip()).resolve()==ROOT.resolve()
    except OSError:return False


def git_head() -> str:
    if not _own_git():return 'NO_PROJECT_GIT'
    value=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],capture_output=True,text=True)
    return value.stdout.strip() if value.returncode==0 else 'UNBORN_PROJECT_GIT'



def _nul_paths(*args: str) -> set[str]:
    data = _run_git(*args, binary=True)
    assert isinstance(data, bytes)
    out: set[str] = set()
    for raw in data.split(b"\0"):
        if not raw:
            continue
        out.add(raw.decode("utf-8", "surrogateescape").replace("\\", "/"))
    return out


def current_dirty_paths() -> set[str]:
    if not _own_git():
        paths=set()
        for folder,dirs,files in os.walk(ROOT):
            here=Path(folder)
            dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','__pycache__'} and not (here/d).is_symlink()
                     and not (here/d).resolve().is_relative_to((FRAMEWORK_ROOT/'runtime').resolve())]
            paths.update((here/f).relative_to(ROOT).as_posix() for f in files)
        return paths
    # These three commands deliberately observe Git state rather than infer it from
    # filenames. Union is recall-first and handles unstaged, staged and untracked files.
    return (
        _nul_paths("diff", "--name-only", "-z")
        | _nul_paths("diff", "--cached", "--name-only", "-z")
        | _nul_paths("ls-files", "--others", "--exclude-standard", "-z")
    )


def file_state(rel: str) -> dict[str, str]:
    path = (ROOT / rel).resolve(strict=False)
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ActivityError(f"activity path escapes repository: {rel}") from exc
    if path.is_symlink():
        target = os.readlink(path)
        digest = hashlib.sha256(target.encode("utf-8", "surrogateescape")).hexdigest()
        return {"path": rel, "state": "symlink", "sha256": digest}
    if path.is_file():
        return {"path": rel, "state": "file", "sha256": sha256_file(path)}
    if path.is_dir():
        return {"path": rel, "state": "directory", "sha256": ""}
    return {"path": rel, "state": "missing", "sha256": ""}


def snapshot_rows(paths: Iterable[str]) -> list[dict[str, str]]:
    return [file_state(p) for p in sorted(set(paths))]


def tr_file_hashes(turn_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("REQUEST.md", "CHECKLIST.md", "TEST.md", "TURN.md"):
        path = turn_dir / name
        if not path.is_file():
            raise ActivityError(f"Turn file missing during activity snapshot: {name}")
        result[name] = sha256_file(path)
    return result


def parallel_units(turn_dir: Path) -> list[str]:
    p = turn_dir / "parallel"
    if not p.is_dir():
        return []
    return sorted(
        child.name
        for child in p.iterdir()
        if child.is_dir() and child.name.startswith("PA-")
    )


def _write_atomic(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, mode)
    try:
        total = 0
        while total < len(payload):
            written = os.write(fd, payload[total:])
            if written <= 0:
                raise ActivityError(f"short write while creating {path.name}")
            total += written
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def init_baseline(turn_dir_raw: str | Path) -> tuple[Path, dict]:
    contract = load_audit_contract()
    turn_dir = validate_turn_dir(turn_dir_raw)
    baseline_path, events_path, report_path = audit_paths(turn_dir, contract)
    if baseline_path.exists():
        raise ActivityError("activity baseline already exists; baseline is immutable")
    if events_path.exists() or report_path.exists():
        raise ActivityError("cannot create baseline after activity/audit evidence already exists")

    dirty = current_dirty_paths()
    record = {
        "schema": ACTIVITY_SCHEMA,
        "turn": posix_rel(turn_dir),
        "request_sha256": request_sha256(turn_dir),
        "git_head": git_head(),
        "dirty_rows": snapshot_rows(dirty),
        "turn_files": tr_file_hashes(turn_dir),
        "parallel_units": parallel_units(turn_dir),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _write_atomic(baseline_path, canonical_json(record) + b"\n")
    return baseline_path, record


def load_baseline(turn_dir: Path, contract: dict) -> dict:
    baseline_path, _, _ = audit_paths(turn_dir, contract)
    if not baseline_path.is_file():
        raise ActivityError(
            "activity baseline is missing; do not create it retroactively after work has started",
            EXIT_NOT_INITIALIZED,
        )
    try:
        record = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ActivityError("activity baseline is invalid JSON") from exc
    if not isinstance(record, dict) or record.get("schema") != ACTIVITY_SCHEMA:
        raise ActivityError("activity baseline schema mismatch")
    if record.get("turn") != posix_rel(turn_dir):
        raise ActivityError("activity baseline belongs to a different Turn")
    if record.get("request_sha256") != request_sha256(turn_dir):
        raise ActivityError("Turn REQUEST.md changed since activity baseline")
    return record


def _validate_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ActivityError(f"{path.name} exists but is not a file")
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ActivityError(f"{path.name} has a partial final line")
    rows: list[dict] = []
    for lineno, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            raise ActivityError(f"{path.name} has blank line {lineno}")
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActivityError(f"{path.name} is invalid at line {lineno}") from exc
        if not isinstance(row, dict) or row.get("schema") != ACTIVITY_SCHEMA:
            raise ActivityError(f"{path.name} has unsupported record at line {lineno}")
        rows.append(row)
    return rows


def _append_jsonl(path: Path, record: dict) -> None:
    _validate_jsonl(path)
    payload = canonical_json(record) + b"\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        total = 0
        while total < len(payload):
            written = os.write(fd, payload[total:])
            if written <= 0:
                raise ActivityError(f"short write while appending {path.name}")
            total += written
        os.fsync(fd)
    finally:
        os.close(fd)


def record_event(turn_dir_raw: str | Path, kind: str, detail: str | None = None) -> tuple[Path, dict]:
    contract = load_audit_contract()
    turn_dir = validate_turn_dir(turn_dir_raw)
    baseline = load_baseline(turn_dir, contract)
    _, events_path, _ = audit_paths(turn_dir, contract)
    events = contract["audit"].get("events", {})
    spec = events.get(kind)
    if not isinstance(spec, dict):
        raise ActivityError(f"unknown activity event kind: {kind}", EXIT_NOT_INITIALIZED)
    unsigned = {
        "schema": ACTIVITY_SCHEMA,
        "turn": posix_rel(turn_dir),
        "kind": kind,
        "phases": list(spec.get("phases", [])),
        "capabilities": list(spec.get("capabilities", [])),
        "detail": detail,
        "baseline_created_at": baseline["created_at"],
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    digest = hashlib.sha256(canonical_json(unsigned) + str(time.time_ns()).encode("ascii")).hexdigest()[:16]
    record = {"event_id": f"AE-{digest}", **unsigned}
    _append_jsonl(events_path, record)
    return events_path, record


def load_events(turn_dir: Path, contract: dict, baseline: dict) -> list[dict]:
    _, events_path, _ = audit_paths(turn_dir, contract)
    rows = _validate_jsonl(events_path)
    out: list[dict] = []
    for i, row in enumerate(rows):
        if row.get("turn") != posix_rel(turn_dir):
            raise ActivityError(f"activity event[{i}] belongs to a different Turn")
        if row.get("baseline_created_at") != baseline.get("created_at"):
            raise ActivityError(f"activity event[{i}] belongs to a different baseline")
        kind = row.get("kind")
        spec = contract["audit"].get("events", {}).get(kind)
        if not isinstance(spec, dict):
            raise ActivityError(f"activity event[{i}] has unknown kind: {kind}")
        # Event meaning is contract-owned. Callers may choose the event kind, but
        # cannot invent weaker phases/capabilities inside the JSONL.
        if row.get("phases") != list(spec.get("phases", [])):
            raise ActivityError(f"activity event[{i}] phase requirements drifted from routing.toml")
        if row.get("capabilities") != list(spec.get("capabilities", [])):
            raise ActivityError(f"activity event[{i}] capability requirements drifted from routing.toml")
        out.append(row)
    return out


def _committed_paths_between(old_head: str, new_head: str) -> set[str]:
    if old_head == new_head:
        return set()
    if old_head in {'NO_PROJECT_GIT','UNBORN_PROJECT_GIT'} or new_head in {'NO_PROJECT_GIT','UNBORN_PROJECT_GIT'}:
        raise ActivityError('version-control identity changed mid-Turn; start/rebase a real request boundary, not a fabricated commit')
    try:
        return _nul_paths("diff", "--name-only", "-z", old_head, new_head)
    except ActivityError:
        # HEAD movement itself is still observable and will require delivery;
        # inability to enumerate paths is not silently ignored.
        raise ActivityError("Git HEAD changed but committed path delta could not be enumerated")


def collect_activity(turn_dir_raw: str | Path) -> dict:
    contract = load_audit_contract()
    turn_dir = validate_turn_dir(turn_dir_raw)
    baseline = load_baseline(turn_dir, contract)

    baseline_rows = {
        row["path"]: row
        for row in baseline.get("dirty_rows", [])
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    current_dirty = current_dirty_paths()
    candidates = set(current_dirty) | set(baseline_rows)

    changed_since_baseline: set[str] = set()
    for rel in candidates:
        current = file_state(rel)
        if rel not in baseline_rows:
            # Path was clean/not present in the baseline dirty set and is dirty now.
            if rel in current_dirty:
                changed_since_baseline.add(rel)
            continue
        if current != baseline_rows[rel]:
            changed_since_baseline.add(rel)

    current_head = git_head()
    committed = _committed_paths_between(str(baseline["git_head"]), current_head)
    changed_since_baseline |= committed

    current_turn_files = tr_file_hashes(turn_dir)
    turn_file_changes = sorted(
        name
        for name, old_hash in baseline.get("turn_files", {}).items()
        if current_turn_files.get(name) != old_hash
    )

    current_parallel = set(parallel_units(turn_dir))
    baseline_parallel = set(baseline.get("parallel_units", []))
    new_parallel = sorted(current_parallel - baseline_parallel)

    events = load_events(turn_dir, contract, baseline)

    return {
        "baseline": baseline,
        "current_git_head": current_head,
        "git_head_changed": current_head != baseline.get("git_head"),
        "changed_paths": sorted(changed_since_baseline),
        "turn_file_changes": turn_file_changes,
        "new_parallel_units": new_parallel,
        "events": events,
    }


def _private_json(path: Path, value: dict) -> None:
    """Write owned evidence atomically, with visibility and a matching digest."""
    payload = canonical_json(value) + b"\n"
    _write_atomic(path, payload)
    sidecar = path.with_name(path.name + '.apcf-meta.yaml')
    _write_atomic(sidecar, ('# APCF-META {"schema":1,"visibility":"private"}\n'
                          'schema: 1\nvisibility: private\nsha256: '
                          + hashlib.sha256(payload).hexdigest() + '\n').encode('utf-8'))


def _contract_digest(turn_dir: Path) -> str:
    """Bind requirements, not mutable progress/status/evidence columns."""
    from test_ledger import parse_checklist, parse_tests
    checklist = parse_checklist((turn_dir / 'CHECKLIST.md').read_text(encoding='utf-8'))
    tests = parse_tests((turn_dir / 'TEST.md').read_text(encoding='utf-8'))
    value = {'checklist': [{k: row[k] for k in ('id', 'object', 'body')} for row in checklist],
             'tests': [{k: row[k] for k in ('id', 'refs', 'object', 'context', 'action', 'expected')}
                       for row in tests]}
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _relative_target(raw: str) -> str:
    from repair_io import inside
    candidate=Path(raw)
    if candidate.is_absolute():
        try:raw=candidate.relative_to(ROOT).as_posix()
        except ValueError as exc:raise ActivityError('target outside project') from exc
    try:return inside(ROOT,raw).relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:raise ActivityError(str(exc)) from exc


def _reference(turn_dir: Path, raw: str) -> dict:
    from repair_io import inside
    try:path=inside(turn_dir,raw,must_exist=True)
    except ValueError as exc:raise ActivityError(str(exc)) from exc
    if not path.is_relative_to((turn_dir/'evidence').resolve()) or not path.is_file():
        raise ActivityError('review/investigation must reference an existing current-Turn evidence file')
    if path.stat().st_size==0:raise ActivityError('empty evidence cannot establish an investigation or review')
    return {'path':path.relative_to(turn_dir.resolve()).as_posix(),'sha256':sha256_file(path)}


def _reference_errors(turn_dir: Path, rows: object) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return ['actual supporting evidence is missing']
    errors = []
    for row in rows:
        try:
            if not isinstance(row, dict) or _reference(turn_dir, row['path']) != row:
                errors.append('supporting evidence is stale or has a digest mismatch')
        except (ActivityError, KeyError, TypeError, OSError):
            errors.append('supporting evidence is unavailable or outside this Turn')
    return errors


def managed_targets(turn_dir: Path) -> list[str]:
    """Reuse the post-route classifier so target ownership does not drift."""
    from audit_routes import classify_activity
    activity = collect_activity(turn_dir)
    return classify_activity(turn_dir, load_audit_contract(), activity)['target_paths']


def record_plan(turn_dir_raw, targets, investigation_paths, regression_tests, post_delivery_tests=None) -> dict:
    """Record an existing investigation and planned checks inside this TR's evidence."""
    from test_ledger import parse_checklist, parse_tests, validate_file
    turn_dir = validate_turn_dir(turn_dir_raw)
    errors = validate_file(turn_dir / 'TEST.md', turn_dir / 'CHECKLIST.md')
    if errors:
        raise ActivityError('plan requires valid Checklist/TEST: ' + '; '.join(errors))
    baseline = load_baseline(turn_dir, load_audit_contract())
    current_test_text = (turn_dir / 'TEST.md').read_text(encoding='utf-8')
    if 'APCF-TEST-FORMAT v3' in current_test_text:
        from execution_session import load as load_session
        load_session(turn_dir)
        from repair_io import digest, canonical, private_json, lock
        plan_path=turn_dir/'evidence/workflow.json'
        actual_targets=set(managed_targets(turn_dir))
        if not plan_path.exists() and actual_targets:
            raise ActivityError('first plan is after business changes; cannot retroactively authorize: '+', '.join(sorted(actual_targets)))
        if plan_path.exists():
            old=json.loads(plan_path.read_text())
            if old.get('contract_digest') != _contract_digest(turn_dir):
                # A maintained amendment artifact makes scope changes explicit instead of silently overwriting goals.
                amendment=turn_dir/'evidence/goal-amendment.json'
                try:
                    change=json.loads(amendment.read_text())
                    if (change.get('previous_digest')!=old.get('contract_digest') or
                        change.get('current_digest')!=_contract_digest(turn_dir) or not change.get('reason')):
                        raise ValueError('amendment source/target mismatch')
                except (OSError,ValueError,AttributeError) as exc:
                    raise ActivityError('goal change requires explicit current amendment: '+str(exc))
                unplanned=actual_targets-set(old.get('targets',[]))
                if unplanned: raise ActivityError('new targets changed before amendment: '+', '.join(sorted(unplanned)))
    rows = parse_tests(current_test_text)
    ids = {r['id'] for r in rows}
    if not regression_tests or not set(regression_tests) <= ids:
        raise ActivityError('plan regression checks must refer to current TEST IDs')
    deferred = list(post_delivery_tests or [])
    if (not set(deferred) <= ids or any(not r['context'].startswith('delivery-postcondition:')
            for r in rows if r['id'] in deferred)):
        raise ActivityError('post-delivery checks need explicit delivery-postcondition contexts in TEST.md')
    record = {'schema': 1, 'turn': posix_rel(turn_dir),
              'request_sha256': baseline['request_sha256'],
              'baseline_created_at': baseline['created_at'],
              'contract_digest': _contract_digest(turn_dir),
              'investigation': [_reference(turn_dir, p) for p in investigation_paths],
              'targets': sorted({_relative_target(p) for p in targets}),
              'tests': [r['id'] for r in rows], 'regression_tests': list(regression_tests),
              'post_delivery_tests': deferred}
    if not record['investigation']:
        raise ActivityError('plan needs actual investigation evidence')
    if 'APCF-TEST-FORMAT v3' in current_test_text:
        from repair_io import lock, private_json
        with lock(FRAMEWORK_ROOT/'runtime/tmp/.plan.lock'):
            seq=len(list((turn_dir/'evidence').glob('plan-revision-*.json')))+1
            record['sequence']=seq
            record['sealed_at']=datetime.now().astimezone().isoformat()
            record['target_preimages']=snapshot_rows(record['targets'])
            record['goal_snapshot']=[{k:r[k] for k in ('id','object','body')} for r in parse_checklist((turn_dir/'CHECKLIST.md').read_text(encoding='utf-8'))]
            private_json(turn_dir/'evidence'/f'plan-revision-{seq:06d}.json',record,create=True)
            _private_json(turn_dir / 'evidence/workflow.json', record)
    else:
        _private_json(turn_dir / 'evidence/workflow.json', record)
    return record


def workflow_errors(turn_dir: Path, targets=None) -> list[str]:
    from test_ledger import parse_tests, validate_file
    errors = validate_file(turn_dir / 'TEST.md', turn_dir / 'CHECKLIST.md')
    current_text=(turn_dir/'TEST.md').read_text(encoding='utf-8')
    session=turn_dir/'evidence/execution-session.json'
    if session.exists() or 'APCF-TEST-FORMAT v3' in current_text:
        try:
            from execution_session import load as load_session
            load_session(turn_dir)
            if 'APCF-TEST-FORMAT v3' not in current_text:
                raise ValueError('current session cannot downgrade to the legacy ledger')
        except (OSError,ValueError) as exc: errors.append('request/session guard: '+str(exc))
    path = turn_dir / 'evidence/workflow.json'
    try:
        row = json.loads(path.read_text(encoding='utf-8'))
        baseline = load_baseline(turn_dir, load_audit_contract())
        if (row.get('schema') != 1 or row.get('turn') != posix_rel(turn_dir)
                or row.get('request_sha256') != baseline['request_sha256']
                or row.get('baseline_created_at') != baseline['created_at']):
            errors.append('investigation/plan belongs to another Turn or baseline')
        if row.get('contract_digest') != _contract_digest(turn_dir):
            errors.append('scope/acceptance changed: update the investigation and plan')
        errors.extend(_reference_errors(turn_dir, row.get('investigation')))
        planned = row.get('targets')
        if not isinstance(planned, list) or any(not isinstance(p, str) for p in planned):
            errors.append('plan target list is invalid')
            planned = []
        else:
            for p in planned:
                if _relative_target(p) != p:
                    errors.append('plan target is not a canonical repository-relative path')
        needed = managed_targets(turn_dir) + [_relative_target(p) for p in (targets or [])]
        missing = sorted(set(needed) - set(planned))
        if missing:
            errors.append('changed/action targets absent from investigation/plan: ' + ', '.join(missing))
        ids = {r['id'] for r in parse_tests((turn_dir / 'TEST.md').read_text(encoding='utf-8'))}
        if set(row.get('tests', [])) != ids:
            errors.append('plan does not cover all current TEST IDs')
        if not row.get('regression_tests') or not set(row['regression_tests']) <= ids:
            errors.append('plan has no current regression verification scope')
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, KeyError, TypeError, ActivityError) as exc:
        errors.append('investigation/plan evidence missing or invalid: ' + str(exc))
    return errors


def record_semantic_review(turn_dir_raw, observations: dict, evidence_paths: list,
                           phases=None, capabilities=None) -> dict:
    """Bind the caller's concrete review to each current target and its source evidence."""
    turn_dir = validate_turn_dir(turn_dir_raw)
    rows = []
    for raw, note in observations.items():
        rel = _relative_target(raw)
        if not isinstance(note, str) or not note.strip():
            raise ActivityError('semantic review must include an object-specific conclusion')
        rows.append({**file_state(rel), 'basis': note,
                     'evidence': [_reference(turn_dir, p) for p in evidence_paths],
                     'phases': list(phases or []), 'capabilities': list(capabilities or [])})
    record = {'schema': 1, 'turn': posix_rel(turn_dir), 'targets': rows}
    _private_json(turn_dir / 'evidence/semantic-review.json', record)
    return record


def semantic_review(turn_dir: Path, targets: list[str]) -> tuple[list[str], list[str], list[str]]:
    errors, phases, caps = [], set(), set()
    if not targets:
        return errors, [], []
    try:
        record = json.loads((turn_dir / 'evidence/semantic-review.json').read_text(encoding='utf-8'))
        if record.get('schema') != 1 or record.get('turn') != posix_rel(turn_dir):
            raise ActivityError('semantic review belongs to another Turn')
        rows = record['targets']
        if not isinstance(rows, list) or len({r['path'] for r in rows}) != len(rows):
            raise ActivityError('semantic review targets duplicated or invalid')
        by_path = {r['path']: r for r in rows}
        for target in targets:
            row = by_path.get(target, {})
            state = file_state(target)
            if any(row.get(k) != v for k, v in state.items()):
                errors.append(target + ': semantic review absent or candidate changed')
                continue
            if not isinstance(row.get('basis'), str) or not row['basis'].strip():
                errors.append(target + ': concrete semantic review basis missing')
            errors.extend(target + ': ' + e for e in _reference_errors(turn_dir, row.get('evidence')))
            for name, output in [('phases', phases), ('capabilities', caps)]:
                values = row.get(name)
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                    errors.append(target + ': semantic declarations invalid')
                else:
                    output.update(values)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ActivityError) as exc:
        errors.append('semantic review evidence missing or invalid: ' + str(exc))
    return errors, sorted(phases), sorted(caps)


def evidence_snapshot(turn_dir: Path) -> dict:
    names = ('workflow.json', 'semantic-review.json', 'content-review.json', 'checks.jsonl', 'prose-review.json', 'execution-session.json')
    snapshot = {name: sha256_file(turn_dir / 'evidence' / name)
                for name in names if (turn_dir / 'evidence' / name).is_file()}
    review_path = turn_dir / 'evidence/content-review.json'
    if review_path.is_file():
        try:
            record = json.loads(review_path.read_text(encoding='utf-8'))
            for row in record.get('targets', []):
                rel = row.get('terms_review_path') if isinstance(row, dict) else None
                if not isinstance(rel, str) or not rel.strip():
                    continue
                path = (turn_dir / rel).resolve()
                if path.is_relative_to((turn_dir / 'evidence').resolve()) and path.is_file():
                    key = 'terms-review:' + path.relative_to(turn_dir).as_posix()
                    snapshot[key] = sha256_file(path)
                    sidecar = path.with_name(path.name + '.apcf-meta.yaml')
                    if sidecar.is_file():
                        snapshot[key + '.apcf-meta.yaml'] = sha256_file(sidecar)
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError):
            # The content-review validator will report malformed evidence; the
            # snapshot remains deterministic for the same malformed bytes.
            pass
    return snapshot


def _final_user_report(turn_dir: Path, target: str) -> str | None:
    """Return a complete current TURN USER REPORT, if this target is that report."""
    if (ROOT / target).resolve() != (turn_dir / 'TURN.md').resolve():
        return None
    from terminology_review import USER_REPORT_RE, extract_user_report, read_report_text
    payload = read_report_text(ROOT / target)
    markers = list(USER_REPORT_RE.finditer(payload))
    if not markers:
        return None
    if len(markers) == 1 and payload[markers[0].end():].strip() == '尚未收口':
        return None
    return extract_user_report(payload)


def _terms_review_path(turn_dir: Path, raw: str) -> Path:
    path = (turn_dir / raw).resolve()
    if not path.is_relative_to((turn_dir / 'evidence').resolve()):
        raise ActivityError('terminology review must live inside current-Turn evidence/')
    return path


def record_content_review(turn_dir_raw, target: str, capabilities: list[str],
                          evidence_paths: list[str], observations: list[dict], result='PASS',
                          method='agent-review', terms_review_path: str | None = None) -> dict:
    """Save a finite content review; concrete positions and evidence remain inspectable."""
    turn_dir = validate_turn_dir(turn_dir_raw)
    rel = _relative_target(target)
    if method not in {'agent-review','author_self_review','deterministic-check','deterministic-fixture-review'}:
        raise ActivityError('local API cannot authenticate a caller-declared human or independent reviewer')
    if result not in {'PASS', 'FAIL', 'NOT_APPLICABLE'} or not observations:
        raise ActivityError('content review requires a result and concrete observations')
    terminology_review_ref = None
    try:
        report = _final_user_report(turn_dir, rel)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ActivityError('final USER REPORT cannot be reviewed: ' + str(exc)) from exc
    if report is not None:
        if 'APCF-FACTS ' in report and result=='PASS':
            from prose_review import validate_review_file
            defects=validate_review_file(report,turn_dir)
            if defects: raise ActivityError('; '.join(defects))
        review_rel = terms_review_path or 'evidence/terms-review.json'
        review_path = _terms_review_path(turn_dir, review_rel)
        if not review_path.is_file():
            if result == 'PASS':
                raise ActivityError('final USER REPORT PASS requires evidence/terms-review.json or an explicit terms_review_path')
        else:
            try:
                review = json.loads(review_path.read_text(encoding='utf-8'))
                from terminology_review import private_sidecar_errors, validate as validate_terminology_review, write_private_sidecar
                issues = validate_terminology_review(report, review, turn_dir=turn_dir)
                if issues and result == 'PASS':
                    raise ActivityError('final USER REPORT terminology review is incomplete: ' + '; '.join(issues))
                write_private_sidecar(review_path)
                sidecar_errors = private_sidecar_errors(review_path)
                if sidecar_errors:
                    raise ActivityError('final USER REPORT terminology metadata is invalid: ' + '; '.join(sidecar_errors))
                terminology_review_ref = _reference(turn_dir, review_rel)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                if isinstance(exc, ActivityError):
                    raise
                raise ActivityError('final USER REPORT terminology review is invalid: ' + str(exc)) from exc
    norms = {}
    from route_context import build_route, load_contract
    from argparse import Namespace
    sources, _, resolved_caps, _ = build_route(Namespace(phase=[], capability=capabilities, target=[], scope=None), load_contract())
    for source in sources:
        norms[posix_rel(source.path)] = sha256_file(source.path)
    references = [_reference(turn_dir, p) for p in evidence_paths]
    if terminology_review_ref and not any(ref.get('path') == terminology_review_ref['path'] for ref in references):
        references.append(terminology_review_ref)
    row = {**file_state(rel), 'capabilities': resolved_caps, 'norms': norms,
           'method': method, 'result': result, 'observations': observations,
           'evidence': references}
    if terminology_review_ref:
        row['terms_review_path'] = terminology_review_ref['path']
    if (ROOT / rel).resolve() == (turn_dir / 'TURN.md').resolve():
        row['normalized_turn_sha256'] = normalized_turn_sha256((ROOT / rel).read_bytes())
    path = turn_dir / 'evidence/content-review.json'
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema': 1, 'turn': posix_rel(turn_dir), 'targets': []}
    record['targets'] = [r for r in record['targets'] if r['path'] != rel] + [row]
    _private_json(path, record)
    return row


def normalized_turn_sha256(payload: bytes) -> str:
    """Normalize exactly the controlled status field, retaining every other byte."""
    lines = payload.decode('utf-8').splitlines(keepends=True)
    count = 0
    result = []
    for line in lines:
        value = line.rstrip('\r\n')
        if value in {'- **Status**：IN_PROGRESS', '- **Status**：FINALIZED'}:
            count += 1
            ending = line[len(value):]
            line = '- **Status**：<FINALIZE_STATUS>' + ending
        result.append(line)
    if count != 1:
        raise ActivityError('TURN must have exactly one recognized lifecycle status')
    return hashlib.sha256(''.join(result).encode('utf-8')).hexdigest()


def _controlled_finalization_review(turn_dir: Path, target: str, row: dict) -> bool:
    if (ROOT / target).resolve() != (turn_dir / 'TURN.md').resolve():
        return False
    try:
        journal = json.loads((turn_dir / 'evidence/finalize-transaction.json').read_text(encoding='utf-8'))
        before, after = journal['preimage'], journal['postimage']
        gate = journal['gate_attempt']
        from gate_kernel import gate_paths, load_gate_contract, load_history
        attempts, _ = gate_paths(turn_dir, load_gate_contract())
        history = load_history(attempts, posix_rel(turn_dir))
        approved = next((r for r in history if r['attempt_id'] == gate['attempt_id']), {})
        payload = (ROOT / target).read_bytes()
        current = ROOT / 'CURRENT.md'
        current_text = current.read_text(encoding='utf-8')
        source = re.search(r'^- \*\*Source TURN\*\*：`([^`]+)`', current_text, re.MULTILINE)
        turn_report = payload.decode('utf-8').split('## 1.1. USER REPORT', 1)[1].strip()
        current_report = current_text.split('## 1.1. 最新完整用户报告', 1)[1].strip()
        digest = normalized_turn_sha256(payload)
        return (journal.get('schema') == 1 and journal.get('turn') == posix_rel(turn_dir)
                and journal.get('result') == 'COMMITTED' and gate.get('result') == 'PASS'
                and approved.get('result') == 'PASS' and approved.get('attempt_hash') == gate.get('attempt_hash')
                and approved.get('candidate_fingerprint') == gate.get('candidate_fingerprint')
                and before['turn_sha256'] == row.get('sha256')
                and after['turn_sha256'] == hashlib.sha256(payload).hexdigest()
                and after['current_sha256'] == sha256_file(current)
                and before['normalized_turn_sha256'] == after['normalized_turn_sha256'] == row.get('normalized_turn_sha256') == digest
                and before['report_sha256'] == after['report_sha256'] == hashlib.sha256(turn_report.encode('utf-8')).hexdigest()
                and source is not None and source.group(1) == posix_rel(turn_dir)
                and turn_report == current_report)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, ActivityError, Exception):
        return False


def content_review_errors(turn_dir: Path, target: str, capabilities: list[str]) -> list[str]:
    errors = []
    try:
        record = json.loads((turn_dir / 'evidence/content-review.json').read_text(encoding='utf-8'))
        if record.get('schema') != 1 or record.get('turn') != posix_rel(turn_dir):
            raise ActivityError('content review belongs to another Turn')
        matches = [r for r in record['targets'] if r.get('path') == target]
        if len(matches) != 1:
            raise ActivityError('one current review per target is required')
        row = matches[0]
        if any(row.get(k) != v for k, v in file_state(target).items()) and not _controlled_finalization_review(turn_dir, target, row):
            errors.append('content review candidate SHA is stale')
        if row.get('result') != 'PASS':
            errors.append('content review has not passed')
        if row.get('method') not in {'agent-review','author_self_review','deterministic-check','deterministic-fixture-review'}:
            errors.append('reviewer method is not authenticated by this local interface')
        if not set(capabilities) <= set(row.get('capabilities', [])):
            errors.append('content review omits an applicable capability')
        from route_context import build_route, load_contract
        from argparse import Namespace
        sources, _, _, _ = build_route(Namespace(phase=[], capability=capabilities, target=[], scope=None), load_contract())
        for source in sources:
            if row.get('norms', {}).get(posix_rel(source.path)) != sha256_file(source.path):
                errors.append('content review normative source changed: ' + posix_rel(source.path))
        observations = row.get('observations')
        if not isinstance(observations, list) or not observations:
            errors.append('content review has no located observations')
        else:
            lines = (ROOT / target).read_text(encoding='utf-8').splitlines()
            for obs in observations:
                if (not isinstance(obs, dict) or not isinstance(obs.get('line'), int)
                        or not 1 <= obs['line'] <= len(lines) or not obs.get('criterion')
                        or not obs.get('observed') or obs.get('result') != 'PASS'):
                    errors.append('content review lacks a valid position, criterion or observed PASS')
        errors.extend(_reference_errors(turn_dir, row.get('evidence')))
        try:
            report = _final_user_report(turn_dir, target)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append('final USER REPORT terminology scope is invalid: ' + str(exc))
            report = None
        if report is not None:
            if 'APCF-FACTS ' in report:
                from prose_review import validate_review_file
                errors.extend(validate_review_file(report,turn_dir))
            review_rel = row.get('terms_review_path')
            if not isinstance(review_rel, str) or not review_rel.strip():
                review_rel = 'evidence/terms-review.json'
                errors.append('final USER REPORT terminology evidence is not bound to content review')
            evidence_refs = row.get('evidence') if isinstance(row.get('evidence'), list) else []
            if not any(isinstance(ref, dict) and ref.get('path') == review_rel for ref in evidence_refs):
                errors.append('content review does not cite the current terminology evidence')
            try:
                review_path = _terms_review_path(turn_dir, review_rel)
                review = json.loads(review_path.read_text(encoding='utf-8'))
                from terminology_review import private_sidecar_errors, validate as validate_terminology_review
                errors.extend('terminology review: ' + issue for issue in validate_terminology_review(report, review, turn_dir=turn_dir))
                errors.extend('terminology review: ' + issue for issue in private_sidecar_errors(review_path))
            except (OSError, UnicodeError, json.JSONDecodeError, ActivityError, ValueError) as exc:
                errors.append('final USER REPORT terminology evidence missing or invalid: ' + str(exc))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ActivityError) as exc:
        errors.append('content evidence missing or invalid: ' + str(exc))
    return errors


def run_check(turn_dir_raw, test_ids: list[str], targets: list[str], command: list[str],
              expected_exit=0, required_output=None) -> tuple[int, dict]:
    """Execute one real check and retain immutable raw output; never synthesize PASS."""
    from test_ledger import parse_tests
    turn_dir = validate_turn_dir(turn_dir_raw)
    tests = parse_tests((turn_dir / 'TEST.md').read_text(encoding='utf-8'))
    known = {r['id'] for r in tests}
    if not command or not test_ids or not set(test_ids) <= known:
        raise ActivityError('check requires a command and current TEST IDs')
    before = [file_state(_relative_target(p)) for p in targets]
    if not before and managed_targets(turn_dir):
        raise ActivityError('check must bind actual candidate objects when this Turn has changed targets')
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    after = [file_state(_relative_target(p)) for p in targets]
    passed = proc.returncode == expected_exit and before == after
    passed &= all(s in proc.stdout + proc.stderr for s in (required_output or []))
    record = {'schema': 1, 'turn': posix_rel(turn_dir), 'test_ids': test_ids,
              'command': command, 'expected_exit': expected_exit, 'exit_code': proc.returncode,
              'required_output': list(required_output or []), 'stdout': proc.stdout,
              'stderr': proc.stderr, 'targets': after, 'contract_digest': _contract_digest(turn_dir),
              'result': 'PASS' if passed else 'FAIL', 'created_at': datetime.now().astimezone().isoformat()}
    name = f'check-{time.time_ns()}.json'
    path = turn_dir / 'evidence' / name
    _private_json(path, record)
    ref = { 'schema': 1, **_reference(turn_dir, 'evidence/' + name) }
    _append_jsonl(turn_dir / 'evidence/checks.jsonl', ref)
    return (0 if passed else 2), record


def acceptance_errors(turn_dir: Path, stage='final') -> list[str]:
    """Require direct check artifacts for current PASS rows, beyond form validation."""
    from test_ledger import parse_tests, validate_file
    errors = validate_file(turn_dir / 'TEST.md', turn_dir / 'CHECKLIST.md')
    tests = parse_tests((turn_dir / 'TEST.md').read_text(encoding='utf-8'))
    deferred = set()
    if stage == 'publish':
        try:
            plan = json.loads((turn_dir / 'evidence/workflow.json').read_text(encoding='utf-8'))
            if plan.get('contract_digest') != _contract_digest(turn_dir):
                raise ActivityError('publish plan contract is stale')
            deferred = set(plan.get('post_delivery_tests', []))
            if not deferred <= {r['id'] for r in tests} or any(
                    not r['context'].startswith('delivery-postcondition:') for r in tests if r['id'] in deferred):
                raise ActivityError('invalid post-delivery acceptance scope')
        except (OSError, ValueError, TypeError, ActivityError) as exc:
            errors.append('publish acceptance stage invalid: ' + str(exc))
    records = []
    try:
        refs = _validate_jsonl(turn_dir / 'evidence/checks.jsonl')
        for ref in refs:
            checked_ref = {k: ref[k] for k in ('path', 'sha256')}
            if _reference_errors(turn_dir, [checked_ref]):
                continue
            row = json.loads((turn_dir / ref['path']).read_text(encoding='utf-8'))
            if (row.get('result') == 'PASS' and row.get('turn') == posix_rel(turn_dir)
                    and row.get('contract_digest') == _contract_digest(turn_dir)
                    and row.get('exit_code') == row.get('expected_exit')
                    and row.get('command') and all(file_state(p['path']) == p for p in row.get('targets', []))
                    and all(s in row.get('stdout', '') + row.get('stderr', '') for s in row.get('required_output', []))):
                row['_artifact_path']=ref['path']
                records.append(row)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ActivityError) as exc:
        errors.append('actual TEST check evidence unavailable: ' + str(exc))
    for row in tests:
        if row['id'] in deferred and row['status'] in {'未执行', '进行中'}:
            # A preflight cannot prove its own invocation or remote postconditions.
            # They remain visibly pending and are mandatory at finalization.
            continue
        if row['status'] == '不适用':
            if not row['actual'].strip() or row['actual'] in {'不适用', 'N/A'}:
                errors.append(row['id'] + ': not-applicable requires a concrete scope reason')
        elif row['status'] != 'PASS':
            errors.append(row['id'] + ': required current acceptance has not passed')
        elif not any(row['id'] in r.get('test_ids', []) and (row.get('format_version')!=3 or r.get('_artifact_path','<missing>') in row['evidence']) for r in records):
            errors.append(row['id'] + ': formatted PASS has no actual current check evidence')
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture or extend APCF Turn activity evidence")
    sub = ap.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create immutable Turn activity baseline")
    init.add_argument("--turn-dir", required=True)

    record = sub.add_parser("record", help="Append a configured additive activity event")
    record.add_argument("--turn-dir", required=True)
    record.add_argument("--kind", required=True)
    record.add_argument("--detail")

    show = sub.add_parser("show", help="Show current observed activity since baseline")
    show.add_argument("--turn-dir", required=True)

    plan = sub.add_parser('plan', help='Bind existing investigation evidence and planned targets to current CL/TEST')
    plan.add_argument('--turn-dir', required=True)
    plan.add_argument('--target', action='append', default=[])
    plan.add_argument('--investigation', action='append', required=True)
    plan.add_argument('--regression-test', action='append', required=True)
    plan.add_argument('--post-delivery-test', action='append', default=[])
    check = sub.add_parser('check', help='Run one check and save real current-candidate evidence')
    check.add_argument('--turn-dir', required=True)
    check.add_argument('--test-id', action='append', required=True)
    check.add_argument('--target', action='append', default=[])
    check.add_argument('--expected-exit', type=int, default=0)
    check.add_argument('--required-output', action='append', default=[])
    check.add_argument('--command', dest='check_command', nargs=argparse.REMAINDER, required=True)

    args = ap.parse_args()
    try:
        if args.command == 'plan':
            value = record_plan(args.turn_dir, args.target, args.investigation, args.regression_test, args.post_delivery_test)
            print('PASS: investigation/plan recorded; targets=' + str(len(value['targets'])))
            return 0
        if args.command == 'check':
            code, value = run_check(args.turn_dir, args.test_id, args.target, args.check_command,
                                    args.expected_exit, args.required_output)
            print(value['result'] + ': actual check evidence recorded; TEST=' + ','.join(args.test_id))
            return code
        if args.command == "init":
            path, record_obj = init_baseline(args.turn_dir)
            print(f"PASS: activity baseline created; path={posix_rel(path)}; git_head={record_obj['git_head']}")
            return 0
        if args.command == "record":
            path, event = record_event(args.turn_dir, args.kind, args.detail)
            print(f"PASS: activity event recorded; id={event['event_id']}; kind={event['kind']}; path={posix_rel(path)}")
            return 0
        activity = collect_activity(args.turn_dir)
        print(json.dumps(activity, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ActivityError, ReceiptError) as exc:
        print(f"FAIL: {exc}")
        return getattr(exc, "code", EXIT_INVALID)
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL: activity I/O or parse error: {exc}")
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
