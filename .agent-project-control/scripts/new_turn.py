# APCF-META {"schema":1,"visibility":"public"}
import argparse
from pathlib import Path
import shutil
from routing_activity import init_baseline
from gate_kernel import GateError
from gate_enforce import EnforcementError, enforce_entrypoint
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--title',required=True)
    ap.add_argument('--request-text',default='')
    a=ap.parse_args()
    active=[]
    for p in (FRAMEWORK_ROOT/'iterations').glob('IT-*'):
        f=p/'ITERATION.md'
        if f.exists() and '**Status**：ACTIVE' in f.read_text(encoding='utf-8'):
            active.append(p)
    if len(active)!=1:
        raise SystemExit(f'FAIL: expected one ACTIVE IT, found {len(active)}')
    rid=next_id('TR',FRAMEWORK_ROOT/'iterations')
    s=now_stamp()
    d=active[0]/'turns'/f'{rid}_{s}_{slugify(a.title)}'
    if d.exists():
        raise SystemExit('FAIL: new Turn path already exists')
    dir_marker(d); dir_marker(d/'evidence','private'); dir_marker(d/'parallel','private')
    write_md(d/'REQUEST.md','# 1. 用户原始请求\n\n'+a.request_text,'private')
    write_md(
        d/'CHECKLIST.md',
        '# 1. 当前执行清单\n\n'
        '- 【未开始】【CL-01】【规则加载】：当新的执行轮次开始时，因旧上下文可能导致当前规则与作用域漂移，必须重新读取当前作用域适用规则，并以规则入口、作用域和当前要求均已重新核对确认通过\n'
    )
    write_md(
        d/'TEST.md',
        '# 1. 当前验收记录\n\n'
        '<!-- APCF-TEST-FORMAT v2 -->\n\n'
        '当前尚未建立 TEST-ID；执行前根据当前 Checklist 建立本轮验收表单；每个 TEST-ID 只记录当前候选的有效验收结果，一条 Checklist 可以由一个或多个 TEST 从不同验收维度共同证明\n'
    )
    write_md(
        d/'TURN.md',
        f'# 1. {rid} 执行轮次报告\n\n- **Status**：IN_PROGRESS\n- **Started**：{s}\n\n## 1.1. USER REPORT\n\n尚未收口\n'
    )
    try:
        init_baseline(d)
        code, _ = enforce_entrypoint(entrypoint="bootstrap", turn_dir_raw=d)
        if code:
            raise SystemExit(code)
    except BaseException:
        # Only this invocation's newly created, unexecuted Turn is rolled back.
        if d.resolve().parent != (active[0] / 'turns').resolve():
            raise RuntimeError('FAIL: unsafe new Turn rollback path')
        shutil.rmtree(d)
        raise
    print(d)


if __name__ == '__main__':
    try: main()
    except (GateError, EnforcementError) as exc:
        print(f'FAIL: {exc}'); raise SystemExit(exc.code)
