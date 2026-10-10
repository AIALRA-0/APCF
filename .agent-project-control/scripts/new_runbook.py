# APCF-META {"schema":1,"visibility":"public"}
import argparse
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md
def _main():
    ap=argparse.ArgumentParser(); ap.add_argument('--title',required=True); a=ap.parse_args(); rid=next_id('RB',FRAMEWORK_ROOT/'runbooks'); s=now_stamp(); f=FRAMEWORK_ROOT/'runbooks'/f'{rid}_{s}_{slugify(a.title)}.md'; write_md(f,f'# 1. {rid} {a.title}\n\n## 1.1. Trigger\n\n待填写\n\n## 1.2. Desired Outcome\n\n待填写\n\n## 1.3. Prerequisites / Tools / Permissions\n\n待填写\n\n## 1.4. Steps\n\n待填写\n\n## 1.5. Validation\n\n待填写\n\n## 1.6. Failure Handling / Recovery\n\n待填写\n'); return f
def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        result=_main()
        from refresh_indexes import main as refresh
        refresh()
        print(result)
        return result

if __name__=='__main__': main()
