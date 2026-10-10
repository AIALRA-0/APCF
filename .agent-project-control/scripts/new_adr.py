# APCF-META {"schema":1,"visibility":"public"}
import argparse
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md
def _main():
    ap=argparse.ArgumentParser(); ap.add_argument('--title',required=True); a=ap.parse_args(); rid=next_id('ADR',FRAMEWORK_ROOT/'decisions'); s=now_stamp(); f=FRAMEWORK_ROOT/'decisions'/f'{rid}_{s}_{slugify(a.title)}.md'; write_md(f,f'# 1. {rid} {a.title}\n\n- **Status**：PROPOSED\n\n## 1.1. Context\n\n待填写\n\n## 1.2. Decision\n\n待填写\n\n## 1.3. Why\n\n待填写\n\n## 1.4. Alternatives\n\n待填写\n\n## 1.5. Consequences\n\n待填写\n'); return f
def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        result=_main()
        from refresh_indexes import main as refresh
        refresh()
        print(result)
        return result

if __name__=='__main__': main()
