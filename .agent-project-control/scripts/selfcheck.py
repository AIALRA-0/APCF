# APCF-META {"schema":1,"visibility":"public"}
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import stat
import importlib.util
import zipfile
from common import ROOT,now_stamp,parse_meta
from rule_sync import MODULES
from contextlib import contextmanager
from test_ledger import TEST_FORMAT_MARKER, parse_tests, serialize_v2, validate_text
from selfcheck_runlog import make_run_id, store_run


WRITING_INTERFACE = '.agent-project-control/interfaces/WRITING_STANDARD.md'
STYLE_INTERFACE = '.agent-project-control/interfaces/STYLE_STANDARD.md'
WRITING_SOURCE = '.agent-project-control/standards/human-readable-chinese-writing-v0.1.md'
STYLE_SOURCE = '.agent-project-control/standards/human-readable-chinese-style-v0.1.md'
DESIGN_SOURCES = [
    '.agent-project-control/DESIGN.md',
    '.agent-project-control/design/INDEX.md',
    '.agent-project-control/design/RULES.md',
    '.agent-project-control/design/VERIFICATION.md',
    '.agent-project-control/design/BASELINES.lock.yaml',
]


def unresolved_interface_bytes(original):
    """Change only the live interface status, preserving historical prose."""
    marker = '- **状态**：`RESOLVED`'.encode('utf-8')
    assert original.count(marker) == 1
    return original.replace(marker, marker.replace(b'RESOLVED', b'UNRESOLVED'), 1)


@contextmanager
def unresolved_interface(root, rel=WRITING_INTERFACE):
    path = root / rel
    original = path.read_bytes()
    try:
        path.write_bytes(unresolved_interface_bytes(original))
        yield path
    finally:
        path.write_bytes(original)
        assert path.read_bytes() == original, rel


def disabled_style_bytes(original):
    marker = b'[capabilities.style]\nenabled = true'
    assert original.count(marker) == 1
    return original.replace(marker, marker.replace(b'true', b'false'), 1)

RUN_ID = make_run_id()
CASE = ROOT / '.agent-project-control/runtime/testbed' / RUN_ID
META = '# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n'
ROWS = []

def mark(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '.apcf-dir.yaml').write_text(META, encoding='utf-8')


def fixture_test_rows(text):
    """Keep explicit v1 fixture inputs while emitting current v2 records."""
    assert not validate_text(text), validate_text(text)
    return '\n'.join(serialize_v2(row) for row in parse_tests(text)) + '\n'


def fixture_test_document(text):
    rows = fixture_test_rows(text)
    return ('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'
            '# 1. 当前验收记录\n\n' + TEST_FORMAT_MARKER + '\n\n' + rows)


def fixture_terms_review(report):
    """Replay explicit terminology judgments for the controlled regression reports.

    This is test evidence for an APCF maintainer, never a production review
    generator. An unfamiliar token deliberately fails instead of granting an
    automatic exemption to an arbitrary report.
    """
    from datetime import datetime, timezone
    from terminology_review import initial_review, validate, glossary_lines
    reviewer = 'Codex: reviewer of the finite APCF regression fixture'
    timestamp = datetime.now(timezone.utc).isoformat()
    audience = 'APCF framework maintainers exercising synthetic lifecycle regressions; they have read AGENTS and the canonical rules'
    identities = {'IT': 'stable iteration objective', 'TR': 'current execution record',
                  'CL': 'Checklist requirement identity', 'TEST': 'current acceptance record',
                  'PA': 'one-layer parallel task', 'REG': 'regression record',
                  'ADR': 'architecture decision record', 'MAT': 'material record',
                  'RB': 'runbook record', 'APCF': 'this framework',
                  'SHA': 'candidate file digest', 'ID': 'stable record identifier',
                  'UI': 'the fixture user interface', 'CSS': 'fixture stylesheet source',
                  'README': 'repository landing document',
                  'BP': 'the single-layer unordered list used by this report fixture under R20 and Writing section 13'}
    statuses = {'PASS', 'FAIL', 'BLOCKED', 'UNKNOWN'}
    review = initial_review(report)
    review.update(reviewer=reviewer, reviewed_at=timestamp, audience_context=audience,
                  semantic_review_completed=True)
    for item in review['items']:
        term = item['term']
        if term not in identities and term not in statuses:
            raise AssertionError('Unreviewed terminology in controlled fixture: ' + term)
        role = identities.get(term, 'literal acceptance status ' + term)
        meaning = item['meanings'][0]
        meaning.update(decision='LITERAL_FORMAT' if term in statuses else 'KNOWN_TO_AUDIENCE',
                       reason=f'{term} denotes {role} in this inspected fixture; the declared maintainer audience already uses this exact framework identity',
                       audience_context=audience, domain_context='APCF synthetic regression only',
                       current_use=f'{term}: {role} on the recorded occurrence lines',
                       context_relevance='This identity connects the observed fixture result to its lifecycle record',
                       name_status='NOT_APPLICABLE', verified_full_name='',
                       name_limit='This fixture preserves the local identity without asserting an English expansion',
                       definition=role, source_or_basis='.agent-project-control/rules/INDEX.md and the controlled regression report occurrence lines',
                       reviewer=reviewer, reviewed_at=timestamp)
    review['attestations'] = {name: True for name in review['attestations']}
    if not glossary_lines(report):
        review['no_glossary_reason'] = 'This controlled report uses only the explicitly reviewed lifecycle identities already known to its APCF-maintainer audience'
    assert not validate(report, review), validate(report, review)
    return review

def _childenv(scripts_dir, base=None):
    """Make fixture-local sibling modules importable for script-file children."""
    child = dict(os.environ if base is None else base)
    child.setdefault('PYTHONIOENCODING', 'utf-8')
    scripts_path = str(Path(scripts_dir))
    inherited = child.get('PYTHONPATH', '')
    entries = inherited.split(os.pathsep) if inherited else []
    if scripts_path not in entries:
        child['PYTHONPATH'] = os.pathsep.join([scripts_path, *entries])
    return child



def seed_fixture_root(fixture):
    """Preserve real instruction/state inputs, but synthesize fixture-owned documents.

    A consuming project is not required to contain the template's README or test
    plan. No real consumer file is modified, and missing AGENTS/CURRENT still fail.
    """
    fixture=Path(fixture)
    for name in ('AGENTS.md', 'CURRENT.md'):
        shutil.copyfile(ROOT/name, fixture/name)
    (fixture/'.gitignore').write_text('.agent-project-control/runtime/\n.codex/skills/\n',encoding='utf-8',newline='\n')
    for name in ('README.md','README.en.md','TEMPLATE_SPEC.md','CODEX_PROMPT.md','CODEX_DEPLOY.md','PILOT_TEST_PLAN.md','VALIDATION.md'):
        (fixture/name).write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# Agent Project Control Framework v0.3.0\n\nSynthetic fixture documentation, not project facts.\n',encoding='utf-8',newline='\n')

def assert_fixture_git_root(fixture):
    """Refuse parent-repository fallback before a synthetic fixture Git operation.

    Windows path-length and alias failures must not stage or commit the maintainer's
    real repository. Resolve both returned and requested roots before comparison.
    """
    fixture=Path(fixture).resolve()
    query=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=fixture,
                         capture_output=True,text=True,encoding='utf-8',errors='replace')
    if query.returncode or Path(query.stdout.strip()).resolve()!=fixture:
        raise RuntimeError('fixture Git root mismatch; no synthetic Git write permitted')

_FIXTURE_GIT_PROCESS_CONFIG = None


def configure_fixture_git_longpaths(fixture):
    """Use only this selfcheck process's owned Windows Git configuration.

    Git for Windows consults the global-source setting before its repository-local
    and command-line overrides for this deep path case. This file is not the user's
    global config: it lives in the first verified private fixture and is inherited
    only by this selfcheck's children, then removed with that fixture.
    """
    global _FIXTURE_GIT_PROCESS_CONFIG
    fixture = Path(fixture).resolve()
    assert_fixture_git_root(fixture)
    if os.name == 'nt' and _FIXTURE_GIT_PROCESS_CONFIG is None:
        # main deliberately removes CASE/.git and empties CASE/runtime before
        # the historical matrices; keep this owned config beside CASE instead.
        config = CASE.parent / (RUN_ID + '-git-longpaths.config')
        with config.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write('# APCF-META {"schema":1,"visibility":"private"}\n[core]\n    longpaths = true\n')
        _FIXTURE_GIT_PROCESS_CONFIG = config
        os.environ['GIT_CONFIG_GLOBAL'] = str(config)


def remove_readonly(func,path,exc):
    if not isinstance(exc[1],PermissionError): raise exc[1]
    Path(path).chmod(stat.S_IWRITE|stat.S_IREAD); func(path)

def run(name, *args, expected=0, case=None, full_output=False):
    scripts = CASE / '.agent-project-control/scripts'
    r = subprocess.run([sys.executable, '-B', str(scripts / name), *map(str, args)], cwd=CASE, capture_output=True, text=True, encoding='utf-8', env=_childenv(scripts))
    ROWS.append({'script': name, 'arguments': [str(a).replace(str(ROOT), '<workspace>') for a in args], 'exit_code': r.returncode, 'expected_exit_code': expected, 'stdout': r.stdout.replace(str(ROOT), '<workspace>'), 'stderr': r.stderr.replace(str(ROOT), '<workspace>')})
    if case is not None: ROWS[-1]['case'] = case
    if name == 'new_turn.py' and r.returncode == 0:
        check_bootstrap_output(CASE, r.stdout)
    assert r.returncode == expected, (name, r.returncode, r.stdout, r.stderr)
    return r.stdout if full_output else (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else '')


