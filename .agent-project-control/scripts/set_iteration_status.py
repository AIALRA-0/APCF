# APCF-META {"schema":1,"visibility":"public"}
import argparse,re
from common import FRAMEWORK_ROOT
ALLOWED=['ACTIVE','PAUSED','BLOCKED','COMPLETED','SUPERSEDED','CANCELLED']
def _main():
    ap=argparse.ArgumentParser(); ap.add_argument('it_id'); ap.add_argument('status',choices=ALLOWED); a=ap.parse_args(); hits=list((FRAMEWORK_ROOT/'iterations').glob(a.it_id+'_*'))
    if len(hits)!=1: raise SystemExit('FAIL: IT not unique')
    if a.status=='ACTIVE':
        others=[p for p in (FRAMEWORK_ROOT/'iterations').glob('IT-*/ITERATION.md') if p.parent!=hits[0] and '**Status**：ACTIVE' in p.read_text(encoding='utf-8')]
        if others:raise SystemExit('FAIL: another ACTIVE iteration exists; pause it explicitly first')
    f=hits[0]/'ITERATION.md'; t=f.read_text(encoding='utf-8'); t,n=re.subn(r'- \*\*Status\*\*：\w+',f'- **Status**：{a.status}',t,count=1)
    if not n: raise SystemExit('FAIL: status missing')
    f.write_text(t,encoding='utf-8'); print('PASS')
def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        return _main()

if __name__=='__main__': main()
