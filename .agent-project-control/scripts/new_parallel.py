# APCF-META {"schema":1,"visibility":"public"}
import argparse
from pathlib import Path
from gate_kernel import GateError
from gate_enforce import EnforcementError, enforce_entrypoint
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('turn_dir'); ap.add_argument('--title',required=True); ap.add_argument('--request-text',required=True); a=ap.parse_args(); tr=Path(a.turn_dir).resolve()
    if tr.name.startswith('PA-') or any(x.name=='parallel' for x in tr.parents): raise SystemExit('FAIL: nested Parallel Agent is forbidden')
    if not tr.name.startswith('TR-'): raise SystemExit('FAIL: parent must be TR')
    code, _ = enforce_entrypoint(entrypoint='parallel', turn_dir_raw=tr)
    if code: raise SystemExit(code)
    rid=next_id('PA',FRAMEWORK_ROOT/'iterations'); s=now_stamp(); d=tr/'parallel'/f'{rid}_{s}_{slugify(a.title)}'; dir_marker(d); dir_marker(d/'evidence')
    for fn,title,body in [('REQUEST.md','并行任务原始请求',a.request_text),('CHECKLIST.md','并行任务执行清单','- 【未开始】【范围】：只执行主智能体分配的边界'),('TEST.md','并行任务验收记录','<!-- APCF-TEST-FORMAT v2 -->\n\n当前尚未执行测试'),('TURN.md',rid+' 并行任务报告','- **Status**：IN_PROGRESS')]: write_md(d/fn,f'# 1. {title}\n\n{body}\n')
    print(d)
if __name__=='__main__':
    try: main()
    except (GateError, EnforcementError) as exc:
        print(f'FAIL: {exc}'); raise SystemExit(exc.code)
