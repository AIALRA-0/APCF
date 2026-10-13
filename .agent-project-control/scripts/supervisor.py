# APCF-META {"schema":1,"visibility":"public"}
"""Coordinate existing APCF guards and record what this entrypoint really observed.

The request, plan, routing, TEST and finalize journal remain authoritative. This
module adds no alternate task state machine. Its hash-linked event log detects
accidental drift, NOT forgery by a same-user shell. It cannot intercept unwrapped
shells, desktop chat, or authenticate a human's receipt or semantic understanding.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import execution_session as session
from repair_io import canonical, digest, inside, linked, lock, private_json, text_digest

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / '.agent-project-control'
SCRIPTS = CONTROL / 'scripts'
PHASES = {'bootstrap', 'scope', 'tools', 'verification', 'delivery', 'framework', 'finalization', 'writing'}
LIMITS = {
    'mode': 'COOPERATIVE_GUARDED_ENTRYPOINT',
    'unwrapped_tools': 'NOT_INTERCEPTED',
    'model_understanding': 'NOT_CERTIFIED',
    'reviewer_identity': 'NOT_INDEPENDENTLY_AUTHENTICATED',
    'desktop_transport': 'NOT_VERIFIED',
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _turn(raw) -> Path:
    """Validate a real TR and reject reparse/symlink aliases before accessing it."""
    raw = Path(raw)
    candidate = raw if raw.is_absolute() else ROOT / raw
    rel = candidate.absolute().relative_to(ROOT.resolve()).as_posix()
    if '..' in Path(rel).parts:
        raise ValueError('Turn traversal is not accepted')
    path = inside(ROOT, rel)
    if not path.is_dir():
        raise ValueError('Turn directory is missing')
    return session._safe_turn(path)


def _events_path(turn: Path) -> Path:
    return inside(turn, 'evidence/supervision.json')


def events(turn: Path) -> list[dict]:
    """Read the small event index and verify its chain; no raw stdout is duplicated."""
    path = _events_path(turn)
    if not path.exists():
        return []
    obj = json.loads(path.read_text(encoding='utf-8'))
    if obj.get('schema') != 1 or not isinstance(obj.get('events'), list):
        raise ValueError('invalid supervision event format')
    previous = '0' * 64
    for seq, row in enumerate(obj['events'], 1):
        unsigned = {k: v for k, v in row.items() if k != 'sha256'}
        if (row.get('sequence') != seq or row.get('previous') != previous or
                row.get('sha256') != digest(canonical(unsigned))):
            raise ValueError('supervision event chain is damaged; preserve it for recovery')
        previous = row['sha256']
    return obj['events']


def _append(turn: Path, request: str, action: str, outcome: str, facts: dict) -> dict:
    """Append under one advisory lock, reusing private metadata and atomic writes."""
    with lock(CONTROL / 'runtime/tmp/.supervisor-log.lock'):
        rows = events(turn)
        row = {'schema': 1, 'sequence': len(rows) + 1, 'request_id': request,
               'action': action, 'outcome': outcome, 'timestamp': _now(),
               'previous': rows[-1]['sha256'] if rows else '0' * 64, 'facts': facts}
        row['sha256'] = digest(canonical(row))
        private_json(_events_path(turn), {'schema': 1, 'events': rows + [row]})
        return row


def _latest(turn, request, action):
    return next((r for r in reversed(events(turn)) if r['request_id'] == request and
                 r['action'] == action and r['outcome'] == 'PASS'), None)


def _binding(turn, request):
    row = session.load(turn, request)
    return {'request_id': row['request_id'], 'request_sha256': row['request_sha256'],
            'authority_sha256': digest(canonical(row['authority'])), 'nonce': row['nonce'],
            'control_code_sha256': digest(canonical({p.name: digest(p.read_bytes()) for p in sorted(SCRIPTS.glob('*.py'))}))}


def inspect(turn, request, *, project=None, emit_sources=False) -> dict:
    """Read real CURRENT and its source TURN, not an agent-supplied status claim.

    project permits an explicit project root when the host starts in its parent.
    Without it, cwd must be inside this exact project. No IT is auto-created/closed.
    """
    turn = _turn(turn)
    binding = _binding(turn, request)
    cwd = Path.cwd().resolve()
    if project is not None:
        if Path(project).resolve() != ROOT.resolve():
            raise ValueError('explicit project differs from this installed framework')
    elif not cwd.is_relative_to(ROOT.resolve()):
        raise ValueError('cwd is outside the project; pass the exact --project explicitly')
    from state_integrity import validate
    problems = validate()
    if problems:
        raise ValueError('CURRENT/source TURN mismatch: ' + '; '.join(problems))
    current = inside(ROOT, 'CURRENT.md', must_exist=True)
    current_raw = current.read_bytes()
    text = current_raw.decode('utf-8-sig')
    source = re.search(r'Source TURN[^`]*`([^`]+)`', text)
    files = {'CURRENT.md': digest(current_raw), 'AGENTS.md': digest((ROOT/'AGENTS.md').read_bytes())}
    if source:
        old = inside(ROOT, source.group(1) + '/TURN.md', must_exist=True)
        files[old.relative_to(ROOT).as_posix()] = digest(old.read_bytes())
    it = turn.parents[1] / 'ITERATION.md'
    if not it.is_file() or '**Status**：ACTIVE' not in it.read_text(encoding='utf-8'):
        raise ValueError('current TR must belong to an existing ACTIVE objective')
    active = [p for p in (CONTROL/'iterations').glob('IT-*/ITERATION.md')
              if '**Status**：ACTIVE' in p.read_text(encoding='utf-8')]
    if len(active) != 1 or active[0].resolve() != it.resolve():
        raise ValueError('ambiguous ACTIVE IT; use the existing lifecycle commands deliberately')
    files[it.relative_to(ROOT).as_posix()] = digest(it.read_bytes())
    git = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT,
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    git_root = str(Path(git.stdout.strip()).resolve()) if git.returncode == 0 else None
    if git.returncode != 0:
        known_repository=any((parent/'.git').exists() for parent in (ROOT,*ROOT.parents))
        if known_repository or 'not a git repository' not in git.stderr.lower():
            raise ValueError('cannot verify Git ownership: '+git.stderr.strip())
    if git_root and Path(git_root) != ROOT.resolve():
        raise ValueError('Git command would operate on a parent repository, not this project')
    if emit_sources:
        for path in (current, it):
            rel = path.relative_to(ROOT).as_posix()
            print('===== APCF CONTEXT SOURCE | '+rel+' | sha256='+files[rel]+' =====')
            print(path.read_text(encoding='utf-8-sig'))
            print('===== APCF CONTEXT SOURCE END =====')
    return _append(turn, request, 'context', 'PASS', {**binding, 'cwd': str(cwd),
                   'project': str(ROOT.resolve()), 'git_root': git_root, 'files': files,
                   'model_delivery': 'SOURCE_EMITTED' if emit_sources else 'PROGRAM_READ_ONLY',
                   'reading_scope': 'program read and cross-check; not model comprehension'})


def _require_context(turn, request):
    bound = _binding(turn, request)
    row = _latest(turn, request, 'context')
    if row is None or any(row['facts'].get(k) != v for k, v in bound.items()):
        raise ValueError('current context not inspected, or authority/request/control code changed')
    cancelled = _latest(turn, request, 'interrupt')
    if cancelled and cancelled['sequence'] > row['sequence']:
        raise ValueError('request interrupted; explicitly inspect and reload before resuming')
    for rel, sha in row['facts']['files'].items():
        path = inside(ROOT, rel, must_exist=True)
        # Finalize legitimately changes CURRENT; only accept its real committed result.
        if digest(path.read_bytes()) != sha:
            if rel == 'CURRENT.md':
                _committed(turn)
            else:
                raise ValueError('context input changed: ' + rel + '; inspect again')
    return bound


def load_rules(turn, request, phase, capabilities=(), targets=()) -> dict:
    """Emit canonical source bodies at phase boundaries and retain only their hashes.

    Actual host delivery/truncation must be checked outside this local program.
    There is no claim that the model understood everything printed on stdout.
    """
    turn = _turn(turn); bound = _require_context(turn, request)
    if phase not in PHASES:
        raise ValueError('unknown phase')
    args = [sys.executable, '-B', str(SCRIPTS/'route_context.py'), '--turn-dir', str(turn),
            '--phase', 'finalization' if phase == 'writing' else phase]
    caps = list(dict.fromkeys([*capabilities, *(['human-readable'] if phase == 'writing' else [])]))
    for cap in caps:
        args += ['--capability', cap]
    for target in targets:
        inside(ROOT, target); args += ['--target', target]
    start = time.monotonic()
    # Inherit stdout so source text remains on the host tool channel, not hidden in a log.
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run(args, cwd=ROOT, env=environment)
    if result.returncode:
        _append(turn, request, 'read:' + phase, 'FAIL', {'exit_code': result.returncode})
        raise ValueError('canonical route could not be resolved; no optional skill fallback is fabricated')
    from routing_receipt import load_records, verify_record
    rows = load_records(turn/'evidence/routing.jsonl')
    latest = rows[-1]
    problems = verify_record(latest, turn)
    if problems:
        raise ValueError('; '.join(problems))
    return _append(turn, request, 'read:' + phase, 'PASS', {**bound,
        'receipt_id': latest['receipt_id'], 'receipt_sha256': digest(canonical(latest)),
        'elapsed_ms': round((time.monotonic()-start)*1000), 'caps': caps,
        'model_delivery': 'SOURCE_EMITTED_NOT_COMPREHENSION_CERTIFIED'})


def _require_read(turn, request, phase):
    bound = _require_context(turn, request)
    row = _latest(turn, request, 'read:' + phase)
    context = _latest(turn, request, 'context')
    if (row is None or row['sequence'] <= context['sequence'] or
            any(row['facts'].get(k) != v for k, v in bound.items())):
        raise ValueError('missing source emission after latest context/recovery for phase: ' + phase)
    from routing_receipt import load_records, verify_record
    match = next((r for r in load_records(turn/'evidence/routing.jsonl')
                  if r['receipt_id'] == row['facts']['receipt_id']), None)
    if not match or digest(canonical(match)) != row['facts']['receipt_sha256'] or verify_record(match, turn):
        raise ValueError('source receipt missing or stale')
    return row


def authorize(turn, request) -> dict:
    """Reuse the r1 pre-write goal/plan guard; do not invent another plan ledger."""
    turn = _turn(turn); _require_read(turn, request, 'scope')
    from routing_activity import _contract_digest
    ticket = session.authorize(turn, request)
    return _append(turn, request, 'authorize', 'PASS',
                   {'goal_digest': _contract_digest(turn), 'ticket_sha256': digest(canonical(ticket)),
                    'scope': [v['path'] for v in ticket['targets']]})


def write_file(turn, request, target, payload: bytes, before_sha):
    """Apply one guarded CAS write; arbitrary shell commands are deliberately excluded."""
    turn = _turn(turn); _require_read(turn, request, 'scope')
    from routing_activity import _contract_digest
    row = _latest(turn, request, 'authorize')
    if row is None or row['facts']['goal_digest'] != _contract_digest(turn):
        raise ValueError('supervisor has not authorized this plan')
    after = session.apply_file(turn, request, target, payload, before_sha)
    return _append(turn, request, 'write', 'PASS', {'path': target, 'before_sha256': before_sha,
                   'after_sha256': after, 'scope': 'only this explicit file write'})


def check(turn, request, test_ids, targets, command, expected_exit=0, required_output=()):
    """Run the current regression once using the canonical check/evidence writer.

    The child may have side effects; this wrapper is not a shell sandbox. Keep the
    host's existing approvals and OS permissions. No implicit retry loop is added.
    """
    turn = _turn(turn); _require_read(turn, request, 'verification')
    from routing_activity import workflow_errors, run_check
    problems = workflow_errors(turn)
    if problems:
        raise ValueError('; '.join(problems))
    code, result = run_check(turn, test_ids, targets, command, expected_exit, required_output)
    receipt = _append(turn, request, 'check', 'PASS' if code == 0 else 'FAIL',
               {'test_ids': test_ids, 'exit_code': result['exit_code'], 'expected_exit': expected_exit,
                'result_sha256': digest(canonical(result)), 'evidence_index': 'evidence/checks.jsonl'})
    return code, receipt


def prepare(turn, request, output: Path):
    """Validate the actual visible report with existing content contracts before delivery."""
    turn = _turn(turn); _require_read(turn, request, 'writing')
    from routing_activity import acceptance_errors, workflow_errors
    errors = workflow_errors(turn) + acceptance_errors(turn)
    if errors:
        raise ValueError('; '.join(errors))
    receipt = session.emit(turn, request, output)
    return _append(turn, request, 'prepare-output', 'PASS', receipt)


def _committed(turn: Path):
    """Prove Finalize actually committed this Turn and CURRENT still reflects it."""
    import finalize_turn as final
    from state_integrity import validate
    journal, _ = final._journal_paths(turn)
    row = final._load_journal(turn, journal)
    if row.get('result') != 'COMMITTED':
        raise ValueError('Finalize transaction is not committed')
    if not final._current_matches_turn((ROOT/'CURRENT.md').read_bytes(), turn, (turn/'TURN.md').read_bytes()):
        raise ValueError('CURRENT does not match this actual finalized TURN')
    final._validate_journal_gate(turn, row)
    actual_image = final._image((turn/'TURN.md').read_bytes(), (ROOT/'CURRENT.md').read_bytes())
    if actual_image != row.get('postimage'):
        raise ValueError('finalized source bytes changed after commit')
    errors = validate()
    if errors:
        raise ValueError('; '.join(errors))
    return row


def finalize(turn, request):
    """Delegate the sole Gate/Finalize transaction, then record its real postcondition."""
    turn = _turn(turn); _require_read(turn, request, 'writing')
    prepared = _latest(turn, request, 'prepare-output')
    if prepared is None:
        raise ValueError('prepare the validated visible output before finalizing')
    from terminology_review import extract_user_report, read_report_text
    if prepared['facts'].get('report_sha256') != text_digest(extract_user_report(read_report_text(turn/'TURN.md'))):
        raise ValueError('report changed after prepare; validate and prepare the current version')
    import finalize_turn as final
    rc = final._finalize(turn)
    if rc:
        _append(turn, request, 'finalize', 'FAIL', {'exit_code': rc})
        return rc
    journal = _committed(turn)
    _append(turn, request, 'finalize', 'PASS', {'journal_sha256': digest(canonical(journal)),
            'turn_sha256': digest((turn/'TURN.md').read_bytes()),
            'current_sha256': digest((ROOT/'CURRENT.md').read_bytes())})
    return 0


def observe_output(turn, request, captured: Path):
    """Compare captured bytes only after real Finalize; this is not a human receipt."""
    turn = _turn(turn); session.load(turn, request)
    _committed(turn)
    # R1 report validation also checks the visible-text review binding.
    receipt = session.emit(turn, request, captured, observed=True)
    return _append(turn, request, 'captured-output', 'PASS', {**receipt,
        'transport_scope': 'caller-supplied capture; authenticity requires a separately tested host adapter'})


def interrupt(turn, request, reason):
    """Stop this cooperative entrypoint without falsely completing or cancelling the IT."""
    turn = _turn(turn); session.load(turn, request)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('interruption requires a concrete reason')
    return _append(turn, request, 'interrupt', 'PASS', {'reason': reason, 'resume': 'inspect then load'})


def status(turn, request):
    """Derive a compact status from real artifacts; never accept supplied PASS flags."""
    turn = _turn(turn)
    out = {'schema': 1, 'request_id': request, 'turn': turn.relative_to(ROOT).as_posix(),
           'limits': LIMITS, 'checks': {}}
    for name, probe in [('context', lambda: _require_context(turn, request)),
                        ('scope_read', lambda: _require_read(turn, request, 'scope')),
                        ('writing_read', lambda: _require_read(turn, request, 'writing')),
                        ('committed_turn', lambda: _committed(turn))]:
        try:
            probe(); out['checks'][name] = {'result': 'VERIFIED'}
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            out['checks'][name] = {'result': 'NOT_VERIFIED', 'reason': str(exc)}
    captured = _latest(turn, request, 'captured-output')
    try:
        session.load(turn, request)
        if captured:
            from terminology_review import extract_user_report, read_report_text
            _committed(turn)
            actual = text_digest(extract_user_report(read_report_text(turn/'TURN.md')))
            if captured['facts'].get('report_sha256') != actual:
                raise ValueError('capture belongs to another report version')
        out['checks']['captured_output'] = {'result': 'CAPTURE_COMPARED' if captured else 'NOT_OBSERVED'}
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        out['checks']['captured_output'] = {'result': 'NOT_VERIFIED', 'reason': str(exc)}
    out['event_count'] = len(events(turn))
    out['semantic_assurance'] = 'bindings and recorded author review only; no automatic all-rules quality certificate'
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect','load','authorize','write','check','prepare','finalize','observe','interrupt','status'])
    parser.add_argument('--turn', required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--project')
    parser.add_argument('--reason')
    parser.add_argument('--phase', choices=sorted(PHASES))
    parser.add_argument('--capability', action='append', default=[])
    parser.add_argument('--target', action='append', default=[])
    parser.add_argument('--input'); parser.add_argument('--before-sha256'); parser.add_argument('--output')
    parser.add_argument('--test-id', action='append', default=[])
    parser.add_argument('--expected-exit', type=int, default=0)
    parser.add_argument('--required-output', action='append', default=[])
    parser.add_argument('--command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        turn = _turn(args.turn); rid = args.request_id
        if args.action == 'inspect': value = inspect(turn, rid, project=args.project, emit_sources=True)
        elif args.action == 'load': value = load_rules(turn, rid, args.phase, args.capability, args.target)
        elif args.action == 'authorize': value = authorize(turn, rid)
        elif args.action == 'write':
            if len(args.target) != 1 or not args.input: raise ValueError('write requires one --target and --input')
            value = write_file(turn, rid, args.target[0], Path(args.input).read_bytes(), args.before_sha256)
        elif args.action == 'check':
            rc, value = check(turn, rid, args.test_id, args.target, args.command or [], args.expected_exit, args.required_output)
            print(json.dumps(value, ensure_ascii=False, indent=2)); return rc
        elif args.action == 'prepare':
            if not args.output: raise ValueError('prepare requires --output')
            value = prepare(turn, rid, Path(args.output))
        elif args.action == 'finalize': return finalize(turn, rid)
        elif args.action == 'interrupt': value = interrupt(turn, rid, args.reason)
        elif args.action == 'observe':
            if not args.output: raise ValueError('observe requires captured --output')
            value = observe_output(turn, rid, Path(args.output))
        else: value = status(turn, rid)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('BLOCKED:', exc, file=sys.stderr); return 2


# APCF-REPORT14-ADAPTER v1
from report14.bridge import install as _install_report14
_install_report14('supervisor', globals())

if __name__ == '__main__':
    raise SystemExit(main())
