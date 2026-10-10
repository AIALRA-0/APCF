# APCF-META {"schema":1,"visibility":"public"}
import argparse
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker
def _main():
    ap=argparse.ArgumentParser(); ap.add_argument('--title',required=True); ap.add_argument('--objective',required=True); a=ap.parse_args()
    active=[]
    for p in (FRAMEWORK_ROOT/'iterations').glob('IT-*'):
        f=p/'ITERATION.md'
        if f.exists() and '**Status**：ACTIVE' in f.read_text(encoding='utf-8'): active.append(p)
    if active: raise SystemExit('FAIL: ACTIVE IT already exists')
    rid=next_id('IT',FRAMEWORK_ROOT/'iterations'); s=now_stamp(); d=FRAMEWORK_ROOT/'iterations'/f'{rid}_{s}_{slugify(a.title)}'; dir_marker(d); dir_marker(d/'turns')
    write_md(d/'ITERATION.md',f'# 1. {rid} {a.title}\n\n- **Status**：ACTIVE\n- **Created**：{s}\n- **Objective**：{a.objective}\n')
    from refresh_indexes import main as r; r(); print(d)
def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        return _main()

if __name__=='__main__': main()
