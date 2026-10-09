# APCF-META {"schema":1,"visibility":"public"}
"""Run finite synthetic success/repair examples in a new, isolated project.

The examples execute real framework commands and assertions. They never publish,
modify source-template history, adopt a Design Profile, or attest real user work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def invoke(project: Path, script: str, *args, expected=0) -> str:
    command = [sys.executable, '-B', str(project / '.agent-project-control/scripts' / script), *map(str, args)]
    environment = os.environ.copy()
    environment['PYTHONUTF8'] = '1'
    environment['PYTHONIOENCODING'] = 'utf-8'
    result = subprocess.run(command, cwd=project, capture_output=True, text=True, encoding='utf-8', env=environment)
    logs = project / '.agent-project-control/runtime/runs'
    from time import time_ns
    name = logs / ('demo-command-' + str(time_ns()) + '.json')
    payload = json.dumps({'command': command, 'exit_code': result.returncode,
                          'stdout': result.stdout, 'stderr': result.stderr}, ensure_ascii=False).encode('utf-8')
    name.write_bytes(payload)
    name.with_name(name.name + '.apcf-meta.yaml').write_text(
        '# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\nsha256: '
        + hashlib.sha256(payload).hexdigest() + '\n', encoding='utf-8')
    if result.returncode != expected:
        raise RuntimeError(f'{script}: expected {expected}, observed {result.returncode}; evidence={name.name}')
    return result.stdout


def review_demo_terms(report: str) -> dict:
    """Replay the reviewed meanings of this finite example, never arbitrary text."""
    from datetime import datetime, timezone
    from terminology_review import initial_review, report_sections, validate
    definitions = {
        'IT': '框架中承载一个稳定目标的迭代单元，本例用它组织当前合成任务',
        'TR': '当前合成任务的一次执行记录，保存清单、验收和报告',
        'Full Gate': '收口前的完整检查，核对路由、实际证据和内容复核',
        'Profile': '可选设计方案，本例未采用任何方案',
    }
    review = initial_review(report)
    stamp = datetime.now(timezone.utc).isoformat()
    audience = '阅读框架首次使用示例的开发者；IT/TR 和 Full Gate 已在本例术语表解释'
    reviewer = 'Codex: author reviewing the bounded synthetic example'
    review.update(reviewer=reviewer, reviewed_at=stamp, audience_context=audience, semantic_review_completed=True)
    def meaning(term, lines, explained):
        return dict(meaning_id='example-use', line_numbers=lines,
                    decision='EXPLAINED' if explained else 'LITERAL_FORMAT',
                    reason=f'{term} 在当前示例中表示 '+(definitions[term] if explained else '验收状态原始标记'),
                    audience_context=audience, domain_context='合成框架使用示例',
                    current_use=definitions[term] if explained else term+' 当前验收状态',
                    context_relevance='帮助读者核对本例结果和实际检查步骤',
                    name_status='NOT_APPLICABLE', verified_full_name='',
                    name_limit='框架局部身份和状态标签不臆造英文展开',
                    definition=definitions[term] if explained else '验收状态标记',
                    source_or_basis='.agent-project-control/rules/INDEX.md 及本例逐项术语说明',
                    reviewer=reviewer, reviewed_at=stamp)
    for item in review['items']:
        term = item['term']
        if term not in definitions and term not in {'PASS', 'FAIL', 'BLOCKED'}:
            raise AssertionError('Unreviewed term outside the finite example: '+term)
        item['meanings'] = [meaning(term, item['line_numbers'], term in definitions)]
    _, sections = report_sections(report)
    start, end = sections[2][2:]
    excluded = set(range(report[:start].count('\n')+1, report[:end].count('\n')+2))
    for term in ('Full Gate', 'Profile'):
        lines = [n for n,line in enumerate(report.splitlines(),1) if n not in excluded and term in line]
        if lines:
            review['manual_terms'].append(dict(term=term, line_numbers=lines, meanings=[meaning(term, lines, True)]))
    review['attestations'] = {name: True for name in review['attestations']}
    assert not validate(report, review), validate(report, review)
    return review


def worker(project: Path, scenario: str) -> None:
    sys.path.insert(0, str(project / '.agent-project-control/scripts'))
    from common import dir_marker, write_md
    from routing_activity import (record_content_review, record_plan, record_semantic_review, run_check, _private_json)
    from route_context import capability_closure, load_contract, matching_capabilities
    from audit_routes import classify_activity
    from routing_activity import collect_activity, load_audit_contract
    from report_contract import SECTION_TITLES
    from test_ledger import TEST_FORMAT_MARKER, serialize_v2

    iteration = Path(invoke(project, 'new_iteration.py', '--title', 'synthetic-demo',
                            '--objective', '验证独立合成示例，不代表业务项目采用事实').strip().splitlines()[-1])
    turn = Path(invoke(project, 'new_turn.py', '--title', scenario,
                       '--request-text', 'Synthetic example: verify a local result and the managed lifecycle.').strip().splitlines()[-1])
    target = 'demo.py' if scenario == 'success' else 'demo.md'
    checklist = '- 【进行中】【CL-DEMO】【合成结果】：在独立合成环境中验证结果，并以真实断言和 Full Gate 当前验收确认完成'
    test_row = dict(status='未执行', id='TEST-DEMO', refs=['CL-DEMO'], object='合成结果',
                    context='独立合成项目和当前候选', action='运行结果断言及必要负向检查',
                    expected='结果符合预期且错误内容被拒绝', actual='尚未执行', evidence='evidence/checks.jsonl')
    test = serialize_v2(test_row)
    write_md(turn / 'CHECKLIST.md', '# 1. 当前执行清单\n\n' + checklist)
    write_md(turn / 'TEST.md', '# 1. 当前验收记录\n\n' + TEST_FORMAT_MARKER + '\n\n' + test)
    write_md(turn / 'evidence/investigation.md', '# 1. 合成调查\n\n'
             '当前输入是显式生成的最小演示，不包含真实用户资料\n\n'
             '成功用例检查两个独立函数输入；修复用例检查可编辑正文和受保护代码块，实际命令结果保存在本轮证据\n', 'private')
    record_plan(turn, [target], ['evidence/investigation.md'], ['TEST-DEMO'])
    invoke(project, 'route_context.py', '--phase', 'scope', '--phase', 'verification',
           '--phase', 'tools', '--phase', 'finalization', '--target', target, '--turn-dir', turn)
    record_semantic_review(turn, {target: '目标是合成结果文件；Python 用例没有隐藏的 UI 或部署行为'},
                           ['evidence/investigation.md'])
    if scenario == 'success':
        body = 'def increment(value):\n    return value + 1\n'
    else:
        body = '# 1. 合成说明\n\n当前结果已保存。\n\n```python\nprint("受保护原文。")\n```\n'
    code = 'from pathlib import Path; Path(' + repr(target) + ').write_text(' + repr(body) + ',encoding="utf-8")'
    invoke(project, 'gate_enforce.py', '--entrypoint', 'action', '--turn-dir', turn,
           '--target', target, '--run', sys.executable, '-B', '-c', code)

    if scenario == 'repair':
        record_content_review(turn, target, ['human-readable'], ['evidence/investigation.md'],
                              [{'line': 3, 'criterion': 'Writing v0.1 §1',
                                'observed': '可编辑正文含中文句号，代码块属于保留原文', 'result': 'FAIL'}], result='FAIL')
        before = (project / target).read_bytes()
        invoke(project, 'gate_check.py', '--turn-dir', turn, '--profile', 'full', expected=3)
        assert (project / target).read_bytes() == before, 'Gate denial must not change content'
        write_md(turn / 'evidence/diagnosis.md', '# 1. 合成诊断\n\n'
                 '拒绝来自可编辑正文的格式问题；修复只删除该正文末尾句号，代码块字符保持原样\n', 'private')
        repaired = body.replace('当前结果已保存。', '当前结果已保存')
        (project / target).write_text(repaired, encoding='utf-8')
        assert 'print("受保护原文。")' in repaired
        command = [sys.executable, '-B', '-c',
                   'from pathlib import Path; s=Path("demo.md").read_text(encoding="utf-8"); '
                   'assert "当前结果已保存。" not in s; assert \'print("受保护原文。")\' in s; print("PASS: prose repaired and protected bytes retained")']
    else:
        command = [sys.executable, '-B', '-c',
                   'from demo import increment; assert increment(0)==1; assert increment(-2)==-1; print("PASS: both input assertions")']
    record_semantic_review(turn, {target: '实际候选只含本用例结果；已读取当前文件并核对没有隐藏的专用行为'},
                           ['evidence/investigation.md'])
    code, result = run_check(turn, ['TEST-DEMO'], [target], command, required_output=['PASS:'])
    assert code == 0, result
    checklist = checklist.replace('【进行中】', '【已完成】')
    test_row.update(status='PASS', actual='真实结果断言满足，证据已保存')
    test = serialize_v2(test_row)
    write_md(turn / 'CHECKLIST.md', '# 1. 当前执行清单\n\n' + checklist)
    write_md(turn / 'TEST.md', '# 1. 当前验收记录\n\n' + TEST_FORMAT_MARKER + '\n\n' + test)
    sections = [
        '- **IT**：' + iteration.name.split('_')[0] + '\n- **TR**：' + turn.name.split('_')[0]
        + '\n- **结果状态**：合成范围通过\n- **Checklist 摘要**：已完成 1\n- **Test 摘要**：PASS 1 / FAIL 0 / BLOCKED 0',
        '本轮从干净合成项目开始，实际执行初始化和规则路由\n\n当前合成结果通过直接断言，随后检查完整收口路径',
        '- IT：框架内承载一个稳定目标的迭代单元，本例用它组织当前合成任务\n'
        '- TR：框架内一次执行轮次的独立记录，本例用它保存请求、清单、验收和报告\n'
        '- Full Gate：完整验收检查，核对当前候选的路由、真实证据和内容复核后才允许收口\n'
        '- Profile：项目可选的设计方案，本例保持未采用，不让示例代替业务项目选择',
        checklist, test,
        '本用例使用真实命令和断言，报告只说明当前有限合成范围；修复用例另保留原失败与局部修复证据',
        '- **合成结果具备直接证据**：结果由实际运行的断言确认，证据只支持本例覆盖的输入和内容边界',
        '- **当前无需用户补充**：本例没有外部账号和生产系统依赖',
        '- **业务采用仍由真实事实决定**：本例不采用任何 Profile，也不证明实际项目全部场景',
        '- **保留有限验证结论**：后续真实项目应按当前用户需求调查和验收，本例只提供可复核的操作路径',
    ]
    report = '\n\n'.join('## ' + str(i) + '. ' + title + '\n\n' + sections[i]
                          for i, title in enumerate(SECTION_TITLES))
    write_md(turn / 'TURN.md', '# 1. ' + turn.name.split('_')[0] + ' 合成报告\n\n'
             '- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n' + report)
    from report_contract import validate_report
    from gate_check import _markdown_prose
    assert validate_report(report, turn) == [], validate_report(report, turn)
    _private_json(turn / 'evidence/terms-review.json', review_demo_terms(report))
    paths = classify_activity(turn, load_audit_contract(), collect_activity(turn))['target_paths']
    for rel in paths + [(turn / n).relative_to(project).as_posix() for n in ('CHECKLIST.md', 'TEST.md', 'TURN.md')]:
        caps, _ = matching_capabilities(load_contract(), [project / rel])
        closure = capability_closure(load_contract(), caps)
        needed = [c for c in closure if c in {'writing', 'style', 'design', 'readme'}]
        if needed:
            text = (project / rel).read_text(encoding='utf-8')
            assert text, 'actual review object must exist'
            assert all('。' not in prose for _, prose in _markdown_prose(text))
            record_content_review(turn, rel, needed, ['evidence/investigation.md'],
                                  [{'line': 1, 'criterion': '有限合成输入的 R20 对照和可编辑正文检查',
                                    'observed': '实际执行报告结构、源 CL/TEST 一致性、可编辑正文断言；代码块保留检查单独通过', 'result': 'PASS'}],
                                  method='deterministic-fixture-review')
    record_plan(turn, paths, ['evidence/investigation.md'], ['TEST-DEMO'])
    invoke(project, 'audit_routes.py', '--turn-dir', turn)
    invoke(project, 'finalize_turn.py', turn)
    invoke(project, 'state_integrity.py')
    current = (project / 'CURRENT.md').read_text(encoding='utf-8').split('## 1.1. 最新完整用户报告', 1)[1].strip()
    final = (turn / 'TURN.md').read_text(encoding='utf-8').split('## 1.1. USER REPORT', 1)[1].strip()
    assert current == final == report
    print('PASS: synthetic ' + scenario + '; direct assertions, Audit, Full Gate and Finalize completed')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--scenario', choices=['success', 'repair'], required=True)
    parser.add_argument('--installed-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if args.installed_worker:
        worker(project, args.scenario)
        return
    source = Path(__file__).resolve().parents[1]
    if project.exists() and any(project.iterdir()):
        raise SystemExit('FAIL: demo target must be a new empty project')
    subprocess.run([sys.executable, '-B', str(source / '.agent-project-control/scripts/bootstrap.py'), str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'init', '--initial-branch=main'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(project), 'config', 'user.name', 'Synthetic Template Example'], check=True)
    subprocess.run(['git', '-C', str(project), 'config', 'user.email', 'example@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(project), 'config', 'core.autocrlf', 'false'], check=True)
    subprocess.run(['git', '-C', str(project), 'add', '--', 'AGENTS.md', 'CURRENT.md', '.agent-project-control', '.codex'], check=True)
    subprocess.run(['git', '-C', str(project), 'commit', '-m', 'Initialize synthetic control shell'], check=True, capture_output=True)
    subprocess.run([sys.executable, '-B', str(Path(__file__)), '--project', str(project),
                    '--scenario', args.scenario, '--installed-worker'], check=True)


if __name__ == '__main__':
    main()
