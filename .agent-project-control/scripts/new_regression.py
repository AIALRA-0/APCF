# APCF-META {"schema":1,"visibility":"public"}
import argparse
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--title',required=True); a=ap.parse_args(); rid=next_id('REG',FRAMEWORK_ROOT/'regressions'); s=now_stamp(); d=FRAMEWORK_ROOT/'regressions'/f'{rid}_{s}_{slugify(a.title)}'; dir_marker(d); dir_marker(d/'repro')
    write_md(d/'REGRESSION.md',f'# 1. {rid} {a.title}\n\n- **Status**：OPEN\n\n## 1.1. Trigger\n\n待填写\n\n## 1.2. Original Failure\n\n待填写\n\n## 1.3. Impact\n\n待填写\n\n## 1.4. Root Cause\n\n待填写\n\n## 1.5. Fix Mechanism\n\n待填写\n\n## 1.6. Scope / Non-Scope\n\n待填写\n\n## 1.7. Long-term Regression / Objective Pass Criterion\n\n待填写\n\n## 1.8. Related Tests / Turn / REG\n\n待填写\n')
    from refresh_indexes import main as r; r(); print(d)
if __name__=='__main__': main()
