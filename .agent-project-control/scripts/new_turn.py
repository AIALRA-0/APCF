# APCF-META {"schema":1,"visibility":"public"}
import argparse
from pathlib import Path
import shutil
from routing_activity import init_baseline
from gate_kernel import GateError
from gate_enforce import EnforcementError, enforce_entrypoint
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker


def initial_goal():
    from test_ledger import serialize_goal
    prose='当本轮开始或上下文恢复时，旧工作目录与已缓存规则可能不再适用，这会使后续修改越过当前目标边界；因此必须核实真实项目根、原始请求和适用规范，并以入口实际可读、作用域明确且计划先于业务修改作为完成判据'
    return serialize_goal({'status':'未开始','id':'CL-01','object':'规则与项目入口'},prose,{
        'context':'当本轮开始或上下文恢复时','problem':'旧工作目录与已缓存规则可能不再适用',
        'consequence':'这会使后续修改越过当前目标边界','requirement':'必须核实真实项目根、原始请求和适用规范',
        'criterion':'入口实际可读、作用域明确且计划先于业务修改'})

def _main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--title',required=True)
    group=ap.add_mutually_exclusive_group()
    group.add_argument('--request-text',default='')
    group.add_argument('--request-file')
    a=ap.parse_args()
    active=[]
    for p in (FRAMEWORK_ROOT/'iterations').glob('IT-*'):
        f=p/'ITERATION.md'
        if f.exists() and '**Status**：ACTIVE' in f.read_text(encoding='utf-8'):
            active.append(p)
    if len(active)!=1:
        raise SystemExit(f'FAIL: expected one ACTIVE IT, found {len(active)}')
    request=Path(a.request_file).read_text(encoding='utf-8') if a.request_file else a.request_text
    if not request.strip():raise SystemExit('FAIL: original current request is required before the first business write')
    rid=next_id('TR',FRAMEWORK_ROOT/'iterations')
    s=now_stamp()
    d=active[0]/'turns'/f'{rid}_{s}_{slugify(a.title)}'
    if d.exists():
        raise SystemExit('FAIL: new Turn path already exists')
    dir_marker(d); dir_marker(d/'evidence','private'); dir_marker(d/'parallel','private')
    write_md(d/'REQUEST.md','# 1. 用户原始请求\n\n'+request,'private')
    write_md(
        d/'CHECKLIST.md',
        '# 1. 当前执行清单\n\n<!-- APCF-GOAL-FORMAT v1 -->\n\n' +
        initial_goal() + '\n'
    )
    write_md(
        d/'TEST.md',
        '# 1. 当前验收记录\n\n'
        '<!-- APCF-TEST-FORMAT v3 -->\n\n'
        '当前尚未建立 TEST-ID；执行前根据当前 Checklist 建立本轮验收表单；每个 TEST-ID 只记录当前候选的有效验收结果，一条 Checklist 可以由一个或多个 TEST 从不同验收维度共同证明\n'
    )
    write_md(
        d/'TURN.md',
        f'# 1. {rid} 执行轮次报告\n\n- **Status**：IN_PROGRESS\n- **Started**：{s}\n\n## 1.1. USER REPORT\n\n尚未收口\n'
    )
    rollback_state={}
    try:
        init_baseline(d)
        from execution_session import begin
        begin(d,rollback_state=rollback_state)
        from writing_guard import bind as bind_writing_contract
        bind_writing_contract(d)
        code, _ = enforce_entrypoint(entrypoint="bootstrap", turn_dir_raw=d)
        if code:
            raise SystemExit(code)
    except BaseException:
        from execution_session import rollback_begin
        rollback_begin(rollback_state)
        # Only this invocation's newly created, unexecuted Turn is rolled back.
        if d.resolve().parent != (active[0] / 'turns').resolve():
            raise RuntimeError('FAIL: unsafe new Turn rollback path')
        shutil.rmtree(d)
        raise
    print(d)


def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        return _main()

if __name__ == '__main__':
    try: main()
    except (GateError, EnforcementError) as exc:
        print(f'FAIL: {exc}'); raise SystemExit(exc.code)