def record_fixture_evidence(fixture, tr, post_delivery_tests=None):
    """Create finite synthetic evidence by inspecting and hashing the isolated candidate."""
    source = r'''
import sys, json, re, subprocess, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[2]) / '.agent-project-control/scripts'))
from routing_activity import managed_targets, file_state, record_plan, record_semantic_review, record_content_review, run_check, _private_json
from route_context import load_contract, matching_capabilities, capability_closure, resolve_inside_repo
from test_ledger import parse_tests
from gate_check import _markdown_prose
from standards_contract import validate as validate_standards
from terminology_review import extract_user_report
from selfcheck import fixture_terms_review
tr = Path(sys.argv[1])
root = Path(sys.argv[2])
deferred = json.loads(sys.argv[3])
targets = managed_targets(tr)
tests = parse_tests((tr / 'TEST.md').read_text(encoding='utf-8'))
if not tests:
    raise SystemExit('fixture has no current TEST records')
details = ['<!-- APCF-META {"schema":1,"visibility":"private"} -->', '',
           '# Investigated current candidate', '',
           'The fixture helper inspected each changed object, its current hash and its applicable routed content obligations.']
semantic = {}
for rel in targets:
    state = file_state(rel)
    path = root / rel
    if state['state'] == 'file':
        raw = path.read_bytes()
        excerpt = raw[:240].decode('utf-8', 'replace').replace('\r', ' ').replace('\n', ' ')
        basis = f"Reviewed {rel}; current SHA-256 is {state['sha256']}, and inspected bytes begin {excerpt!r}. The object remains within its observed implementation scope."
        details.append(f"- `{rel}`: state=file; SHA-256={state['sha256']}; inspected excerpt={excerpt!r}")
    elif state['state'] == 'missing':
        basis = f"Reviewed deletion of {rel}; current state is missing, so the absent candidate remains explicitly scoped."
        details.append(f"- `{rel}`: state=missing")
    else:
        basis = f"Reviewed {rel}; current state is {state['state']} with digest {state['sha256']}."
        details.append(f"- `{rel}`: state={state['state']}; SHA-256={state['sha256']}")
    semantic[rel] = basis
evidence = tr / 'evidence/selfcheck-investigation.md'
evidence.write_text('\n'.join(details) + '\n', encoding='utf-8')
evidence_rel = 'evidence/selfcheck-investigation.md'
record_semantic_review(tr, semantic, [evidence_rel])
ids = [row['id'] for row in tests]
record_plan(tr, targets, [evidence_rel], [ids[0]], deferred)
passing = [row['id'] for row in tests if row['status'] == 'PASS']
checks_log = tr / 'evidence/checks.jsonl'
prior_check_paths = set()
if checks_log.is_file():
    prior_check_paths = {json.loads(line)['path'] for line in checks_log.read_text(encoding='utf-8').splitlines() if line.strip()}
if passing:
    expected = [file_state(rel) for rel in targets]
    check_code = """import sys,json,hashlib
from pathlib import Path
for row in json.loads(sys.argv[1]):
    p=Path(row['path'])
    if row['state']=='file':
        assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'], row
    elif row['state']=='missing':
        assert not p.exists(), row
    elif row['state']=='symlink':
        assert p.is_symlink() and hashlib.sha256(str(p.readlink()).encode()).hexdigest()==row['sha256'], row
    elif row['state']=='directory':
        assert p.is_dir(), row
if 'TEST-DELIVERY' in sys.argv[2:]:
    result=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    commit=__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip()
    rendered=(Path(sys.argv[3]) / result['rendered_path']).read_bytes()
    assert result['result']=='PASS' and result['commit']==commit
    assert hashlib.sha256(rendered).hexdigest()==result['rendered_sha256']
print('CANDIDATE_CHECK_OK')
"""
    delivery_arg = [str(tr / 'evidence/remote-delivery-result.json'), str(tr), 'TEST-DELIVERY'] if 'TEST-DELIVERY' in passing else []
    command = [sys.executable, '-B', '-c', check_code, json.dumps(expected, sort_keys=True), *delivery_arg]
    code, result = run_check(tr, passing, targets, command, required_output=['CANDIDATE_CHECK_OK'])
    if code:
        raise SystemExit('actual candidate check failed: ' + result['stderr'])
contract = load_contract()
content_targets = list(dict.fromkeys(targets + [
    (tr / name).resolve().relative_to(root.resolve()).as_posix()
    for name in ('CHECKLIST.md', 'TEST.md', 'TURN.md')
]))
reviewed = []
route_targets = []
required_route_capabilities = set()
for rel in content_targets:
    path = root / rel
    if not path.is_file():
        continue
    triggered, _ = matching_capabilities(contract, [resolve_inside_repo(rel)])
    closure = capability_closure(contract, triggered)
    needed = [name for name in closure if name in {'writing','style','design','readme'}]
    if not needed:
        continue
    lines = path.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise SystemExit('content candidate is empty: ' + rel)
    if 'writing' in needed and path.suffix.lower() in {'.md','.mdx','.rst','.adoc'}:
        standard_errors = validate_standards()
        if standard_errors:
            raise SystemExit('normative source check failed: ' + '; '.join(standard_errors))
        for number, prose in _markdown_prose(path.read_text(encoding='utf-8')):
            if '。' in prose and any('\u3400' <= char <= '\u9fff' for char in prose):
                raise SystemExit(f'Writing v0.1 punctuation failed at {rel}:{number}')
    line_number = next((i for i,line in enumerate(lines,1)
                        if line.strip() and not line.startswith('<!-- APCF-META') and not line.startswith('# ')), 1)
    observed = lines[line_number-1].strip()
    if not observed:
        raise SystemExit('content observation has no text: ' + rel)
    if path.resolve() == (tr / 'TURN.md').resolve() and '## 0. 精确状态头' in path.read_text(encoding='utf-8'):
        report = extract_user_report(path.read_text(encoding='utf-8'))
        _private_json(tr / 'evidence/terms-review.json', fixture_terms_review(report))
    record_content_review(tr, rel, closure, [evidence_rel], [{
        'line': line_number, 'criterion': 'current candidate and applicable normative source inspected',
        'observed': observed[:240], 'result': 'PASS'
    }], method='deterministic-fixture-review')
    reviewed.append(rel)
    if path.suffix.lower() in {'.md','.mdx','.rst','.adoc'} or (
            path.suffix.lower() in {'.html','.htm','.jsx','.tsx'} and 'design' in needed):
        route_targets.append(rel)
        required_route_capabilities.update(closure)

routing_evidence = None
if route_targets:
    router = root / '.agent-project-control/scripts/route_context.py'
    argv = [sys.executable, '-B', str(router), '--turn-dir', str(tr)]
    for rel in route_targets:
        argv.extend(['--target', rel])
    route_result = subprocess.run(argv, cwd=root, capture_output=True, text=True, encoding='utf-8',
                                  env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'})
    if route_result.returncode:
        raise SystemExit('actual Router capability evidence failed: ' + route_result.stderr + route_result.stdout)
    match = re.search(r'receipt: recorded; id=([^;]+);', route_result.stdout)
    if not match:
        raise SystemExit('actual Router output did not identify its recorded Receipt')
    route_log = tr / 'evidence/routing.jsonl'
    receipts = [json.loads(line) for line in route_log.read_text(encoding='utf-8').splitlines() if line.strip()]
    receipt = next((row for row in receipts if row.get('receipt_id') == match.group(1)), None)
    if not receipt or receipt.get('status') != 'RESOLVED':
        raise SystemExit('actual Router Receipt is missing or unresolved')
    if receipt.get('targets') != route_targets:
        raise SystemExit('actual Router Receipt targets differ from inspected Markdown targets')
    if not required_route_capabilities <= set(receipt.get('resolved_capabilities', [])):
        raise SystemExit('actual Router Receipt omits a capability required by reviewed Markdown')
    routing_evidence = f'evidence/selfcheck-router-{receipt["receipt_id"]}.json'
    _private_json(tr / routing_evidence, {
        'schema': 1, 'turn': receipt['turn'], 'command': argv, 'cwd': str(root),
        'targets': route_targets, 'required_capabilities': sorted(required_route_capabilities),
        'exit_code': route_result.returncode, 'stdout': route_result.stdout,
        'stderr': route_result.stderr, 'receipt': receipt,
    })
private_json_paths = [tr / 'evidence/workflow.json', tr / 'evidence/semantic-review.json',
                      tr / 'evidence/content-review.json']
if routing_evidence:
    private_json_paths.append(tr / routing_evidence)
if checks_log.is_file():
    current_refs = [json.loads(line) for line in checks_log.read_text(encoding='utf-8').splitlines() if line.strip()]
    private_json_paths.extend(tr / row['path'] for row in current_refs if row['path'] not in prior_check_paths)
for path in private_json_paths:
    sidecar = path.with_name(path.name + '.apcf-meta.yaml')
    sidecar_text = sidecar.read_text(encoding='utf-8')
    sidecar_hash = re.search(r'^sha256: ([0-9a-f]{64})$', sidecar_text, re.MULTILINE)
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if (not sidecar_hash or sidecar_hash.group(1) != actual_hash
            or not sidecar_text.startswith('# APCF-META {"schema":1,"visibility":"private"}\n')):
        raise SystemExit('private evidence sidecar does not bind exact bytes: ' + path.name)
print(json.dumps({'targets': targets, 'tests': ids, 'reviewed_content': reviewed,
                  'routing_evidence': routing_evidence,
                  'route_targets': route_targets,
                  'route_capabilities': sorted(required_route_capabilities),
                  'router_stdout': route_result.stdout if route_targets else '',
                  'route_receipt': receipt if route_targets else None}, ensure_ascii=False))
'''
    result = subprocess.run([sys.executable, '-B', '-c', source, str(tr), str(fixture),
                             json.dumps(list(post_delivery_tests or []))],
                           cwd=fixture, capture_output=True, text=True, encoding='utf-8',
                           env=_childenv(fixture / '.agent-project-control/scripts'))
    ROWS.append({'case': f'fixture-evidence/{tr.name}', 'script': 'routing_activity.py',
                 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)

def check_rule_surfaces():
    agents = CASE / 'AGENTS.md'
    index = CASE / '.agent-project-control/rules/INDEX.md'
    original_bytes = agents.read_bytes()
    original_agents = agents.read_text(encoding='utf-8')
    heading = re.compile(r'^##[ \t]+\d+\.\d+\.[ \t]+(R\d+)\b[^\n]*$', re.M)
    modules = [CASE / rel for rel in MODULES]
    module_rows = [(p.name, [m.group(1) for m in heading.finditer(p.read_text(encoding='utf-8'))]) for p in modules]
    assert len(module_rows) == 6
    assert sorted(rid for _, ids in module_rows for rid in ids) == [f'R{i:02d}' for i in range(1, 32)]

    def line(module, ids):
        return f'- `{module}` → `{", ".join(ids)}`'

    lines = [line(module, sorted(ids, key=lambda rid: int(rid[1:]))) for module, ids in module_rows]
    for kind in ['INDEX', 'READBACK']:
        start = '<!-- APCF-RULE-' + kind + '-START -->'
        end = '<!-- APCF-RULE-' + kind + '-END -->'
        assert original_agents.count(start) == original_agents.count(end) == 1
        body = original_agents.split(start, 1)[1].split(end, 1)[0].strip()
        assert body.splitlines() == lines
    run('lint_framework.py', case='AGENTS/normal-coverage')
    original_index = index.read_bytes()
    run('rule_sync.py', case='AGENTS/idempotent-sync')
    assert agents.read_bytes() == original_bytes and index.read_bytes() == original_index

    def reject_agents(label, candidate, marker_error=False):
        assert candidate != original_agents, label
        try:
            agents.write_text(candidate, encoding='utf-8')
            run('lint_framework.py', expected=2, case=label)
            detail = 'marker must occur exactly once' if marker_error else 'AGENTS rule indexes drifted'
            assert detail in ROWS[-1]['stdout'], (label, ROWS[-1])
            if marker_error:
                bad_bytes = agents.read_bytes()
                run('rule_sync.py', expected=1, case=label + '/sync-rejected')
                assert agents.read_bytes() == bad_bytes and index.read_bytes() == original_index
            else:
                run('rule_sync.py', case=label + '/sync-repaired')
                assert agents.read_text(encoding='utf-8') == original_agents
                assert index.read_bytes() == original_index
        finally:
            agents.write_bytes(original_bytes)
        run('lint_framework.py', case=label + '/restored')

    first_module, first_ids = module_rows[0]
    other_module, other_ids = module_rows[1]
    sample = first_ids[0]
    mutations = [
        ('missing-rule', [line(first_module, first_ids[1:])] + lines[1:]),
        ('duplicate-rule-across-modules', [lines[0], line(other_module, other_ids + [sample])] + lines[2:]),
        ('unknown-rule', [line(first_module, first_ids + ['R99'])] + lines[1:]),
        ('wrong-canonical-module', [line(first_module, first_ids[1:]), line(other_module, other_ids + [sample])] + lines[2:]),
        ('missing-module', lines[1:]),
        ('duplicate-module', lines + [lines[0]]),
        ('unknown-module', [line('unknown-module.md', first_ids)] + lines[1:]),
        ('module-order', list(reversed(lines))),
        ('rule-order', [line(first_module, list(reversed(first_ids)))] + lines[1:]),
        ('mapping-format', [lines[0].replace(' → ', ' -> ', 1)] + lines[1:]),
    ]
    agents_cases = 0
    for kind in ['INDEX', 'READBACK']:
        start = '<!-- APCF-RULE-' + kind + '-START -->'
        end = '<!-- APCF-RULE-' + kind + '-END -->'
        prefix, rest = original_agents.split(start, 1)
        _, suffix = rest.split(end, 1)
        for name, changed_lines in mutations:
            candidate = prefix + start + '\n' + '\n'.join(changed_lines) + '\n' + end + suffix
            reject_agents('AGENTS/' + kind + '/' + name, candidate)
            agents_cases += 1
        for marker_name, marker in [('start', start), ('end', end)]:
            reject_agents('AGENTS/' + kind + '/missing-' + marker_name, original_agents.replace(marker, '', 1), True)
            agents_cases += 1
        reject_agents('AGENTS/' + kind + '/duplicate-marker', original_agents + '\n' + start + '\n' + end + '\n', True)
        agents_cases += 1
    start = '<!-- APCF-RULE-READBACK-START -->'
    end = '<!-- APCF-RULE-READBACK-END -->'
    prefix, rest = original_agents.split(start, 1)
    _, suffix = rest.split(end, 1)
    reject_agents('AGENTS/markers-disagree', prefix + start + '\n' + '\n'.join(lines[1:] + lines[:1]) + '\n' + end + suffix)
    agents_cases += 1

    first = modules[0]
    other = modules[1]
    first_text = first.read_text(encoding='utf-8')
    other_text = other.read_text(encoding='utf-8')
    first_heading = heading.search(first_text).group(0)
    other_heading = heading.search(other_text).group(0)
    heading_cases = [
        ('missing', first, first_text.replace(first_heading, '## 1.1. Removed rule heading', 1), 'missing Rule IDs: ' + sample),
        ('duplicate-within-module', first, first_text + '\n' + first_heading + '\n', 'duplicate Rule ID ' + sample),
        ('duplicate-across-modules', other, other_text.replace(other_heading, other_heading.replace(other_ids[0], sample, 1), 1), 'duplicate Rule ID ' + sample),
        ('unknown', first, first_text + '\n## 1.99. R99 Synthetic unknown rule\n', 'unknown Rule ID R99'),
    ]
    for name, module, candidate, token in heading_cases:
        saved = module.read_bytes()
        label = 'Canonical/' + name
        try:
            module.write_text(candidate, encoding='utf-8')
            run('lint_framework.py', expected=2, case=label)
            assert token in ROWS[-1]['stdout'], (label, ROWS[-1])
            run('rule_sync.py', expected=1, case=label + '/sync-rejected')
            assert agents.read_bytes() == original_bytes and index.read_bytes() == original_index
        finally:
            module.write_bytes(saved)
        run('lint_framework.py', case=label + '/restored')
    print('PASS:', agents_cases, 'AGENTS mapping negative cases and', len(heading_cases), 'canonical heading negative cases rejected; normal coverage and repair passed')

def check_router(root, record):
    import uuid
    root = root.resolve()
    fw = root / '.agent-project-control'
    script = fw / 'scripts/route_context.py'
    scratch = fw / 'runtime/tmp' / ('router-scope-' + uuid.uuid4().hex)
    assert not scratch.exists() and scratch.resolve().is_relative_to((fw / 'runtime/tmp').resolve())
    scratch.mkdir()
    (scratch / '.apcf-dir.yaml').write_text(META, encoding='utf-8')
    (scratch / 'AGENTS.md').write_text('<!-- APCF-META {"schema":1,"visibility":"private"} -->\nNested router fixture\n', encoding='utf-8')
    css = scratch / 'sample.css'
    css.write_text('/* APCF-META {"schema":1,"visibility":"private"} */\nbody { color: black; }\n', encoding='utf-8')
    env = _childenv(fw / 'scripts', {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
    evidence = []
    restores = []
    rules = '.agent-project-control/rules/'
    mod = lambda name: rules + name
    begin = re.compile(r'^===== APCF ROUTE SOURCE BEGIN \| ([^|]+) \| (.+) =====\n', re.M)

    def snapshot():
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}
        head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        index = Path(subprocess.check_output(['git', '-C', str(root), 'rev-parse', '--git-path', 'index'], text=True).strip())
        if not index.is_absolute():
            index = root / index
        return files, head, hashlib.sha256(index.read_bytes()).hexdigest()

    before = snapshot()

    def call(number, expected, *args):
        proc = subprocess.run([sys.executable, '-B', str(script), *args], cwd=root,
                              capture_output=True, text=True, encoding='utf-8', env=env)
        row = {'script': 'route_context.py', 'case': 'Router/matrix-%02d' % number,
               'arguments': list(args), 'exit_code': proc.returncode,
               'stdout': proc.stdout, 'stderr': proc.stderr}
        record(row)
        assert proc.returncode == expected, row
        assert not proc.stderr, row
        sources = []
        for match in begin.finditer(proc.stdout):
            kind, rel = match.groups()
            stop = '===== APCF ROUTE SOURCE END | ' + kind + ' | ' + rel + ' ====='
            end = proc.stdout.index(stop, match.end())
            body = proc.stdout[match.end():end]
            actual = (root / rel).read_text(encoding='utf-8')
            assert body == actual + ('' if actual.endswith('\n') else '\n'), rel
            evidence.append({'case': number, 'path': rel, 'text_sha256': hashlib.sha256(body.encode()).hexdigest(),
                             'bytes_sha256': hashlib.sha256((root / rel).read_bytes()).hexdigest()})
            sources.append(rel)
        assert len(sources) == len(set(sources)), row
        return proc.stdout, sources

    def mutated(number, rel, transform, expected, args, token):
        path = root / rel
        original = path.read_bytes()
        try:
            candidate = transform(original)
            assert candidate is None or candidate != original
            if number == 10:
                assert '- **状态**：`UNRESOLVED`'.encode('utf-8') in candidate
            if candidate is None:
                path.unlink()
            else:
                path.write_bytes(candidate)
            out, sources = call(number, expected, *args)
            assert token in out, (number, out)
            return out, sources
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original, rel
            restores.append({'case': number, 'path': rel, 'sha256': hashlib.sha256(original).hexdigest()})

    try:
        out, sources = call(1, 0, '--phase', 'bootstrap')
        assert sources == ['AGENTS.md', rules + 'INDEX.md', mod('01-context-state.md'), mod('02-execution-scope.md')]
        out, sources = call(2, 0, '--phase', 'verification')
        assert sources == [mod('03-verification-regression.md')]
        out, sources = call(3, 0, '--phase', 'verification', '--phase', 'tools')
        assert sources == [mod('03-verification-regression.md'), mod('04-tools-parallel.md')]
        css_target = css.relative_to(root).as_posix()
        out, sources = call(4, 0, '--phase', 'scope', '--target', css_target)
        assert 'capabilities: design\n' in out
        assert sources == [mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
        out, sources = call(5, 0, '--phase', 'scope', '--target', script.relative_to(root).as_posix())
        assert 'coverage-notice: targets with no deterministic capability trigger:' in out
        assert sources == [mod('02-execution-scope.md')]
        out, sources = call(6, 0, '--phase', 'scope', '--scope', scratch.relative_to(root).as_posix())
        assert sources[:2] == ['AGENTS.md', (scratch / 'AGENTS.md').relative_to(root).as_posix()]
        first, sources = call(7, 0, '--phase', 'verification', '--phase', 'tools')
        second, repeated = call(7, 0, '--phase', 'verification', '--phase', 'tools')
        assert first == second and sources == repeated
        out, sources = call(8, 0, '--phase', 'bootstrap', '--target', css_target)
        assert sources == ['AGENTS.md', rules + 'INDEX.md', mod('01-context-state.md'),
                           mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
        readme_args = ('--phase', 'tools', '--target', 'README.md')
        out, sources = call(9, 0, *readme_args)
        assert 'capabilities: writing, style, human-readable, readme\n' in out
        assert sources == [mod('04-tools-parallel.md'), mod('06-framework-contract.md'),
                           WRITING_INTERFACE, WRITING_SOURCE, '.agent-project-control/standards/RULE-ACTIVATION-v0.1.md', '.agent-project-control/standards/WRITING-MINIMAL-EXAMPLES.md', STYLE_INTERFACE, STYLE_SOURCE,
                           '.agent-project-control/skills/SKILLS.lock.yaml',
                           '.codex/skills/github-readme-standardizer/SKILL.md']
        for rel in [WRITING_INTERFACE, STYLE_INTERFACE]:
            mutated(10, rel, unresolved_interface_bytes, 3, readme_args,
                    'ROUTE_UNRESOLVED: capability entrypoints are not resolved')
            assert '- **状态**：`RESOLVED`' in (root / rel).read_text(encoding='utf-8')
            call(10, 0, *readme_args)
        style_args = ('--phase', 'scope', '--capability', 'style')
        out, sources = call(11, 0, *style_args)
        assert sources == [mod('02-execution-scope.md'), STYLE_INTERFACE, STYLE_SOURCE]
        mutated(11, '.agent-project-control/routing.toml', disabled_style_bytes,
                3, style_args, 'reserved but not enabled')
        call(11, 0, *style_args)
        out, _ = call(12, 3, '--phase', 'scope', '--capability', 'unknown-test-capability')
        assert 'unknown capability' in out
        out, _ = call(13, 3, '--phase', 'unknown-test-phase')
        assert 'unknown phase' in out
        mutated(14, rules + 'INDEX.md',
                lambda b: re.sub(rb'(\|\s*`R06`\s*\|\s*)`[^`]+`', rb'\1`01-context-state.md`', b, count=1),
                2, ('--phase', 'verification'), "rules index differs from canonical headings: ['R06']")
        mutated(15, mod('03-verification-regression.md'), lambda b: None,
                2, ('--phase', 'verification'), 'canonical Rule coverage mismatch')
        mutated(16, mod('03-verification-regression.md'),
                lambda b: b + b'\n## 3.99. R06 Duplicate router fixture\n',
                2, ('--phase', 'verification'), 'duplicate canonical Rule ID R06')
        mutated(17, '.agent-project-control/routing.toml',
                lambda b: b.replace(b'modules = ["03-verification-regression.md"]', b'modules = ["missing-test-module.md"]', 1),
                2, ('--phase', 'verification'), 'references non-canonical module')
        mutated(18, '.agent-project-control/routing.toml',
                lambda b: b.replace(b'dependencies = ["human-readable"]', b'dependencies = ["readme"]', 1),
                2, readme_args, 'capability dependency cycle')
        out, sources = mutated(19, '.agent-project-control/DESIGN.md', lambda b: None,
                               2, ('--phase', 'scope', '--capability', 'design'), 'design contract invalid: missing:')
        assert 'DESIGN.md' in out and not sources
        mutated(20, '.agent-project-control/skills/SKILLS.lock.yaml',
                lambda b: re.sub(rb'(resolved_commit: )[^\r\n]+', rb'\g<1>' + b'0' * 40, b, count=1),
                3, readme_args, 'installed skill commit mismatch')
        out, _ = call(21, 2, '--phase', 'scope', '--target', '../router-escape-test')
        assert 'target escapes repository' in out
        out, sources = call(22, 0, '--phase', 'scope', '--target', 'README.md', '--target', css_target)
        assert len(sources) == len(set(sources))
        assert set(sources) == {mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES,
                                WRITING_INTERFACE, WRITING_SOURCE, '.agent-project-control/standards/RULE-ACTIVATION-v0.1.md', '.agent-project-control/standards/WRITING-MINIMAL-EXAMPLES.md', STYLE_INTERFACE, STYLE_SOURCE,
                                '.agent-project-control/skills/SKILLS.lock.yaml',
                                '.codex/skills/github-readme-standardizer/SKILL.md'}
        assert '.codex/skills/github-safe-publish/SKILL.md' not in sources
        out, sources = call(23, 0, '--phase', 'scope', '--capability', 'design',
                            '--capability', 'design', '--target', css_target)
        assert 'capabilities: design\n' in out
        assert sources == [mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
        args = ('--phase', 'verification', '--phase', 'tools', '--phase', 'verification',
                '--capability', 'readme', '--capability', 'design', '--target', css_target)
        out, sources = call(24, 0, *args)
        assert sources[:3] == [mod('03-verification-regression.md'), mod('04-tools-parallel.md'), mod('06-framework-contract.md')]
        again, _ = call(24, 0, *args)
        assert out == again
        assert snapshot() == before, 'Router changed files, HEAD, or index after restored mutations'
        record({'script': 'route_context.py', 'case': 'Router/matrix-25', 'arguments': [],
                'exit_code': 0, 'stdout': 'PASS: all repository file hashes, Git HEAD and index unchanged', 'stderr': ''})
        design_args = ('--phase', 'scope', '--capability', 'design')
        out, sources = mutated(26, '.agent-project-control/design/RULES.md',
                               lambda b: b + b'\n<!-- negative baseline mismatch -->\n',
                               2, design_args, 'design contract invalid: RULES.md hash differs from BASELINES.lock.yaml')
        assert not sources and 'SOURCE BEGIN' not in out
        out, sources = call(27, 0, *design_args)
        assert sources == [mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
        github_publish_args = ('--phase', 'scope', '--capability', 'github-publish')
        out, sources = mutated(28, '.codex/skills/github-safe-publish/SKILL.md',
                               lambda b: b + b'\n<!-- negative pinned-local hash mismatch -->\n',
                               3, github_publish_args,
                               'installed skill source hash mismatch: github-safe-publish')
        assert not sources and 'SOURCE BEGIN' not in out
        out, sources = call(29, 0, *github_publish_args)
        assert sources == [mod('02-execution-scope.md'), '.agent-project-control/skills/SKILLS.lock.yaml',
                           '.codex/skills/github-safe-publish/SKILL.md']
        design_contract = root / '.agent-project-control/scripts/design_contract.py'
        lock_path = root / '.agent-project-control/design/BASELINES.lock.yaml'
        lock_before = lock_path.read_bytes()
        assert re.search(rb'(?m)^rules_version: "v0\.1"$', lock_before)
        assert "**正式版本**：`v0.1`" in (root / '.agent-project-control/design/INDEX.md').read_text(encoding='utf-8')
        design_check = subprocess.run([sys.executable, '-B', str(design_contract), '--check'], cwd=root,
                                       capture_output=True, text=True, encoding='utf-8', env=env)
        record({'script': 'design_contract.py', 'case': 'Router/design-version/current', 'arguments': ['--check'],
                'exit_code': design_check.returncode, 'stdout': design_check.stdout, 'stderr': design_check.stderr})
        assert design_check.returncode == 0 and 'PASS' in design_check.stdout
        for offset, version in enumerate(('2.3.1', 'v9.9'), 30):
            candidate = re.sub(rb'(?m)^rules_version: "[^"]+"$',
                                f'rules_version: "{version}"'.encode('ascii'), lock_before, count=1)
            assert candidate != lock_before
            try:
                lock_path.write_bytes(candidate)
                broken = subprocess.run([sys.executable, '-B', str(design_contract), '--check'], cwd=root,
                                         capture_output=True, text=True, encoding='utf-8', env=env)
                record({'script': 'design_contract.py', 'case': f'Router/design-version/{version}/check',
                        'arguments': ['--check'], 'exit_code': broken.returncode,
                        'stdout': broken.stdout, 'stderr': broken.stderr})
                assert broken.returncode == 2 and 'rules_version' in broken.stdout
                out, sources = call(offset, 2, '--phase', 'scope', '--capability', 'design')
                assert 'rules_version' in out and not sources
            finally:
                lock_path.write_bytes(lock_before)
                assert lock_path.read_bytes() == lock_before
            _, restored_sources = call(offset, 0, '--phase', 'scope', '--capability', 'design')
            assert restored_sources == [mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
        for number, suffix in [(30, '.css'), (31, '.html'), (32, '.tsx')]:
            root_target = root / ('router-root-trigger-' + str(number) + suffix)
            assert not root_target.exists()
            root_target.write_text('synthetic root-level routing target\n', encoding='utf-8')
            try:
                out, sources = call(number, 0, '--phase', 'scope', '--target', root_target.name)
                assert 'capabilities: design\n' in out
                assert sources == [mod('02-execution-scope.md'), mod('06-framework-contract.md'), *DESIGN_SOURCES]
            finally:
                root_target.unlink(missing_ok=True)
        root_python = root / 'router-root-trigger.py'
        assert not root_python.exists()
        root_python.write_text('print("generic")\n', encoding='utf-8')
        try:
            out, sources = call(33, 0, '--phase', 'scope', '--target', root_python.name)
            assert 'coverage-notice: targets with no deterministic capability trigger:' in out
            assert 'capabilities: design' not in out and sources == [mod('02-execution-scope.md')]
        finally:
            root_python.unlink(missing_ok=True)
        assert snapshot() == before, 'Router changed files, HEAD, or index after restored Design/Skill/root-trigger checks'
        print('PASS: Router matrix; Design rules_version positives and legacy/unknown negatives; %d exact text bodies; %d byte-restored mutations; readonly snapshot matched' % (len(evidence), len(restores)))
        return {'source_evidence': evidence, 'restores': restores, 'readonly': True}
    finally:
        assert scratch.resolve().is_relative_to((fw / 'runtime/tmp').resolve())
        shutil.rmtree(scratch, onerror=remove_readonly)

def _skill_tree_snapshot(root):
    root = Path(root)
    assert root.is_dir() and not root.is_symlink(), f'Expected a skill directory: {root.name}'
    entries = {}
    pending = [root]
    while pending:
        parent = pending.pop()
        for child in sorted(parent.iterdir(), key=lambda path: path.name):
            rel = child.relative_to(root).as_posix()
            if child.is_symlink():
                entries[rel] = ('symlink', os.readlink(child))
            elif child.is_dir():
                entries[rel] = ('directory', None)
                pending.append(child)
            elif child.is_file():
                entries[rel] = ('file', child.read_bytes())
            else:
                raise AssertionError(f'Unsupported skill cache entry: {rel}')
    return entries



def prepare_synthetic_skills(fixture):
    """Finite routing fixtures, never installed into the source/user skill cache.

    Core cold-start tests exercise mechanisms offline. A selected real skill must
    separately pass the actual lock acquisition; these fake docs aren't that claim.
    """
    cache=fixture/'.codex/skills';cache.mkdir(parents=True,exist_ok=True)
    entries=[]
    for identity,source in [('github-readme-standardizer','AIALRA-0/github-readme-standardizer'),
                            ('github-safe-publish','AIALRA-0/agent-github-safe-publish')]:
        folder=cache/identity
        folder.mkdir(parents=True,exist_ok=True)
        text=('# Synthetic fixture: '+identity+'\n\nMechanism test only; no product skill or external delivery authorization.\n')
        (folder/'SKILL.md').write_text(text,encoding='utf-8',newline='\n')
        entries.append(f'  - id: {identity}\n    source: {source}\n    requested_ref: synthetic-fixture-only\n    resolved_commit: null\n    install_mode: pinned-local\n    skill_file_sha256: {hashlib.sha256(text.encode()).hexdigest()}\n    required: '+('true' if identity=='github-readme-standardizer' else 'false')+'\n')
    (fixture/'.agent-project-control/skills/SKILLS.lock.yaml').write_text(
        '# APCF-META {"schema":1,"visibility":"public"}\nschema: 1\nskills:\n'+''.join(entries),encoding='utf-8')

def check_router_fixture():
    prepare_synthetic_skills(CASE)
    check_router(CASE, ROWS.append)


def check_bootstrap_output(root, output):
    """Verify visible, complete Source bodies and the unique final success path."""
    lines = output.strip().splitlines()
    tr = Path(lines[-1])
    assert tr.is_dir() and tr.name.startswith('TR-')
    assert sum(line == str(tr) for line in lines) == 1
    sources = [('agents', 'AGENTS.md'), ('rule-index', '.agent-project-control/rules/INDEX.md'),
               ('canonical-module', '.agent-project-control/rules/01-context-state.md'),
               ('canonical-module', '.agent-project-control/rules/02-execution-scope.md')]
    for kind, rel in sources:
        begin = f'===== APCF ROUTE SOURCE BEGIN | {kind} | {rel} =====\n'
        end = f'===== APCF ROUTE SOURCE END | {kind} | {rel} ====='
        assert output.count(begin) == output.count(end) == 1
        body = output.split(begin, 1)[1].split(end, 1)[0]
        text = (root / rel).read_text(encoding='utf-8')
        assert body == text + ('' if text.endswith('\n') else '\n')
    scripts = root / '.agent-project-control/scripts'
    verified = subprocess.run([sys.executable, '-B', str(scripts / 'routing_receipt.py'),
                               '--turn-dir', str(tr), '--phase', 'bootstrap'], cwd=root,
                              capture_output=True, text=True, encoding='utf-8', env=_childenv(scripts))
    assert verified.returncode == 0, (verified.stdout, verified.stderr)
    assert not (tr / 'evidence/gate-attempts.jsonl').exists()
    session=tr/'evidence/execution-session.json'
    if session.exists():
        assert Path(root).resolve().is_relative_to(CASE.parent.resolve()), 'fixture conversion may never touch real project history'
        row=json.loads(session.read_text())
        assert row['project_root']==str(Path(root).resolve()) and row['request_sha256']==hashlib.sha256((tr/'REQUEST.md').read_bytes()).hexdigest()
        ROWS.append({'case':'legacy-fixture-session-conversion','exit_code':0,'stdout':'New session validated; this disposable fixture deliberately replays a pre-v3 client','stderr':'','session':row})
        session.unlink();session.with_name(session.name+'.apcf-meta.yaml').unlink()
    return tr


def unrouted_turn_fixture(root, template, title):
    """Build intentionally incomplete test input; never remove a successful receipt."""
    code = """
import sys,shutil
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'.agent-project-control/scripts'))
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,dir_marker
from routing_activity import init_baseline
source=Path(sys.argv[1])
d=source.parent/(next_id('TR',FRAMEWORK_ROOT/'iterations')+'_'+now_stamp()+'_'+slugify(sys.argv[2]))
assert not d.exists()
dir_marker(d);dir_marker(d/'evidence','private');dir_marker(d/'parallel','private')
for name in ['REQUEST.md','CHECKLIST.md','TEST.md','TURN.md']:shutil.copyfile(source/name,d/name)
init_baseline(d)
assert not (d/'evidence/routing.jsonl').exists()
print(d)
"""
    proc = subprocess.run([sys.executable, '-B', '-c', code, str(template), title], cwd=root,
                          capture_output=True, text=True, encoding='utf-8',
                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    tr = Path(proc.stdout.strip())
    assert tr.is_dir() and not (tr / 'evidence/routing.jsonl').exists()
    ROWS.append({'case': 'Step1EB/legacy-unrouted-fixture', 'exit_code': 0, 'stdout': proc.stdout, 'stderr': proc.stderr,
                 'purpose': title, 'simulation': 'explicit incomplete skeleton, real allocator and baseline; no existing Receipt removed'})
    return tr


def check_receipts(root, turn, record):
    root = root.resolve()
    turn = turn.resolve()
    original_turn = turn
    bootstrap_bytes = (turn / 'evidence/routing.jsonl').read_bytes()
    turn = unrouted_turn_fixture(root, turn, 'receipt-append-negative-fixture')
    scripts = root / '.agent-project-control/scripts'
    log = turn / 'evidence/routing.jsonl'
    assert not log.exists(), 'Receipt negative tests use explicit incomplete input; real bootstrap Receipt is preserved'
    env = _childenv(scripts, {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'})
    turn_rel = turn.relative_to(root).as_posix()
    route_args = ('--phase', 'verification', '--turn-dir', turn_rel)
    restores = []
    proof = {}
    native = root / '.agent-project-control/runtime/tmp/receipt-native.py'
    css = root / '.agent-project-control/runtime/tmp/receipt-target.css'
    assert not native.exists() and not css.exists()
    native.write_bytes(b'# APCF-META {"schema":1,"visibility":"private"}\nvalue = 1\n')
    css.write_bytes(b'/* APCF-META {"schema":1,"visibility":"private"} */\nbody { color: black; }\n')

    def call(number, name, expected, *args, helper=None):
        command = [sys.executable, '-B', str(scripts / name), *args]
        if helper is not None:
            command = [sys.executable, '-B', '-c', helper]
        call_env = env if helper is not None else _childenv(scripts, env)
        proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', env=call_env)
        row = {'script': name, 'case': 'Receipt/matrix-' + str(number).zfill(2),
               'arguments': list(args), 'exit_code': proc.returncode,
               'stdout': proc.stdout, 'stderr': proc.stderr}
        if helper is not None:
            row['simulation'] = 'source/authority changed inside actual emit'
        record(row)
        assert proc.returncode == expected and not proc.stderr, row
        return proc.stdout

    def verify(number, expected=0, phase='verification'):
        return call(number, 'routing_receipt.py', expected, '--turn-dir', turn_rel, '--phase', phase)

    def route(number, expected=0, args=route_args, helper=None):
        return call(number, 'route_context.py', expected, *args, helper=helper)

    def check(number, message, **extra):
        record({'script': 'receipt assertion', 'case': 'Receipt/matrix-' + str(number).zfill(2),
                'arguments': [], 'exit_code': 0, 'stdout': 'PASS: ' + message, 'stderr': '', **extra})

    def mutate(number, path, expected, action):
        original = path.read_bytes()
        try:
            # JSON authority must remain parseable: this case tests receipt
            # byte identity, not a module-import failure from malformed JSON.
            delta = b'\n' if path.suffix == '.json' else b'\n# Receipt temporary mutation\n'
            path.write_bytes(original + delta)
            out = action(number, expected)
            return out
        finally:
            path.write_bytes(original)
            assert path.read_bytes() == original
            restores.append({'case': number, 'path': path.relative_to(root).as_posix(),
                             'sha256': hashlib.sha256(original).hexdigest()})

    try:
        output = route(1)
        one = log.read_bytes()
        assert len(one.splitlines()) == 1
        route(2)
        two = log.read_bytes()
        assert two.startswith(one) and len(two.splitlines()) == 2
        receipts = [json.loads(line) for line in two.splitlines()]
        first, second = receipts
        check(3, 'each JSONL line independently parses', receipt_example=first)
        proof['example'] = first
        assert first['status'] == 'RESOLVED' and first['turn'] == turn_rel
        assert first['request_sha256'] == hashlib.sha256((turn / 'REQUEST.md').read_bytes()).hexdigest()
        verify(4)
        before = log.read_bytes()
        out = route(5, args=('--phase', 'verification'))
        assert 'receipt: not recorded; no --turn-dir supplied' in out and log.read_bytes() == before
        writing_args = ('--phase', 'tools', '--capability', 'human-readable', '--turn-dir', turn_rel)
        out = route('6-resolved', args=writing_args)
        resolved = json.loads(log.read_bytes().splitlines()[-1])
        assert resolved['resolved_capabilities'] == ['writing', 'style', 'human-readable']
        assert {WRITING_INTERFACE, WRITING_SOURCE, STYLE_INTERFACE, STYLE_SOURCE} <= {s['path'] for s in resolved['sources']}
        for source in resolved['sources']:
            path = root / source['path']
            assert source['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
            begin = f"===== APCF ROUTE SOURCE BEGIN | {source['kind']} | {source['path']} =====\n"
            end = f"===== APCF ROUTE SOURCE END | {source['kind']} | {source['path']} ====="
            body = out.split(begin, 1)[1].split(end, 1)[0]
            text = path.read_text(encoding='utf-8')
            assert body == text + ('' if text.endswith('\n') else '\n')
        assert log.read_bytes().startswith(before) and len(log.read_bytes().splitlines()) == 3
        before = log.read_bytes()
        for rel in [WRITING_INTERFACE, STYLE_INTERFACE]:
            with unresolved_interface(root, rel) as path:
                out = route(6, 3, writing_args)
                assert 'ROUTE_UNRESOLVED' in out and log.read_bytes() == before
            restores.append({'case': 6, 'path': rel, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        verify('6-restored', phase='tools')
        out = route(7, 3, ('--phase', 'verification', '--capability', 'unknown-receipt-capability', '--turn-dir', turn_rel))
        assert 'unknown capability' in out and log.read_bytes() == before
        index = root / '.agent-project-control/rules/INDEX.md'
        original = index.read_bytes()
        try:
            changed = re.sub(rb'(\|\s*`R06`\s*\|\s*)`[^`]+`', rb'\1`01-context-state.md`', original, count=1)
            assert changed != original
            index.write_bytes(changed)
            out = route(8, 2)
            assert 'rules index differs from canonical headings' in out and log.read_bytes() == before
        finally:
            index.write_bytes(original)
            assert index.read_bytes() == original
            restores.append({'case': 8, 'path': index.relative_to(root).as_posix(), 'sha256': hashlib.sha256(original).hexdigest()})
        out = route(9, 2, ('--phase', 'verification', '--turn-dir', '.agent-project-control/runtime/tmp'))
        assert 'SOURCE BEGIN' not in out and 'outside iterations/' in out and log.read_bytes() == before
        request = turn / 'REQUEST.md'
        original = request.read_bytes()
        try:
            request.unlink()
            out = route(10, 2)
            assert 'REQUEST.md' in out and 'SOURCE BEGIN' not in out and log.read_bytes() == before
        finally:
            request.write_bytes(original)
            assert request.read_bytes() == original
            restores.append({'case': 10, 'path': request.relative_to(root).as_posix(), 'sha256': hashlib.sha256(original).hexdigest()})
        evidence = turn / 'evidence'
        moved = turn / 'receipt-test-evidence'
        assert not moved.exists() and moved.resolve().parent == turn
        try:
            evidence.rename(moved)
            out = route(11, 2)
            assert 'evidence' in out and 'SOURCE BEGIN' not in out
            assert (moved / 'routing.jsonl').read_bytes() == before
        finally:
            if moved.exists():
                moved.rename(evidence)
            assert log.read_bytes() == before
            restores.append({'case': 11, 'path': log.relative_to(root).as_posix(), 'sha256': hashlib.sha256(before).hexdigest()})
        for row in first['sources']:
            assert row['sha256'] == hashlib.sha256((root / row['path']).read_bytes()).hexdigest()
        check(12, 'all Source SHA-256 values match raw file bytes')
        expected_authority = {'.agent-project-control/framework.yaml', '.agent-project-control/routing.toml',
                              '.agent-project-control/rules/INDEX.md', '.agent-project-control/scripts/route_context.py',
                              '.agent-project-control/scripts/routing_receipt.py'}
        # Report14 and report_bridge add their contracts and implementation to
        # receipt authority. Derive this inventory independently of
        # authority_paths(), so a production omission still fails rather than
        # being copied into the oracle.
        for rel in ('.agent-project-control/reporting', '.agent-project-control/scripts/report14',
                    '.agent-project-control/scripts/report_bridge'):
            expected_authority.update(p.relative_to(root).as_posix() for p in (root / rel).rglob('*')
                                      if p.is_file() and '__pycache__' not in p.parts
                                      and p.name != 'agent.local.json')
        assert {row['path'] for row in first['authority']} == expected_authority
        for row in first['authority']:
            assert row['sha256'] == hashlib.sha256((root / row['path']).read_bytes()).hexdigest()
        check(13, 'all original, Report14, and report_bridge Authority SHA-256 values match raw file bytes')
        module = root / '.agent-project-control/rules/03-verification-regression.md'
        out = mutate(14, module, 2, verify)
        assert 'source[0] changed:' in out
        verify(15)
        for number, rel in [(16, '.agent-project-control/framework.yaml'), (17, '.agent-project-control/routing.toml'),
                            (18, '.agent-project-control/rules/INDEX.md'), (19, '.agent-project-control/scripts/route_context.py'),
                            (20, '.agent-project-control/scripts/routing_receipt.py'),
                            ('20-report14-contract', '.agent-project-control/reporting/contract.json'),
                            ('20-report14-approved', '.agent-project-control/reporting/APPROVED-REFERENCE.md'),
                            ('20-report14-bridge', '.agent-project-control/scripts/report14/bridge.py'),
                            ('20-report-bridge-native', '.agent-project-control/scripts/report_bridge/native.py')]:
            out = mutate(number, root / rel, 2, verify)
            assert 'authority[' in out and 'changed:' in out
        out = mutate(21, request, 2, verify)
        assert 'REQUEST.md changed since routing' in out
        for number, path in [(22, native), (23, turn / 'CHECKLIST.md'), (24, turn / 'TEST.md'), (25, turn / 'TURN.md')]:
            mutate(number, path, 0, verify)

        def corrupt(number, candidate, operations):
            original = log.read_bytes()
            try:
                log.write_bytes(candidate)
                for case, action in operations:
                    out = action(case, 2)
                    assert log.read_bytes() == candidate, 'Failed operation appended to damaged log'
            finally:
                log.write_bytes(original)
                assert log.read_bytes() == original
                restores.append({'case': number, 'path': log.relative_to(root).as_posix(),
                                 'sha256': hashlib.sha256(original).hexdigest()})

        corrupt(26, two + b'{bad-json}\n', [(26, verify), (28, route)])
        corrupt(27, two[:-1], [(27, verify)])
        corrupt('26-blank', two + b'\n', [('26-blank-verifier', verify), ('26-blank-route', route)])
        route(29, args=('--phase', 'verification', '--phase', 'tools', '--turn-dir', turn_rel))
        combined = json.loads(log.read_bytes().splitlines()[-1])
        assert combined['phases'] == ['verification', 'tools']
        assert len(combined['sources']) == len({row['path'] for row in combined['sources']}) == 2
        target = css.relative_to(root).as_posix()
        route(30, args=('--phase', 'scope', '--target', target, '--turn-dir', turn_rel))
        design = json.loads(log.read_bytes().splitlines()[-1])
        assert design['targets'] == [target] and design['resolved_capabilities'] == ['design']
        assert {row['path'] for row in design['sources']} == {
            '.agent-project-control/rules/02-execution-scope.md',
            '.agent-project-control/rules/06-framework-contract.md', *DESIGN_SOURCES}
        route(31, args=('--phase', 'scope', '--capability', 'design', '--target', target, '--turn-dir', turn_rel))
        deduped = json.loads(log.read_bytes().splitlines()[-1])
        assert deduped['declared_capabilities'] == deduped['resolved_capabilities'] == ['design']
        assert len(deduped['sources']) == len({row['path'] for row in deduped['sources']})
        assert {row['path'] for row in deduped['sources']} == {
            '.agent-project-control/rules/02-execution-scope.md',
            '.agent-project-control/rules/06-framework-contract.md', *DESIGN_SOURCES}
        for row in design['sources']:
            assert row['sha256'] == hashlib.sha256((root / row['path']).read_bytes()).hexdigest()
        assert first['receipt_id'] != second['receipt_id']
        assert first['route_fingerprint'] == second['route_fingerprint']
        check(32, 'different receipt_id and identical route_fingerprint', receipt_ids=[first['receipt_id'],second['receipt_id']],
              route_fingerprint=first['route_fingerprint'])
        route(33, args=('--phase', 'tools', '--turn-dir', turn_rel))
        different = json.loads(log.read_bytes().splitlines()[-1])
        assert different['route_fingerprint'] != first['route_fingerprint']
        end = output.rfind('===== APCF ROUTE SOURCE END')
        recorded = output.index('receipt: recorded;')
        passed = output.index('PASS: route context resolved and emitted')
        assert end < recorded < passed
        check(34, 'last SOURCE END precedes recorded message, which precedes PASS')
        for number, rel in [(35, module.relative_to(root).as_posix()), (36, '.agent-project-control/framework.yaml')]:
            old_log = log.read_bytes()
            original = (root / rel).read_bytes()
            helper = ("import sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(scripts)) +
                      ")\nimport route_context as route\npath=Path(" + repr(str(root / rel)) +
                      ")\noriginal=path.read_bytes()\nnormal=route.emit\n" +
                      "def changed(*args):\n normal(*args)\n path.write_bytes(original+b'\\n# Changed inside emit\\n')\n" +
                      "route.emit=changed\nsys.argv=['route_context.py'," +
                      ','.join(repr(x) for x in route_args) + "]\ntry:\n code=route.main()\nfinally:\n path.write_bytes(original)\nsys.exit(code)\n")
            try:
                out = route(number, 2, helper=helper)
                assert 'routing sources changed during emit' in out
                assert log.read_bytes() == old_log and (root / rel).read_bytes() == original
            finally:
                (root / rel).write_bytes(original)
                assert (root / rel).read_bytes() == original
                restores.append({'case': number, 'path': rel, 'sha256': hashlib.sha256(original).hexdigest()})
        out = verify(37, 3, 'unrecorded-test-phase')
        assert 'ROUTE_RECEIPT_NOT_FOUND' in out
        other = Path(call('38-setup', 'new_turn.py', 0, '--title', 'receipt-other-turn', '--request-text', 'Receipt identity fixture').strip().splitlines()[-1])
        other_test = other / 'TEST.md'
        generated_test = other_test.read_text(encoding='utf-8')
        assert '。' not in generated_test, 'new_turn.py TEST default must satisfy the active Writing v0.1 punctuation rule'
        check('38-generated-test', 'new Turn TEST default contains no editable Chinese full stop',
              path=other_test.relative_to(root).as_posix(),
              sha256=hashlib.sha256(other_test.read_bytes()).hexdigest())
        original = log.read_bytes()
        try:
            rows = [json.loads(line) for line in original.splitlines()]
            rows[-1]['turn'] = other.relative_to(root).as_posix()
            log.write_bytes(b''.join(json.dumps(row, ensure_ascii=False).encode('utf-8') + b'\n' for row in rows))
            out = verify(38, 2, 'tools')
            assert 'receipt belongs to a different turn' in out
        finally:
            log.write_bytes(original)
            assert log.read_bytes() == original
            restores.append({'case': 38, 'path': log.relative_to(root).as_posix(), 'sha256': hashlib.sha256(original).hexdigest()})
        verify('38-restored', phase='tools')
        proof['restores'] = restores
        check('restoration', 'all temporary mutation bytes restored', restoration_proof=restores)
        print('PASS: Receipt matrix 1-38 plus blank-line rejection; %d byte-restored mutations' % len(restores))
        return proof
    finally:
        native.unlink(missing_ok=True)
        css.unlink(missing_ok=True)
        assert (original_turn / 'evidence/routing.jsonl').read_bytes() == bootstrap_bytes
        assert turn.resolve().parent == original_turn.resolve().parent
        shutil.rmtree(turn, onerror=remove_readonly)

def check_post_route_audit():
    from contextlib import contextmanager
    from argparse import Namespace

    fixture = _new_core_test_fixture('audit')
    mark(fixture)
    scripts = fixture / '.agent-project-control/scripts'
    passed = set()
    restored = []
    module_before = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in MODULES}

    def invoke(number, name, *args, expected=0, code=None):
        command = [sys.executable, '-B', '-c', code] if code else [sys.executable, '-B', str(scripts / name), *map(str, args)]
        call_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'} if code else _childenv(scripts)
        result = subprocess.run(command, cwd=fixture, capture_output=True, text=True, encoding='utf-8', env=call_env)
        ROWS.append({'case': f'Step1D/{number}', 'script': name, 'arguments': list(map(str, args)), 'exit_code': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
        assert result.returncode == expected, (number, name, result.returncode, result.stdout, result.stderr)
        return result.stdout

    def done(number, **evidence):
        passed.add(number)
        ROWS.append({'case': f'Step1D/{number}/assertions', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '', **evidence})

    def git(*args):
        if not args or args[0] != 'init': assert_fixture_git_root(fixture)
        result = subprocess.run(['git', '-C', str(fixture), *args], capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    @contextmanager
    def mutate(path, candidate):
        path = Path(path)
        original = path.read_bytes() if path.exists() else None
        try:
            if candidate is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(candidate)
            yield
        finally:
            if original is None:
                if path.exists(): path.unlink()
            else:
                path.write_bytes(original)
            assert (path.read_bytes() if path.exists() else None) == original
            restored.append(path.relative_to(fixture).as_posix())

    def turn(number):
        output = invoke(number, 'new_turn.py', '--title', 'audit-' + str(number), '--request-text', 'Step 1D synthetic request')
        path = Path(output.strip().splitlines()[-1])
        assert path == check_bootstrap_output(fixture, output)
        return path

    def audit(number, tr, *args, expected=3):
        if '--semantic-reviewed' in args:
            code = '''
import sys
from pathlib import Path
sys.path.insert(0, __SCRIPTS__)
import routing_activity as activity
tr = Path(__TURN__)
targets = activity.managed_targets(tr)
observations = {}
rows = ['# Synthetic current-object semantic review', '']
for rel in targets:
    state = activity.file_state(rel)
    path = Path(__FIXTURE__) / rel
    if path.is_file():
        raw = path.read_bytes()
        sample = raw[:160].decode('utf-8', 'replace').replace('\\r', ' ').replace('\\n', ' ')
        basis = f"Reviewed {rel} at current SHA-256 {state['sha256']}; inspected candidate begins {sample!r} and remains within its explicit scope."
        rows.append(f"- `{rel}`: state={state['state']}; SHA-256={state['sha256']}; excerpt={sample!r}")
    else:
        basis = f"Reviewed deletion of {rel}; current state is {state['state']} and the absent candidate remains within the same explicit scope."
        rows.append(f"- `{rel}`: state={state['state']}; SHA-256={state['sha256']}")
    observations[rel] = basis
evidence = tr / 'evidence/selfcheck-semantic-review.md'
evidence.write_text('\\n'.join(rows) + '\\n', encoding='utf-8')
activity.record_semantic_review(tr, observations, ['evidence/selfcheck-semantic-review.md'])
'''
            code = (code.replace('__SCRIPTS__', repr(str(scripts)))
                    .replace('__FIXTURE__', repr(str(fixture)))
                    .replace('__TURN__', repr(str(tr))))
            invoke('semantic-evidence', 'routing_activity.py', code=code)
        output = invoke(number, 'audit_routes.py', '--turn-dir', tr, *args, expected=expected)
        report = json.JSONDecoder().raw_decode(output)[0]
        assert report['result'] == {0: 'COVERED', 3: 'ROUTE_GAP', 4: 'ROUTE_UNRESOLVED'}[expected]
        return report

    def route(number, tr, *args, expected=0):
        return invoke(number, 'route_context.py', *args, '--turn-dir', tr, expected=expected)

    def event(number, tr, kind, expected=0):
        return invoke(number, 'routing_activity.py', 'record', '--turn-dir', tr, '--kind', kind, expected=expected)

    try:
        shutil.copytree(CASE / '.agent-project-control', fixture / '.agent-project-control',
                        ignore=shutil.ignore_patterns('runtime', 'iterations', 'materials', 'regressions', 'decisions', 'runbooks', '__pycache__'))
        seed_fixture_root(fixture)
        for name in ['iterations', 'materials', 'regressions', 'decisions', 'runbooks']:
            directory = fixture / '.agent-project-control' / name
            mark(directory)
            (directory / 'INDEX.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. Synthetic index\n', encoding='utf-8')
        for name in ['testbed', 'runs', 'downloads', 'tmp', 'cache', 'large', 'distribution']:
            mark(fixture / '.agent-project-control/runtime' / name)
        mark(fixture / '.agent-project-control/runtime')
        mark(fixture / '.codex'); mark(fixture / '.codex/skills')
        prepare_synthetic_skills(fixture)
        initial_files = {'src/server.py': b'print("initial")\n', 'src/preexisting.py': b'print("initial dirty target")\n',
                         'src/theme.css': b'body { color: black; }\n', 'src/view.tsx': b'export const View = () => null;\n',
                         'src/components/button.js': b'export const button = 1;\n', 'src/nested/AGENTS.md': b'# Nested synthetic instructions\n',
                         'src/nested/server.py': b'print("nested")\n'}
        for rel, content in initial_files.items():
            path = fixture / rel; mark(path.parent); path.write_bytes(content)
        git('init', '-q'); configure_fixture_git_longpaths(fixture); git('config', 'user.name', 'APCF synthetic test'); git('config', 'user.email', 'synthetic@example.invalid')
        git('config', 'core.autocrlf', 'false'); git('config', 'core.hooksPath', '.git/hooks')
        git('add', '--all'); git('commit', '-q', '-m', 'Synthetic baseline')
        invoke(1, 'new_iteration.py', '--title', 'post-route-audit', '--objective', 'Isolated Step 1D matrix')
        dirty = fixture / 'src/preexisting.py'; dirty.write_bytes(b'print("preexisting user work")\n')
        untracked = fixture / 'src/preexisting.txt'; untracked.write_bytes(b'preexisting untracked work\n')
        tr = turn(1); baseline_path = tr / 'evidence/activity-baseline.json'
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        assert baseline['turn'] == tr.relative_to(fixture).as_posix()
        assert baseline['request_sha256'] == hashlib.sha256((tr / 'REQUEST.md').read_bytes()).hexdigest()
        assert set(baseline['turn_files']) == {'REQUEST.md', 'CHECKLIST.md', 'TEST.md', 'TURN.md'}
        assert baseline['git_head'] == git('rev-parse', 'HEAD') and (tr / 'evidence').is_dir()
        done(1, baseline=baseline)
        before = baseline_path.read_bytes()
        invoke(2, 'routing_activity.py', 'init', '--turn-dir', tr, expected=2)
        assert baseline_path.read_bytes() == before; done(2)
        with mutate(baseline_path, None):
            invoke(3, 'audit_routes.py', '--turn-dir', tr, expected=4)
            assert not baseline_path.exists(); done(3)
        wrong = dict(baseline); wrong['turn'] += '-wrong'
        with mutate(baseline_path, json.dumps(wrong).encode()):
            invoke(4, 'audit_routes.py', '--turn-dir', tr, expected=2); done(4)
        request = tr / 'REQUEST.md'
        with mutate(request, request.read_bytes() + b'changed\n'):
            invoke(5, 'audit_routes.py', '--turn-dir', tr, expected=2); done(5)
        unchanged = audit(6, tr, expected=0)
        assert 'src/preexisting.py' not in unchanged['activity']['changed_paths']; done(6, activity=unchanged['activity'])
        with mutate(dirty, dirty.read_bytes() + b'print("new activity")\n'):
            report = audit(7, tr, '--semantic-reviewed')
            assert 'src/preexisting.py' in report['activity']['changed_paths']; done(7)
        assert 'src/preexisting.txt' not in unchanged['activity']['changed_paths']; done(8)
        for content in [b'changed untracked\n', None]:
            with mutate(untracked, content):
                report = audit(9, tr, '--semantic-reviewed')
                assert 'src/preexisting.txt' in report['activity']['changed_paths']
        done(9)
        server = fixture / 'src/server.py'
        with mutate(server, server.read_bytes() + b'print("implementation")\n'):
            report = audit(10, tr, '--semantic-reviewed')
            assert 'scope' in report['required']['phases']; done(10)
        with mutate(fixture / 'src/new.py', b'print("new")\n'):
            report = audit(11, tr, '--semantic-reviewed')
            assert 'src/new.py' in report['activity']['changed_paths'] and 'scope' in report['required']['phases']; done(11)
        with mutate(server, None):
            report = audit(12, tr, '--semantic-reviewed')
            assert 'src/server.py' in report['activity']['changed_paths'] and 'scope' in report['required']['phases']; done(12)
        with mutate(server, server.read_bytes() + b'print("committed activity")\n'):
            git('add', '--all'); git('commit', '-q', '-m', 'Synthetic clean HEAD movement')
            assert git('status', '--porcelain') == ''
            report = audit(13, tr, '--semantic-reviewed')
            assert report['activity']['git_head_changed'] and 'delivery' in report['required']['phases']
            assert 'src/server.py' in report['activity']['changed_paths']
            done(13, clean_before_audit=True, report=report)
        tr = turn(14)
        fw_script = scripts / 'common.py'
        with mutate(fw_script, fw_script.read_bytes() + b'\n# Synthetic activity\n'):
            report = audit(14, tr, '--semantic-reviewed')
            assert {'scope', 'framework'} <= set(report['required']['phases']); done(14)
        readme = fixture / 'README.md'
        with mutate(readme, readme.read_bytes() + b'\nSynthetic README activity\n'):
            report = audit(15, tr)
            assert {'readme', 'human-readable', 'writing', 'style'} <= set(report['required']['capabilities'])
            assert {'readme', 'human-readable', 'writing', 'style'} <= set(report['gaps']['capabilities'])
            assert not report['unresolved']; done(15, report=report)
            for rel, cap in [(WRITING_INTERFACE, 'writing'), (STYLE_INTERFACE, 'style')]:
                with unresolved_interface(fixture, rel):
                    unresolved = audit(40, tr, expected=4)
                    assert any(cap in reason for reason in unresolved['unresolved'])
                restored.append(rel)
            done(40, report=unresolved)
        for rel in ['src/theme.css', 'src/view.tsx', 'src/components/button.js']:
            target = fixture / rel
            with mutate(target, target.read_bytes() + b'\n// synthetic activity\n'):
                report = audit(16, tr)
                assert 'design' in report['required']['capabilities']
        done(16)
        with mutate(fixture / '.agent-project-control/runtime/tmp/neutral.bin', b'neutral'), mutate(fixture / '.agent-project-control/generated/TREE.md', b'neutral\n'):
            report = audit(17, tr, expected=0)
            assert report['required']['phases'] == ['bootstrap'] and not report['required']['capabilities']
            assert all(f['disposition'] == 'neutral' for f in report['facts']); done(17)
        with mutate(tr / 'evidence/sample.json', b'{"synthetic":true}\n'):
            report = audit(18, tr, expected=0)
            assert report['required']['phases'] == ['bootstrap']; done(18)
        for number, name, phase in [(19, 'TEST.md', 'verification'), (20, 'TURN.md', 'finalization')]:
            path = tr / name
            with mutate(path, path.read_bytes() + b'\nSynthetic activity\n'):
                report = audit(number, tr)
                assert phase in report['required']['phases'] and name in report['activity']['turn_file_changes']; done(number)
        public_meta = '<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'
        (tr / 'CHECKLIST.md').write_text(
            public_meta + '# 1. Current fixture checklist\n\n'
            '- 【进行中】【CL-PA-01】【未收口父轮中的并行创建】：在父TR仍处于IN_PROGRESS且验收未完成时，验证受管并行创建可以继续执行\n',
            encoding='utf-8')
        (tr / 'TEST.md').write_text(
            fixture_test_document(public_meta + '# 1. Current fixture acceptance\n\n'
            '- 【进行中】【TEST-PA-01】【对应 CL-PA-01】【未收口父轮中的并行创建】：在【当前合成Turn / 父TR仍为IN_PROGRESS / 完整收口尚未执行】下，执行【记录真实调查计划后创建受管PA】，必须观察到【PA归属父TR且父TR及当前验收仍保持未完成】；实际观察到【当前工作流计划已建立，PA创建尚待本项完整检查】，证据为【Step1D/21后续断言】\n'),
            encoding='utf-8')
        plan_source = r'''
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0, __SCRIPTS__)
import routing_activity as activity
tr=Path(__TURN__)
root=Path(__FIXTURE__)
checklist=(tr/'CHECKLIST.md').read_bytes()
test=(tr/'TEST.md').read_bytes()
turn=(tr/'TURN.md').read_bytes()
targets=activity.managed_targets(tr)
status=next((line.strip() for line in turn.decode('utf-8').splitlines() if 'Status' in line),'')
assert 'IN_PROGRESS' in status
assert '【进行中】【CL-PA-01】' in checklist.decode('utf-8')
assert '【进行中】【TEST-PA-01】' in test.decode('utf-8')
evidence=tr/'evidence/selfcheck-pa-investigation.md'
evidence.write_text('<!-- APCF-META {"schema":1,"visibility":"private"} -->\n'
    '# Investigation before managed PA creation\n\n'
    f'- Parent status: {status}\n'
    f'- Checklist SHA-256: {hashlib.sha256(checklist).hexdigest()}\n'
    f'- TEST SHA-256: {hashlib.sha256(test).hexdigest()}\n'
    f'- TURN SHA-256: {hashlib.sha256(turn).hexdigest()}\n'
    f'- Current managed targets: {targets!r}\n',encoding='utf-8')
record=activity.record_plan(tr,targets,['evidence/selfcheck-pa-investigation.md'],['TEST-PA-01'])
print(json.dumps({'targets':record['targets'],'tests':record['tests'],
                  'regression_tests':record['regression_tests'],
                  'investigation':record['investigation']},ensure_ascii=False))
'''.replace('__SCRIPTS__', repr(str(scripts)))
        plan_source = (plan_source.replace('__FIXTURE__', repr(str(fixture)))
                       .replace('__TURN__', repr(str(tr))))
        plan_output = invoke(21, 'record-fixture-workflow-plan', code=plan_source)
        plan_row = json.loads(plan_output)
        assert plan_row['tests'] == ['TEST-PA-01'] and plan_row['regression_tests'] == ['TEST-PA-01']
        assert '- **Status**：IN_PROGRESS' in (tr / 'TURN.md').read_text(encoding='utf-8')
        assert '【进行中】【CL-PA-01】' in (tr / 'CHECKLIST.md').read_text(encoding='utf-8')
        assert '【进行中】【TEST-PA-01】' in (tr / 'TEST.md').read_text(encoding='utf-8')
        invoke(21, 'route_context.py', '--phase', 'scope', '--phase', 'verification', '--turn-dir', tr)
        pa_output = invoke(21, 'new_parallel.py', tr, '--title', 'audit-pa', '--request-text', 'Synthetic PA activity')
        assert 'phases: tools' in pa_output and 'APCF ROUTE SOURCE BEGIN' in pa_output
        pa = Path(pa_output.strip().splitlines()[-1])
        assert pa.parent == tr / 'parallel'
        assert '- **Status**：IN_PROGRESS' in (tr / 'TURN.md').read_text(encoding='utf-8')
        assert '【进行中】【CL-PA-01】' in (tr / 'CHECKLIST.md').read_text(encoding='utf-8')
        assert '【进行中】【TEST-PA-01】' in (tr / 'TEST.md').read_text(encoding='utf-8')
        # The successful PA creation adds scope and human-readable Markdown activity.
        invoke(21, 'route_context.py', '--phase', 'scope', '--phase', 'verification', '--turn-dir', tr)
        pa_gap = audit('21-capability-gap', tr, '--semantic-reviewed')
        assert set(pa_gap['gaps']['capabilities']) == {'writing', 'style', 'human-readable'}
        assert not pa_gap['gaps']['phases'] and not pa_gap['unresolved']
        invoke(21, 'route_context.py', '--capability', 'human-readable', '--turn-dir', tr)
        report = audit(21, tr, '--semantic-reviewed', expected=0)
        assert pa.name in report['activity']['new_parallel_units'] and 'tools' in report['required']['phases']; done(21)
        tr = turn(22)
        # Import the fixture modules so expected routes use the same real resolver.
        sys.path.insert(0, str(scripts))
        names = ['common', 'route_context', 'routing_receipt', 'routing_activity', 'audit_routes', 'design_contract']
        saved_modules = {name: sys.modules.pop(name, None) for name in names}
        try:
            import route_context as router
            import audit_routes as auditor
            import routing_receipt as receipt
            import design_contract as design
            assert design.ROOT == fixture
            contract = router.load_contract()
            css = fixture / 'src/theme.css'
            with mutate(css, css.read_bytes() + b'\n/* activity */\n'):
                report = audit(22, tr)
                matched, _ = router.matching_capabilities(contract, [css])
                assert set(report['required']['capabilities']) == set(router.capability_closure(contract, matched)); done(22)
            expected_closure = router.capability_closure(contract, {'readme'})
            report = audit(23, tr, '--capability', 'readme')
            assert report['required']['capabilities'] == expected_closure; done(23)
            with mutate(css, css.read_bytes() + b'\n/* multi */\n'), mutate(server, server.read_bytes() + b'print("multi")\n'):
                report = audit(24, tr, '--semantic-reviewed')
                assert len(report['required']['sources']) == len(set(report['required']['sources']))
                args = Namespace(phase=['bootstrap', 'scope'], capability=[], target=['src/theme.css', 'src/server.py'], scope=None, turn_dir=None)
                sources, phases, caps, _ = router.build_route(args, contract)
                assert set(report['required']['sources']) == {router.posix_rel(s.path) for s in sources}
                assert set(report['required']['phases']) == set(phases) and report['required']['capabilities'] == caps; done(24)
            with mutate(server, server.read_bytes() + b'print("generic")\n'):
                unresolved = audit(25, tr, expected=4); done(25, report=unresolved)
                hint_output = invoke('25-legacy-hint', 'audit_routes.py', '--turn-dir', tr,
                                     '--semantic-reviewed', expected=4)
                hint_report = json.JSONDecoder().raw_decode(hint_output)[0]
                assert hint_report['semantic_review']['legacy_hint'] is True
                assert hint_report['semantic_review']['reviewed'] is False
                assert hint_report['semantic_review']['evidence_problems']
                done('25-legacy-hint', hint=hint_report['semantic_review'])
                route(26, tr, '--phase', 'bootstrap', '--phase', 'scope')
                covered = audit(26, tr, '--semantic-reviewed', expected=0); done(26, report=covered)
                added = audit(27, tr, '--semantic-reviewed', '--capability', 'design')
                assert set(covered['required']['phases']) <= set(added['required']['phases'])
                assert set(covered['required']['sources']) <= set(added['required']['sources']) and 'design' in added['required']['capabilities']; done(27)
                explicit = audit(28, tr, '--semantic-reviewed', '--unresolved', 'Pending semantic evidence', expected=4)
                assert 'Pending semantic evidence' in explicit['unresolved']; done(28)
            nested = fixture / 'src/nested/server.py'
            with mutate(nested, nested.read_bytes() + b'print("nested activity")\n'):
                report = audit(29, tr, '--semantic-reviewed')
                assert {'AGENTS.md', 'src/nested/AGENTS.md'} <= set(report['required']['sources']); done(29, report=report)
                assert 'src/nested/AGENTS.md' in report['gaps']['sources']; done(30, report=report)
                route(30, tr, '--phase', 'scope', '--scope', 'src/nested')
                closed = audit(30, tr, '--semantic-reviewed', expected=0)
                assert 'src/nested/AGENTS.md' not in closed['gaps']['sources']
            tr = unrouted_turn_fixture(fixture, turn(31), 'audit-missing-bootstrap')
            report = audit(31, tr)
            assert 'bootstrap' in report['gaps']['phases'] and not report['satisfied']['valid_receipts']; done(31, report=report)
            route(32, tr, '--phase', 'bootstrap')
            report = audit(32, tr, expected=0)
            assert 'bootstrap' in report['satisfied']['phases'] and report['satisfied']['valid_receipts']; done(32, report=report)
            log = tr / 'evidence/routing.jsonl'; original_records = receipt.load_records(log)
            invalid = dict(original_records[0]); invalid['turn'] += '-other'
            with mutate(log, (json.dumps(invalid) + '\n').encode()):
                report = audit(33, tr)
                assert not report['satisfied']['valid_receipts'] and report['satisfied']['invalid_receipts']; done(33)
            authority_source = fixture / '.agent-project-control/rules/01-context-state.md'
            with mutate(authority_source, authority_source.read_bytes() + b'\n<!-- stale source -->\n'):
                report = audit(33, tr, '--semantic-reviewed')
                assert not report['satisfied']['valid_receipts'] and report['satisfied']['invalid_receipts']
            predating = dict(original_records[0]); predating['created_at'] = '2000-01-01T00:00:00-07:00'
            predating.pop('receipt_id'); predating['receipt_id'] = receipt.make_receipt_id(predating)
            assert not receipt.verify_record(predating, tr), receipt.verify_record(predating, tr)
            with mutate(log, (json.dumps(predating) + '\n').encode()):
                report = audit(34, tr)
                assert not report['satisfied']['valid_receipts'] and 'predates' in report['satisfied']['invalid_receipts'][0]['problems'][0]; done(34)
            with mutate(server, server.read_bytes() + b'print("scope gap")\n'):
                report = audit(35, tr, '--semantic-reviewed'); assert 'scope' in report['gaps']['phases']
                route(35, tr, '--phase', 'scope')
                report = audit(35, tr, '--semantic-reviewed', expected=0)
                assert 'scope' not in report['gaps']['phases']; done(35)
            route(36, tr, '--phase', 'framework')
            with mutate(css, css.read_bytes() + b'\n/* design gap */\n'):
                report = audit(36, tr)
                assert '.agent-project-control/rules/06-framework-contract.md' in report['satisfied']['sources']
                assert 'design' in report['gaps']['capabilities']
                assert set(report['gaps']['sources']) == set(DESIGN_SOURCES); done(36, report=report)
                route(37, tr, '--phase', 'scope', '--target', 'src/theme.css')
                report = audit(37, tr, expected=0)
                assert not any(report['gaps'].values()); done(37)
            event(38, tr, 'verification')
            path = tr / 'TEST.md'
            with mutate(path, path.read_bytes() + b'\nSynthetic verification activity\n'):
                report = audit(38, tr); assert 'verification' in report['gaps']['phases']
                route(38, tr, '--phase', 'verification')
                report = audit(38, tr, expected=0); assert 'verification' in report['satisfied']['phases']; done(38)
            config = fixture / '.agent-project-control/routing.toml'
            with mutate(config, config.read_bytes() + b'\n# Changed authority\n'):
                report = audit(39, tr, '--semantic-reviewed')
                assert not report['satisfied']['valid_receipts'] and report['satisfied']['invalid_receipts']; done(39)
            tr = turn(41)
            for number, kind, phase in [(41, 'external-tool', 'tools'), (42, 'delivery', 'delivery'), (43, 'framework-change', 'framework')]:
                event(number, tr, kind)
                report = audit(number, tr)
                assert phase in report['required']['phases']; done(number)
            event(44, tr, 'unknown-kind', expected=3); done(44)
            events = tr / 'evidence/activity.jsonl'
            for bad in [b'not-json\n', b'{"schema":1}', b'\n']:
                with mutate(events, bad):
                    invoke(45, 'audit_routes.py', '--turn-dir', tr, expected=2)
            done(45)
            rows = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
            for key, value in [('phases', []), ('capabilities', ['design'])]:
                bad_rows = [dict(row) for row in rows]; bad_rows[0][key] = value
                with mutate(events, ('\n'.join(json.dumps(row) for row in bad_rows) + '\n').encode()):
                    invoke(46, 'audit_routes.py', '--turn-dir', tr, expected=2)
            done(46)
            report = audit(47, tr)
            assert all(f['disposition'] in {'mapped', 'neutral', 'unresolved'} for f in report['facts'])
            observed = {(f['kind'], f['subject']) for f in report['facts']}
            assert all(('path-change', p) in observed for p in report['activity']['changed_paths'])
            assert all(('turn-file-change', n) in observed for n in report['activity']['turn_file_changes'])
            assert all(('parallel-agent', n) in observed for n in report['activity']['new_parallel_units'])
            assert set(report['activity']['event_ids']) <= {f.get('event_id') for f in report['facts']}; done(47, report=report)
            injection = (f'import sys; sys.path.insert(0, {str(scripts)!r}); import audit_routes as a; old=a.classify_activity; '
                         'a.classify_activity=lambda *args: dict(old(*args), facts=old(*args)["facts"]+[{"kind":"injected","subject":"unconsumed"}]); '
                         f'sys.argv=["audit_routes.py","--turn-dir",{str(tr)!r}]; raise SystemExit(a.main())')
            output = invoke(48, 'audit_routes.py', expected=2, code=injection)
            assert 'not completely consumed' in output; done(48)
            report_path = tr / 'evidence/route-audit.json'
            assert report_path.is_file() and report_path.parent == tr / 'evidence'
            stored = json.loads(report_path.read_text(encoding='utf-8'))
            assert stored['turn'] == tr.relative_to(fixture).as_posix(); done(49)
            again = audit(50, tr)
            assert again['required'] == report['required']
            report_rel = report_path.relative_to(fixture).as_posix()
            assert any(f['subject'] == report_rel and f['disposition'] == 'neutral' for f in again['facts']); done(50)
            # The automated creator must propagate baseline failure and keep its final path contract on success.
            bad_contract = config.read_bytes().replace(b'[audit]\nschema = 1', b'[audit]\nschema = 999')
            assert bad_contract != config.read_bytes()
            with mutate(config, bad_contract):
                before_turns = set((fixture / '.agent-project-control/iterations').glob('IT-*/turns/TR-*'))
                invoke(1, 'new_turn.py', '--title', 'baseline-failure', '--request-text', 'synthetic invalid-baseline request', expected=1)
                assert set((fixture / '.agent-project-control/iterations').glob('IT-*/turns/TR-*')) == before_turns
        finally:
            for name in names:
                sys.modules.pop(name, None)
                if saved_modules[name] is not None: sys.modules[name] = saved_modules[name]
            sys.path.remove(str(scripts))
        expected_cases = set(range(1, 51)) | {'25-legacy-hint'}
        assert passed == expected_cases, (sorted(expected_cases - passed), sorted(passed - expected_cases))
        assert module_before == {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in MODULES}
        done(60, canonical_sha256=module_before)
        ROWS.append({'case': 'Step1D/summary', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '',
                     'matrix_cases': sorted(passed, key=str), 'byte_restored_mutations': restored})
        print('PASS: Post-route Audit matrix 1-50 and 60; immutable baseline, shared resolver, receipt gaps, fact consumption; ' + str(len(restored)) + ' byte-restored mutations')
    finally:
        assert fixture.resolve().parent == CASE.parent.resolve()
        remove_core_test_fixture(fixture, CASE.parent)


def main():
    assert CASE.resolve().is_relative_to((ROOT / '.agent-project-control/runtime/testbed').resolve())
    assert not CASE.exists(), 'Use an unused selfcheck directory'
    mark(CASE)
    excluded = {'runtime','iterations','regressions','decisions','runbooks','materials'}
    for src in ROOT.iterdir():
        if src.is_file() and src.name in ['AGENTS.md','APCF-START.md','README.md','README.en.md','TEMPLATE_SPEC.md','CODEX_PROMPT.md','CODEX_DEPLOY.md','PILOT_TEST_PLAN.md','VALIDATION.md','.gitignore']:
            shutil.copy2(src,CASE/src.name)
    # Root documentation in this disposable fixture is synthetic even when the
    # consumer owns a README mentioning APCF. Never infer permission from its text.
    for name in ['README.md','README.en.md','TEMPLATE_SPEC.md','CODEX_PROMPT.md','CODEX_DEPLOY.md','PILOT_TEST_PLAN.md','VALIDATION.md']:
        (CASE/name).write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# Agent Project Control Framework v0.3.0\n\nSynthetic fixture documentation, not project facts.\n',encoding='utf-8',newline='\n')
    if not (CASE/'.gitignore').is_file():
        (CASE/'.gitignore').write_text('.agent-project-control/runtime/\n',encoding='utf-8',newline='\n')
    for src in (ROOT/'.agent-project-control').rglob('*'):
        rel=src.relative_to(ROOT/'.agent-project-control')
        if rel.parts[0] in excluded or '__pycache__' in rel.parts: continue
        dst=CASE/'.agent-project-control'/rel
        if src.is_dir(): dst.mkdir(parents=True,exist_ok=True)
        else:
            dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    for folder in excluded:
        d=CASE/'.agent-project-control'/folder; mark(d)
        if folder!='runtime':
            (d/'INDEX.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. Synthetic index\n',encoding='utf-8')
    for folder in ['testbed','runs','downloads','tmp','cache','large','distribution']: mark(CASE/'.agent-project-control/runtime'/folder)
    mark(CASE/'.codex'); mark(CASE/'.codex/skills')
    prepare_synthetic_skills(CASE)
    # Core publication audit requires the same valid Git HEAD from Turn creation onward.
    subprocess.run(['git', 'init', '-q', str(CASE)], check=True)
    configure_fixture_git_longpaths(CASE)
    for key, value in [('user.name', 'APCF synthetic test'), ('user.email', 'synthetic@example.invalid'), ('core.hooksPath', '.git/hooks')]:
        subprocess.run(['git', '-C', str(CASE), 'config', key, value], check=True)
    subprocess.run(['git', '-C', str(CASE), 'commit', '-q', '--allow-empty', '-m', 'Synthetic publication Gate baseline'], check=True)
    for p in (ROOT / '.agent-project-control/scripts').glob('*.py'):
        compile(p.read_bytes(), str(p), 'exec')
    run('lint_framework.py')
    run('closeout_selfcheck.py')
    check_rule_surfaces()
    check_router_fixture()
    module = CASE / '.agent-project-control/rules/01-context-state.md'
    original_module = module.read_text(encoding='utf-8')
    first, remainder = original_module.split('## 1.2. R02', 1)
    module.write_text(first.replace('错误示例（Bad Example）', 'Removed example') + '## 1.2. R02' + remainder, encoding='utf-8')
    assert 'R01 missing Bad Example' in run('lint_framework.py', expected=2)
    module.write_text(original_module, encoding='utf-8')
    run('lint_framework.py')
    index = CASE / '.agent-project-control/rules/INDEX.md'
    original_index = index.read_text(encoding='utf-8')
    index.write_text(original_index.replace('01-context-state.md', 'wrong-module.md', 1), encoding='utf-8')
    assert 'rules/INDEX.md drifted' in run('lint_framework.py', expected=2)
    index.write_text(original_index, encoding='utf-8')
    design_index = CASE / '.agent-project-control/design/INDEX.md'
    original_design_index = design_index.read_text(encoding='utf-8')
    design_index.write_text(original_design_index.replace('**D01**.', '**D99**.', 1), encoding='utf-8')
    assert 'design/INDEX.md drifted' in run('lint_framework.py', expected=2)
    run('design_contract.py', '--sync')
    assert design_index.read_text(encoding='utf-8') == original_design_index
    run('design_contract.py', '--check')
    spec=importlib.util.spec_from_file_location('case_design_contract',CASE/'.agent-project-control/scripts/design_contract.py')
    design=importlib.util.module_from_spec(spec); spec.loader.exec_module(design)
    reference=CASE/design.lock_value('reference_archive_path')
    tokens=CASE/design.lock_value('tokens_path')
    assert design.validate_reference_archive(reference,tokens)==[]
    with zipfile.ZipFile(reference) as archive:
        reference_members={name:archive.read(name) for name in archive.namelist()}
    mutated=CASE/'.agent-project-control/runtime/tmp/reference-negative.zip'
    mutated.with_name(mutated.name+'.apcf-meta.yaml').write_text(META,encoding='utf-8')
    for kind in ['history','auto-adopt','html-hash','tokens','history-path']:
        members=dict(reference_members)
        descriptor=json.loads(members['TEMPLATE.json'])
        if kind=='history': descriptor['current_turn']='TR-1234'
        if kind=='auto-adopt': descriptor['auto_adopt']=True
        if kind=='html-hash': members['Workbench.html']+=b'\nchanged'
        if kind=='tokens': members['src/tokens.json']+=b'\n'
        if kind=='history-path': members['iterations/TR-1234/REQUEST.md']=b'Synthetic source request'
        members['TEMPLATE.json']=json.dumps(descriptor).encode('utf-8')
        with zipfile.ZipFile(mutated,'w') as archive:
            for name,data in members.items(): archive.writestr(name,data)
        assert design.validate_reference_archive(mutated,tokens),kind
    mutated.unlink();mutated.with_name(mutated.name+'.apcf-meta.yaml').unlink()
    skill=CASE/'.codex/skills/synthetic-cache'
    mark(skill)
    (skill/'SKILL.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\nSynthetic installed skill\n',encoding='utf-8')
    run('render_tree.py')
    tree=(CASE/'.agent-project-control/generated/TREE.md').read_text(encoding='utf-8')
    assert 'synthetic-cache' not in tree and str(CASE).replace('\\','/') not in tree
    run('lint_framework.py')
    it = Path(run('new_iteration.py', '--title', 'synthetic-goal', '--objective', 'Synthetic lifecycle selfcheck'))
    run('new_iteration.py', '--title', 'conflict', '--objective', 'Second active goal', expected=1)
    tr = Path(run('new_turn.py', '--title', 'synthetic-turn', '--request-text', 'Synthetic request'))
    assert (tr / 'REQUEST.md').read_text(encoding='utf-8').endswith('Synthetic request\n')
    assert '"visibility":"private"' in (tr/'REQUEST.md').read_text(encoding='utf-8').splitlines()[0]
    assert 'visibility: private' in (tr/'evidence/.apcf-dir.yaml').read_text(encoding='utf-8')
    assert 'visibility: private' in (tr/'parallel/.apcf-dir.yaml').read_text(encoding='utf-8')
    check_receipts(CASE, tr, ROWS.append)
    parallel_checklist = ('- 【已完成】【CL-01】【并行入口工作流】：当本轮需要受管并行执行时，因单独路由不能证明已有调查计划，必须记录真实候选检查和当前回归范围并以活动对象SHA保持一致确认通过\n')
    parallel_test = ('- 【PASS】【TEST-001】【对应 CL-01】【当前候选计划】：在【当前候选 / 隔离自检 / 实际路径可读】下，执行【读取并核对本轮候选状态】，必须观察到【当前计划绑定本轮回归且候选状态稳定】；实际观察到【当前计划绑定本轮回归且候选状态稳定】，证据为【synthetic-workflow-check】\n')
    parallel_test = fixture_test_rows(parallel_test)
    (tr/'CHECKLIST.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前执行清单\n\n'+parallel_checklist,encoding='utf-8')
    (tr/'TEST.md').write_text(fixture_test_document('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前验收记录\n\n'+parallel_test),encoding='utf-8')
    record_fixture_evidence(CASE,tr)
    run('route_context.py', '--phase', 'scope', '--phase', 'verification', '--phase', 'finalization', '--turn-dir', tr)
    pa = Path(run('new_parallel.py', tr, '--title', 'synthetic-parallel', '--request-text', 'Synthetic child request'))
    assert not (pa / 'parallel').exists()
    run('new_parallel.py', pa, '--title', 'nested', '--request-text', 'Rejected nested child', expected=1)
    reg = Path(run('new_regression.py', '--title', 'synthetic-regression'))
    adr = Path(run('new_adr.py', '--title', 'synthetic-decision'))
    rb = Path(run('new_runbook.py', '--title', 'synthetic-runbook'))
    source = CASE / '.agent-project-control/runtime/tmp/sample.bin'
    payload = b'synthetic material\x00\x01\xff'
    source.write_bytes(payload)
    (source.with_name(source.name + '.apcf-meta.yaml')).write_text(META, encoding='utf-8')
    mat = Path(run('import_material.py', source))
    assert (mat / 'original/sample.bin').read_bytes() == payload
    assert hashlib.sha256(payload).hexdigest() in (mat / 'MATERIAL.md').read_text(encoding='utf-8')
    run('refresh_indexes.py')
    assert str(CASE).replace('\\', '/') not in (CASE / '.agent-project-control/iterations/INDEX.md').read_text(encoding='utf-8')
    for folder, path in [('regressions', reg), ('decisions', adr), ('runbooks', rb), ('materials', mat)]:
        assert path.name in (CASE / f'.agent-project-control/{folder}/INDEX.md').read_text(encoding='utf-8')
    run('finalize_turn.py', tr, expected=2)
    checklist_body='- 【已完成】【CL-01】【规则加载】：当新的执行轮次开始时，因旧上下文可能导致规则漂移，必须重新读取当前作用域适用规则，并以规则入口和当前范围已核对确认通过\n- 【已完成】【CL-02】【合成结果】：当本轮需要产生可验证结果时，因只运行命令不能证明结果正确，必须生成并检查结果，并以文件存在且内容正确确认通过\n'
    test_body='- 【PASS】【TEST-001】【对应 CL-01】【规则入口存在】：在【当前候选 / 合成环境 / 规则文件可读】下，执行【读取规则入口并核对作用域】，必须观察到【规则入口存在且作用域可确定】；实际观察到【规则入口存在且作用域已确定】，证据为【synthetic-rule】\n- 【PASS】【TEST-002】【对应 CL-02】【结果文件存在】：在【当前候选 / 合成环境 / 输出目录可写】下，执行【生成并读取结果文件】，必须观察到【结果文件存在】；实际观察到【结果文件存在】，证据为【synthetic-file】\n- 【PASS】【TEST-003】【对应 CL-02】【结果内容正确】：在【当前候选 / 合成环境 / 结果文件已生成】下，执行【比较结果内容与预期值】，必须观察到【内容与预期一致】；实际观察到【内容与预期一致】，证据为【synthetic-content】\n'
    test_body = fixture_test_rows(test_body)
    (tr/'CHECKLIST.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前执行清单\n\n'+checklist_body,encoding='utf-8')
    (tr/'TEST.md').write_text(fixture_test_document('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前验收记录\n\n'+test_body),encoding='utf-8')
    run('test_ledger.py', tr/'TEST.md', '--checklist', tr/'CHECKLIST.md')
    good_test=(tr/'TEST.md').read_text(encoding='utf-8')
    bad_ledgers=[
        good_test.replace('【PASS】【TEST-002】','【FAIL】【TEST-002】',1),
        good_test.replace('【对应 CL-02】','【对应 CL-99】',1),
        good_test+good_test.splitlines()[-1]+'\n',
        good_test.replace('；证据：synthetic-rule','；证据：',1),
        good_test.replace('【对应 CL-02】','【对应 CL-01】'),
    ]
    for bad in bad_ledgers:
        (tr/'TEST.md').write_text(bad,encoding='utf-8')
        run('test_ledger.py', tr/'TEST.md', '--checklist', tr/'CHECKLIST.md', expected=2)
    (tr/'TEST.md').write_text(good_test,encoding='utf-8')
    good_checklist=(tr/'CHECKLIST.md').read_text(encoding='utf-8')
    bad_checklists=[
        good_checklist+'- 【已完成】【CL-03】：missing object and coverage\n',
        good_checklist.replace('【CL-02】【合成结果】','【CL-02】',1),
        good_checklist+good_checklist.splitlines()[-1]+'\n',
    ]
    for bad in bad_checklists:
        (tr/'CHECKLIST.md').write_text(bad,encoding='utf-8')
        run('test_ledger.py', tr/'TEST.md', '--checklist', tr/'CHECKLIST.md', expected=2)
    (tr/'CHECKLIST.md').write_text(good_checklist,encoding='utf-8')
    f=tr/'TURN.md'; prefix=f.read_text(encoding='utf-8').split('尚未收口',1)[0]
    report=f'''## 0. 精确状态头

- **结果状态**：合成验证
- **IT / TR**：IT-0001 / TR-0001
- **Checklist 摘要**：2 项已完成
- **Test 摘要**：3 个 TEST-ID 当前 PASS 3，FAIL 0，BLOCKED 0

## 1. 承上启下

上一状态已经具备可运行的合成项目和当前规则入口，但仍需要验证新的当前 TEST 表单以及一条 Checklist 对应多个 TEST 的关系。\n\n本轮因此让 CL-02 同时由结果文件存在和结果内容正确两个独立 TEST 验收，用来确认验收关系可以按真实失效面拆分，而不是机械一一对应。\n\n当前三个 TEST-ID 都已经通过，执行清单与验收记录和源文件一致，因此可以继续验证完整讲解、关键要点和后续行动结构。

## 2. 术语表

- **合成验证（Synthetic Validation）**：不依赖真实用户数据的框架自检

## 3. 执行清单

{checklist_body.strip()}

## 4. 验收记录

{test_body.strip()}

## 5. 完整讲解

本轮检查报告十区块结构，完整清单与完整验收记录分别独立展示；同时检查关键要点和下一步使用带主旨的小标题，且单层行动不伪造二级编号

## 6. 关键要点

- **最终报告现在同时保留完整账本和可快速理解的摘要**：执行清单与验收记录已经被独立展示，因此当前状态不会再被长技术说明淹没，用户既可以快速确认整体进度，也可以逐项核对具体证据。
- **单层行动不再为了格式强行制造二级编号**：平面内容现在直接使用 BP 列表，让编号只在真实存在第二层结构时出现，因此报告层级能够与实际语义保持一致。

## 7. 用户需要执行

- **当前无需用户额外操作**：合成自检由脚本完成

## 8. 需要继续讨论、搜索或决策

- **当前没有需要外部决策的事项**：所有合成输入均已在本地闭环

## 9. 下一步推荐

- **自检通过后再进入真实项目行为测试**：确定性结构错误先由脚本直接拒绝，后续 Router 与真实 Pilot 就可以专注观察模型是否发生语义漂移，从而更准确地定位失败究竟来自规则设计还是模型遵守。
'''
    safe_report=report.replace('。','；')
    arrow_report=safe_report.replace('执行清单与验收记录已经被独立展示，因此当前状态不会再被长技术说明淹没，用户既可以快速确认整体进度，也可以逐项核对具体证据；','执行清单与验收记录独立展示 → 避免状态被长技术说明淹没 → 用户快速确认整体进度')
    f.write_text(prefix+arrow_report,encoding='utf-8')
    run('finalize_turn.py', tr, expected=2)
    f.write_text(prefix+safe_report,encoding='utf-8')
    run('route_context.py', '--phase', 'scope', '--phase', 'verification', '--turn-dir', tr)
    record_fixture_evidence(CASE,tr)
    run('finalize_turn.py', tr)
    assert (CASE/'CURRENT.md').read_text(encoding='utf-8').endswith(safe_report.strip()+'\n')
    assert 'FINALIZED' in f.read_text(encoding='utf-8')
    assert parse_meta(CASE/'CURRENT.md') == {'schema':1,'visibility':'public'}
    run('state_integrity.py')
    saved_turn=f.read_bytes(); f.unlink()
    run('state_integrity.py', expected=2)
    private_evidence=tr/'evidence/.apcf-dir.yaml'
    private_evidence.write_text(META,encoding='utf-8')
    run('repair_current_state.py', expected=1)
    assert not f.exists(), 'repair must not invent a finalized report'
    f.write_bytes(saved_turn)
    run('repair_current_state.py')
    assert f.read_text(encoding='utf-8').split('## 1.1. USER REPORT',1)[1].strip()==safe_report.strip()
    assert private_evidence.read_text(encoding='utf-8')==META
    run('state_integrity.py')
    request=tr/'REQUEST.md'; saved_request=request.read_bytes()
    recovery_originals={p:p.read_bytes() for p in [f,tr/'CHECKLIST.md',tr/'TEST.md',it/'ITERATION.md',request]}
    for missing in recovery_originals: missing.unlink()
    run('repair_current_state.py', expected=1)
    assert all(not p.exists() for p in recovery_originals), 'untrusted recovery fabricated history'
    for missing,original in recovery_originals.items():
        if missing!=request:missing.write_bytes(original)
    run('repair_current_state.py')
    run('state_integrity.py')
    assert not request.exists(), 'repair fabricated REQUEST.md'
    assert checklist_body.strip() in (tr/'CHECKLIST.md').read_text(encoding='utf-8')
    assert test_body.strip() in (tr/'TEST.md').read_text(encoding='utf-8')
    request.write_bytes(saved_request)
    current=CASE/'CURRENT.md'; saved_current=current.read_bytes()
    relative=tr.relative_to(CASE).as_posix()
    current.write_text(current.read_text(encoding='utf-8').replace(relative,'../outside/turns/TR-invalid'),encoding='utf-8')
    run('repair_current_state.py',expected=1)
    assert not (CASE.parent/'outside').exists(), 'escaped Source TURN was written'
    current.write_bytes(saved_current)
    run('state_integrity.py')
    run('set_iteration_status.py', 'IT-0001', 'PAUSED')
    it2 = Path(run('new_iteration.py', '--title', 'synthetic-second-goal', '--objective', 'New goal after pause'))
    run('set_iteration_status.py', 'IT-0002', 'COMPLETED')
    run('set_iteration_status.py', 'IT-0001', 'COMPLETED')
    run('new_turn.py', '--title', 'no-active', expected=1)
    before = source.read_bytes()
    run('cleanup_runtime.py', '--all')
    assert source.read_bytes() == before
    native = CASE / '.agent-project-control/runtime/testbed/native-project'
    mark(native)
    (native / 'native.js').write_text('console.log("native unchanged");\n', encoding='utf-8')
    native_bytes = (native / 'native.js').read_bytes()
    run('bootstrap.py', native)
    assert (native/'CURRENT.md').exists(), 'bootstrap must initialize root CURRENT.md'
    assert not any((native/'.agent-project-control/iterations').glob('IT-*')), 'bootstrap copied template-source IT/TR history'
    assert not any((native/'.agent-project-control/materials').glob('MAT-*')), 'bootstrap copied template-source materials'
    assert (native/'.agent-project-control/design/INDEX.md').is_file(), 'bootstrap missed shared design router'
    assert (native/'.agent-project-control/design/profiles/tool-workbench-2.3.1/PROFILE.md').is_file(), 'bootstrap missed optional Workbench Profile'
    target_design=(native/'.agent-project-control/DESIGN.md').read_text(encoding='utf-8')
    assert '**采用状态**：`UNRESOLVED`' in target_design and '**Profile 状态**：`UNRESOLVED`' in target_design, 'bootstrap copied adopted design profile state'
    run('design_contract.py', '--check')
    assert (native / 'native.js').read_bytes() == native_bytes
    assert not (native / '.agent-project-control/runtime/tmp/sample.bin').exists(), 'bootstrap copied runtime material'
    assert not (native/'.codex/skills/synthetic-cache').exists(), 'bootstrap copied installed skill cache'
    assert not (native/'.agent-project-control/materials'/mat.name).exists(), 'bootstrap copied private source material'
    run('bootstrap.py', native, expected=1)
    run('lint_framework.py')
    subprocess.run(['git', 'init', '-q', str(CASE)], check=True)
    configure_fixture_git_longpaths(CASE)
    marker=CASE/'.agent-project-control/runtime/testbed/nested/.apcf-dir.yaml'
    mark(marker.parent)
    ignored=subprocess.run(['git','-C',str(CASE),'check-ignore',str(marker)],capture_output=True,text=True)
    assert ignored.returncode==0, 'nested runtime marker is not ignored'
    run('repair_current_state.py', '--stage')
    run('state_integrity.py', '--require-tracked')
    private = CASE / '.agent-project-control/private-check.md'
    private.write_text('<!-- APCF-META {"schema":1,"visibility":"private"} -->\nSynthetic private content\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(CASE), 'add', '.agent-project-control/private-check.md'], check=True)
    run('route_context.py', '--phase', 'scope', '--phase', 'verification', '--phase', 'framework',
        '--phase', 'finalization', '--capability', 'github-publish', '--capability', 'human-readable', '--turn-dir', tr)
    record_fixture_evidence(CASE, tr)
    private_guard_output=run('publish_guard.py', '--turn-dir', tr, expected=2, full_output=True)
    assert '.agent-project-control/private-check.md: private object staged' in private_guard_output
    assert 'state-integrity:' not in private_guard_output
    private_gate=json.loads((tr/'evidence/gate-latest.json').read_text(encoding='utf-8'))
    assert private_gate['result']=='PASS' and private_gate['findings']==[], 'Full Gate must pass before the source privacy scan'
    subprocess.run(['git', '-C', str(CASE), 'rm', '--cached', '-q', '.agent-project-control/private-check.md'], check=True)
    turn_rel=tr.relative_to(CASE).as_posix()+'/TURN.md'
    subprocess.run(['git', '-C', str(CASE), 'rm', '--cached', '-q', turn_rel], check=True)
    untracked_state=run('state_integrity.py', '--require-tracked', expected=2, full_output=True)
    untracked_state_paths=untracked_state.replace('\\','/')
    assert turn_rel in untracked_state_paths and 'not Git-tracked' in untracked_state
    run('repair_current_state.py', '--stage')
    record_fixture_evidence(CASE, tr)
    run('state_integrity.py','--require-tracked')
    for p in [current,f]: p.write_text(p.read_text(encoding='utf-8')+'\nSynthetic unstaged report update\n',encoding='utf-8')
    record_fixture_evidence(CASE, tr)
    run('state_integrity.py')
    state_failure=run('state_integrity.py','--require-tracked',expected=2,full_output=True)
    state_failure_paths=state_failure.replace('\\','/')
    assert 'CURRENT.md' in state_failure_paths and 'TURN.md' in state_failure_paths and 'not Git-tracked or index differs' in state_failure
    run('route_context.py', '--phase', 'scope', '--phase', 'verification', '--phase', 'finalization',
        '--capability', 'github-publish', '--capability', 'human-readable', '--turn-dir', tr)
    publish_state_failure=run('publish_guard.py', '--turn-dir', tr, expected=2, full_output=True)
    assert 'state-integrity:' in publish_state_failure and 'CURRENT.md' in publish_state_failure and 'TURN.md' in publish_state_failure
    assert json.loads((tr/'evidence/gate-latest.json').read_text(encoding='utf-8'))['result']=='PASS'
    run('repair_current_state.py','--stage')
    run('route_context.py', '--phase', 'scope', '--phase', 'verification', '--phase', 'finalization',
        '--capability', 'github-publish', '--capability', 'human-readable', '--turn-dir', tr)
    run('publish_guard.py', '--turn-dir', tr)
    tracked=subprocess.check_output(['git','-C',str(CASE),'ls-files'],text=True,encoding='utf-8').splitlines()
    assert request.relative_to(CASE).as_posix() not in tracked
    assert private_evidence.relative_to(CASE).as_posix() not in tracked
    # Locked design text remains byte-identical after a real Windows-style checkout.
    subprocess.run(['git','-C',str(CASE),'config','core.autocrlf','true'],check=True)
    subprocess.run(['git','-C',str(CASE),'add','.agent-project-control/design'],check=True,capture_output=True)
    checkout=CASE/'.agent-project-control/runtime/tmp/design-checkout'
    subprocess.run(['git','-C',str(CASE),'checkout-index','--all','--prefix='+checkout.as_posix()+'/'],check=True,capture_output=True)
    for rel in ['RULES.md','profiles/tool-workbench-2.3.1/tokens.json']:
        assert (CASE/'.agent-project-control/design'/rel).read_bytes()==(checkout/'.agent-project-control/design'/rel).read_bytes(),rel
    git_dir=(CASE/'.git').resolve()
    assert git_dir.parent==CASE.resolve()
    shutil.rmtree(git_dir,onerror=remove_readonly)
    (CASE / '.apcf-dir.yaml').write_text(META, encoding='utf-8')
    note=tr/'evidence/COMPACT-NOTE.md'
    note.write_text('<!-- APCF-META {"schema":1,"visibility":"private"} -->\n'+it2.name+'\n'+mat.name+'\n',encoding='utf-8')
    framework_path=CASE/'.agent-project-control/framework.yaml'
    framework_original=framework_path.read_bytes()
    framework_text=framework_original.decode('utf-8')
    def framework_mode(value):
        changed,count=re.subn(r'(?m)^(template_source:[ \t]*)(?:true|false)(\r?)$',
                              lambda match:match.group(1)+value+match.group(2),framework_text)
        assert count==1, 'framework source-mode field must be unique in the isolated CASE'
        return changed.encode('utf-8')
    protected_before={path:path.read_bytes() for path in [CASE/'CURRENT.md',it2/'ITERATION.md',tr/'TURN.md',
                       tr/'CHECKLIST.md',tr/'TEST.md',mat/'MATERIAL.md']}
    try:
        downstream_bytes=framework_mode('false')
        framework_path.write_bytes(downstream_bytes)
        run('compact_template_source.py',expected=1)
        downstream_output=ROWS[-1]['stderr']
        assert 'FAIL: compaction is allowed only in the template source repository' in downstream_output
        assert framework_path.read_bytes()==downstream_bytes, 'downstream rejection changed framework mode bytes'
        assert all(path.read_bytes()==data for path,data in protected_before.items()), 'downstream compaction rejection changed durable or historical objects'

        source_bytes=framework_mode('true')
        framework_path.write_bytes(source_bytes)
        run('compact_template_source.py')
        preview=ROWS[-1]['stdout']
        assert 'DRY-RUN '+str(it2.relative_to(CASE)) in preview, 'source preview falsely retained old iteration'
        assert 'DRY-RUN '+str(mat.relative_to(CASE)) in preview, 'source preview falsely retained old material'
        assert framework_path.read_bytes()==source_bytes, 'source preview changed framework mode bytes'
        assert all(path.read_bytes()==data for path,data in protected_before.items()), 'source preview changed durable or historical objects'
    finally:
        framework_path.write_bytes(framework_original)
    assert framework_path.read_bytes()==framework_original, 'isolated compaction mode test did not restore framework bytes'
    native_source = CASE/'native-source.py'
    native_bytes = b'print("native source unchanged")\n'
    native_source.write_bytes(native_bytes)
    native_source.with_name(native_source.name+'.apcf-meta.yaml').write_text(META,encoding='utf-8')
    cleanup_before={p:p.read_bytes() for p in (CASE/'.agent-project-control/runtime').rglob('*') if p.is_file()}
    run('cleanup_runtime.py', '--all', '--apply', expected=1)
    assert all(p.is_file() and p.read_bytes()==data for p,data in cleanup_before.items()), 'refused cleanup mutated evidence'
    runtime = CASE/'.agent-project-control/runtime'
    # Owned disposable fixture teardown (not production cleanup authorization).
    for directory in runtime.iterdir():
        if directory.is_dir():
            for p in list(directory.iterdir()):
                if p.name!='.apcf-dir.yaml':
                    shutil.rmtree(p,onerror=remove_readonly) if p.is_dir() else p.unlink()
        elif directory.name!='.apcf-dir.yaml':directory.unlink()
    assert {p.name for p in runtime.iterdir()} == {'testbed','runs','downloads','tmp','cache','large','distribution','.apcf-dir.yaml'}
    assert all(list(p.iterdir()) == [p/'.apcf-dir.yaml'] for p in runtime.iterdir() if p.is_dir())
    assert native_source.read_bytes() == native_bytes, 'runtime cleanup changed native source'
    check_post_route_audit()
    check_gate_routes()
    check_core_profiles_bootstrap()
    check_core_entrypoints()
    assert any(r.get('case') == 'Step1D/summary' for r in ROWS)
    assert any(r.get('case') == 'Step1EA/matrix-summary' for r in ROWS)
    cases = {int(r['case'].split('/')[1]) for r in ROWS if r.get('case', '').startswith('Step1EB/') and r['case'].endswith('/assertions')}
    assert cases == set(range(1, 91)), sorted(set(range(1, 91)) - cases)
    ROWS.append({'case': 'Step1EB/91/assertions', 'exit_code': 0, 'stdout': 'PASS: original regression chain and cases 1-90', 'stderr': ''})
    print('PASS:', len(ROWS), 'script invocations and lifecycle assertions')

def check_gate_kernel_cases(kernel, turn_factory, done, mutate):
    """Run the assigned Step 1E-A cases against an imported real gate_kernel."""
    records_by_case: dict[int, list[dict]] = {}
    failures: list[dict] = []

    def _turn(number: int) -> Path:
        path = Path(turn_factory(number))
        if not path.is_absolute():
            path = Path(kernel.ROOT) / path
        return path.resolve()

    def _paths(turn: Path) -> tuple[Path, Path]:
        return kernel.gate_paths(turn, kernel.load_gate_contract())

    def _file_bytes(path: Path) -> bytes | None:
        return path.read_bytes() if path.is_file() else None

    def _state(value: bytes | None) -> dict:
        return {
            "exists": value is not None,
            "length": len(value) if value is not None else 0,
            "sha256": hashlib.sha256(value).hexdigest() if value is not None else None,
        }

    def _evaluate(
        number: int,
        turn: Path,
        candidate: dict,
        findings: list[dict],
        *,
        gate_id: str | None = None,
    ) -> tuple[int, dict]:
        attempts, latest = _paths(turn)
        turn_rel = kernel.posix_rel(turn)
        before = kernel.load_history(attempts, turn_rel)
        exit_code, record = kernel.evaluate_gate(
            turn_dir_raw=turn,
            gate_id=gate_id or f"step1ea-case-{number:02d}",
            candidate_snapshot=candidate,
            findings=findings,
            adapter="step1ea-isolated-kernel-test",
        )
        records_by_case.setdefault(number, []).append(record)
        after = kernel.load_history(attempts, turn_rel)
        assert after == before + [record], "evaluate_gate did not append/reload the full Attempt"
        assert json.loads(latest.read_text(encoding="utf-8")) == record, "gate-latest.json differs from appended Attempt"
        return exit_code, record

    def _invalid_without_writes(
        number: int,
        turn: Path,
        target: Path,
        replacement: bytes | None,
        *,
        candidate: dict | None = None,
        findings: list[dict] | None = None,
    ) -> dict:
        attempts, latest = _paths(turn)
        with mutate(target, replacement):
            before_attempts = _file_bytes(attempts)
            before_latest = _file_bytes(latest)
            try:
                kernel.evaluate_gate(
                    turn_dir_raw=turn,
                    gate_id=f"step1ea-case-{number:02d}",
                    candidate_snapshot=candidate or {"case": number},
                    findings=findings or [],
                    adapter="step1ea-isolated-kernel-test",
                )
            except kernel.GateError as exc:
                assert exc.code == 2, f"expected GateError.code == 2, got {exc.code}: {exc}"
                error = str(exc)
            else:
                raise AssertionError("invalid gate input unexpectedly evaluated successfully")
            after_attempts = _file_bytes(attempts)
            after_latest = _file_bytes(latest)
            assert after_attempts == before_attempts, "invalid gate input changed gate-attempts.jsonl"
            assert after_latest == before_latest, "invalid gate input changed gate-latest.json"
        return {
            "gate_error_code": 2,
            "error": error,
            "attempts_state": _state(before_attempts),
            "latest_state": _state(before_latest),
        }

    def _finding(
        code: str = "SYNTHETIC_FAILURE",
        subject: str = "subject-a",
        *,
        message: str = "synthetic finding",
        evidence: list | None = None,
        target: str = "file:synthetic-a",
        repairability: str = "repairable",
        include_repair: bool = True,
    ) -> dict:
        finding = {
            "source": "step1ea-synthetic",
            "code": code,
            "subject": subject,
            "message": message,
            "repairability": repairability,
            "scope": ["synthetic-scope"],
            "evidence": evidence if evidence is not None else [{"detail": "evidence-a"}],
        }
        if include_repair:
            finding["repair"] = {
                "kind": "edit",
                "target": target,
                "instruction": "repair the synthetic condition",
                "verification": "re-evaluate the synthetic condition",
                "scope": ["synthetic-scope"],
            }
        return finding

    def _record_rows(path: Path) -> list[dict]:
        return [json.loads(line.decode("utf-8")) for line in path.read_bytes().splitlines() if line.strip()]

    def _run(number: int, body) -> None:
        records_by_case.setdefault(number, [])
        try:
            evidence = body() or {}
        except Exception as exc:
            failures.append(
                {
                    "case": number,
                    "error": f"{type(exc).__name__}: {exc}",
                    "records": records_by_case[number],
                }
            )
        else:
            done(number, records=records_by_case[number], **evidence)

    def case_1() -> dict:
        contract = kernel.load_gate_contract()
        assert contract["schema"] == kernel.GATE_SCHEMA == 1
        assert contract["exit_codes"] == {
            "PASS": 0,
            "INVALID": 2,
            "REPAIR_REQUIRED": 3,
            "BLOCKED": 4,
            "NO_PROGRESS": 5,
        }
        assert contract["attempts_relpath"] and contract["latest_relpath"] and contract["default_gate_id"]
        assert contract["convergence"]["cycle_scope"] == "since-last-pass"
        return {"schema": contract["schema"], "exit_codes": contract["exit_codes"], "cycle_scope": contract["convergence"]["cycle_scope"]}

    def case_2() -> dict:
        turn = _turn(2)
        contract_path = Path(kernel.GATE_CONTRACT)
        original = contract_path.read_bytes()
        lines = original.splitlines(keepends=True)
        damaged = b"".join(line for line in lines if not line.lstrip().startswith(b"attempts_relpath"))
        assert damaged != original, "could not locate attempts_relpath in gate contract"
        return _invalid_without_writes(2, turn, contract_path, damaged)

    def case_3() -> dict:
        turn = _turn(3)
        code, record = _evaluate(3, turn, {"candidate": "pass"}, [])
        assert code == 0 and record["result"] == kernel.RESULT_PASS
        assert record["attempt_id"].startswith("GA-")
        return {"exit_code": code, "result": record["result"], "attempt_id": record["attempt_id"]}

    def case_4() -> dict:
        turn = _turn(4)
        code, record = _evaluate(4, turn, {"candidate": "repairable"}, [_finding()])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "INITIAL"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_5() -> dict:
        turn = _turn(5)
        blocked = _finding(code="BLOCKED_FAILURE", repairability="blocked", include_repair=False)
        code, record = _evaluate(5, turn, {"candidate": "blocked"}, [blocked])
        assert code == 4 and record["result"] == kernel.RESULT_BLOCKED
        return {"exit_code": code, "result": record["result"], "finding_ids": record["finding_ids"]}

    def case_6() -> dict:
        turn = _turn(6)
        code, record = _evaluate(6, turn, {"candidate": "latest"}, [])
        attempts, latest = _paths(turn)
        assert json.loads(latest.read_text(encoding="utf-8")) == record
        rows = _record_rows(attempts)
        assert rows[-1] == record
        return {"exit_code": code, "latest_matches_attempt": True, "attempt_count": len(rows)}

    def case_7() -> dict:
        turn = _turn(7)
        _evaluate(7, turn, {"candidate": "jsonl"}, [])
        _evaluate(7, turn, {"candidate": "jsonl-next"}, [])
        attempts, _ = _paths(turn)
        raw = attempts.read_bytes()
        assert raw.endswith(b"\n")
        lines = raw.splitlines()
        assert lines and all(line.strip() for line in lines)
        parsed = [json.loads(line.decode("utf-8")) for line in lines]
        assert len(parsed) == len(lines)
        return {"independent_json_rows": len(parsed), "newline_terminated": True}

    def case_8() -> dict:
        turn = _turn(8)
        attempts, _ = _paths(turn)
        return _invalid_without_writes(8, turn, attempts, b"{not-json}\n")

    def case_9() -> dict:
        turn = _turn(9)
        _evaluate(9, turn, {"seed": 1}, [], gate_id="step1ea-case-09")
        attempts, _ = _paths(turn)
        original = attempts.read_bytes()
        assert original.endswith(b"\n")
        return _invalid_without_writes(9, turn, attempts, original[:-1])

    def case_10() -> dict:
        turn = _turn(10)
        _evaluate(10, turn, {"seed": 1}, [], gate_id="step1ea-case-10")
        attempts, _ = _paths(turn)
        original = attempts.read_bytes()
        assert original.endswith(b"\n")
        return _invalid_without_writes(10, turn, attempts, original + b"\n")

    def case_11() -> dict:
        turn = _turn(11)
        _evaluate(11, turn, {"seed": 1}, [], gate_id="step1ea-case-11")
        attempts, _ = _paths(turn)
        rows = _record_rows(attempts)
        rows[0]["adapter"] = "tampered-without-rehash"
        damaged = b"".join(kernel.canonical_json(row) + b"\n" for row in rows)
        return _invalid_without_writes(11, turn, attempts, damaged)

    def case_12() -> dict:
        turn = _turn(12)
        _evaluate(12, turn, {"seed": 1}, [], gate_id="step1ea-case-12")
        _evaluate(12, turn, {"seed": 2}, [], gate_id="step1ea-case-12")
        attempts, _ = _paths(turn)
        rows = _record_rows(attempts)
        assert len(rows) == 2
        rows[1]["previous_attempt_hash"] = "f" * 64
        damaged = b"".join(kernel.canonical_json(row) + b"\n" for row in rows)
        return _invalid_without_writes(12, turn, attempts, damaged)

    def case_13() -> dict:
        turn = _turn(13)
        _evaluate(13, turn, {"seed": 1}, [], gate_id="step1ea-case-13")
        attempts, _ = _paths(turn)
        rows = _record_rows(attempts)
        rows[0]["turn"] = ".agent-project-control/iterations/TR-OTHER"
        damaged = b"".join(kernel.canonical_json(row) + b"\n" for row in rows)
        return _invalid_without_writes(13, turn, attempts, damaged)

    def case_14() -> dict:
        candidate = {"business_files": {"src/a.py": "a" * 64}, "checklist_sha256": "b" * 64}
        snapshot_copy = json.loads(json.dumps(candidate, sort_keys=True))
        first = kernel.candidate_fingerprint(candidate)
        second = kernel.candidate_fingerprint(snapshot_copy)
        assert first == second
        return {"candidate_fingerprint": first, "recomputed_fingerprint": second}

    def case_21() -> dict:
        first = _finding(message="first text", evidence=[{"item": "first"}])
        second = _finding(message="changed text", evidence=[{"item": "second"}])
        first_id = kernel.normalize_findings([first])[0]["finding_id"]
        second_id = kernel.normalize_findings([second])[0]["finding_id"]
        assert first_id == second_id
        return {"finding_id": first_id, "message_changed": True, "evidence_changed": True}

    def case_22() -> dict:
        first = kernel.normalize_findings([_finding(code="SAME_CODE", subject="subject-a")])[0]
        second = kernel.normalize_findings([_finding(code="SAME_CODE", subject="subject-b")])[0]
        assert first["finding_id"] != second["finding_id"]
        return {"finding_ids": [first["finding_id"], second["finding_id"]]}

    def case_23() -> dict:
        a = _finding(code="FAIL_A", subject="a")
        b = _finding(code="FAIL_B", subject="b")
        forward = kernel.failure_fingerprint(kernel.normalize_findings([a, b]))
        reverse = kernel.failure_fingerprint(kernel.normalize_findings([b, a]))
        assert forward == reverse
        return {"failure_fingerprint": forward}

    def case_24() -> dict:
        a = _finding(code="REPAIR_A", subject="a", target="file:a")
        b = _finding(code="REPAIR_B", subject="b", target="file:b")
        forward = kernel.repair_fingerprint(kernel.build_repair_set(kernel.normalize_findings([a, b])))
        reverse = kernel.repair_fingerprint(kernel.build_repair_set(kernel.normalize_findings([b, a])))
        assert forward == reverse
        return {"repair_fingerprint": forward}

    def case_25() -> dict:
        findings = kernel.normalize_findings(
            [
                _finding(code="SHARED_A", subject="a", target="file:shared"),
                _finding(code="SHARED_B", subject="b", target="file:shared"),
            ]
        )
        repairs = kernel.build_repair_set(findings)
        assert len(repairs) == 1
        return {"repair_ids": [repair["repair_id"] for repair in repairs]}

    def case_26() -> dict:
        findings = kernel.normalize_findings(
            [
                _finding(code="MERGE_A", subject="a", target="file:shared"),
                _finding(code="MERGE_B", subject="b", target="file:shared"),
            ]
        )
        repairs = kernel.build_repair_set(findings)
        assert len(repairs) == 1
        assert repairs[0]["finding_ids"] == sorted(finding["finding_id"] for finding in findings)
        return {"repair_set": repairs}

    def case_27() -> dict:
        findings = kernel.normalize_findings(
            [
                _finding(code="TARGET_A", subject="a", target="file:a"),
                _finding(code="TARGET_B", subject="b", target="file:b"),
            ]
        )
        repairs = kernel.build_repair_set(findings)
        assert len(repairs) == 2
        assert {repair["target"] for repair in repairs} == {"file:a", "file:b"}
        return {"repair_set": repairs}

    def case_28() -> dict:
        turn = _turn(28)
        bad = _finding(code="BLOCKED_HAS_REPAIR", repairability="blocked", include_repair=True)
        attempts, _ = _paths(turn)
        return _invalid_without_writes(28, turn, attempts, _file_bytes(attempts), findings=[bad])

    def case_29() -> dict:
        turn = _turn(29)
        bad = _finding(code="MISSING_REPAIR", repairability="repairable", include_repair=False)
        attempts, _ = _paths(turn)
        return _invalid_without_writes(29, turn, attempts, _file_bytes(attempts), findings=[bad])

    def case_35() -> dict:
        turn = _turn(35)
        code, record = _evaluate(35, turn, {"candidate": "first"}, [_finding()])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "INITIAL"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_36() -> dict:
        turn = _turn(36)
        finding = _finding(code="SAME_FAILURE", subject="same")
        _evaluate(36, turn, {"candidate": "same"}, [finding])
        code, record = _evaluate(36, turn, {"candidate": "same"}, [finding])
        assert code == 5 and record["result"] == kernel.RESULT_NO_PROGRESS
        assert record["transition"]["kind"] == "STALLED"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_37() -> dict:
        turn = _turn(37)
        finding = _finding(code="SAME_FAILURE", subject="same")
        _evaluate(37, turn, {"candidate": "before"}, [finding])
        code, record = _evaluate(37, turn, {"candidate": "after"}, [finding])
        assert code == 5 and record["result"] == kernel.RESULT_NO_PROGRESS
        assert record["transition"]["kind"] == "STALLED"
        assert record["transition"]["no_progress_reason"] == "candidate-changed-but-failure-set-unchanged"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_38() -> dict:
        turn = _turn(38)
        a = _finding(code="A", subject="A")
        b = _finding(code="B", subject="B")
        _evaluate(38, turn, {"candidate": "before"}, [a, b])
        code, record = _evaluate(38, turn, {"candidate": "after"}, [a])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "IMPROVED"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_39() -> dict:
        turn = _turn(39)
        a = _finding(code="A", subject="A")
        b = _finding(code="B", subject="B")
        _evaluate(39, turn, {"candidate": "before"}, [a])
        code, record = _evaluate(39, turn, {"candidate": "after"}, [a, b])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "REGRESSED"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_40() -> dict:
        turn = _turn(40)
        a = _finding(code="A", subject="A")
        b = _finding(code="B", subject="B")
        c = _finding(code="C", subject="C")
        _evaluate(40, turn, {"candidate": "before"}, [a, b])
        code, record = _evaluate(40, turn, {"candidate": "after"}, [a, c])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "MIXED"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_41() -> dict:
        turn = _turn(41)
        a = _finding(code="A", subject="A")
        b = _finding(code="B", subject="B")
        _evaluate(41, turn, {"candidate": "before"}, [a])
        code, record = _evaluate(41, turn, {"candidate": "after"}, [b])
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "CHANGED", (
            "case 41 requires disjoint {A}->{B} to classify as CHANGED; "
            f"the actual kernel returned {record['transition']['kind']}"
        )
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_42() -> dict:
        turn = _turn(42)
        a = _finding(code="A", subject="A")
        b = _finding(code="B", subject="B")
        _evaluate(42, turn, {"candidate": "one"}, [a])
        _evaluate(42, turn, {"candidate": "two"}, [b])
        code, record = _evaluate(42, turn, {"candidate": "three"}, [a])
        assert code == 5 and record["result"] == kernel.RESULT_NO_PROGRESS
        assert record["transition"]["kind"] == "CYCLE"
        return {"exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_43() -> dict:
        turn = _turn(43)
        a = _finding(code="A", subject="A")
        _evaluate(43, turn, {"candidate": "failure"}, [a])
        pass_code, pass_record = _evaluate(43, turn, {"candidate": "pass"}, [])
        code, record = _evaluate(43, turn, {"candidate": "failure-again"}, [a])
        assert pass_code == 0 and pass_record["result"] == kernel.RESULT_PASS
        assert code == 3 and record["result"] == kernel.RESULT_REPAIR
        assert record["transition"]["kind"] == "INITIAL"
        return {"pass_result": pass_record["result"], "exit_code": code, "result": record["result"], "transition": record["transition"]}

    def case_44() -> dict:
        turn = _turn(44)
        outcomes = [_evaluate(44, turn, {"pass": index}, [])[1] for index in range(3)]
        assert all(record["result"] == kernel.RESULT_PASS for record in outcomes)
        assert all(record["exit_code"] == 0 for record in outcomes)
        return {"results": [record["result"] for record in outcomes], "exit_codes": [record["exit_code"] for record in outcomes]}

    def case_45() -> dict:
        turn = _turn(45)
        blocked = _finding(code="BLOCKED_REPEAT", subject="same", repairability="blocked", include_repair=False)
        first_code, first = _evaluate(45, turn, {"candidate": "one"}, [blocked])
        second_code, second = _evaluate(45, turn, {"candidate": "two"}, [blocked])
        assert first_code == second_code == 4
        assert first["result"] == second["result"] == kernel.RESULT_BLOCKED
        return {
            "exit_codes": [first_code, second_code],
            "results": [first["result"], second["result"]],
            "transitions": [first["transition"], second["transition"]],
        }

    for number, body in (
        (1, case_1), (2, case_2), (3, case_3), (4, case_4), (5, case_5), (6, case_6), (7, case_7),
        (8, case_8), (9, case_9), (10, case_10), (11, case_11), (12, case_12), (13, case_13), (14, case_14),
        (21, case_21), (22, case_22), (23, case_23), (24, case_24), (25, case_25), (26, case_26), (27, case_27),
        (28, case_28), (29, case_29),
        (35, case_35), (36, case_36), (37, case_37), (38, case_38), (39, case_39), (40, case_40), (41, case_41),
        (42, case_42), (43, case_43), (44, case_44), (45, case_45),
    ):
        _run(number, body)

    if failures:
        details = json.dumps(failures, ensure_ascii=False, sort_keys=True, default=str)
        raise AssertionError(f"Step 1E-A Gate Kernel assigned cases failed: {details}")


def check_gate_routes():
    protected_agents = (ROOT / 'AGENTS.md').read_bytes()
    from contextlib import contextmanager
    import importlib

    fixture = _new_core_test_fixture('gate')
    mark(fixture)
    scripts = fixture / '.agent-project-control/scripts'
    passed, restored = set(), []
    module_names = ['common', 'rule_sync', 'route_context', 'routing_receipt', 'routing_activity', 'audit_routes', 'gate_kernel', 'gate_check', 'design_contract']
    saved_modules = {name: sys.modules.get(name) for name in module_names}
    old_path = list(sys.path)

    def done(number, **evidence):
        passed.add(number)
        ROWS.append({'case': f'Step1EA/{number}/assertions', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '', **evidence})

    def invoke(number, name, *args, expected=0):
        result = subprocess.run([sys.executable, '-B', str(scripts / name), *map(str, args)], cwd=fixture,
                                capture_output=True, text=True, encoding='utf-8', env=_childenv(scripts))
        ROWS.append({'case': f'Step1EA/{number}', 'script': name, 'arguments': list(map(str, args)),
                     'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        assert result.returncode == expected, (number, name, result.returncode, result.stdout, result.stderr)
        return result.stdout

    def git(*args):
        if not args or args[0] != 'init': assert_fixture_git_root(fixture)
        result = subprocess.run(['git', '-C', str(fixture), *args], capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    @contextmanager
    def mutate(path, data):
        original = path.read_bytes() if path.exists() else None
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            yield
        finally:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
            assert (path.read_bytes() if path.exists() else None) == original
            restored.append(path.relative_to(fixture).as_posix())

    def turn(number):
        output = invoke(number, 'new_turn.py', '--title', 'gate-' + str(number), '--request-text', 'Step 1E-A isolated Gate request')
        tr = Path(output.strip().splitlines()[-1])
        assert tr == check_bootstrap_output(fixture, output)
        return tr

    def route(number, tr, *args):
        invoke(number, 'route_context.py', *args, '--turn-dir', tr)

    def attach_semantic_review(tr):
        targets = activity.managed_targets(tr)
        observations = {}
        evidence_lines = ['# Synthetic current-object semantic review', '']
        for rel in targets:
            state = activity.file_state(rel)
            path = fixture / rel
            if path.is_file():
                raw = path.read_bytes()
                sample = raw[:160].decode('utf-8', 'replace').replace('\r', ' ').replace('\n', ' ')
                basis = (f"Reviewed {rel} at current SHA-256 {state['sha256']}; its candidate bytes begin "
                         f"with {sample!r}, so the change belongs to the inspected implementation object.")
                evidence_lines.append(f"- `{rel}`: state={state['state']}; SHA-256={state['sha256']}; excerpt={sample!r}")
            else:
                basis = (f"Reviewed deletion of {rel}; the current object state is {state['state']} and the prior "
                         "tracked object is absent from the candidate, so its routing scope remains explicit.")
                evidence_lines.append(f"- `{rel}`: state={state['state']}; SHA-256={state['sha256']}")
            observations[rel] = basis
        evidence = tr / 'evidence/selfcheck-semantic-review.md'
        evidence.write_text('\n'.join(evidence_lines) + '\n', encoding='utf-8')
        activity.record_semantic_review(tr, observations, ['evidence/selfcheck-semantic-review.md'])

    def gate(number, tr, *, expected, phases=None, capabilities=None, reviewed=False):
        if reviewed:
            attach_semantic_review(tr)
        code, record = adapter.evaluate_route_gate(turn_dir_raw=str(tr), gate_id='route-readiness', phases=phases or [],
                                                   capabilities=capabilities or [], semantic_reviewed=reviewed, unresolved=[],
                                                   require_content=False)
        ROWS.append({'case': f'Step1EA/{number}/gate', 'exit_code': code, 'stdout': record['result'], 'stderr': '', 'record': record})
        assert code == expected and record['result'] == {0: 'PASS', 3: 'REPAIR_REQUIRED', 4: 'BLOCKED', 5: 'NO_PROGRESS'}[expected], record
        history = kernel.load_history(tr / 'evidence/gate-attempts.jsonl', kernel.posix_rel(tr))
        assert history[-1] == record and json.loads((tr / 'evidence/gate-latest.json').read_bytes()) == record
        return record

    def snapshot(tr):
        return kernel.candidate_fingerprint(adapter._candidate_snapshot(tr))

    try:
        shutil.copytree(ROOT / '.agent-project-control', fixture / '.agent-project-control',
                        ignore=shutil.ignore_patterns('runtime', 'iterations', 'materials', 'regressions', 'decisions', 'runbooks', '__pycache__'))
        seed_fixture_root(fixture)
        for name in ['iterations', 'materials', 'regressions', 'decisions', 'runbooks']:
            directory = fixture / '.agent-project-control' / name
            mark(directory)
            (directory / 'INDEX.md').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. Synthetic index\n', encoding='utf-8')
        for name in ['testbed', 'runs', 'downloads', 'tmp', 'cache', 'large', 'distribution']:
            mark(fixture / '.agent-project-control/runtime' / name)
        mark(fixture / '.agent-project-control/runtime')
        initial = {'src/server.py': b'print("initial")\n', 'src/theme.css': b'body { color: black; }\n',
                   'src/nested/AGENTS.md': b'# Isolated nested instructions\n', 'src/nested/theme.css': b'body {}\n'}
        for rel, data in initial.items():
            path = fixture / rel
            mark(path.parent)
            path.write_bytes(data)
        git('init', '-q'); configure_fixture_git_longpaths(fixture); git('config', 'user.name', 'APCF synthetic test'); git('config', 'user.email', 'synthetic@example.invalid')
        git('config', 'core.autocrlf', 'false'); git('config', 'core.hooksPath', '.git/hooks')
        git('add', '--all'); git('commit', '-q', '-m', 'Synthetic Gate baseline')
        invoke(1, 'new_iteration.py', '--title', 'gate-kernel', '--objective', 'Isolated Step 1E-A matrix')
        for name in module_names:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(scripts))
        kernel = importlib.import_module('gate_kernel')
        adapter = importlib.import_module('gate_check')
        activity = importlib.import_module('routing_activity')
        design = importlib.import_module('design_contract')
        assert kernel.ROOT == adapter.ROOT == activity.ROOT == design.ROOT == fixture
        check_gate_kernel_cases(kernel, turn, done, mutate)

        design_version_turn = turn('rules-version')
        design_lock = fixture / '.agent-project-control/design/BASELINES.lock.yaml'
        design_index = fixture / '.agent-project-control/design/INDEX.md'
        lock_before = design_lock.read_bytes()
        assert design.lock_value('rules_version') == 'v0.1'
        assert design.render_index() == design_index.read_text(encoding='utf-8')
        route('rules-version-positive', design_version_turn, '--phase', 'scope', '--capability', 'design')
        receipt_log = design_version_turn / 'evidence/routing.jsonl'
        receipt_before = receipt_log.read_bytes()
        verified = invoke('rules-version-valid-receipt', 'routing_receipt.py',
                          '--turn-dir', design_version_turn, '--phase', 'scope')
        assert 'PASS' in verified
        for version in ('2.3.1', 'v9.9'):
            candidate = re.sub(rb'(?m)^rules_version: "[^"]+"$',
                               f'rules_version: "{version}"'.encode('ascii'), lock_before, count=1)
            with mutate(design_lock, candidate):
                assert design_lock.read_bytes() != lock_before
                check = subprocess.run([sys.executable, '-B', str(scripts / 'design_contract.py'), '--check'],
                                       cwd=fixture, capture_output=True, text=True, encoding='utf-8',
                                       env=_childenv(scripts))
                ROWS.append({'case': f'Step1EA/rules-version/{version}/check', 'script': 'design_contract.py',
                             'arguments': ['--check'], 'exit_code': check.returncode,
                             'stdout': check.stdout, 'stderr': check.stderr})
                assert check.returncode == 2 and 'rules_version' in check.stdout
                failed_route = invoke(f'rules-version-{version}', 'route_context.py', '--phase', 'scope',
                                      '--capability', 'design', '--turn-dir', design_version_turn, expected=2)
                assert 'rules_version' in failed_route and receipt_log.read_bytes() == receipt_before
                stale = invoke(f'rules-version-{version}-stale-receipt', 'routing_receipt.py',
                               '--turn-dir', design_version_turn, '--phase', 'scope', expected=2)
                assert 'FAIL' in stale or 'invalid' in stale.lower()
            assert design_lock.read_bytes() == lock_before
            restored_receipt_output = invoke(f'rules-version-{version}-restored-receipt', 'routing_receipt.py',
                                             '--turn-dir', design_version_turn, '--phase', 'scope')
            assert 'PASS' in restored_receipt_output and design.validate() == []

        tr = turn(15)
        fp = snapshot(tr)
        with mutate(fixture / 'src/server.py', b'print("candidate changed")\n'):
            changed = snapshot(tr)
            assert changed != fp
            done(15, before=fp, after=changed)
        assert snapshot(tr) == fp
        route(16, tr, '--phase', 'bootstrap')
        before = snapshot(tr)
        first = gate(16, tr, expected=0)
        second = gate(16, tr, expected=0)
        assert first['attempt_hash'] != second['attempt_hash'] and first['candidate_fingerprint'] == second['candidate_fingerprint'] == before == snapshot(tr)
        done(16, records=[first, second])
        audit_path = tr / 'evidence/route-audit.json'
        with mutate(audit_path, b'{"synthetic evidence only":true}\n'):
            assert snapshot(tr) == before
            done(17, fingerprint=before)
        for path in [fixture / '.agent-project-control/runtime/tmp/neutral.txt', fixture / '.agent-project-control/generated/TREE.md']:
            with mutate(path, b'route-neutral output change\n'):
                assert snapshot(tr) == before
        done(18, fingerprint=before)
        observations = []
        for name in ['CHECKLIST.md', 'TEST.md', 'TURN.md']:
            path = tr / name
            with mutate(path, path.read_bytes() + b'candidate control file change\n'):
                value = snapshot(tr)
                assert value != before
                observations.append({'file': name, 'fingerprint': value})
        done(19, before=before, changed=observations)
        event_path = tr / 'evidence/activity.jsonl'
        with mutate(event_path, b''):
            activity.record_event(tr, 'verification', 'Gate matrix event')
            changed = snapshot(tr)
            assert changed != before
            done(20, before=before, after=changed)

        tr = turn(30)
        route(30, tr, '--phase', 'bootstrap', '--phase', 'scope')
        with mutate(fixture / 'src/theme.css', b'body { color: blue; }\n'):
            record = gate(30, tr, expected=3)
            repairs = record['repair_set']
            assert len(repairs) == 1 and repairs[0]['kind'] == 'route-capability' and repairs[0]['target'] == 'design', record
            report = json.loads((tr / 'evidence/route-audit.json').read_bytes())
            assert set(report['gaps']['sources']) == {'.agent-project-control/rules/06-framework-contract.md', *DESIGN_SOURCES}
            assert report['gaps']['capabilities'] == ['design']
            done(30, gaps=report['gaps'], record=record)
            done(48, record=record); done(49, gaps=report['gaps'], repairs=repairs)
            assert {r['target'] for r in repairs} == {'design'}
            done(34, repairs=repairs)
            old_fp = record['candidate_fingerprint']
            route(54, tr, '--capability', 'design')
            passed_record = gate(54, tr, expected=0)
            assert passed_record['candidate_fingerprint'] == old_fp and not passed_record['findings']
            done(54, before=record, after=passed_record)
        tr = turn(31)
        route(31, tr, '--phase', 'bootstrap', '--phase', 'scope')
        with mutate(fixture / 'src/nested/theme.css', b'body { color: green; }\n'):
            record = gate(31, tr, expected=3)
            scoped = [r for r in record['repair_set'] if r['kind'] == 'route-scope']
            assert len(scoped) == 1 and scoped[0]['target'] == 'src/nested' and scoped[0]['scope'] == ['src/nested']
            assert any(r['target'] == 'design' for r in record['repair_set'])
            done(31, record=record); done(50, record=record)
        tr = unrouted_turn_fixture(fixture, turn(32), 'gate-missing-bootstrap-32')
        record = gate(32, tr, expected=3)
        assert len(record['repair_set']) == 1 and record['repair_set'][0]['kind'] == 'route-phase' and record['repair_set'][0]['target'] == 'bootstrap'
        done(32, record=record)
        tr = turn(33)
        route(33, tr, '--phase', 'bootstrap', '--phase', 'scope')
        with mutate(fixture / 'src/server.py', b'print("unmatched semantic target")\n'):
            record = gate(33, tr, expected=3)
            assert len(record['repair_set']) == 1 and record['repair_set'][0]['kind'] == 'semantic-route-review'
            assert record['repair_set'][0]['scope'] == ['src/server.py']
            hint_code, hint = adapter.evaluate_route_gate(
                turn_dir_raw=str(tr), gate_id='route-readiness', phases=[], capabilities=[],
                semantic_reviewed=True, unresolved=[], require_content=False)
            ROWS.append({'case': 'Step1EA/33/legacy-semantic-hint', 'exit_code': hint_code,
                         'stdout': hint['result'], 'stderr': '', 'record': hint})
            assert hint_code == 5 and hint['result'] == 'NO_PROGRESS'
            assert any(f['code'] == 'SEMANTIC_ROUTE_REVIEW_REQUIRED' for f in hint['findings'])
            reviewed = gate(33, tr, expected=0, reviewed=True)
            assert reviewed['result'] == 'PASS'
            done(33, record=record, legacy_hint=hint, evidence_bound_review=reviewed)
            done(51, record=record, legacy_hint_rejected=True, evidence_bound_review=reviewed)
        tr = unrouted_turn_fixture(fixture, turn(46), 'gate-missing-bootstrap-46')
        record = gate(46, tr, expected=3)
        route(46, tr, '--phase', 'bootstrap')
        after = gate(46, tr, expected=0)
        assert record['candidate_fingerprint'] == after['candidate_fingerprint'] and after['transition']['kind'] == 'PASS'
        done(46, before=record, after=after)
        tr = turn(47)
        route(47, tr, '--phase', 'bootstrap')
        activity.record_event(tr, 'external-tool')
        record = gate(47, tr, expected=3)
        assert len(record['repair_set']) == 1 and record['repair_set'][0]['target'] == 'tools'
        assert record['findings'][0]['code'] == 'ROUTE_PHASE_GAP'
        repeat = gate(47, tr, expected=5)
        assert repeat['finding_ids'] == record['finding_ids']
        done(47, record=record, repeat=repeat)
        tr = turn(52)
        route(52, tr, '--phase', 'bootstrap')
        record = gate('52-resolved', tr, expected=3, capabilities=['writing'])
        gaps = [f for f in record['findings'] if f['code'] == 'ROUTE_CAPABILITY_GAP']
        assert len(gaps) == 1 and gaps[0]['subject'] == 'writing' and gaps[0]['repairability'] == 'repairable'
        with unresolved_interface(fixture):
            record = gate(52, tr, expected=4, capabilities=['writing'])
            blocked = [f for f in record['findings'] if f['code'] == 'CAPABILITY_ENTRYPOINT_UNRESOLVED']
            assert len(blocked) == 1 and blocked[0]['subject'] == 'writing' and blocked[0]['repairability'] == 'blocked' and blocked[0]['repair'] is None
        restored.append(WRITING_INTERFACE)
        done(52, record=record)
        tr = turn(53)
        route(53, tr, '--phase', 'bootstrap')
        for path, data, expected_code in [(tr / 'evidence/activity-baseline.json', b'{bad\n', 'CANDIDATE_SNAPSHOT_INVALID'),
                                           (tr / 'evidence/routing.jsonl', b'{bad\n', 'ROUTE_AUDIT_INVALID'),
                                           (tr / 'TEST.md', None, 'CANDIDATE_SNAPSHOT_INVALID')]:
            with mutate(path, data):
                record = gate(53, tr, expected=4)
                assert any(f['code'] == expected_code and f['repairability'] == 'blocked' for f in record['findings'])
        done(53, defects=['baseline JSON', 'receipt JSON', 'missing candidate TEST.md'])
        tr = turn(55)
        route(55, tr, '--phase', 'bootstrap', '--phase', 'tools')
        activity.record_event(tr, 'external-tool')
        assert gate(55, tr, expected=0)['result'] == 'PASS'
        rules = fixture / '.agent-project-control/rules/04-tools-parallel.md'
        with mutate(rules, rules.read_bytes() + b'\nSynthetic stale source change\n'):
            record = gate(55, tr, expected=3, reviewed=True)
            report = json.loads((tr / 'evidence/route-audit.json').read_bytes())
            assert report['satisfied']['invalid_receipts'] and 'tools' not in report['satisfied']['phases']
            assert 'bootstrap' in report['satisfied']['phases'] and report['satisfied']['valid_receipts']
            assert any(f['code'] == 'ROUTE_PHASE_GAP' and f['subject'] == 'tools' for f in record['findings'])
            done(55, record=record, satisfied=report['satisfied'])

        tr = unrouted_turn_fixture(fixture, turn(56), 'gate-missing-bootstrap-56')
        def business():
            return {p.relative_to(fixture).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.rglob('*')
                    if p.is_file() and '.git' not in p.relative_to(fixture).parts and not p.is_relative_to(tr / 'evidence')}
        before = business()
        gate(56, tr, expected=3)
        assert business() == before
        changes = {p.name for p in (tr / 'evidence').iterdir()}
        assert changes == {'.apcf-dir.yaml', 'activity-baseline.json', 'route-audit.json', 'gate-attempts.jsonl', 'gate-latest.json'}
        done(56, evidence_files=sorted(changes), protected_count=len(before))
        forbidden = ['finalize_turn.py', 'new_parallel.py', 'new_turn.py', 'publish_guard.py', 'prepare_distribution.py', 'bootstrap.py']
        assert all((scripts / n).read_bytes() == (ROOT / '.agent-project-control/scripts' / n).read_bytes() for n in forbidden)
        text = (scripts / 'gate_kernel.py').read_text(encoding='utf-8') + (scripts / 'gate_check.py').read_text(encoding='utf-8')
        assert 'subprocess' not in text and 'while retry' not in text
        assert business() == before
        done(57, unchanged_entries=forbidden, auto_repair=False)
        assert (fixture / 'AGENTS.md').read_bytes() == (ROOT / 'AGENTS.md').read_bytes()
        assert (ROOT / 'AGENTS.md').read_bytes() == protected_agents
        expected_agents = hashlib.sha256(protected_agents).hexdigest()
        canonical = {}
        for rel in MODULES:
            assert (fixture / rel).read_bytes() == (ROOT / rel).read_bytes()
            canonical[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        for rel in [WRITING_INTERFACE, STYLE_INTERFACE]:
            assert '- **状态**：`RESOLVED`' in (fixture / rel).read_text(encoding='utf-8')
        assert adapter.load_contract()['capabilities']['style']['enabled']
        for rel in [WRITING_INTERFACE, STYLE_INTERFACE]:
            with unresolved_interface(fixture, rel):
                invoke(60, 'route_context.py', '--capability', 'human-readable', '--turn-dir', tr, expected=3)
            restored.append(rel)
        routing = fixture / '.agent-project-control/routing.toml'
        with mutate(routing, disabled_style_bytes(routing.read_bytes())):
            invoke(60, 'route_context.py', '--capability', 'style', '--turn-dir', tr, expected=3)
        done(60, agents_sha256=expected_agents, canonical_sha256=canonical, writing='RESOLVED', style='RESOLVED', style_enabled=True)
        earlier = [row for row in ROWS if row.get('case') == 'Step1D/summary']
        if earlier:
            assert set(earlier[-1]['matrix_cases']) == set(range(1, 51)) | {'25-legacy-hint', 60}
            assert any(row.get('case') == 'AGENTS/normal-coverage' for row in ROWS)
            done(58, original_checks='Step 1A-1D completed before Gate cases', audit_summary=earlier[-1])
        expected = set(range(1, 58)) | {60}
        if earlier:
            expected.add(58)
        assert passed == expected, ('Missing Step 1E-A cases', sorted(expected - passed), sorted(passed - expected))
        ROWS.append({'case': 'Step1EA/matrix-summary', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '',
                     'cases': sorted(passed), 'byte_restored_mutations': restored,
                     'outer_chain_cases': [58, 59]})
        print('PASS: Gate Kernel matrix 1-57 and 60; real history, route adapter, minimal repairs; %d byte-restored mutations' % len(restored))
    finally:
        sys.path[:] = old_path
        for name in module_names:
            sys.modules.pop(name, None)
            if saved_modules[name] is not None:
                sys.modules[name] = saved_modules[name]
        assert fixture.resolve().parent == CASE.parent.resolve()
        remove_core_test_fixture(fixture, CASE.parent)


def _new_core_test_fixture(prefix):
    """Own one collision-checked full-UUID fixture beside the current Source root."""
    import uuid
    parent = CASE.parent.resolve()
    fixture = parent / (prefix + '-' + uuid.uuid4().hex)
    assert fixture.resolve().parent == parent
    assert not fixture.exists(), 'Refusing to reuse an existing core test fixture'
    return fixture


def remove_core_test_fixture(fixture, parent):
    """Clean only the newly owned fixture; tolerate late Git metadata writes on Windows."""
    import time
    assert fixture.resolve().parent == parent.resolve()
    for attempt in range(4):
        if not fixture.exists():
            break
        try:
            shutil.rmtree(fixture, onerror=remove_readonly)
            break
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in {32, 145} or attempt == 3:
                raise
            time.sleep(0.1 * (attempt + 1))
    assert not fixture.exists()


def check_core_profiles_bootstrap():
    import json, os, re, shutil, subprocess, sys, time, tomllib
    from pathlib import Path

    fixture = _new_core_test_fixture("ebp")
    assert fixture.resolve().parent == CASE.parent.resolve()
    assert CASE.is_dir()
    shutil.copytree(CASE, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__", "runtime"))
    env = _childenv(fixture / ".agent-project-control/scripts", {**os.environ, "PYTHONIOENCODING": "utf-8"})

    def record(n, **evidence):
        ROWS.append({"case": f"Step1EB/{n}/assertions", "exit_code": 0,
                     "stdout": "PASS: executable assertion verified", "stderr": "", **evidence})

    def call(n, script, *args, expected=0):
        p = subprocess.run([sys.executable, "-B", str(fixture / ".agent-project-control/scripts" / script),
                            *map(str, args)], cwd=fixture, capture_output=True, text=True,
                            encoding="utf-8", env=env)
        ROWS.append({"case": f"Step1EB/{n}/invocation", "script": script,
                     "arguments": list(map(str, args)), "exit_code": p.returncode,
                     "stdout": p.stdout, "stderr": p.stderr})
        assert p.returncode == expected, (n, script, p.returncode, p.stdout, p.stderr)
        return p

    def git(*args):
        if not args or args[0] != 'init': assert_fixture_git_root(fixture)
        p = subprocess.run(["git", "-C", str(fixture), *args], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        assert p.returncode == 0, (args, p.stdout, p.stderr)
        return p.stdout.strip()

    def turn(n, title):
        out = call(n, "new_turn.py", "--title", title, "--request-text", "Step 1E-B isolated matrix").stdout
        tr = Path(out.strip().splitlines()[-1]).resolve()
        assert check_bootstrap_output(fixture, out) == tr
        return tr, out

    def route(n, tr, *args):
        return call(n, "route_context.py", *args, "--turn-dir", tr)

    def attempts(tr):
        p = tr / "evidence/gate-attempts.jsonl"
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    def gate(n, tr, profile, expected, gate_id="route-readiness"):
        args = ["--turn-dir", tr, "--gate-id", gate_id]
        if profile is not None:
            args += ["--profile", profile]
        p = call(n, "gate_check.py", *args, expected=expected)
        label = {0:"PASS", 3:"REPAIR_REQUIRED", 4:"BLOCKED", 5:"NO_PROGRESS"}[expected]
        rec = json.loads(p.stdout.split("\n" + label + ":", 1)[0])
        assert rec["result"] == label and rec["exit_code"] == expected
        return rec

    def report_for(tr):
        current = (fixture / "CURRENT.md").read_text(encoding="utf-8")
        tick = chr(96)
        source_line = next(line for line in current.splitlines() if "Source TURN" in line)
        source_rel = source_line.rsplit(tick, 2)[1]
        source = fixture / source_rel
        old_turn = (source / "TURN.md").read_text(encoding="utf-8")
        old_report = old_turn.split("## 1.1. USER REPORT", 1)[1].strip()
        old_report, count = re.subn(r"(?m)^- \*\*IT / TR\*\*：.*$",
                                    f"- **IT / TR**：{tr.parents[1].name} / {tr.name.split('_', 1)[0]}",
                                    old_report, count=1)
        if count == 0:
            old_report, it_count = re.subn(r"(?m)^- \*\*当前 IT\*\*：.*$",
                                           f"- **当前 IT**：{tr.parents[1].name}", old_report, count=1)
            old_report, tr_count = re.subn(r"(?m)^- \*\*当前 TR\*\*：.*$",
                                           f"- **当前 TR**：{tr.name.split('_', 1)[0]}", old_report, count=1)
            assert it_count == tr_count == 1
        shutil.copyfile(source / "CHECKLIST.md", tr / "CHECKLIST.md")
        shutil.copyfile(source / "TEST.md", tr / "TEST.md")
        f = tr / "TURN.md"
        prefix = f.read_text(encoding="utf-8").split("## 1.1. USER REPORT", 1)[0]
        f.write_text(prefix + "## 1.1. USER REPORT\n\n" + old_report + "\n", encoding="utf-8")

    def prepare(n, title):
        tr, _ = turn(n, title)
        report_for(tr)
        route(n, tr, "--phase", "scope")
        route(n, tr, "--phase", "verification")
        return tr

    def setup_git():
        src = fixture / "src/theme.css"
        src.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            src.write_text("body { color: black; }\n", encoding="utf-8")
        prepare_synthetic_skills(fixture)
        subprocess.run(["git", "init", "-q", str(fixture)], check=True)
        configure_fixture_git_longpaths(fixture)
        git("config", "user.name", "APCF synthetic test")
        git("config", "user.email", "synthetic@example.invalid")
        git("config", "core.autocrlf", "false")
        git("config", "core.hooksPath", ".git/hooks")
        git("add", "--all")
        git("commit", "-q", "-m", "Synthetic Step 1E-B immutable baseline")

    try:
        setup_git()
        it = call(0, "new_iteration.py", "--title", "step1eb-core-profiles",
                  "--objective", "Isolated Step 1E-B profile and bootstrap matrix")
        assert it.returncode == 0

        contract = tomllib.loads((fixture / ".agent-project-control/gate.toml").read_text(encoding="utf-8"))
        core = set(contract["profiles"]["core"]["enforce_classes"])
        full = set(contract["profiles"]["full"]["enforce_classes"])
        assert core == {"integrity", "phase", "scope", "source"}
        record(1, profile="core", enforced_classes=sorted(core))
        assert full == core | {"capability", "semantic"}
        record(2, profile="full", enforced_classes=sorted(full))

        adapter_path = str(fixture / ".agent-project-control/scripts")
        for n, expression, phrase in [
            (3, "gate_check._profile_findings([], 'not-a-profile')", "unknown gate profile"),
            (4, "gate_check._profile_findings([{'code':'synthetic'}], 'core')", "enforcement_class"),
        ]:
            source = ("import sys;sys.path.insert(0," + repr(adapter_path) + ");import gate_check\n"
                      "try:\n " + expression + "\nexcept Exception as e:\n"
                      " assert e.__class__.__name__=='GateError' and e.code==2 and " + repr(phrase) + " in str(e)\n sys.exit(e.code)\n"
                      "else: raise AssertionError('invalid profile/finding accepted')\n")
            p = subprocess.run([sys.executable, "-B", "-c", source], cwd=fixture,
                               capture_output=True, text=True, encoding="utf-8")
            assert p.returncode == 2, (n, p.stdout, p.stderr)
            record(n, actual_adapter_rejection=phrase, invalid_exit_code=p.returncode)
        for n, cls, profile in [
            (5,"phase","core"), (6,"scope","core"), (7,"source","core"), (8,"integrity","core"),
            (9,"capability","core"), (10,"semantic","core"), (11,"capability","full"), (12,"semantic","full"),
        ]:
            expected_enforced = n not in {9,10}
            source = ("import sys;sys.path.insert(0," + repr(adapter_path) + ");import gate_check\n"
                      "enforced,deferred=gate_check._profile_findings([{'enforcement_class':" + repr(cls) +
                      "}]," + repr(profile) + ")\n"
                      "assert (len(enforced)==1 and not deferred) is " + repr(expected_enforced) + "\n"
                      "assert (len(deferred)==1 and not enforced) is " + repr(not expected_enforced) + "\n")
            p = subprocess.run([sys.executable, "-B", "-c", source], cwd=fixture,
                               capture_output=True, text=True, encoding="utf-8")
            assert p.returncode == 0, (n, p.stdout, p.stderr)
            record(n, enforcement_class=cls, profile=profile, adapter_enforced=expected_enforced)

        # Adapter evidence preserves deferred findings and route-audit evidence.
        tr13, _ = turn(13, "profile-adapter")
        call(3, "gate_check.py", "--turn-dir", tr13, "--profile", "not-a-profile", expected=2)
        readme = fixture / "README.md"
        original_readme = readme.read_bytes()
        readme.write_bytes(original_readme + b"\nSynthetic README candidate for profile adapter.\n")
        route(13, tr13, "--phase", "scope")
        rec13 = gate(13, tr13, "core", 0)
        deferred = rec13["adapter_evidence"][0]["deferred_findings"]
        assert any(x["enforcement_class"] == "capability" and "readme" in x["subject"] for x in deferred)
        record(13, gate_result=rec13["result"], deferred_findings=deferred)
        audit = json.loads((tr13 / "evidence/route-audit.json").read_text(encoding="utf-8"))
        assert audit["gaps"]["capabilities"] and set(audit["gaps"]["capabilities"]) <= set(audit["required"]["capabilities"])
        record(14, retained_capability_gaps=audit["gaps"]["capabilities"])
        rec15 = gate(15, tr13, None, 3)
        assert rec15["result"] == "REPAIR_REQUIRED"
        assert {'readme', 'writing', 'style', 'human-readable'} <= {x['subject'] for x in rec15['findings'] if x['code'] == 'ROUTE_CAPABILITY_GAP'}
        with unresolved_interface(fixture):
            unresolved15 = gate('15-unresolved', tr13, None, 4)
            assert any(x['code'] == 'CAPABILITY_ENTRYPOINT_UNRESOLVED' and x['subject'] == 'writing' for x in unresolved15['findings'])
        record(15, default_profile="full", default_result=rec15["result"], unresolved_result=unresolved15["result"])
        readme.write_bytes(original_readme)

        # Bootstrap cases execute the actual allocator, route controller, and Receipt verifier.
        boot, output = turn(16, "bootstrap-real-auto-route")
        baseline = json.loads((boot / "evidence/activity-baseline.json").read_text(encoding="utf-8"))
        assert baseline["turn"] == boot.relative_to(fixture).as_posix()
        record(16, baseline=baseline)
        receipts = [json.loads(line) for line in (boot / "evidence/routing.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any("bootstrap" in x["phases"] for x in receipts)
        record(17, bootstrap_receipts=[x["receipt_id"] for x in receipts])
        source_paths = {s["path"] for r in receipts if "bootstrap" in r["phases"] for s in r["sources"]}
        required = {"AGENTS.md", ".agent-project-control/rules/INDEX.md",
                    ".agent-project-control/rules/01-context-state.md",
                    ".agent-project-control/rules/02-execution-scope.md"}
        assert required <= source_paths
        record(18, required_sources=sorted(required), observed_sources=sorted(source_paths))
        verify = call(20, "routing_receipt.py", "--turn-dir", boot, "--phase", "bootstrap")
        assert verify.returncode == 0
        record(19, current_turn=boot.relative_to(fixture).as_posix(), bootstrap_receipt_valid=True)
        record(20, verifier_exit=verify.returncode)
        assert output.strip().splitlines()[-1] == str(boot) and output.count(str(boot)) == 1
        record(21, unique_final_path=str(boot), occurrences=1)

        existing = sorted(p.resolve() for p in boot.parent.glob("TR-*"))
        protected = {p:{name:(p/name).read_bytes() for name in ("TURN.md","CHECKLIST.md","TEST.md")} for p in existing}
        protected_attempts = {p:((p/"evidence/gate-attempts.jsonl").read_bytes()
                                 if (p/"evidence/gate-attempts.jsonl").exists() else None) for p in existing}
        routing = fixture / ".agent-project-control/routing.toml"
        original_routing = routing.read_bytes()
        damaged = original_routing.replace(b'modules = ["01-context-state.md", "02-execution-scope.md"]',
                                            b'modules = ["missing-core-module.md"]', 1)
        assert damaged != original_routing
        routing.write_bytes(damaged)
        try:
            failed = call(22, "new_turn.py", "--title", "bootstrap-structure-failure",
                          "--request-text", "expected structural rejection", expected=2)
            assert sorted(p.resolve() for p in boot.parent.glob("TR-*")) == existing
            record(22, failed_exit=failed.returncode, newly_allocated_path_rolled_back=True)
            after = {p:{name:(p/name).read_bytes() for name in ("TURN.md","CHECKLIST.md","TEST.md")} for p in existing}
            assert after == protected
            record(23, no_failed_turn_remains=True)
            record(24, existing_turn_bytes_unchanged=True)
            after_attempts = {p:((p/"evidence/gate-attempts.jsonl").read_bytes()
                                 if (p/"evidence/gate-attempts.jsonl").exists() else None) for p in existing}
            assert after_attempts == protected_attempts
            record(25, existing_gate_attempts_unchanged=True, failed_turn_gate_attempts_absent=True)
        finally:
            routing.write_bytes(original_routing)

        # A real README candidate is deferred by an explicit core Gate and enforced by full.
        finalize_core = prepare(53, "readme-core-profile")
        original_readme = readme.read_bytes()
        readme.write_bytes(original_readme + b"\nSynthetic README core/full candidate.\n")
        route(53, finalize_core, "--phase", "scope")
        route(53, finalize_core, "--phase", "verification")
        route(54, finalize_core, "--phase", "finalization")
        comparison_core = gate(54, finalize_core, "core", 0, gate_id="same-candidate-core")
        comparison_full = gate(54, finalize_core, "full", 3, gate_id="route-readiness")
        assert comparison_core["candidate_fingerprint"] == comparison_full["candidate_fingerprint"]
        state_before = ((finalize_core / "TURN.md").read_bytes(), (fixture / "CURRENT.md").read_bytes())
        finalized = call(53, "finalize_turn.py", finalize_core, expected=3)
        rows = attempts(finalize_core)
        assert rows[-1]["gate_id"] == "full-finalization" and rows[-1]["result"] == "REPAIR_REQUIRED"
        assert ((finalize_core / "TURN.md").read_bytes(), (fixture / "CURRENT.md").read_bytes()) == state_before
        assert any(x["code"] == "ROUTE_CAPABILITY_GAP" and x["subject"] == "readme" for x in rows[-1]["findings"])
        record(53, core_result=comparison_core["result"], full_result=comparison_full["result"],
               finalize_gate=rows[-1]["gate_id"], finalize_result=rows[-1]["result"],
               state_unchanged=True)
        same = comparison_full
        assert same["result"] == "REPAIR_REQUIRED"
        record(54, same_candidate_profile="full", result=same["result"],
               candidate_fingerprint=same["candidate_fingerprint"], core_fingerprint=comparison_core["candidate_fingerprint"],
               core_result=comparison_core["result"], identical_candidate=True)
        readme.write_bytes(original_readme)

        # CSS/design is capability-only for core and enforced by full Finalize.
        design_turn = prepare(55, "design-core-profile")
        css = fixture / "src/theme.css"
        original_css = css.read_bytes()
        css.write_bytes(original_css + b"\n/* synthetic design candidate */\n")
        route(55, design_turn, "--phase", "scope")
        route(55, design_turn, "--phase", "verification")
        before = ((design_turn / "TURN.md").read_bytes(), (fixture / "CURRENT.md").read_bytes())
        call(55, "finalize_turn.py", design_turn, expected=3)
        full_attempt = attempts(design_turn)[-1]
        assert full_attempt["gate_id"] == "full-finalization" and full_attempt["result"] == "REPAIR_REQUIRED"
        assert ((design_turn / "TURN.md").read_bytes(), (fixture / "CURRENT.md").read_bytes()) == before
        assert any(x["code"] == "ROUTE_CAPABILITY_GAP" and x["subject"] == "design" for x in full_attempt["findings"])
        full_design = gate(55, design_turn, "full", 3)
        assert any(x["code"] == "ROUTE_CAPABILITY_GAP" and x["subject"] == "design" for x in full_design["findings"])
        record(55, core_finalize_gate=full_attempt["gate_id"], core_finalize_result=full_attempt["result"],
               full_result=full_design["result"], state_unchanged=True)
        css.write_bytes(original_css)

        # An integrity finding remains enforced while capability findings are deferred.
        integrity_turn, _ = turn(56, "integrity-with-deferred-capability")
        readme.write_bytes(original_readme + b"\nSynthetic README integrity case.\n")
        route(56, integrity_turn, "--phase", "scope")
        integrity_call = call(56, "gate_check.py", "--turn-dir", integrity_turn, "--profile", "core",
                              "--unresolved", "synthetic integrity conflict", expected=4)
        integrity_result = json.loads(integrity_call.stdout.split("\nBLOCKED:", 1)[0])
        assert integrity_result["result"] == "BLOCKED"
        assert any(x["enforcement_class"] == "integrity" for x in integrity_result["findings"])
        assert any(x["enforcement_class"] == "capability"
                   for x in integrity_result["adapter_evidence"][0]["deferred_findings"])
        record(56, result=integrity_result["result"], integrity_enforced=True, capability_deferred=True)
        readme.write_bytes(original_readme)

        # The production Finalize entrypoint stays Full and rejects the candidate
        # until route, workflow, acceptance and content evidence are current.
        gate_file = fixture / ".agent-project-control/gate.toml"
        gate_contract = tomllib.loads(gate_file.read_text(encoding="utf-8"))
        finalize_spec = gate_contract["entrypoints"]["finalize"]
        assert finalize_spec["profile"] == "full"
        assert finalize_spec["require_workflow"] and finalize_spec["require_acceptance"] and finalize_spec["require_content"]
        restore_turn, _ = turn(57, "full-finalize-rejects-incomplete-evidence")
        report_for(restore_turn)
        original_readme = readme.read_bytes()
        readme.write_bytes(original_readme + b"\nSynthetic full-finalize candidate.\n")
        route(57, restore_turn, "--phase", "scope")
        route(57, restore_turn, "--phase", "verification")
        before_count = len(attempts(restore_turn))
        turn_before = (restore_turn/"TURN.md").read_bytes()
        current_before = (fixture/"CURRENT.md").read_bytes()
        blocked = call(57, "finalize_turn.py", restore_turn, expected=3)
        after_block = attempts(restore_turn)
        assert len(after_block) == before_count + 1 and after_block[-1]["result"] == "REPAIR_REQUIRED"
        assert after_block[-1]["gate_id"] == "full-finalization"
        assert (restore_turn/"TURN.md").read_bytes() == turn_before
        assert (fixture/"CURRENT.md").read_bytes() == current_before
        with unresolved_interface(fixture):
            unresolved_call = call('57-unresolved', "finalize_turn.py", restore_turn, expected=4)
            after_unresolved = attempts(restore_turn)
            assert len(after_unresolved) == before_count + 2 and after_unresolved[-1]['result'] == 'BLOCKED'
            assert any(x['code'] == 'CAPABILITY_ENTRYPOINT_UNRESOLVED' and x['subject'] == 'writing' for x in after_unresolved[-1]['findings'])
            assert (restore_turn/"TURN.md").read_bytes() == turn_before
            assert (fixture/"CURRENT.md").read_bytes() == current_before
        assert blocked.returncode == 3 and unresolved_call.returncode == 4
        record(57, finalize_profile=finalize_spec["profile"], finalize_requirements={k: finalize_spec[k] for k in
               ("require_workflow", "require_acceptance", "require_content")},
               rejected_result=after_block[-1]["result"], unresolved_result=after_unresolved[-1]["result"],
               rejected_turn_current_bytes_unchanged=True)
        readme.write_bytes(original_readme)
    finally:
        assert fixture.resolve().parent == CASE.parent.resolve()
        remove_core_test_fixture(fixture, CASE.parent)


def check_core_entrypoints():
    """Exercise the real Step 1E-B entrypoints without changing their dependencies."""
    fixture = _new_core_test_fixture('eb')
    scripts = fixture / '.agent-project-control/scripts'
    passed, invocations = set(), []
    public = '<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'

    def done(number, **proof):
        passed.add(number)
        ROWS.append({'case': f'Step1EB/{number}/assertions', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '', **proof})

    def attempts(tr):
        p = tr / 'evidence/gate-attempts.jsonl'
        return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []

    def call(number, name, *args, expected=0, tr=None):
        history = tr / 'evidence/gate-attempts.jsonl' if tr else None
        before = len(history.read_bytes().splitlines()) if history and history.exists() else 0
        r = subprocess.run([sys.executable, '-B', str(scripts / name), *map(str, args)], cwd=fixture,
                           capture_output=True, text=True, encoding='utf-8', env=_childenv(scripts))
        ROWS.append({'case': f'Step1EB/{number}', 'script': name, 'arguments': list(map(str, args)),
                     'exit_code': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr})
        if tr:
            delta = (len(history.read_bytes().splitlines()) if history.exists() else 0) - before
            assert 0 <= delta <= 1, (name, delta)
            invocations.append({'case': number, 'script': name, 'attempt_delta': delta})
        assert r.returncode == expected, (number, name, r.returncode, r.stdout[-1600:], r.stderr)
        return r.stdout

    def inline(number, source, *args, expected=0, tr=None):
        history = tr / 'evidence/gate-attempts.jsonl' if tr else None
        before = len(history.read_bytes().splitlines()) if history and history.exists() else 0
        r = subprocess.run([sys.executable, '-B', '-c', source, *map(str, args)], cwd=fixture,
                           capture_output=True, text=True, encoding='utf-8',
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        ROWS.append({'case': f'Step1EB/{number}', 'script': 'inline-fixture-check',
                     'arguments': list(map(str, args)), 'exit_code': r.returncode,
                     'stdout': r.stdout, 'stderr': r.stderr})
        if tr:
            delta = (len(history.read_bytes().splitlines()) if history.exists() else 0) - before
            assert 0 <= delta <= 1, (number, delta)
            invocations.append({'case': number, 'script': 'finalize_turn.py', 'attempt_delta': delta})
        assert r.returncode == expected, (number, r.returncode, r.stdout[-1600:], r.stderr)
        return r.stdout

    def git(*args):
        if not args or args[0] != 'init': assert_fixture_git_root(fixture)
        r = subprocess.run(['git', '-C', str(fixture), *args], capture_output=True, text=True, encoding='utf-8')
        assert r.returncode == 0, (args, r.stdout, r.stderr)
        return r.stdout.strip()

    def turn(number):
        out = call(number, 'new_turn.py', '--title', 'entry-' + str(number), '--request-text', 'Synthetic enforcement test')
        return check_bootstrap_output(fixture, out)

    def route(number, tr, *args):
        return call(number, 'route_context.py', *args, '--turn-dir', tr)

    def state(tr):
        return (tr.joinpath('TURN.md').read_bytes(), fixture.joinpath('CURRENT.md').read_bytes())

    def pa_state(tr):
        return sorted(p.name for p in (tr / 'parallel').iterdir())

    def valid_report(tr, delivery=False, delivered=False):
        cl_status = '已完成' if not delivery or delivered else '进行中'
        cl = f'- 【{cl_status}】【CL-01】【合成结果】：当本轮需要验收时，因命令退出不能证明内容正确，必须核对合成结果，并以真实证据确认通过\n'
        rows = ['- 【PASS】【TEST-001】【对应 CL-01】【合成结果正确】：在【当前候选 / 合成环境 / 结果可读】下，执行【比较合成结果】，必须观察到【内容与预期一致】；实际观察到【内容与预期一致】，证据为【synthetic-result】']
        if delivery:
            delivery_status = 'PASS' if delivered else '进行中'
            actual = '远端提交存在且渲染回读内容与提交SHA一致' if delivered else '等待远端提交与渲染回读证据'
            evidence = 'verified-delivery-result' if delivered else 'pending-delivery-postcondition'
            rows.append(f'- 【{delivery_status}】【TEST-DELIVERY】【对应 CL-01】【远端交付闭环】：在【delivery-postcondition: synthetic fixture remote response】下，执行【比较远端提交和渲染回读记录】，必须观察到【提交SHA与渲染内容对应】；实际观察到【{actual}】，证据为【{evidence}】')
            if delivered:
                rendered_rel = 'evidence/remote-rendered.html'
                rendered = b'<html><body>synthetic rendered candidate</body></html>\n'
                (tr / rendered_rel).write_bytes(rendered)
                delivery_record = {'schema': 1, 'result': 'PASS', 'mode': 'synthetic-fixture',
                                   'commit': git('rev-parse', 'HEAD'), 'rendered_path': rendered_rel,
                                   'rendered_sha256': hashlib.sha256(rendered).hexdigest()}
                (tr / 'evidence/remote-delivery-result.json').write_text(
                    json.dumps(delivery_record, sort_keys=True) + '\n', encoding='utf-8')
        test = fixture_test_rows('\n'.join(rows))
        (tr / 'CHECKLIST.md').write_text(public + '# 1. 当前执行清单\n\n' + cl, encoding='utf-8')
        (tr / 'TEST.md').write_text(fixture_test_document(public + '# 1. 当前验收记录\n\n' + test), encoding='utf-8')
        passing = 1 + int(delivery and delivered)
        pending = int(delivery and not delivered)
        test_summary = f'{len(rows)} 个 TEST-ID 当前 PASS {passing}，进行中 {pending}，FAIL 0，BLOCKED 0'
        sections = [f'- **IT / TR**：合成 IT / TR\n- **Checklist 摘要**：1 项{cl_status}\n- **Test 摘要**：{test_summary}',
                    '上一状态已经具备可运行的合成项目，但仍需验证入口是否在写入前检查当前候选。\n\n本轮因此使用真实脚本验证通过和拒绝路径，避免仅比较代码结构。\n\n当前结果由独立验收记录支持，后续可以核对持久化状态和拒绝时的字节保护。',
                    '- **合成验证（Synthetic Validation）**：使用独立输入验证实际脚本', cl.strip(), test.strip(),
                    '本轮实际调用入口，核对 Gate 的退出码、历史数量和持久化字节，并保留真实证据。',
                    '- **入口必须在实际写入前检查当前候选**：本轮通过独立环境调用真实脚本，因而能够分别核对通过和拒绝结果，并证明拒绝不会写入最终状态。',
                    '- **当前无需用户操作**：合成环境由自检维护', '- **当前没有外部决策事项**：本轮只验证已经确定的合同',
                    '- **通过后停止当前步骤**：本轮已核对真实入口和字节保护，因此应保留证据并等待下一项授权。']
        sections = [body.replace('。', '；') for body in sections]
        titles = ['精确状态头', '承上启下', '术语表', '执行清单', '验收记录', '完整讲解', '关键要点', '用户需要执行', '需要继续讨论、搜索或决策', '下一步推荐']
        report = '\n\n'.join(f'## {n}. {title}\n\n{body}' for n, (title, body) in enumerate(zip(titles, sections)))
        path = tr / 'TURN.md'
        prefix = path.read_text(encoding='utf-8').split('## 1.1. USER REPORT', 1)[0]
        path.write_text(prefix + '## 1.1. USER REPORT\n\n' + report + '\n', encoding='utf-8')
        return report

    def ready(number, tr):
        route(number, tr, '--phase', 'scope', '--phase', 'verification')

    def prepare_full_evidence(tr, post_delivery=False):
        deferred = ["TEST-DELIVERY"] if post_delivery else []
        return record_fixture_evidence(fixture, tr, deferred)

    def denied_finalize(number, tr, code):
        old = state(tr)
        out = call(number, 'finalize_turn.py', tr, expected=code, tr=tr)
        assert state(tr) == old and '**Status**：IN_PROGRESS' in old[0].decode('utf-8')
        return out

    try:
        mark(fixture)
        shutil.copytree(ROOT / '.agent-project-control', fixture / '.agent-project-control',
                        ignore=shutil.ignore_patterns('runtime', 'iterations', 'materials', 'regressions', 'decisions', 'runbooks', '__pycache__'))
        seed_fixture_root(fixture)
        mark(fixture / '.codex'); mark(fixture / '.codex/skills')
        prepare_synthetic_skills(fixture)
        for name in ['iterations', 'materials', 'regressions', 'decisions', 'runbooks']:
            d = fixture / '.agent-project-control' / name
            mark(d); (d / 'INDEX.md').write_text(public + '# 1. Synthetic index\n', encoding='utf-8')
        mark(fixture / '.agent-project-control/runtime')
        for name in ['testbed', 'runs', 'downloads', 'tmp', 'cache', 'large', 'distribution']:
            mark(fixture / '.agent-project-control/runtime' / name)
        for name in ['a', 'b']:
            d = fixture / 'src' / name
            mark(d)
            (d / 'AGENTS.md').write_text('# Synthetic scoped instructions\n', encoding='utf-8')
            (d / 'theme.css').write_text('body {}\n', encoding='utf-8')
        mark(fixture / 'src')
        (fixture / 'src/server.py').write_text('print("baseline")\n', encoding='utf-8')
        git('init', '-q'); configure_fixture_git_longpaths(fixture); git('config', 'user.name', 'APCF synthetic test'); git('config', 'user.email', 'synthetic@example.invalid')
        git('config', 'core.autocrlf', 'false'); git('config', 'core.hooksPath', '.git/hooks')
        git('add', '--all'); git('commit', '-q', '-m', 'Synthetic core entrypoint baseline')
        call(26, 'new_iteration.py', '--title', 'core-entrypoints', '--objective', 'Step 1E-B real entrypoint matrix')

        tr = turn(26)
        valid_report(tr)
        prepare_full_evidence(tr)
        route(26, tr, '--phase', 'scope', '--phase', 'verification', '--phase', 'finalization')
        before = pa_state(tr)
        out = call(26, 'new_parallel.py', tr, '--title', 'allowed', '--request-text', 'Synthetic PA request', tr=tr)
        pa = Path(out.strip().splitlines()[-1])
        assert 'phases: tools' in out and 'APCF ROUTE SOURCE BEGIN' in out
        done(26)
        receipt = call(27, 'routing_receipt.py', '--turn-dir', tr, '--phase', 'tools')
        assert 'PASS' in receipt; done(27)
        assert pa.parent == tr / 'parallel' and len(pa_state(tr)) == len(before) + 1
        done(28)
        call(33, 'new_parallel.py', pa, '--title', 'nested', '--request-text', 'Rejected nested PA', expected=1)
        assert not (pa / 'parallel').exists(); done(33)
        assert all((pa / n).exists() for n in ['REQUEST.md', 'CHECKLIST.md', 'TEST.md', 'TURN.md', 'evidence'])
        assert (pa / 'TEST.md').read_text(encoding='utf-8').count('<!-- APCF-TEST-FORMAT v3 -->') == 1
        assert (pa / 'REQUEST.md').read_text(encoding='utf-8').endswith('Synthetic PA request\n')
        done(34)

        tr = turn(29)
        p = fixture / 'src/server.py'; old = p.read_bytes()
        try:
            p.write_bytes(old + b'# changed\n')
            before = pa_state(tr)
            call(29, 'new_parallel.py', tr, '--title', 'denied', '--request-text', 'Scope gap', expected=3, tr=tr)
            assert pa_state(tr) == before; done(29)
            call(31, 'new_parallel.py', tr, '--title', 'repeat', '--request-text', 'Same gap', expected=5, tr=tr)
            assert pa_state(tr) == before; done(31)
        finally:
            p.write_bytes(old)
        tr = turn(30)
        baseline = tr / 'evidence/activity-baseline.json'
        old = baseline.read_bytes()
        try:
            baseline.write_bytes(b'{}\n')
            before = pa_state(tr)
            call(30, 'new_parallel.py', tr, '--title', 'blocked', '--request-text', 'Invalid audit', expected=4, tr=tr)
            assert pa_state(tr) == before; done(30)
        finally:
            baseline.write_bytes(old)
        tr = turn(32)
        hist = tr / 'evidence/gate-attempts.jsonl'
        hist.write_bytes(b'{invalid\n')
        before = pa_state(tr)
        call(32, 'new_parallel.py', tr, '--title', 'invalid', '--request-text', 'Invalid history', expected=2, tr=tr)
        assert pa_state(tr) == before and hist.read_bytes() == b'{invalid\n'; done(32)
        hist.unlink()
        assert all(x['attempt_delta'] <= 1 for x in invocations if x['script'] == 'new_parallel.py'); done(35)

        tr = turn(36)
        denied_finalize(36, tr, 2)
        assert not attempts(tr); done(36)
        valid_report(tr)
        p = tr / 'TEST.md'; old = p.read_bytes()
        p.write_bytes(old.replace(b'PASS', b'FAIL', 1))
        denied_finalize(37, tr, 2)
        assert not attempts(tr); p.write_bytes(old); done(37)
        tr = turn(41); valid_report(tr)
        denied_finalize(41, tr, 3); done(41)
        denied_finalize(45, tr, 5); done(45)
        route(42, tr, '--phase', 'scope')
        denied_finalize(42, tr, 3)
        assert any(f['code'] == 'ROUTE_PHASE_GAP' and f['subject'] == 'verification' for f in attempts(tr)[-1]['findings']); done(42)
        ready(47, tr)
        prepare_full_evidence(tr)
        before = state(tr)
        call(47, 'finalize_turn.py', tr, tr=tr)
        assert state(tr) != before; done(47)
        assert '**Status**：FINALIZED' in (tr / 'TURN.md').read_text(encoding='utf-8'); done(48)
        assert parse_meta(fixture / 'CURRENT.md') == {'schema': 1, 'visibility': 'public'}; done(71)
        assert f'`{tr.relative_to(fixture).as_posix()}`' in (fixture / 'CURRENT.md').read_text(encoding='utf-8'); done(49)
        call(50, 'state_integrity.py'); done(50)
        finalized_state = state(tr)
        finalized_attempts = len(attempts(tr))
        call(38, 'finalize_turn.py', tr, expected=2, tr=tr)
        assert state(tr) == finalized_state and len(attempts(tr)) == finalized_attempts
        done(38, duplicate_finalize_rejected=True, committed_state_unchanged=True)
        call(39, 'routing_receipt.py', '--turn-dir', tr, '--phase', 'finalization'); done(39)
        final_state = state(tr)
        before_attempts = len(attempts(tr))
        call(72, 'finalize_turn.py', tr, expected=2, tr=tr)
        assert state(tr) == final_state and len(attempts(tr)) == before_attempts; done(72)
        journal_path = tr / 'evidence/finalize-transaction.json'
        journal_before = journal_path.read_bytes()
        journal_row = json.loads(journal_before)
        journal_row['gate_attempt']['attempt_hash'] = '0' * 64
        journal_path.write_text(json.dumps(journal_row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        call(73, 'finalize_turn.py', tr, expected=2, tr=tr)
        assert state(tr) == final_state
        journal_path.write_bytes(journal_before)
        assert journal_path.read_bytes() == journal_before
        call(74, 'finalize_turn.py', tr, expected=2, tr=tr)
        assert state(tr) == final_state; done(73, forged_gate_attempt_rejected=True, committed_state_preserved=True)
        done(74, restored_committed_journal_still_immutable=True)

        recovery_turn = turn(75)
        valid_report(recovery_turn)
        ready(75, recovery_turn)
        prepare_full_evidence(recovery_turn)
        recovery_preimage = state(recovery_turn)
        interrupt_source = '''
import sys,json
from pathlib import Path
sys.path.insert(0, __SCRIPTS__)
import finalize_turn as finalizer
tr=Path(sys.argv[1])
atomic=finalizer._atomic_write
count={'n':0}
def interrupted_write(path,payload):
    count['n']+=1
    if count['n']==4:
        raise OSError('selfcheck simulated interruption between TURN and CURRENT writes')
    return atomic(path,payload)
def interrupted_rollback(*args,**kwargs):
    raise OSError('selfcheck process interruption leaves PREPARED journal for recovery')
finalizer._atomic_write=interrupted_write
finalizer._restore=interrupted_rollback
result=finalizer._finalize(tr)
assert result==2
journal=json.loads((tr/'evidence/finalize-transaction.json').read_text(encoding='utf-8'))
assert journal['result']=='PREPARED'
print(json.dumps({'result':result,'journal':journal['result'],'writes':count['n']}))
'''.replace('__SCRIPTS__', repr(str(scripts)))
        interruption = inline(75, interrupt_source, recovery_turn, tr=recovery_turn)
        assert 'PREPARED' in interruption
        prepared_path = recovery_turn / 'evidence/finalize-transaction.json'
        prepared_bytes = prepared_path.read_bytes()
        prepared_row = json.loads(prepared_bytes)
        assert (recovery_turn / 'TURN.md').read_bytes() != recovery_preimage[0]
        assert (fixture / 'CURRENT.md').read_bytes() == recovery_preimage[1]
        forged_preimage = json.loads(prepared_bytes)
        forged_preimage['preimage']['turn_sha256'] = '0' * 64
        prepared_path.write_text(json.dumps(forged_preimage, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        tampered_state = state(recovery_turn)
        call(86, 'finalize_turn.py', recovery_turn, expected=2, tr=recovery_turn)
        assert state(recovery_turn) == tampered_state
        prepared_path.write_bytes(prepared_bytes)
        done(86, unbound_preimage_rejected=True, interrupted_state_preserved=True)

        prepared_row['gate_attempt']['attempt_hash'] = 'f' * 64
        prepared_path.write_text(json.dumps(prepared_row, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        tampered_state = state(recovery_turn)
        call(76, 'finalize_turn.py', recovery_turn, expected=2, tr=recovery_turn)
        assert state(recovery_turn) == tampered_state
        prepared_path.write_bytes(prepared_bytes)
        forged_normalization = json.loads(prepared_bytes)
        forged_normalization['postimage']['normalized_turn_sha256'] = 'f' * 64
        prepared_path.write_text(json.dumps(forged_normalization, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', encoding='utf-8')
        tampered_state = state(recovery_turn)
        call(87, 'finalize_turn.py', recovery_turn, expected=2, tr=recovery_turn)
        assert state(recovery_turn) == tampered_state
        prepared_path.write_bytes(prepared_bytes)
        recovered = call(77, 'finalize_turn.py', recovery_turn, expected=2, tr=recovery_turn)
        assert 'rolled back' in recovered and state(recovery_turn) == recovery_preimage
        done(75, gate_passed_before_injected_interruption=True, prepared_journal_left=True)
        done(76, forged_prepared_gate_attempt_rejected=True, interrupted_state_preserved=True)
        done(87, forged_prepared_normalization_rejected=True, interrupted_state_preserved=True)
        done(77, prepared_transaction_restored_exact_preimage=True)
        call(78, 'finalize_turn.py', recovery_turn, tr=recovery_turn)
        assert '**Status**：FINALIZED' in (recovery_turn / 'TURN.md').read_text(encoding='utf-8')
        assert parse_meta(fixture / 'CURRENT.md') == {'schema': 1, 'visibility': 'public'}
        done(78, recovered_turn_finalized_with_public_current=True)

        action_turn = turn(79)
        valid_report(action_turn)
        css_action = fixture / 'src/a/theme.css'
        css_action_b = fixture / 'src/b/theme.css'
        css_before = css_action.read_bytes()
        css_before_b = css_action_b.read_bytes()
        css_action.write_bytes(css_before + b'/* action candidate */\n')
        css_action_b.write_bytes(css_before_b + b'/* second action candidate */\n')
        prepare_full_evidence(action_turn)
        marker = fixture / '.agent-project-control/runtime/tmp/action-runs.txt'
        command_code = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text((p.read_text(encoding='utf-8') if p.exists() else '')+'ran\\n',encoding='utf-8')"
        call(79, 'gate_enforce.py', '--entrypoint', 'action', '--turn-dir', action_turn,
             '--run', sys.executable, '-B', '-c', command_code, marker, expected=2, tr=action_turn)
        assert not marker.exists(); done(79, missing_action_target_rejected=True, command_not_run=True)
        call(80, 'gate_enforce.py', '--entrypoint', 'action', '--turn-dir', action_turn,
             '--target', 'src/a/theme.css', '--target', 'src/b/theme.css', expected=2, tr=action_turn)
        assert not marker.exists(); done(80, missing_action_command_rejected=True, command_not_run=True)
        route(81, action_turn, '--phase', 'scope', '--scope', 'src/a')
        route(81, action_turn, '--phase', 'scope', '--scope', 'src/b')
        call(81, 'gate_enforce.py', '--entrypoint', 'action', '--turn-dir', action_turn,
             '--target', 'src/a/theme.css', '--target', 'src/b/theme.css',
             '--run', sys.executable, '-B', '-c',
             command_code, marker, expected=3, tr=action_turn)
        assert not marker.exists()
        action_route_gaps = [f for f in attempts(action_turn)[-1]['findings']
                             if f['code'] == 'ACTION_TARGET_ROUTE_GAP']
        assert {f['subject'] for f in action_route_gaps} == {'src/a/theme.css', 'src/b/theme.css'}
        done(81, target_capability_receipt_required=True, command_not_run=True)
        route(82, action_turn, '--phase', 'scope', '--scope', 'src/a', '--capability', 'design',
              '--target', 'src/a/theme.css')
        route(82, action_turn, '--phase', 'scope', '--scope', 'src/b', '--capability', 'design',
              '--target', 'src/b/theme.css')
        route(82, action_turn, '--phase', 'finalization')
        action_output = call(82, 'gate_enforce.py', '--entrypoint', 'action', '--turn-dir', action_turn,
                             '--target', 'src/a/theme.css', '--target', 'src/b/theme.css',
                             '--run', sys.executable, '-B', '-c',
                             command_code, marker, tr=action_turn)
        assert marker.read_text(encoding='utf-8').splitlines() == ['ran']
        assert attempts(action_turn)[-1]['result'] == 'PASS' and 'PASS: entrypoint=action' in action_output
        done(82, action_gate='PASS', command_executions=len(marker.read_text(encoding='utf-8').splitlines()),
             action_targets=['src/a/theme.css', 'src/b/theme.css'])
        css_action.write_bytes(css_before)
        css_action_b.write_bytes(css_before_b)

        publish_turn = turn(83)
        valid_report(publish_turn, delivery=True)
        ready(83, publish_turn)
        route(83, publish_turn, '--phase', 'finalization', '--capability', 'github-publish',
              '--capability', 'human-readable')
        prepare_full_evidence(publish_turn, post_delivery=True)
        publish_output = call(83, 'gate_enforce.py', '--entrypoint', 'publish', '--turn-dir', publish_turn,
                              tr=publish_turn)
        publish_attempt = attempts(publish_turn)[-1]
        preflight = next(row for row in publish_attempt['adapter_evidence']
                         if row.get('kind') == 'operation-preflight')
        assert publish_attempt['gate_id'] == 'full-publish' and publish_attempt['result'] == 'PASS'
        assert preflight['pending_post_delivery_tests'] == ['TEST-DELIVERY']
        check_refs = [json.loads(line) for line in (publish_turn / 'evidence/checks.jsonl').read_text(encoding='utf-8').splitlines()]
        check_rows = [json.loads((publish_turn / row['path']).read_text(encoding='utf-8')) for row in check_refs]
        assert all('TEST-DELIVERY' not in row['test_ids'] for row in check_rows)
        assert 'TEST-DELIVERY' in (publish_turn / 'TEST.md').read_text(encoding='utf-8')
        assert '【进行中】【TEST-DELIVERY】' in (publish_turn / 'TEST.md').read_text(encoding='utf-8')
        done(83, publish_gate='PASS', deferred_postconditions=['TEST-DELIVERY'],
             delivery_check_not_fabricated=True, output=publish_output.strip().splitlines()[-1])

        denied_finalize(84, publish_turn, 3)
        assert any(f['code'] == 'ACTUAL_TEST_EVIDENCE_REQUIRED'
                   and any('TEST-DELIVERY' in problem for problem in f['evidence'][0]['problems'])
                   for f in attempts(publish_turn)[-1]['findings'])
        done(84, finalization_remains_strict=True, pending_delivery_state_preserved=True)

        valid_report(publish_turn, delivery=True, delivered=True)
        prepare_full_evidence(publish_turn)
        call(85, 'finalize_turn.py', publish_turn, tr=publish_turn)
        assert '**Status**：FINALIZED' in (publish_turn / 'TURN.md').read_text(encoding='utf-8')
        assert parse_meta(fixture / 'CURRENT.md') == {'schema': 1, 'visibility': 'public'}
        done(85, all_current_tests_passed=True, finalized=True, current_metadata='public')

        publish_mode_source = '''
import sys
from pathlib import Path
sys.path.insert(0, __SCRIPTS__)
import publish_guard as guard
turn=Path(sys.argv[1]).resolve()
candidate_mode=sys.argv[5]=='candidate'
gate_calls=[]
state_calls=[]
guard.resolve_delivery_turn=lambda raw: turn
def fake_gate(*,entrypoint,turn_dir_raw):
    gate_calls.append((entrypoint,Path(turn_dir_raw).resolve()))
    return (0,None)
guard.enforce_entrypoint=fake_gate
guard._source_stage_errors=lambda: []
guard.validate_state=lambda require_tracked: state_calls.append(require_tracked) or []
guard._candidate_errors=lambda *args: ([],set(),set())
argv=['publish_guard.py','--turn-dir',str(turn)]
if candidate_mode:
    argv.extend(['--candidate-repo',sys.argv[2],'--manifest',sys.argv[3],'--candidate-zip',sys.argv[4]])
sys.argv=argv
guard.main()
assert gate_calls==[('publish',turn)]
assert state_calls==([False] if candidate_mode else [True])
'''.replace('__SCRIPTS__', repr(str(scripts)))
        inline(88, publish_mode_source, publish_turn, fixture / 'candidate-repo',
               fixture / 'manifest.json', fixture / 'candidate.zip', 'candidate', tr=publish_turn)
        done(88, candidate_mode_publish_gate_turn=str(publish_turn), candidate_state_validation=False)
        inline(89, publish_mode_source, publish_turn, fixture / 'candidate-repo',
               fixture / 'manifest.json', fixture / 'candidate.zip', 'normal', tr=publish_turn)
        done(89, normal_mode_publish_gate_turn=str(publish_turn), source_state_validation=True)

        candidate_index_source = '''
import sys,hashlib,subprocess
from pathlib import Path
sys.path.insert(0, __SCRIPTS__)
import publish_guard as guard
root=Path(sys.argv[1])
repo=root/'.idx'
assert not repo.exists()
repo.mkdir(parents=True)
def git(*args):
    return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
secret_key=b'to'+b'ken='
index_secret=b'SYNTHETIC_' + b'SECRET_INDEX_ONLY_12345'
worktree_secret=b'SYNTHETIC_' + b'SECRET_WORKTREE_ONLY_98765'
git('init','-q')
git('config','user.name','APCF index fixture')
git('config','user.email','index-fixture@example.invalid')
(repo/'release.txt').write_bytes(secret_key+index_secret+b'\\n')
(repo/'stale.txt').write_bytes(b'preserved worktree deletion fixture\\n')
git('add','--all')
git('commit','-q','-m','Index fixture baseline')
index=repo/'.git/index'
def indexed_payloads():
    entries=guard._index_entries(repo,candidate=True)
    return entries,{name:guard._blob(repo,row['oid'],candidate=True) for name,row in entries.items()}
entries,baseline=indexed_payloads()
expected={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in baseline.items()}
index_before=index.read_bytes()
(repo/'release.txt').write_bytes(b'clean worktree view\\n')
assert index.read_bytes()==index_before
stage=guard._materialize_index(repo,entries,root/'.agent-project-control/runtime/tmp/index-stage-scan',expected)
assert stage['release.txt']['file'].read_bytes()==baseline['release.txt']
secret_findings=guard._native_findings(stage)
assert ('release.txt',1,'token_or_secret') in secret_findings
assert index_secret.decode() not in repr(secret_findings)
(repo/'release.txt').write_bytes(b'clean indexed candidate\\n')
git('add','--','release.txt')
entries,clean_index=indexed_payloads()
clean_expected={name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in clean_index.items()}
safe_index=index.read_bytes()
(repo/'release.txt').write_bytes(secret_key+worktree_secret+b'\\n')
assert index.read_bytes()==safe_index
stage=guard._materialize_index(repo,entries,root/'.agent-project-control/runtime/tmp/index-clean-scan',clean_expected)
assert stage['release.txt']['file'].read_bytes()==clean_index['release.txt']
assert not any(row[0]=='release.txt' for row in guard._native_findings(stage))
deletion_index_before=index.read_bytes()
git('rm','--cached','-q','--','stale.txt')
deletion_index_after=index.read_bytes()
assert deletion_index_before!=deletion_index_after and (repo/'stale.txt').is_file()
entries,_=indexed_payloads()
assert 'stale.txt' not in entries
remaining=guard._materialize_index(repo,entries,root/'.agent-project-control/runtime/tmp/index-deletion-scan',clean_expected)
residual=guard._check_inventory('candidate Git index',remaining,clean_expected)
assert any('missing manifest object: stale.txt' in error for error in residual)
print('PASS: actual Git index bytes govern candidate scan, split view and staged deletion')
'''.replace('__SCRIPTS__', repr(str(scripts)))
        candidate_index_repo = fixture / '.idx'
        try:
            index_result = inline(90, candidate_index_source, fixture, tr=publish_turn)
        finally:
            if candidate_index_repo.exists():
                shutil.rmtree(candidate_index_repo, onerror=remove_readonly)
        assert 'actual Git index bytes govern' in index_result
        done(90, index_to_worktree_split=True, staged_deletion_manifest_residual=True,
             actual_git_index_bytes=True)

        contract = (fixture / '.agent-project-control/gate.toml').read_bytes()
        try:
            path = fixture / '.agent-project-control/gate.toml'
            path.write_bytes(contract.replace(b'auto_route_phases = ["finalization"]', b'auto_route_phases = []'))
            gap = turn(40); valid_report(gap); ready(40, gap)
            denied_finalize(40, gap, 3)
            assert any(f['subject'] == 'finalization' for f in attempts(gap)[-1]['findings']); done(40)
        finally:
            path.write_bytes(contract)

        tr = turn(44); valid_report(tr); ready(44, tr)
        baseline = tr / 'evidence/activity-baseline.json'; old = baseline.read_bytes()
        try:
            baseline.write_bytes(b'{}\n')
            baseline_denial = denied_finalize(44, tr, 2)
            assert 'activity baseline schema mismatch' in baseline_denial
            done(44)
        finally:
            baseline.write_bytes(old)
        tr = turn(43); valid_report(tr); ready(43, tr)
        a, b = fixture / 'src/a/theme.css', fixture / 'src/b/theme.css'
        aa, bb = a.read_bytes(), b.read_bytes()
        try:
            a.write_bytes(aa + b'/* A */\n')
            denied_finalize(43, tr, 3)
            assert any(f['code'] == 'ROUTE_SCOPE_SOURCE_GAP' for f in attempts(tr)[-1]['findings']); done(43)
            a.write_bytes(aa); b.write_bytes(bb + b'/* B */\n')
            denied_finalize(46, tr, 3)
            b.write_bytes(bb); a.write_bytes(aa + b'/* A */\n')
            denied_finalize(46, tr, 5)
            assert attempts(tr)[-1]['transition']['no_progress_reason'] == 'failure-set-reappeared-within-current-repair-episode'; done(46)
        finally:
            a.write_bytes(aa); b.write_bytes(bb)
        import ast
        tree = ast.parse((scripts / 'gate_enforce.py').read_text(encoding='utf-8'))
        enforce = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'enforce_entrypoint')
        assert not any(isinstance(n, ast.While) for n in ast.walk(enforce))
        assert sum(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'evaluate_route_gate' for n in ast.walk(enforce)) == 1
        done(51)
        assert all(x['attempt_delta'] <= 1 for x in invocations if x['script'] == 'finalize_turn.py'); done(52)

        tr = turn(58)
        # Each resolver call is real; existing matrix Turns remain intact.
        resolve_code = 'from gate_enforce import resolve_delivery_turn; import sys; print(resolve_delivery_turn(sys.argv[1] if len(sys.argv)>1 else None))'
        def resolve(number, explicit=None, expected=0):
            r = subprocess.run([sys.executable, '-B', '-c', resolve_code, *([str(explicit)] if explicit else [])], cwd=fixture,
                               capture_output=True, text=True, encoding='utf-8', env=_childenv(scripts))
            ROWS.append({'case': f'Step1EB/{number}/resolver', 'exit_code': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr})
            assert r.returncode == expected, (number, r.stdout, r.stderr)
            return r.stdout.strip()
        assert resolve(58, tr) == str(tr); done(58)
        saved = {p: p.read_bytes() for p in (fixture / '.agent-project-control/iterations').glob('IT-*/turns/TR-*/TURN.md')}
        current = fixture / 'CURRENT.md'; current_old = current.read_bytes()
        try:
            for p, content in saved.items():
                if p.parent != tr:
                    p.write_bytes(content.replace(b'IN_PROGRESS', b'FINALIZED'))
            assert resolve(59) == str(tr); done(59)
            other = turn(61)
            before = git('status', '--porcelain'); index_before = (fixture / '.git/index').read_bytes()
            call(61, 'publish_guard.py', expected=2)
            assert (fixture / '.git/index').read_bytes() == index_before and git('status', '--porcelain') == before; done(61)
            other.joinpath('TURN.md').write_bytes(other.joinpath('TURN.md').read_bytes().replace(b'IN_PROGRESS', b'FINALIZED'))
            tr.joinpath('TURN.md').write_bytes(tr.joinpath('TURN.md').read_bytes().replace(b'IN_PROGRESS', b'FINALIZED'))
            current.write_text(public + '# 1. Synthetic current\n- **Source TURN**：`' + tr.relative_to(fixture).as_posix() + '`\n', encoding='utf-8')
            assert resolve(60) == str(tr); done(60)
            current.write_text(public + '# 1. Unresolved current\n', encoding='utf-8')
            call(62, 'publish_guard.py', expected=2); done(62)
        finally:
            for p, content in saved.items(): p.write_bytes(content)
            current.write_bytes(current_old)

        tr = turn(65)
        private = tr / 'REQUEST.md'
        git('add', '-f', '--', private.relative_to(fixture).as_posix())
        index_before = (fixture / '.git/index').read_bytes()
        source_before = (fixture / 'src/server.py').read_bytes()
        old = state(tr)
        out = call(65, 'publish_guard.py', '--turn-dir', tr, expected=3, tr=tr)
        assert 'GATE_DENIED' in out and 'private file staged' not in out
        assert any(f['code'] == 'ROUTE_PHASE_GAP' and f['subject'] == 'finalization' for f in attempts(tr)[-1]['findings']); done(65)
        assert (fixture / '.git/index').read_bytes() == index_before and (fixture / 'src/server.py').read_bytes() == source_before and state(tr) == old; done(68)
        call(63, 'routing_receipt.py', '--turn-dir', tr, '--phase', 'delivery'); done(63)
        valid_report(tr, delivery=True)
        ready(64, tr)
        route(64, tr, '--phase', 'finalization', '--capability', 'github-publish', '--capability', 'human-readable')
        prepare_full_evidence(tr, post_delivery=True)
        out = call(64, 'publish_guard.py', '--turn-dir', tr, expected=2, tr=tr)
        assert attempts(tr)[-1]['result'] == 'PASS' and 'private' in out.lower(); done(64)
        assert 'GATE_DENIED' not in out and 'FAIL' in out; done(66)
        git('reset', '-q', '--', private.relative_to(fixture).as_posix())
        private_runtime = fixture / '.agent-project-control/runtime/tmp/staged-private.txt'
        private_runtime.write_text('# APCF-META {"schema":1,"visibility":"private"}\nSynthetic runtime output\n', encoding='utf-8')
        git('add', '-f', '--', private_runtime.relative_to(fixture).as_posix())
        route(67, tr, '--phase', 'scope', '--phase', 'framework', '--phase', 'finalization',
              '--capability', 'github-publish', '--capability', 'human-readable')
        out = call(67, 'publish_guard.py', '--turn-dir', tr, expected=2, tr=tr)
        assert attempts(tr)[-1]['result'] == 'PASS' and ('private' in out.lower() or 'runtime' in out.lower()); done(67)
        git('reset', '-q', '--', private_runtime.relative_to(fixture).as_posix())
        private_runtime.unlink()
        valid_report(tr); ready(66, tr); prepare_full_evidence(tr)
        call(66, 'finalize_turn.py', tr, tr=tr)
        call(66, 'repair_current_state.py', '--stage')
        prepare_full_evidence(tr)
        route(66, tr, '--phase', 'scope', '--phase', 'verification', '--phase', 'framework',
              '--phase', 'finalization', '--capability', 'github-publish', '--capability', 'human-readable')
        out = call(66, 'publish_guard.py', '--turn-dir', tr, tr=tr)
        assert 'PASS: publication guard' in out and attempts(tr)[-1]['result'] == 'PASS'
        assert all(x['attempt_delta'] <= 1 for x in invocations if x['script'] == 'publish_guard.py'); done(69)
        assert all(x['attempt_delta'] <= 1 for x in invocations)
        done(70, entrypoint_invocations=invocations, automatic_repair=False)
        expected = set(range(26, 53)) | set(range(58, 91))
        assert passed == expected, sorted(expected - passed)
        ROWS.append({'case': 'Step1EB/entrypoint-summary', 'exit_code': 0, 'stdout': 'PASS', 'stderr': '', 'cases': sorted(passed)})
        print('PASS: Step 1E-B real entrypoint cases 26-52 and 58-90')
    finally:
        assert fixture.resolve().parent == CASE.parent.resolve()
        remove_core_test_fixture(fixture, CASE.parent)


if __name__ == '__main__':
    outcome = 'FAIL'
    try:
        main()
        outcome = 'PASS'
    except BaseException as exc:
        import traceback
        ROWS.append({'case': 'selfcheck/uncaught-failure', 'exit_code': 1,
                     'exception_type': type(exc).__name__,
                     'message': str(exc)[:2000],
                     'traceback': [str(frame) for frame in traceback.extract_tb(exc.__traceback__)]})
        raise
    finally:
        if _FIXTURE_GIT_PROCESS_CONFIG is not None:
            # Only this run's exclusively-created file is removed.
            _FIXTURE_GIT_PROCESS_CONFIG.unlink(missing_ok=True)
        summary = store_run(ROOT / '.agent-project-control/runtime/runs', ROWS,
                            outcome, run_id=RUN_ID)
        print('selfcheck run:', summary['run_id'], 'outcome:', outcome,
              'raw SHA-256:', summary['raw_sha256'])
